"""匹配任务接口（API-08/09/10）+ 模型信息（API-12），契约见 docs/backend-api.md §3/§5。"""
import json
import os

from fastapi import APIRouter, BackgroundTasks, Query

from app.common.response import ok
from app.core.errors import AppError, ErrorCode
from app.db import get_db
from app.schemas.match import MatchTaskCreate
from app.svc.match_pipeline import run_match_pipeline
from app.svc.ner import METRICS_FILE

router = APIRouter(tags=["match"])


@router.post("/api/match-tasks", status_code=202)
def create_match_task(background: BackgroundTasks, body: MatchTaskCreate):
    """发起匹配（202 受理），后台执行，前端轮询任务状态"""
    conn = get_db()
    try:
        exists = conn.execute("SELECT 1 FROM jds WHERE id=?", (body.jd_id,)).fetchone()
        if exists is None:
            raise AppError(ErrorCode.NOT_FOUND, f"JD {body.jd_id} 不存在")
        cur = conn.execute(
            "INSERT INTO match_tasks(jd_id, top_k, status, owner_pid) VALUES(?,?,'pending',?)",
            (body.jd_id, body.top_k, os.getpid()),
        )
        task_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    background.add_task(run_match_pipeline, task_id, body.jd_id, body.top_k)
    return ok({"task_id": task_id, "status": "pending"})


@router.get("/api/match-tasks")
def list_match_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
    status: str | None = Query(None),
):
    """历史任务列表（A4 挑刺修复）：匹配结果按 task_id 完整存档，此前界面无入口再打开。

    按 id 降序（新任务在前），带 JD 标题与结果条数，供匹配页历史面板直接回看。
    """
    if status is not None and status not in {"pending", "running", "done", "failed"}:
        raise AppError(ErrorCode.BAD_PARAM, "status 取值非法")
    conds, params = [], []
    if status:
        conds.append("t.status=?")
        params.append(status)
    where = f"WHERE {' AND '.join(conds)}" if conds else ""

    conn = get_db()
    try:
        total = conn.execute(
            f"SELECT COUNT(*) FROM match_tasks t {where}", params
        ).fetchone()[0]
        rows = conn.execute(
            f"SELECT t.id, t.jd_id, j.title AS jd_title, t.top_k, t.status, t.progress, "
            f"t.created_at, t.finished_at, "
            f"(SELECT COUNT(*) FROM match_results m WHERE m.task_id=t.id) AS n_results "
            f"FROM match_tasks t LEFT JOIN jds j ON j.id=t.jd_id {where} "
            "ORDER BY t.id DESC LIMIT ? OFFSET ?",
            [*params, page_size, (page - 1) * page_size],
        ).fetchall()
    finally:
        conn.close()

    from app.common.format import iso_time

    items = [
        {"task_id": r["id"], "jd_id": r["jd_id"], "jd_title": r["jd_title"] or "",
         "top_k": r["top_k"], "status": r["status"], "progress": r["progress"],
         "n_results": r["n_results"],
         "created_at": iso_time(r["created_at"]) if r["created_at"] else "",
         "finished_at": iso_time(r["finished_at"]) if r["finished_at"] else ""}
        for r in rows
    ]
    return ok({"total": total, "items": items})


@router.get("/api/match-tasks/{task_id}")
def match_task_status(task_id: int):
    """轮询任务状态（2s 间隔）"""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id, status, progress, error FROM match_tasks WHERE id=?", (task_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND, f"任务 {task_id} 不存在")
    return ok({
        "task_id": row["id"],
        "status": row["status"],
        "progress": row["progress"],
        "error": row["error"],
    })


