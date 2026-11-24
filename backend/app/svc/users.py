"""用户管理业务（T56）：账号增删查、管理员重置密码。

分层纪律：api 层（app/api/users.py）只做审计埋点，业务在这里。
审计动作约定：user_create / user_delete / user_reset_password（api 层埋点）。
"""
import logging
import sqlite3

from app.common.format import iso_time
from app.core.errors import AppError, ErrorCode
from app.core.security import hash_password
from app.db import get_db

logger = logging.getLogger(__name__)


def list_users() -> dict:
    """全量用户列表（账号量级极小不分页），创建时间倒序、新账号在前。"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT username, role, created_at FROM users ORDER BY created_at DESC, id DESC"
        ).fetchall()
    finally:
        conn.close()
    items = [
        {"username": r["username"], "role": r["role"], "created_at": iso_time(r["created_at"])}
        for r in rows
    ]
    return {"items": items, "total": len(items)}


def create_user(username: str, password: str, role: str) -> dict:
    """建号：重名 409（pre-SELECT 给友好文案，IntegrityError 兜底竞态）。"""
    conn = get_db()
    try:
        dup = conn.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone()
        if dup:
            raise AppError(ErrorCode.CONFLICT, "用户名已存在")
        try:
            conn.execute(
                "INSERT INTO users(username, password_hash, role) VALUES(?,?,?)",
                (username, hash_password(password), role),
            )
            conn.commit()
        except sqlite3.IntegrityError:  # 并发窗口撞 UNIQUE 约束
            raise AppError(ErrorCode.CONFLICT, "用户名已存在")
    finally:
        conn.close()
    return {"username": username, "role": role}


def delete_user(actor: str, username: str) -> dict:
    """删号：不能删自己；至少保留一个管理员。

    该用户全部会话连带删除——其已登录浏览器下一次请求即 401 回登录页。
    """
    if actor == username:
        raise AppError(ErrorCode.CONFLICT, "不能删除自己的账号")
    conn = get_db()
    try:
        row = conn.execute("SELECT role FROM users WHERE username=?", (username,)).fetchone()
        if row is None:
            raise AppError(ErrorCode.NOT_FOUND, "用户不存在")
        if row["role"] == "admin":
            admins = conn.execute(
                "SELECT COUNT(*) FROM users WHERE role='admin' AND username != ?",
                (username,),
            ).fetchone()[0]
            if admins == 0:
                raise AppError(ErrorCode.CONFLICT, "至少保留一个管理员账号")
        cur = conn.execute("DELETE FROM users WHERE username=?", (username,))
        deleted_sessions = conn.execute(
            "DELETE FROM sessions WHERE username=?", (username,)
        ).rowcount
        conn.commit()
        logger.info("用户 %s 被 %s 删除（连带会话 %s 条）", username, actor, deleted_sessions)
    finally:
        conn.close()
    return {"deleted": True, "deleted_sessions": deleted_sessions}


def reset_password(actor: str, username: str, new_password: str) -> dict:
    """管理员重置密码：目标用户全部会话失效，需重新登录。

    不允许对自己执行——重置会删掉自己当前会话，等于把自己登出；
    改自己的密码请走 POST /api/auth/password（保留当前会话）。
    """
    if actor == username:
        raise AppError(ErrorCode.CONFLICT, "不能重置自己的密码，请在修改密码中操作")
    conn = get_db()
    try:
        row = conn.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone()
        if row is None:
            raise AppError(ErrorCode.NOT_FOUND, "用户不存在")
        conn.execute(
            "UPDATE users SET password_hash=? WHERE username=?",
            (hash_password(new_password), username),
        )
        conn.execute("DELETE FROM sessions WHERE username=?", (username,))
        conn.commit()
    finally:
        conn.close()
    return {"reset": True}
