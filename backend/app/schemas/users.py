"""用户管理模块数据契约（T56，与 docs/api-schemas.md §6 同步维护）"""
from typing import Literal

from pydantic import BaseModel, Field

# username 出现在 DELETE /api/users/{username} 路径中，必须路径安全：
# \w 在 pydantic-core 为 Unicode 语义（兼容中文用户名），加 . - 两种常用连接符；
# 空格与 / ? # % 等路径敌对字符一律拒绝（校验失败走统一 422→400 E4001 包裹）
USERNAME_PATTERN = r"^[\w.-]{2,32}$"


class CreateUserIn(BaseModel):
    """POST /api/users 请求体"""

    username: str = Field(
        pattern=USERNAME_PATTERN,
        description="登录名：2~32 位，字母数字下划线点连字符，兼容中文",
    )
    password: str = Field(min_length=6, max_length=128, description="初始密码（只存 pbkdf2 哈希）")
    role: Literal["hr", "admin"] = "hr"


class ResetPasswordIn(BaseModel):
    """POST /api/users/{username}/reset_password 请求体"""

    new_password: str = Field(min_length=6, max_length=128, description="重置后的新密码")


class UserOut(BaseModel):
    """GET /api/users 列表项"""

    username: str
    role: Literal["hr", "admin"]
    created_at: str