@router.get("/api/match-tasks/{task_id}/results")
def match_task_results(task_id: int):
    """排名结果：rank 升序，score 0~1 四位小数，evidence 契约文案"""
    conn = get_db()
    try:
        task = conn.execute(
            "SELECT id, status, jd_id FROM match_tasks WHERE id=?", (task_id,)
        ).fetchone()
        if task is None:
            raise AppError(ErrorCode.NOT_FOUND, f"任务 {task_id} 不存在")
        if task["status"] != "done":
            raise AppError(ErrorCode.CONFLICT, f"任务尚未完成（当前 {task['status']}），完成后再取结果")

        jd = conn.execute("SELECT title FROM jds WHERE id=?", (task["jd_id"],)).fetchone()
        result_rows = conn.execute(
            "SELECT resume_id, rank, score, evidence_json, detail_json FROM match_results "
            "WHERE task_id=? ORDER BY rank",
            (task_id,),
        ).fetchall()
        # 候选人名：取该简历的 name 实体；没有则占位（契约：候选人{resume_id}）
        name_rows = conn.execute(
            "SELECT e.resume_id, e.field_value FROM entities e "
            "JOIN match_results m ON m.resume_id = e.resume_id "
            "WHERE m.task_id=? AND e.field_key='name'",
            (task_id,),
        ).fetchall()
    finally:
        conn.close()

    names = {r["resume_id"]: r["field_value"] for r in name_rows}
    items = [
        {
            "rank": r["rank"],
            "resume_id": r["resume_id"],
            "candidate_name": names.get(r["resume_id"], f"候选人{r['resume_id']}"),
            "score": r["score"],
            "score_detail": json.loads(r["detail_json"]) if r["detail_json"] else None,
            "evidence": json.loads(r["evidence_json"] or "[]"),
        }
        for r in result_rows
    ]
    return ok({"task_id": task_id, "jd_title": jd["title"] if jd else "", "items": items})


@router.get("/api/match-tasks/{task_id}/score_distribution")
def match_task_score_distribution(task_id: int):
    """全量分数分布（T40，API-18）：全部候选简历的融合分（降序），分布图用。

    历史任务（分布存档表无行）返回空列表，前端据此隐藏分布图，不算错误。
    """
    conn = get_db()
    try:
        task = conn.execute(
            "SELECT id, status, jd_id FROM match_tasks WHERE id=?", (task_id,)
        ).fetchone()
        if task is None:
            raise AppError(ErrorCode.NOT_FOUND, f"任务 {task_id} 不存在")
        if task["status"] != "done":
            raise AppError(ErrorCode.CONFLICT, f"任务尚未完成（当前 {task['status']}），完成后再取结果")
        dist = conn.execute(
            "SELECT n_candidates, scores_json, ids_json FROM match_score_dist WHERE task_id=?",
            (task_id,),
        ).fetchone()
        jd = conn.execute("SELECT title FROM jds WHERE id=?", (task["jd_id"],)).fetchone()
    finally:
        conn.close()

    scores = json.loads(dist["scores_json"]) if dist else []
    # T43 候选人明细（与 scores 严格同序）：点柱子反查分数段简历用；历史任务无存档为空数组
    items = json.loads(dist["ids_json"]) if dist and dist["ids_json"] else []
    return ok({
        "task_id": task_id,
        "jd_title": jd["title"] if jd else "",
        "n_candidates": dist["n_candidates"] if dist else 0,
        "scores": scores,
        "items": items,
    })


@router.get("/api/model/info")
def model_info():
    """模型信息：训练产物 metrics.json 存在则真实指标，否则如实返回未训练状态。

    C9 挑刺修复：额外带 encoder 字段——当前语义编码器是 BERT 还是 TF-IDF、
    是否为故障降级及原因。此前 BERT 加载失败会静默永久降级，界面上看不出
    分数口径已经换掉。
    """
    from app.svc.embedding import encoder_status

    enc = encoder_status()
    if METRICS_FILE.exists():
        metrics = json.loads(METRICS_FILE.read_text(encoding="utf-8"))
        return ok({
            "model_name": "bert-base-chinese-ner",
            "version": metrics.get("version", "v1"),
            "f1": float(metrics.get("f1", 0.0)),
            "train_samples": int(metrics.get("train_samples", 0)),
            "updated_at": metrics.get("trained_at", ""),
            "encoder": enc,
        })
    label = "bert-base-chinese（语义编码）；NER=规则兜底（微调模型未就位）" if enc["kind"] == "bert" \
        else "TF-IDF 降级编码；NER=规则兜底（模型环境缺失）"
    return ok({
        "model_name": label,
        "version": "v0-rules",
        "f1": 0.0,
        "train_samples": 0,
        "updated_at": "",
        "encoder": enc,
    })
