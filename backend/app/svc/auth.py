"""认证业务（T54）：登录校验、会话签发/注销、管理员引导。

分层纪律：api 层（app/api/auth.py）只做参数校验与审计埋点，业务在这里。
"""
import logging
import os
from datetime import datetime, timedelta

from app.config import settings
from app.core.errors import AppError, ErrorCode
from app.core.security import hash_password, new_token, token_hash, verify_password
from app.db import get_db

logger = logging.getLogger(__name__)

# 与 config 默认值一致才算"未设置的弱密码"（用户显式设了 admin123 就不重复告警）
_DEFAULT_ADMIN_PASSWORD = "admin123"


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def authenticate(username: str, password: str) -> dict:
    """登录校验 → 签发 token。

    用户名不存在与密码错误同一文案（防枚举）；过期会话顺带清理
    （两个 ISO 字符串字典序即时间序，可直接比较）。
    """
    conn = get_db()
    try:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (_now_iso(),))
        row = conn.execute(
            "SELECT password_hash, role FROM users WHERE username=?", (username,)
        ).fetchone()
        if row is None or not verify_password(password, row["password_hash"]):
            conn.commit()  # 失败路径也要把过期清理落库
            raise AppError(ErrorCode.UNAUTHORIZED, "用户名或密码错误")
        token = new_token()
        expires_at = (
            datetime.now() + timedelta(hours=settings.SESSION_TTL_HOURS)
        ).isoformat(timespec="seconds")
        conn.execute(
            "INSERT INTO sessions(token_hash, username, expires_at) VALUES(?,?,?)",
            (token_hash(token), username, expires_at),
        )
        conn.commit()
        return {
            "username": username,
            "role": row["role"],
            "token": token,
            "expires_at": expires_at,
        }
    finally:
        conn.close()


def logout_token(token: str) -> None:
    """删除当前 token 的服务端会话行（幂等：token 无效/已过期时静默）"""
    if not token:
        return
    conn = get_db()
    try:
        conn.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(token),))
        conn.commit()
    finally:
        conn.close()


def ensure_admin() -> None:
    """首次启动（users 空表）按 ADMIN_USERNAME/ADMIN_PASSWORD 引导创建管理员。

    未显式设置密码时用默认弱密码并在日志 ⚠ 提示——不阻断启动（课程演示环境）。
    """
    conn = get_db()
    try:
        n = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if n:
            return
        conn.execute(
            "INSERT INTO users(username, password_hash, role) VALUES(?,?,'admin')",
            (settings.ADMIN_USERNAME, hash_password(settings.ADMIN_PASSWORD)),
        )
        conn.commit()
        logger.info("users 表为空，已创建管理员 %s", settings.ADMIN_USERNAME)
    finally:
        conn.close()
    if settings.ADMIN_PASSWORD == _DEFAULT_ADMIN_PASSWORD and "ADMIN_PASSWORD" not in os.environ:
        logger.warning(
            "ADMIN_PASSWORD 未设置，管理员 %s 使用默认密码 admin123，请尽快在 backend/.env 设置并重启！",
            settings.ADMIN_USERNAME,
        )
