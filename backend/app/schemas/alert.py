from pydantic import BaseModel


class AlertOut(BaseModel):
    level: str  # 高危 / 警告
    code: str
    message: str
    ref_id: str | None = None
