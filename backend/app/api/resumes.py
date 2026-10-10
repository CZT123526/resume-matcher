"""简历模块接口（API-01/02/03/04，契约见 docs/backend-api.md §1）。

纪律：本层只做参数校验、调 svc、组装响应；业务在 svc/。
"""
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Query, UploadFile

from app.common.format import iso_time
from app.common.response import ok
from app.core.errors import AppError, ErrorCode
from app.db import get_db, rows_to_dicts
from app.svc.pipeline import run_parse_pipeline

router = APIRouter(prefix="/api/resumes", tags=["resumes"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 契约：≤10MB
SUPPORTED_EXTS = {".pdf", ".docx"}


@router.post("/upload", status_code=202)
async def upload_resume(background: BackgroundTasks, file: UploadFile = File(...)):
    """上传简历（202 已受理），后台异步解析，前端轮询 GET /api/resumes/{id}"""
    filename = file.filename or ""
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTS:
        raise AppError(ErrorCode.UNSUPPORTED_FILE, f"文件类型不支持: {ext or '未知'}（仅支持 PDF/DOCX）")

    data = await file.read()
    if not data:
        raise AppError(ErrorCode.BAD_PARAM, "文件内容为空")
    if len(data) > MAX_UPLOAD_BYTES:
        raise AppError(ErrorCode.FILE_TOO_LARGE, "文件超过 10MB 上限")

    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO resumes(file_name, file_type, file_size, parse_status) VALUES(?,?,?,'pending')",
            (Path(filename).name, ext.lstrip("."), len(data)),
        )
        resume_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    background.add_task(run_parse_pipeline, resume_id, data, Path(filename).name)
    return ok({"resume_id": resume_id, "file_name": Path(filename).name, "parse_status": "pending"})


@router.get("")
def list_resumes(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    parse_status: str | None = Query(None),
):
    """分页列表（不含 raw_text 大字段）；parse_status 可选过滤"""
    if parse_status is not None and parse_status not in {"pending", "processing", "done", "failed"}:
        raise AppError(ErrorCode.BAD_PARAM, "parse_status 取值非法")

    where, params = "", []
    if parse_status:
        where, params = "WHERE parse_status=?", [parse_status]

    conn = get_db()
    try:
        total = conn.execute(f"SELECT COUNT(*) FROM resumes {where}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT id, file_name, parse_status, created_at FROM resumes {where} "
            "ORDER BY id DESC LIMIT ? OFFSET ?",
            [*params, page_size, (page - 1) * page_size],
        ).fetchall()
    finally:
        conn.close()

    items = [
        {"resume_id": r["id"], "file_name": r["file_name"],
         "parse_status": r["parse_status"], "created_at": iso_time(r["created_at"])}
        for r in rows
    ]
    return ok({"total": total, "items": items})


@router.get("/{resume_id}")
def resume_detail(resume_id: int):
    """详情：解析状态 + 实体列表 + raw_text 前500字预览"""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id, file_name, parse_status, raw_text, created_at FROM resumes WHERE id=?",
            (resume_id,),
        ).fetchone()
        if row is None:
            raise AppError(ErrorCode.NOT_FOUND, f"简历 {resume_id} 不存在")
        entity_rows = conn.execute(
            "SELECT field_key, field_value, source FROM entities WHERE resume_id=? ORDER BY id",
            (resume_id,),
        ).fetchall()
    finally:
        conn.close()

    return ok({
        "resume_id": row["id"],
        "file_name": row["file_name"],
        "parse_status": row["parse_status"],
        "raw_text": (row["raw_text"] or "")[:500] or None,
        "entities": rows_to_dicts(entity_rows),
        "created_at": iso_time(row["created_at"]),
    })


@router.delete("/{resume_id}")
def delete_resume(resume_id: int):
    """删除简历（P1）：实体随 ON DELETE CASCADE 级联清除；向量缓存由匹配侧按 id 集比对自动重建"""
    conn = get_db()
    try:
        exists = conn.execute("SELECT 1 FROM resumes WHERE id=?", (resume_id,)).fetchone()
        if exists is None:
            raise AppError(ErrorCode.NOT_FOUND, f"简历 {resume_id} 不存在")
        conn.execute("DELETE FROM resumes WHERE id=?", (resume_id,))
        conn.commit()
    finally:
        conn.close()
    return ok({"resume_id": resume_id, "deleted": True})
