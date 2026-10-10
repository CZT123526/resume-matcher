"""统一响应包裹（与 docs/backend-api.md 通用约定严格一致）。

成功：{"code": 0, "message": "ok", "data": {...}}
失败：{"code": "E4001", "message": "...", "data": null}
"""
from typing import Any

from fastapi.responses import JSONResponse


def ok(data: Any = None, message: str = "ok") -> dict:
    """成功响应包裹：接口层返回此结构"""
    return {"code": 0, "message": message, "data": data}


def fail(code: str, message: str, http_status: int) -> JSONResponse:
    """失败响应包裹：一般不直接用，优先 raise AppError"""
    return JSONResponse(
        status_code=http_status,
        content={"code": code, "message": message, "data": None},
    )
