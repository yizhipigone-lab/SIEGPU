"""历史数据迁移（一期 W5-6）：存量批量资产卡拆分为一机一卡（D6）。

由 alembic 0007 upgrade 末尾调用（`split_bulk_assets_to_per_device(op.get_bind())`）；
空库 no-op；Σ 不变量失败即抛错，借 alembic 事务整体回滚。

提取为独立可单测函数（不导入数字前缀的 alembic 文件）：测试直接传 conftest 的 `db`
Session（Session.execute(text(...)) 与 Connection 同构）。
"""
import uuid
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.utils.depreciation import depreciation_inputs, q2

# 单台重算后 monthly_depreciation 的容差系数：N 台各经 depreciation_inputs 独立 q2，
# 舍入漂移 ≤ N×0.005；取 0.01×N 留 2× 余量。
_TOLERANCE_PER_UNIT = Decimal("0.01")


def split_bulk_assets_to_per_device(conn: Connection) -> dict:
    """拆分存量批量资产卡为一机一卡。

    对每张批量卡（quantity>1, device_id IS NULL, deleted_at IS NULL）：
      1. 按 quantity 拆 N 台 device（SN=GPU-{start_date 月}-{续 seq}、status='点亮验收'、
         ownership='表内自有'、purchase_value=单台原值）。
      2. N 张单台 Asset（device_id 关联；末期吸收 unit 尾差保 Σ；折旧字段按单台原值经
         depreciation_inputs 重算；operation_status='运营中'）。未点亮的批量卡拆为
         '已转固未运营' 卡（折旧字段 NULL）。
      3. 原批量卡软删（deleted_at=now()）。

    Σ 自检（失败抛 RuntimeError，alembic 整体回滚）：
      - Σ unit_original_value == 原总原值（精确：base 为 2dp，base*(n-1) 与 total 均为 2dp）
      - Σ monthly_depreciation 与原值漂移 ≤ 0.01×N（仅运营卡）

    device.order_id 留 NULL：迁移不改变订单 flow_type 语义（M-1 翻转在 Phase D 单独做）；
    拆出的 asset 仍带原 order_id 保资产→订单溯源。

    返回 {split_cards, created_devices}；空库返回 {0, 0}。
    """
    rows = conn.execute(text("""
        SELECT id, project_id, equipment_model_id, order_id, quantity,
               total_original_value, residual_rate, monthly_depreciation,
               start_date, end_date, created_at
          FROM assets
         WHERE quantity > 1 AND device_id IS NULL AND deleted_at IS NULL
         ORDER BY created_at
    """)).mappings().all()

    if not rows:
        return {"split_cards": 0, "created_devices": 0}

    dev_sql = text("""
        INSERT INTO devices
            (id, sn, project_id, equipment_model_id, purchase_value,
             prepayment_amount, status, ownership)
        VALUES
            (:id, :sn, :project_id, :equipment_model_id, :purchase_value,
             :prepayment_amount, :status, :ownership)
    """)
    asset_sql = text("""
        INSERT INTO assets
            (id, project_id, equipment_model_id, order_id, device_id, quantity,
             unit_original_value, total_original_value, residual_rate,
             residual_value, depreciable_value, annual_depreciation, monthly_depreciation,
             start_date, end_date, status, operation_status)
        VALUES
            (:id, :project_id, :equipment_model_id, :order_id, :device_id, :quantity,
             :unit_original_value, :total_original_value, :residual_rate,
             :residual_value, :depreciable_value, :annual_depreciation, :monthly_depreciation,
             :start_date, :end_date, :status, :operation_status)
    """)

    total_cards = 0
    total_devices = 0
    for a in rows:
        n = int(a["quantity"])
        total_v = Decimal(a["total_original_value"])
        rate = Decimal(a["residual_rate"]) if a["residual_rate"] is not None else Decimal("0.10")
        bulk_monthly = Decimal(a["monthly_depreciation"]) if a["monthly_depreciation"] is not None else None
        operating = a["start_date"] is not None and bulk_monthly is not None
        start_date = a["start_date"]
        end_date = a["end_date"]

        # 末期吸收尾差：base*(n-1) 与 total_v 均 2dp → last_unit 亦 2dp，Σ 精确
        base = q2(total_v / n)
        last_unit = q2(total_v - base * (n - 1))

        prefix = _sn_prefix(a)
        seq0 = _max_sn_seq(conn, prefix)  # 续当前最大 seq

        dev_rows, asset_rows = [], []
        sum_unit = Decimal(0)
        sum_monthly = Decimal(0)
        for i in range(n):
            unit_value = base if i < n - 1 else last_unit
            did = uuid.uuid4()
            dev_rows.append({
                "id": did,
                "sn": f"{prefix}{seq0 + 1 + i:05d}",
                "project_id": a["project_id"],
                "equipment_model_id": a["equipment_model_id"],
                "purchase_value": unit_value,
                "prepayment_amount": Decimal("0"),
                "status": "点亮验收" if operating else "上架",
                "ownership": "表内自有",
            })
            if operating:
                dep = depreciation_inputs(unit_value, residual_rate=rate)
                asset_rows.append({
                    "id": uuid.uuid4(), "project_id": a["project_id"],
                    "equipment_model_id": a["equipment_model_id"], "order_id": a["order_id"],
                    "device_id": did, "quantity": 1,
                    "unit_original_value": unit_value, "total_original_value": unit_value,
                    "residual_rate": rate,
                    "residual_value": dep["residual_value"],
                    "depreciable_value": dep["depreciable_value"],
                    "annual_depreciation": dep["annual_depreciation"],
                    "monthly_depreciation": dep["monthly_depreciation"],
                    "start_date": start_date, "end_date": end_date,
                    "status": "折旧中", "operation_status": "运营中",
                })
                sum_monthly += dep["monthly_depreciation"]
            else:
                asset_rows.append({
                    "id": uuid.uuid4(), "project_id": a["project_id"],
                    "equipment_model_id": a["equipment_model_id"], "order_id": a["order_id"],
                    "device_id": did, "quantity": 1,
                    "unit_original_value": unit_value, "total_original_value": unit_value,
                    "residual_rate": rate,
                    "residual_value": None, "depreciable_value": None,
                    "annual_depreciation": None, "monthly_depreciation": None,
                    "start_date": None, "end_date": None,
                    "status": "折旧中", "operation_status": "已转固未运营",
                })
            sum_unit += unit_value

        # Σ unit_original_value 精确等于原总原值
        if sum_unit != total_v:
            raise RuntimeError(
                f"批量卡 {a['id']} 拆分后 Σ unit_original_value={sum_unit} ≠ 原值 {total_v}"
            )
        # Σ monthly_depreciation 容差（单台独立 q2 的舍入漂移）
        if operating and bulk_monthly is not None:
            tol = (_TOLERANCE_PER_UNIT * n).quantize(Decimal("0.01"))
            drift = abs(sum_monthly - bulk_monthly)
            if drift > tol:
                raise RuntimeError(
                    f"批量卡 {a['id']} 拆分后 Σ monthly_depreciation={sum_monthly} "
                    f"与原值 {bulk_monthly} 漂移 {drift} > 容差 {tol}"
                )

        conn.execute(dev_sql, dev_rows)
        conn.execute(asset_sql, asset_rows)
        conn.execute(
            text("UPDATE assets SET deleted_at = now() WHERE id = :id"),
            {"id": a["id"]},
        )
        total_cards += n
        total_devices += n

    return {"split_cards": total_cards, "created_devices": total_devices}


def _sn_prefix(asset_row) -> str:
    """GPU-{YYYYMM}- 前缀：优先 start_date 月份，回退 created_at 月份。"""
    d = asset_row["start_date"] or asset_row["created_at"]
    ym = f"{d.year:04d}{d.month:02d}" if d else "197001"
    return f"GPU-{ym}-"


def _max_sn_seq(conn, prefix: str) -> int:
    """prefix 下当前最大 SN 序号（RIGHT(sn,5) 转 INT 的 MAX）。无则 0。"""
    row = conn.execute(text(
        "SELECT COALESCE(MAX(CAST(RIGHT(sn, 5) AS INTEGER)), 0) AS m "
        "FROM devices WHERE sn LIKE :p"
    ), {"p": f"{prefix}%"}).mappings().first()
    return int(row["m"]) if row and row["m"] is not None else 0
