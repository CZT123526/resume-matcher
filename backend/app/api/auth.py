"""认证模块路由（T54，契约 docs/backend-api.md §7）。

薄路由：参数校验 + 调 svc/auth + 审计埋点；登录成败都记审计（含 IP）。
/login 是豁免面（无需登录）；/logout、/me 由 auth_guard 统一保护。
"""
from fastapi import APIRouter, Request

from app.common.response import ok
from app.core.errors import AppError, ErrorCode
from app.schemas.auth import ChangePasswordIn, LoginIn
from app.svc.auth import authenticate, change_password, logout_token
from app.svc.audit import log_action, log_request_action

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
def login(body: LoginIn, request: Request):
    """登录：校验通过签发 token；失败文案不区分用户名/密码（防枚举）"""
    ip = request.client.host if request.client else None
    try:
        data = authenticate(body.username, body.password)
    except AppError:
        log_action(body.username, "login_fail", None, "用户名或密码错误", ip)
        raise
    log_action(data["username"], "login_success", None, None, ip)
    return ok(data)


@router.post("/logout")
def logout(request: Request):
    """注销：删除当前 token 的服务端会话行（幂等）"""
    auth = request.headers.get("Authorization", "")
    token = auth[7:].strip() if auth.startswith("Bearer ") else ""
    logout_token(token)
    log_request_action(request, "logout")
    return ok({"logged_out": True})


@router.get("/me")
def me(request: Request):
    """当前登录用户；身份由 auth_guard 校验后写入 request.state，这里只读"""
    # AUTH_ENABLED=0 时守卫直接放行、state 为空——开放模式下如实返回 null
    return ok({
        "username": getattr(request.state, "username", None),
        "role": getattr(request.state, "role", None),
    })


@router.post("/password")
def change_own_password(body: ChangePasswordIn, request: Request):
    """修改自己的密码（T56）：当前会话保留，该用户其他会话全部下线。

    旧密码错误返回 400 E4001 而非 401——前端把 401 契约在「会话失效自动登出」上，
    业务性拒绝必须避开（契约 docs/backend-api.md §7）。
    """
    username = getattr(request.state, "username", None)
    if not username:
        # 仅 AUTH_ENABLED=0 可达：开放模式无会话身份，如实暴露
        raise AppError(ErrorCode.UNAUTHORIZED, "未登录或凭证失效")
    auth = request.headers.get("Authorization", "")
    token = auth[7:].strip() if auth.startswith("Bearer ") else ""
    change_password(username, body.old_password, body.new_password, keep_token=token)
    log_request_action(request, "user_change_password", target=username)
    return ok({"changed": True})
