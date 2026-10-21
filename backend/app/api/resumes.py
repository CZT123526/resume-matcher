"""简历模块接口（API-01/02/03/04/13/14/15/16，契约见 docs/backend-api.md §1）。

纪律：本层只做参数校验、调 svc、组装响应；业务在 svc/。
"""
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Query, UploadFile
from fastapi.responses import FileResponse

from app.common.format import iso_time
from app.common.response import ok
from app.core.errors import AppError, ErrorCode
from app.db import get_db, rows_to_dicts, upload_dir
from app.svc.pipeline import run_parse_pipeline

router = APIRouter(prefix="/api/resumes", tags=["resumes"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 契约：≤10MB
SUPPORTED_EXTS = {".pdf", ".docx"}

# 语料来源（T53 挑刺修复）：上传时显式落列，过滤按列判——不再用 created_at
# 硬编码时间窗（窗口一过口径静默漂移：今天真实上传会被当成外校卷）。
# 历史批量导入区间由 init_db 一次性回填（db.LEGACY_CORPUS_WINDOWS），此处不掺和日期。
_CORPUS_COL = "COALESCE(source, 'business')"  # 加列前的存量行由回填兜底，NULL 双保险按业务简历


def _corpus_conds(corpus: str) -> list[str]:
    """corpus 过滤条件（按 resumes.source 列判；常量拼接无注入面）"""
    if corpus == "all":
        return []
    return [f"{_CORPUS_COL}='{corpus}'"]


@router.post("/upload", status_code=202)
async def upload_resume(background: BackgroundTasks, file: UploadFile = File(...)):
    """上传简历（202 已受理），后台异步解析，前端轮询 GET /api/resumes/{id}。

    B4 挑刺修复：先写临时文件、成功后INSERT 再原子改名——任何一步失败都
    回滚（删临时文件/删行），不再出现"库里有记录、原件不存在"的半截数据。
    """
    import os

    filename = file.filename or ""
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTS:
        raise AppError(ErrorCode.UNSUPPORTED_FILE, f"文件类型不支持: {ext or '未知'}（仅支持 PDF/DOCX）")

    data = await file.read()
    if not data:
        raise AppError(ErrorCode.BAD_PARAM, "文件内容为空")
    if len(data) > MAX_UPLOAD_BYTES:
        raise AppError(ErrorCode.FILE_TOO_LARGE, "文件超过 10MB 上限")

    dest_dir = upload_dir()
    tmp_path = dest_dir / f".upload-tmp-{os.getpid()}-{Path(filename).name}"
    final_path = None
    resume_id = None
    try:
        tmp_path.write_bytes(data)  # 先落盘：写失败在这里就抛，库里不留行
        conn = get_db()
        try:
            cur = conn.execute(
                "INSERT INTO resumes(file_name, file_type, file_size, parse_status, source, owner_pid) "
                "VALUES(?,?,?,'pending','business',?)",
                (Path(filename).name, ext.lstrip("."), len(data), os.getpid()),
            )
            resume_id = cur.lastrowid
            conn.commit()
        finally:
            conn.close()
        # 原件以 resume_id 命名防重名（同盘 rename 原子），供 GET /{id}/file 查看原件
        final_path = dest_dir / f"{resume_id}{ext}"
        os.replace(tmp_path, final_path)
        background.add_task(run_parse_pipeline, resume_id, data, Path(filename).name)
    except Exception:
        # 补偿清理：半截状态不留库不留盘
        tmp_path.unlink(missing_ok=True)
        if final_path is not None:
            final_path.unlink(missing_ok=True)
        if resume_id is not None:
            conn = get_db()
            try:
                conn.execute("DELETE FROM resumes WHERE id=?", (resume_id,))
                conn.commit()
            finally:
                conn.close()
        raise
    return ok({"resume_id": resume_id, "file_name": Path(filename).name, "parse_status": "pending"})


@router.get("")
def list_resumes(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    parse_status: str | None = Query(None),
    corpus: str = Query("all", pattern="^(all|business|rewrite|semispec|fresh)$"),
):
    """分页列表（不含 raw_text 大字段）；parse_status / corpus 可选过滤；响应带五类语料计数"""
    if parse_status is not None and parse_status not in {"pending", "processing", "done", "failed"}:
        raise AppError(ErrorCode.BAD_PARAM, "parse_status 取值非法")

    conds, params = [], []
    if parse_status:
        conds.append("parse_status=?")
        params.append(parse_status)
    conds += _corpus_conds(corpus)
    where = f"WHERE {' AND '.join(conds)}" if conds else ""

    biz_cond = _corpus_conds("business")[0]
    rw_cond = _corpus_conds("rewrite")[0]
    sw_cond = _corpus_conds("semispec")[0]
    fr_cond = _corpus_conds("fresh")[0]

    conn = get_db()
    try:
        total = conn.execute(f"SELECT COUNT(*) FROM resumes {where}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT id, file_name, parse_status, created_at FROM resumes {where} "
            "ORDER BY id DESC LIMIT ? OFFSET ?",
            [*params, page_size, (page - 1) * page_size],
        ).fetchall()
        n_all, n_biz, n_rw, n_sw, n_fr = conn.execute(
            f"SELECT COUNT(*),"
            f" SUM(CASE WHEN {biz_cond} THEN 1 ELSE 0 END),"
            f" SUM(CASE WHEN {rw_cond} THEN 1 ELSE 0 END),"
            f" SUM(CASE WHEN {sw_cond} THEN 1 ELSE 0 END),"
            f" SUM(CASE WHEN {fr_cond} THEN 1 ELSE 0 END)"
            " FROM resumes"
        ).fetchone()
    finally:
        conn.close()

    items = [
        {"resume_id": r["id"], "file_name": r["file_name"],
         "parse_status": r["parse_status"], "created_at": iso_time(r["created_at"])}
        for r in rows
    ]
    return ok({
        "total": total, "items": items,
        "corpus_counts": {"all": n_all, "business": n_biz, "rewrite": n_rw,
                          "semispec": n_sw, "fresh": n_fr},
    })


@router.get("/search")
def search_resumes(q: str = Query(..., min_length=1, max_length=100), limit: int = Query(20, ge=1, le=50)):
    """全文搜索简历（API-15，T29）：FTS5 trigram 支持中文子串；<3 字符退回 LIKE 扫描"""
    keyword = q.strip()
    if not keyword:
        raise AppError(ErrorCode.BAD_PARAM, "搜索词不能为空白")

    conn = get_db()
    try:
        if len(keyword) >= 3:
            # FTS5 语法安全：整体包双引号、内部双引号翻倍，防用户输入被当查询语法
            safe = f'"{keyword.replace(chr(34), chr(34) * 2)}"'
            rows = conn.execute(
                "SELECT r.id, r.file_name, r.parse_status, r.created_at, "
                "snippet(resume_search, 2, '「', '」', '…', 12) AS snippet "
                "FROM resume_search f JOIN resumes r ON r.id = CAST(f.resume_id AS INTEGER) "
                "WHERE resume_search MATCH ? ORDER BY rank LIMIT ?",
                (safe, limit),
            ).fetchall()
        else:  # 1-2 字符低于 trigram 下限，小库直接 LIKE（% _ 转义为字面义，防通配假命中）
            esc = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            rows = conn.execute(
                "SELECT r.id, r.file_name, r.parse_status, r.created_at, "
                "substr(r.raw_text, max(1, instr(r.raw_text, ?) - 20), 80) AS snippet "
                "FROM resumes r WHERE r.raw_text LIKE ? ESCAPE '\\' LIMIT ?",
                (keyword, f"%{esc}%", limit),
            ).fetchall()
    finally:
        conn.close()

    items = [
        {"resume_id": r["id"], "file_name": r["file_name"], "parse_status": r["parse_status"],
         "created_at": iso_time(r["created_at"]), "snippet": r["snippet"]}
        for r in rows
    ]
    return ok({"total": len(items), "items": items})


@router.get("/{resume_id}")
def resume_detail(resume_id: int):
    """详情：解析状态 + 实体列表 + raw_text 全文 + 解析质量信号（T29；T30.1 起返回全文）"""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id, file_name, parse_status, raw_text, parse_error, created_at FROM resumes WHERE id=?",
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

    from app.svc.parsing import looks_like_resume

    full_text = row["raw_text"] or ""
    entities = rows_to_dicts(entity_rows)
    return ok({
        "resume_id": row["id"],
        "file_name": row["file_name"],
        "parse_status": row["parse_status"],
        "parse_error": row["parse_error"],
        "raw_text": full_text or None,  # T30.1：不再截 500 字，弹窗内可滚动看全文
        "entities": entities,
        "created_at": iso_time(row["created_at"]),
        # 质量信号：done 但不像简历/零实体 → 前端给出"疑似扫描件"类提示，不阻断
        "quality": {
            "like_resume": looks_like_resume(full_text) if full_text else False,
            "entity_count": len(entities),
            "text_chars": len(full_text),
        },
    })


@router.get("/{resume_id}/jd_recommendations")
def jd_recommendations(resume_id: int, top_k: int = Query(3, ge=1, le=10)):
    """反向推荐（API-17，T39）：这份简历最适合哪些岗位——Top-K JD + 融合分 + 证据链"""
    from app.svc.recommend import recommend_jds_for_resume

    return ok(recommend_jds_for_resume(resume_id, top_k))


@router.get("/{resume_id}/data")
def resume_data(resume_id: int):
    """解析数据视图（API-16，T29）：这份简历被读成了什么数据——全文/实体/匹配输入/向量"""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id, file_name, parse_status, raw_text, parse_error, created_at FROM resumes WHERE id=?",
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

    entities = rows_to_dicts(entity_rows)
    bert_n = sum(1 for e in entities if e["source"] == "bert")

    # 匹配侧视角：structured_text 是语义匹配真正的编码输入；向量实时编码仅供查看（不动缓存）
    from app.svc.embedding import get_encoder
    from app.svc.vectors import structured_text

    st_text = structured_text({"raw_text": row["raw_text"] or "",
                               "entities": [(e["field_key"], e["field_value"]) for e in entities]})
    vec = get_encoder().encode([st_text])[0]

    return ok({
        "resume_id": row["id"],
        "file_name": row["file_name"],
        "parse_status": row["parse_status"],
        "parse_error": row["parse_error"],
        "created_at": iso_time(row["created_at"]),
        "stats": {
            "text_chars": len(row["raw_text"] or ""),
            "entity_count": len(entities),
            "bert_count": bert_n,
            "rule_count": len(entities) - bert_n,
        },
        "entities": entities,
        "raw_text": row["raw_text"] or "",
        "matching": {
            "structured_text": st_text,
            "vector_dim": int(vec.shape[0]),
            "vector_norm": round(float((vec ** 2).sum() ** 0.5), 4),
            "vector_preview": [round(float(x), 4) for x in vec[:8]],
            "note": "向量仅展示前8维；匹配实际使用完整向量与缓存",
        },
    })


@router.post("/{resume_id}/reparse", status_code=202)
def reparse_resume(background: BackgroundTasks, resume_id: int):
    """重新解析（API-14，T29）：用已落盘原件重跑流水线；失败/换模型后均可手动触发"""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT file_name, file_type FROM resumes WHERE id=?", (resume_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND, f"简历 {resume_id} 不存在")

    ext = f".{row['file_type']}"
    path = upload_dir() / f"{resume_id}{ext}"
    if not path.exists():
        raise AppError(ErrorCode.NOT_FOUND, "原件文件不存在，无法重新解析（请重新上传）")

    conn = get_db()
    try:
        conn.execute("UPDATE resumes SET parse_status='pending', parse_error=NULL WHERE id=?", (resume_id,))
        conn.commit()
    finally:
        conn.close()

    background.add_task(run_parse_pipeline, resume_id, path.read_bytes(), row["file_name"])
    return ok({"resume_id": resume_id, "parse_status": "pending"})


@router.get("/{resume_id}/file")
def download_resume_file(resume_id: int):
    """简历原件（API-13）：PDF 浏览器内预览，DOCX 触发下载；文件随上传落盘于 db/uploads/"""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT file_name, file_type FROM resumes WHERE id=?", (resume_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND, f"简历 {resume_id} 不存在")

    path = upload_dir() / f"{resume_id}.{row['file_type']}"
    if not path.exists():
        raise AppError(ErrorCode.NOT_FOUND, "原件文件不存在（该简历上传于原件保存功能上线前）")
    return FileResponse(path, filename=row["file_name"])


@router.delete("/{resume_id}")
def delete_resume(resume_id: int):
    """删除简历（P1）：实体与历史结果随 ON DELETE CASCADE 级联清除；
    向量缓存由匹配侧按 id 集比对自动重建。

    A1 挑刺修复：match_score_dist 的候选人快照（ids_json）同步摘除该简历——
    此前结果行级联消失、分布快照却永生，同一次删除出现"历史 9 行 / 分布仍 1372 人 /
    点柱反查已删简历 404"的三重自相矛盾。现在两条数据路径同一口径：人删了，
    分布里也摘掉（n_candidates、scores_json、ids_json 同步收缩）。
    """
    import json as _json

    conn = get_db()
    try:
        exists = conn.execute("SELECT 1 FROM resumes WHERE id=?", (resume_id,)).fetchone()
        if exists is None:
            raise AppError(ErrorCode.NOT_FOUND, f"简历 {resume_id} 不存在")
        conn.execute("DELETE FROM resumes WHERE id=?", (resume_id,))
        # 全文索引同步清除（FTS5 的 UNINDEXED 列无类型亲和，CAST 兼容 int/str 混存——T32）
        conn.execute(
            "DELETE FROM resume_search WHERE CAST(resume_id AS INTEGER)=?", (resume_id,)
        )
        # 分布快照摘除该候选人（scores 与 items 严格同序，按 items 过滤后同步重建两列）
        for row in conn.execute(
            "SELECT task_id, n_candidates, scores_json, ids_json FROM match_score_dist"
        ).fetchall():
            items = _json.loads(row["ids_json"]) if row["ids_json"] else []
            kept = [x for x in items if int(x.get("resume_id", -1)) != int(resume_id)]
            if len(kept) == len(items):
                continue
            conn.execute(
                "UPDATE match_score_dist SET n_candidates=?, scores_json=?, ids_json=? WHERE task_id=?",
                (len(kept),
                 _json.dumps([x["score"] for x in kept]),
                 _json.dumps(kept, ensure_ascii=False),
                 row["task_id"]),
            )
        conn.commit()
    finally:
        conn.close()
    # 原件一并清理（尽力而为；按 id 前缀匹配扩展名，缺失不阻断删除）
    for f in upload_dir().glob(f"{resume_id}.*"):
        f.unlink(missing_ok=True)
    return ok({"resume_id": resume_id, "deleted": True})
