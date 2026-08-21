"""对账中心端点（三期 §4.3）：7 维聚合查询。main.py 挂 prefix=/api/reconciliation-center。"""
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.services import reconciliation_service as svc

router = APIRouter()


@router.get("/sales-chain")
def dim1(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {"items": svc.dim1_sales_chain(db)}


@router.get("/purchase-chain")
def dim2(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {"items": svc.dim2_purchase_chain(db)}


@router.get("/asset-delivery")
def dim3(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {"items": svc.dim3_asset_delivery(db)}


@router.get("/supervised-accounts")
def dim4(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {"items": svc.dim4_supervised_accounts(db)}


@router.get("/fx-check")
def dim5(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {"items": svc.dim5_fx_check(db)}


@router.get("/ebs-consistency")
def dim6(inject_demo: bool = False, db: Session = Depends(get_db),
         user: User = Depends(get_current_user)):
    """业财一致性（Mock）。inject_demo=true 手动注入 3 条模拟差异（验收展示管道用）。"""
    return {"items": svc.dim6_ebs_consistency(db, inject_demo=inject_demo), "injected": inject_demo}


@router.get("/flow-diffs")
def dim7(customer_id: UUID | None = None, supplier_id: UUID | None = None,
         db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {"items": svc.dim7_flow_diffs(db, customer_id=customer_id, supplier_id=supplier_id)}


@router.get("/prepay-parity")
def dim8(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """预付款双轨勾稽（期1 R1）：PREPAY 池余额 vs Σ设备预付剩余，按项目对比，差异标「双轨差异」。"""
    return {"items": svc.dim8_prepay_parity(db)}
