"""统一响应包裹的数据契约。

运行时响应用 app/common/response.py 的 ok()/fail() 字典构造（零开销）；
本模型用于：前端 TS 类型对照、将来接 OpenAPI 自动生成文档。
字段定义必须与 docs/backend-api.md 通用约定一致。
"""
from typing import Generic, Optional, TypeVar, Union

from pydantic import BaseModel

T = TypeVar("T")


class Envelope(BaseModel, Generic[T]):
    """code=0(int) 成功；失败时为 "E####"(str)、data=None"""
    code: Union[int, str] = 0
    message: str = "ok"
    data: Optional[T] = None
