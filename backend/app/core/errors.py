"""统一业务异常与错误码。

纪律：业务代码禁止手写 HTTPException，只允许 raise AppError，
由 main.py 的全局异常处理器转成统一响应包裹（错误码表见 docs/backend-api.md）。
"""
from enum import Enum

from fastapi import status


class ErrorCode(str, Enum):
    """错误码：与 docs/backend-api.md 错误码表一一对应，改这里必须先改文档"""

    BAD_PARAM = "E4001"            # 参数错误
    UNSUPPORTED_FILE = "E4002"     # 文件类型不支持
    NOT_FOUND = "E4041"            # 资源不存在
    CONFLICT = "E4091"             # 状态冲突
    FILE_TOO_LARGE = "E4131"       # 文件过大
    INTERNAL = "E5001"             # 服务内部错误


# 错误码 → HTTP 状态码
HTTP_STATUS: dict[ErrorCode, int] = {
    ErrorCode.BAD_PARAM: status.HTTP_400_BAD_REQUEST,
    ErrorCode.UNSUPPORTED_FILE: status.HTTP_400_BAD_REQUEST,
    ErrorCode.NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.CONFLICT: status.HTTP_409_CONFLICT,
    ErrorCode.FILE_TOO_LARGE: status.HTTP_413_CONTENT_TOO_LARGE,
    ErrorCode.INTERNAL: status.HTTP_500_INTERNAL_SERVER_ERROR,
}


class AppError(Exception):
    """业务异常基类：svc 层抛出，api 层不捕获（交给全局处理器）"""

    def __init__(self, code: ErrorCode, message: str):
        self.code = code
        self.message = message
        self.http_status = HTTP_STATUS[code]
        super().__init__(message)
