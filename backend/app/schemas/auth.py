"""认证模块数据契约（T54，与 docs/api-schemas.md §5 同步维护）"""
from typing import Literal

from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    """POST /api/auth/login 请求体"""

    username: str = Field(min_length=1, max_length=64, description="登录名")
    password: str = Field(min_length=1, max_length=128, description="密码（服务端只存 pbkdf2 哈希）")


class LoginOut(BaseModel):
    """POST /api/auth/login 响应 data"""

    username: str
    role: Literal["hr", "admin"]
    token: str  # urlsafe 随机串（43 字符），服务端只存其 SHA-256 哈希
    expires_at: str  # ISO 8601


class MeOut(BaseModel):
    """GET /api/auth/me 响应 data"""

    username: str
    role: Literal["hr", "admin"]
