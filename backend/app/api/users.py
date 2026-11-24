"""用户管理模块接口（API-23，T56 账号管理，契约见 docs/backend-api.md §8）。

全部仅管理员：路由级 require_admin（app 级 auth_guard 先行执行并写入
request.state.role，FastAPI 0.143 实测 app 级依赖先于路由级依赖）。
列表不记审计（高频低敏，与 T54 口径一致）；三个变更动作落 audit_log。
"""
from fastapi import APIRouter, Depends, Request

from app.core.security import require_admin
from app.common.response import ok
from app.schemas.users import CreateUserIn, ResetPasswordIn
from app.svc.audit import log_request_action
from app.svc.users import create_user, delete_user, list_users, reset_password

router = APIRouter(
    prefix="/api/users",
    tags=["users"],
    dependencies=[Depends(require_admin)],
)


@router.get("")
def get_users():
    return ok(list_users())


@router.post("")
def add_user(body: CreateUserIn, request: Request):
    data = create_user(body.username, body.password, body.role)
    log_request_action(request, "user_create", target=body.username)
    return ok(data)


@router.delete("/{username}")
def remove_user(username: str, request: Request):
    actor = getattr(request.state, "username", None)
    data = delete_user(actor, username)
    log_request_action(request, "user_delete", target=username)
    return ok(data)


@router.post("/{username}/reset_password")
def reset_user_password(username: str, body: ResetPasswordIn, request: Request):
    actor = getattr(request.state, "username", None)
    data = reset_password(actor, username, body.new_password)
    log_request_action(request, "user_reset_password", target=username)
    return ok(data)
