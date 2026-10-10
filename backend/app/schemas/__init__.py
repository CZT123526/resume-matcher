"""数据契约（Pydantic 模型）——接口请求/响应的唯一字段定义。

纪律：字段变更 = 先改 docs/api-schemas.md 与 docs/backend-api.md，再改这里；
前端按同一契约并行开发。实体类型枚举见 resume.ENTITY_KEYS。
"""
from app.schemas.jd import JdCreate, JdCreated, JdDetail, JdItem
from app.schemas.match import (
    MatchResults,
    MatchTaskAccepted,
    MatchTaskCreate,
    ResultItem,
    TaskStatus,
)
from app.schemas.resume import (
    ENTITY_KEYS,
    EntityItem,
    ParseStatus,
    ResumeDetail,
    ResumeListItem,
    ResumeListData,
    UploadAccepted,
)
from app.schemas.model_info import ModelInfo

__all__ = [
    "ENTITY_KEYS", "EntityItem", "ParseStatus", "UploadAccepted",
    "ResumeListItem", "ResumeListData", "ResumeDetail",
    "JdCreate", "JdCreated", "JdItem", "JdDetail",
    "MatchTaskCreate", "MatchTaskAccepted", "TaskStatus", "ResultItem", "MatchResults",
    "ModelInfo",
]
