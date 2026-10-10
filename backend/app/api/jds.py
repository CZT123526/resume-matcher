"""JD 模块接口（API-05/06/07，契约见 docs/backend-api.md §2）。"""
import json

from fastapi import APIRouter, Query

from app.common.format import iso_time
from app.common.response import ok
from app.core.errors import AppError, ErrorCode
from app.db import get_db
from app.schemas.jd import JdCreate
from app.svc.jd_parsing import build_jd_requirements

router = APIRouter(prefix="/api/jds", tags=["jds"])


@router.post("")
def create_jd(body: JdCreate):
    """创建 JD：原文入库；req_json 由规则即时抽取（契约：前端不提交 req_json）"""
    req = build_jd_requirements(body.content)
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO jds(title, content, req_json) VALUES(?,?,?)",
            (body.title.strip(), body.content.strip(), json.dumps(req, ensure_ascii=False)),
        )
        jd_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()
    return ok({"jd_id": jd_id, "title": body.title.strip()})


@router.get("")
def list_jds(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    conn = get_db()
    try:
        total = conn.execute("SELECT COUNT(*) FROM jds").fetchone()[0]
        rows = conn.execute(
            "SELECT id, title, created_at FROM jds ORDER BY id DESC LIMIT ? OFFSET ?",
            (page_size, (page - 1) * page_size),
        ).fetchall()
    finally:
        conn.close()
    items = [
        {"jd_id": r["id"], "title": r["title"], "created_at": iso_time(r["created_at"])}
        for r in rows
    ]
    return ok({"total": total, "items": items})


@router.get("/{jd_id}")
def jd_detail(jd_id: int):
    """详情：原文 + req_json（结构化要求）"""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id, title, content, req_json, created_at FROM jds WHERE id=?", (jd_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND, f"JD {jd_id} 不存在")
    return ok({
        "jd_id": row["id"],
        "title": row["title"],
        "content": row["content"],
        "req_json": json.loads(row["req_json"]) if row["req_json"] else None,
        "created_at": iso_time(row["created_at"]),
    })
