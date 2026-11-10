"""认证与密码安全原语（T54）。

零第三方依赖纪律：密码哈希用标准库 hashlib.pbkdf2_hmac（SHA-256，10 万轮），
不引入 bcrypt；存储格式 `pbkdf2$轮次$盐hex$哈希hex` 自描述，未来升轮次时旧哈希仍可校验。
会话 token 只在库里存 SHA-256 哈希——库文件泄露也拿不到可直接复用的凭证。

auth_guard 是 app 级统一鉴权入口（main.py dependencies=[Depends(auth_guard)]）：
豁免面集中在本文件一处（改动必须同步 docs/backend-api.md 通用约定），可审计性好。
"""
import hashlib
import hmac
import secrets
from datetime import datetime

from fastapi import Request

from app.config import settings
from app.core.errors import AppError, ErrorCode
from app.db import get_db

PBKDF2_ITERATIONS = 100_000

# 鉴权豁免面（契约 docs/backend-api.md 通用约定）：仅 login 免登录，
# logout/me 必须带 token；/docs、/openapi.json 是自助文档，/ 是服务信息
EXEMPT_PREFIXES = ("/api/auth/login",)
EXEMPT_PATHS = {"/", "/health", "/api/health", "/docs", "/openapi.json", "/redoc"}


def hash_password(password: str) -> str:
    """密码 → pbkdf2-hmac-sha256（随机盐，10 万轮），格式 pbkdf2$轮次$盐hex$哈希hex"""
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2${PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """校验密码；哈希格式不合法一律 False（不抛异常，脏数据不打崩登录）"""
    try:
        algo, iterations, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(dk.hex(), hash_hex)  # 常数时间比较，防时序侧信道
    except (ValueError, AttributeError):
        return False


def new_token() -> str:
    """签发会话 token：urlsafe 随机 32 字节（43 字符）"""
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    """token 的 SHA-256 十六进制哈希（sessions 表只存这个，不存明文）"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def is_exempt(path: str) -> bool:
    """豁免面判定：集中一处，改这里必须同步契约文档"""
    return path in EXEMPT_PATHS or path.startswith(EXEMPT_PREFIXES)


def auth_guard(request: Request) -> None:
    """app 级鉴权守卫：AUTH_ENABLED=0 一键放行（测试套件/临时关闭）；
    豁免面放行；其余请求必须携带有效 Bearer token，否则 401 E4011。

    校验通过后把 username/role 写入 request.state，供审计（svc.audit）与
    /api/auth/me 读取——api 层无需重复查库。
    """
    if not settings.AUTH_ENABLED or is_exempt(request.url.path):
        return

    auth = request.headers.get("Authorization", "")
    token = auth[7:].strip() if auth.startswith("Bearer ") else ""
    if not token:
        raise AppError(ErrorCode.UNAUTHORIZED, "未登录或凭证失效")

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT s.username, s.expires_at, u.role FROM sessions s "
            "LEFT JOIN users u ON u.username = s.username "
            "WHERE s.token_hash=?",
            (token_hash(token),),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        raise AppError(ErrorCode.UNAUTHORIZED, "未登录或凭证失效")
    try:
        expired = datetime.fromisoformat(row["expires_at"]) <= datetime.now()
    except ValueError:  # 脏数据按过期处理，不放行
        expired = True
    if expired:
        _drop_session(token)  # 顺手清掉过期行，过期会话不积压
        raise AppError(ErrorCode.UNAUTHORIZED, "未登录或凭证失效")

    request.state.username = row["username"]
    request.state.role = row["role"] or "hr"  # 用户被删的极端情况按普通角色，不放大权限


def _drop_session(token: str) -> None:
    """按明文 token 删除会话行（过期清理/注销共用，幂等）"""
    conn = get_db()
    try:
        conn.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(token),))
        conn.commit()
    finally:
        conn.close()
