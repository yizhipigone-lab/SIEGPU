from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.api.v1.endpoints import (
    acceptances, auth, assets, billings, capital, confirmations, contracts, currencies, dashboard, devices, ebs, excel, files, funding, health,
    insurance, invoices, leasing, master, notifications, ocr, orders, payments, prepayments, projects, repayments, reports, revenue_recognitions, sales_orders, workflows,
)
from app.core.db import SessionLocal

# F1：应用内消息提醒——每日 09:00（Asia/Shanghai）扫 alert_service 写 notifications。
# 内存 jobstore（一期，重启丢未读可接受）；lifespan 取代已弃用的 on_event。
_scheduler: BackgroundScheduler | None = None


def _daily_scan_job() -> None:
    """定时任务：开独立 session 扫描并幂等落库。"""
    from app.services.notification_service import scan_and_persist
    db = SessionLocal()
    try:
        scan_and_persist(db)
        db.commit()
    except Exception as exc:  # noqa: BLE001 —— 定时任务绝不能因扫描异常拖垮应用
        import logging
        logging.getLogger("apscheduler").exception("通知扫描失败: %s", exc)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _scheduler
    _scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    # minute=7 避开整点扎堆；每日 09:07 扫一次告警并落库
    _scheduler.add_job(_daily_scan_job, "cron", hour=9, minute=7, id="daily-notification-scan", replace_existing=True)
    _scheduler.start()
    try:
        yield
    finally:
        if _scheduler is not None:
            _scheduler.shutdown(wait=False)


app = FastAPI(title="SIEGPU ERP", version="2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    # W5：收敛白名单 + 关闭 credentials（鉴权用 Bearer，不用 cookie）
    allow_origins=["http://localhost:8088", "http://127.0.0.1:8088", "http://localhost:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(IntegrityError)
async def _integrity_handler(request: Request, exc: IntegrityError):
    # W11：DB 约束冲突统一映射 409，不回原始 SQL（防泄漏）
    return JSONResponse(
        status_code=409,
        content={"code": "INTEGRITY_ERROR", "message": "数据约束冲突（唯一/检查/外键）"},
    )


# 常见字段名中文映射（与前端 utils/errMsg.ts 保持一致）
_FIELD_CN = {
    "project_id": "项目", "contract_id": "合同", "order_id": "订单", "sales_order_id": "销售订单",
    "party_id": "往来单位", "supplier_id": "供应商", "customer_id": "客户", "equipment_model_id": "设备型号",
    "amount": "金额", "quantity": "数量", "price": "单价", "unit_price": "单价",
    "name": "名称", "code": "编号", "date": "日期", "transaction_date": "交易日期",
    "invoice_no": "发票号", "status": "状态", "note": "摘要", "remark": "备注",
}

# 常见 pydantic 错误信息中文映射（按前缀匹配），映射不到则保留原文
_MSG_CN = {
    "Field required": "必填",
    "Input should be a valid integer": "应为整数",
    "Input should be a valid number": "应为数字",
    "Input should be a valid string": "应为字符串",
    "Input should be a valid date": "应为有效日期",
}


def _cn_msg(msg: str) -> str:
    for en, cn in _MSG_CN.items():
        if msg.startswith(en):
            return cn
    return msg or "参数错误"


@app.exception_handler(RequestValidationError)
async def _validation_handler(request: Request, exc: RequestValidationError):
    # ★4：422 结构对齐 BusinessError（detail.code/message），字段名+中文 msg 拼成可读文案
    parts = []
    for err in exc.errors():
        loc = err.get("loc") or ()
        field = str(loc[-1]) if loc else ""
        parts.append(f"{_FIELD_CN.get(field, field)}: {_cn_msg(err.get('msg', ''))}")
    return JSONResponse(
        status_code=422,
        content={"detail": {"code": "VALIDATION", "message": "；".join(parts) or "参数校验失败", "details": {}}},
    )


@app.get("/")
def root():
    return {"name": "SIEGPU ERP", "version": "2.0", "docs": "/docs"}


app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
app.include_router(capital.router, prefix="/api/capital", tags=["capital"])
app.include_router(leasing.router, prefix="/api/leasing", tags=["leasing"])
app.include_router(master.suppliers_router, prefix="/api/suppliers", tags=["master"])
app.include_router(master.customers_router, prefix="/api/customers", tags=["master"])
app.include_router(master.equipment_models_router, prefix="/api/equipment-models", tags=["master"])
app.include_router(master.banks_router, prefix="/api/banks", tags=["master"])
app.include_router(notifications.router, prefix="/api/notifications", tags=["notifications"])
app.include_router(contracts.router, prefix="/api/contracts", tags=["contracts"])
app.include_router(orders.router, prefix="/api/orders", tags=["orders"])
app.include_router(devices.router, prefix="/api/devices", tags=["devices"])
app.include_router(billings.router, prefix="/api/billings", tags=["billings"])
app.include_router(invoices.router, prefix="/api/invoices", tags=["invoices"])
app.include_router(repayments.router, prefix="/api/repayments", tags=["repayments"])
app.include_router(assets.router, prefix="/api/assets", tags=["assets"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["dashboard"])
app.include_router(reports.router, prefix="/api/reports", tags=["reports"])
app.include_router(excel.router, prefix="/api/excel", tags=["excel"])
app.include_router(files.router, prefix="/api/files", tags=["files"])
app.include_router(ocr.router, prefix="/api/ocr", tags=["ocr"])
# v3.1 新增
app.include_router(sales_orders.router, tags=["sales-orders"])
app.include_router(acceptances.router, tags=["acceptances"])
app.include_router(confirmations.router, tags=["confirmations"])
app.include_router(funding.router, tags=["funding"])
app.include_router(workflows.router, tags=["workflows"])
# 二期 W1-2 新增：EBS 接口 Mock（业财一体化出站骨架）
app.include_router(ebs.router, prefix="/api/ebs", tags=["ebs"])
app.include_router(currencies.router, prefix="/api", tags=["currency"])
app.include_router(insurance.router, prefix="/api/insurance", tags=["insurance"])
app.include_router(prepayments.router, prefix="/api", tags=["prepayments"])
app.include_router(payments.router, prefix="/api", tags=["payments"])
app.include_router(revenue_recognitions.router, prefix="/api", tags=["revenue"])
