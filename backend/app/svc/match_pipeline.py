"""匹配任务流水线（后台任务）：缓存就绪 → JD 编码 → 重排融合 → 证据链 → 落库。"""
import json
import logging

from app.config import settings
from app.db import get_db
from app.svc.evidence import compute_evidence
from app.svc.jd_parsing import build_jd_requirements
from app.svc.lexical import extract_jd_keywords, keyword_hit_score
from app.svc.ranking import hybrid_rank
from app.svc.vectors import _current_resume_data, ensure_cache, load_query_encoder, structured_text

logger = logging.getLogger(__name__)


def jd_encode_text(title: str, req: dict, content: str) -> str:
    """JD 编码文本（算法设计 §3.1）：结构化要求 + 原文前500字"""
    parts = [title]
    if req:
        skills = "/".join(req.get("skills") or [])
        parts.append(
            f"学历要求：{req.get('degree') or '不限'}；"
            f"经验要求：{req.get('min_years') if req.get('min_years') is not None else '不限'}年；"
            f"技能：{skills or '不限'}"
        )
    parts.append(content[:500])
    return "\n".join(parts)


def run_match_pipeline(task_id: int, jd_id: int, top_k: int) -> None:
    """后台执行匹配任务。任何异常落为 failed，不抛出。"""

    def _set(conn, status: str, progress: int, error: str | None = None):
        conn.execute(
            "UPDATE match_tasks SET status=?, progress=?, error=? WHERE id=?",
            (status, progress, error, task_id),
        )
        conn.commit()

    conn = get_db()
    try:
        _set(conn, "running", 5)

        jd = conn.execute(
            "SELECT id, title, content, req_json FROM jds WHERE id=?", (jd_id,)
        ).fetchone()
        if jd is None:
            _set(conn, "failed", 0, f"JD {jd_id} 不存在")
            return

        req = json.loads(jd["req_json"]) if jd["req_json"] else None
        if not req:  # 历史数据无 req_json → 现场补抽并回写
            req = build_jd_requirements(jd["content"])
            conn.execute(
                "UPDATE jds SET req_json=? WHERE id=?",
                (json.dumps(req, ensure_ascii=False), jd_id),
            )
            conn.commit()
        _set(conn, "running", 10)

        def rebuild_progress(pct: int):
            """缓存重建占任务进度 10%~60%"""
            _set(conn, "running", 10 + int(pct * 0.5))

        ensure_cache(progress_cb=rebuild_progress)
        _set(conn, "running", 65)

        jd_vec = load_query_encoder().encode([jd_encode_text(jd["title"], req, jd["content"])])[0]
        _set(conn, "running", 75)

        # T34 关键词重排：词面分对全部简历先算好再融合（top-k 截断之前），
        # 词面核查对象与编码同源（structured_text），评测与线上同口径
        keywords = extract_jd_keywords(jd["title"], req)
        resume_texts = {
            rid: structured_text(item) for rid, item in _current_resume_data().items()
        }
        lex_scores = {
            rid: keyword_hit_score(keywords, text) for rid, text in resume_texts.items()
        }
        ranked = hybrid_rank(jd_vec, lex_scores, top_k, alpha=settings.MATCH_ALPHA)
        _set(conn, "running", 85)

        rows = []
        for rank, item in enumerate(ranked, start=1):
            ent_rows = conn.execute(
                "SELECT field_key, field_value, source FROM entities WHERE resume_id=?",
                (item["resume_id"],),
            ).fetchall()
            entities = [dict(r) for r in ent_rows]
            evidence = compute_evidence(req, entities)
            rows.append((task_id, item["resume_id"], rank, item["score"],
                         json.dumps(evidence, ensure_ascii=False)))
        conn.execute("DELETE FROM match_results WHERE task_id=?", (task_id,))
        conn.executemany(
            "INSERT INTO match_results(task_id, resume_id, rank, score, evidence_json) "
            "VALUES(?,?,?,?,?)",
            rows,
        )
        conn.execute(
            "UPDATE match_tasks SET status='done', progress=100, error=NULL, "
            "finished_at=datetime('now','localtime') WHERE id=?",
            (task_id,),
        )
        conn.commit()
        logger.info("匹配任务 %d 完成：%d 条结果", task_id, len(rows))
    except Exception as exc:
        try:
            conn.rollback()
            _set(conn, "failed", 0, str(exc)[:500])
        except Exception:  # 连接可能已坏
            logger.exception("匹配任务 %d 状态写失败", task_id)
        logger.warning("匹配任务 %d 失败: %s", task_id, exc)
    finally:
        conn.close()
