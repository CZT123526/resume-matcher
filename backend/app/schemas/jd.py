"""岗位 JD 模块数据契约（M02）"""
from typing import Optional

from pydantic import BaseModel, Field


class JdCreate(BaseModel):
    """POST /api/jds 请求体"""
    title: str = Field(min_length=1, max_length=100, description="岗位名称")
    content: str = Field(min_length=1, max_length=5000, description="JD原文")


class JdCreated(BaseModel):
    jd_id: int
    title: str


class JdItem(BaseModel):
    """GET /api/jds 列表项"""
    jd_id: int
    title: str
    created_at: str


class JdDetail(BaseModel):
    """GET /api/jds/{id} 详情体；req_json 为结构化要求：
    {"degree": "本科", "min_years": 3, "skills": ["Python", "FastAPI"]}"""
    jd_id: int
    title: str
    content: str
    req_json: Optional[dict] = None
    created_at: str
