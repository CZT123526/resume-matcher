"""匹配任务模块数据契约（M02 核心）"""
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class TaskState(str, Enum):
    """匹配任务状态机：pending → running → done | failed"""
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"


class MatchTaskCreate(BaseModel):
    """POST /api/match-tasks 请求体"""
    jd_id: int
    top_k: int = Field(default=10, ge=1, le=50, description="召回候选人数")


class MatchTaskAccepted(BaseModel):
    task_id: int
    status: TaskState = TaskState.pending


class TaskStatus(BaseModel):
    """GET /api/match-tasks/{id} 轮询响应体"""
    task_id: int
    status: TaskState
    progress: int = Field(ge=0, le=100)
    error: Optional[str] = None


class ResultItem(BaseModel):
    """单条匹配结果：score 为归一化语义相似度(0~1, 4位小数)；
    evidence 为证据链文本数组（打分与解释分离，见 docs/算法设计.md §4）"""
    rank: int
    resume_id: int
    candidate_name: str
    score: float = Field(ge=0, le=1)
    evidence: List[str] = []


class MatchResults(BaseModel):
    """GET /api/match-tasks/{id}/results 响应体"""
    task_id: int
    jd_title: str
    items: List[ResultItem] = []
