"""EBS HTTP Client（二期 W1-2 Mock 实现）。

业财一体化出站最后一跳：把规范化载荷发给 EBS。Mock 期不真正发 HTTP，直接构造成功回执，
养成「同步即落日志 + 幂等 + 留 ebs_reference」的接口契约。真实 EBS 对接属期外里程碑
（§0.3）——届时把 `_real_post` 换成真 httpx 调用即可，调用方（ebs_sync_service）不动。

开关：EBS_MOCK_MODE（默认 true）。期外接真 EBS 时置 false + 配 EBS_BASE_URL。
"""
import os
import uuid

# Mock 开关：默认开。期外接真 EBS 时设 false（届时 _real_post 实现真 httpx 调用）。
EBS_MOCK_MODE = os.getenv("EBS_MOCK_MODE", "true").strip().lower() in ("1", "true", "yes", "on")
# 期外真 EBS 端点（占位，Mock 期不用）。
EBS_BASE_URL = os.getenv("EBS_BASE_URL", "").strip()


class EbsError(Exception):
    """EBS 调用异常（真对接时由 httpx 错误抛；Mock 期仅强制失败测试用）。"""


def post_entity(entity_type: str, payload: dict, sync_type: str = "create") -> dict:
    """把一个实体出站到 EBS。返回 EBS 回执 dict（含 status / ebs_reference）。

    Mock：固定返回 MOCK_SUCCESS + MOCK-EBS-{uuid}（sync_type 入 echo 仅便排错）。
    真实：POST {EBS_BASE_URL}/{entity_type}，按 EBS 规范解析响应（期外实现）。
    """
    if EBS_MOCK_MODE:
        return {
            "status": "MOCK_SUCCESS",
            "ebs_reference": f"MOCK-EBS-{uuid.uuid4()}",
            "echo": {"entity_type": entity_type, "sync_type": sync_type},
        }
    # 期外真对接未实现：Mock 期 EBS_MOCK_MODE 应恒为 true；显式报错防误用。
    raise EbsError("EBS 真实对接尚未实现（期外里程碑）；Mock 期请保持 EBS_MOCK_MODE=true")
