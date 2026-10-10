"""简历模块数据契约（M01）"""
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel

# 统一抽取 Schema：7 类实体字段（与 docs/算法设计.md、db/schema.sql 保持一致）
ENTITY_KEYS = {"name", "degree", "school", "skill", "years", "company", "title"}


class ParseStatus(str, Enum):
    """简历解析状态机：pending → processing → done | failed"""
    pending = "pending"
    processing = "processing"
    done = "done"
    failed = "failed"


class EntityItem(BaseModel):
    """单条实体抽取结果"""
    field_key: str          # 实体类型，取值必须属于 ENTITY_KEYS
    field_value: Optional[str]  # 规范化后的值（years 为数字字符串）
    source: str = "bert"    # 抽取来源，运行时恒为 bert


class UploadAccepted(BaseModel):
    """POST /api/resumes/upload 的 202 响应体"""
    resume_id: int
    file_name: str
    parse_status: ParseStatus = ParseStatus.pending


class ResumeListItem(BaseModel):
    """GET /api/resumes 列表项（不含大字段）"""
    resume_id: int
    file_name: str
    parse_status: ParseStatus
    created_at: str


class ResumeListData(BaseModel):
    total: int
    items: List[ResumeListItem]


class ResumeDetail(BaseModel):
    """GET /api/resumes/{id} 详情体"""
    resume_id: int
    file_name: str
    parse_status: ParseStatus
    raw_text: Optional[str] = None       # 前500字预览
    entities: List[EntityItem] = []
    created_at: str
