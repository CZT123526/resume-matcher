"""访问审计（T54）：谁/何时/做了什么，落 audit_log 表。

纪律：审计是旁路——写入失败只打日志，绝不阻塞业务（库里 busy 等异常
不能让"查看简历"这种主流程 500）。动作清单见 docs/backend-api.md §7。
"""
import logging

from fastapi import Request

from app.db import get_db

logger = logging.getLogger(__name__)


def log_action(username: str | None, action: str, target: str | None = None,
               detail: str | None = None, ip: str | None = None) -> None:
    """落一条审计记录；任何异常只记日志不外抛"""
    try:
        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO audit_log(username, action, target, detail, ip) VALUES(?,?,?,?,?)",
                (username, action, target, detail, ip),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.warning("audit 写入失败 action=%s target=%s", action, target, exc_info=True)


def log_request_action(request: Request, action: str, target: str | None = None,
                       detail: str | None = None) -> None:
    """从请求上下文取操作人（auth_guard 写入 request.state）与 IP 再落审计"""
    username = getattr(request.state, "username", None) or "-"
    ip = request.client.host if request.client else None
    log_action(username, action, target, detail, ip)
