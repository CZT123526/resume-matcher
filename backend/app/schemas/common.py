"""统一响应包裹的数据契约（与 app/common/response.py 的字典结构对应）"""
from typing import Generic, Optional, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Envelope(BaseModel, Generic[T]):
    """标准响应包裹：code=0 成功；失败时 code 为 "E####" 字符串、data=None"""
    code: object = 0
    message: str = "ok"
    data: Optional[T] = None
