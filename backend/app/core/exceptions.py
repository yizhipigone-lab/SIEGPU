from fastapi import HTTPException, status


class BusinessError(HTTPException):
    """业务异常基类，带稳定 code 供前端识别。"""

    def __init__(self, code: str, message: str, http_status: int = status.HTTP_422_UNPROCESSABLE_ENTITY, details: dict | None = None):
        super().__init__(status_code=http_status, detail={"code": code, "message": message, "details": details or {}})


class IllegalTransition(BusinessError):
    def __init__(self, entity: str, frm: str, to: str):
        super().__init__("ILLEGAL_TRANSITION", f"{entity} 不允许从 {frm} 迁移到 {to}", status.HTTP_409_CONFLICT)


class InsufficientAllocatable(BusinessError):
    def __init__(self, need, have):
        super().__init__("INSUFFICIENT_ALLOCATABLE", "可调余额不足", details={"need": str(need), "have": str(have)})


class InvoiceOverContract(BusinessError):
    def __init__(self, contract_amount, invoiced_after):
        super().__init__(
            "INVOICE_OVER_CONTRACT",
            "发票累计超过合同金额，需总监审批",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            details={"contract_amount": str(contract_amount), "invoiced_after": str(invoiced_after)},
        )
