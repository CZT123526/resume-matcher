"""匹配任务流水线（后台任务）：缓存就绪 → JD 编码 → 重排融合 → 证据链 → 落库。"""
import json
import logging
import os

import numpy as np

from app.config import settings
from app.db import get_db
from app.svc.evidence import compute_evidence
from app.svc.jd_parsing import build_jd_requirements
from app.svc.lexical import adaptive_alpha, coverage_from_scores, extract_jd_keywords, keyword_hit_score
from app.svc.ranking import hybrid_scores
from app.svc.vectors import _current_resume_data, ensure_cache, load_query_encoder, structured_text

logger = logging.getLogger(__name__)


def _fuse_rounded(sem: float, lex: float, alpha: float) -> float:
    """存档口径的融合分（C10 挑刺修复）：分量先按契约舍入 4 位、α 同精度，
    再融合舍入——保证从存档的 detail_json（semantic/lexical/alpha）能**精确**
    复算出存档 score。此前 score 从全精度融合值舍入，验算恒差 1e-4（实测
    400 行历史结果 82 行对不上）。排序仍在全精度 final 上做，位级差不会改变名次。"""
    a = round(float(alpha), 4)
    return round(a * round(float(sem), 4) + (1 - a) * round(float(lex), 4), 4)


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
        # 认领任务：盖属主进程 pid（B2）——另一进程启动清扫时探活跳过，不再误杀
        conn.execute(
            "UPDATE match_tasks SET status='running', progress=5, owner_pid=? WHERE id=?",
            (os.getpid(), task_id),
        )
        conn.commit()

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
        alpha = settings.MATCH_ALPHA
        if settings.MATCH_ADAPTIVE_ALPHA:
            # T39 自适应 α：JD 关键词在语料里普遍找不到（覆盖率低）时词面分失去
            # 区分度，按覆盖线性退向纯语义；覆盖满格时 α_eff=base 行为不变
            alpha = adaptive_alpha(alpha, coverage_from_scores(lex_scores.values()))
            logger.info("自适应 α：coverage=%.3f → α_eff=%.3f（base=%.2f）",
                        coverage_from_scores(lex_scores.values()), alpha, settings.MATCH_ALPHA)
        # T40：Top-K 与全量分布同源——hybrid_scores 一次融合，排名就地截断，
        # 全量分数降序存档 match_score_dist（分布图接口读它，不二次计算）。
        # 存档分数一律走 _fuse_rounded（C10）：排序看全精度 final，落库用舍入分量
        # 复算值——两处同一函数，不会出现结果卡与分布图对不上
        final, bert_arr, lex_arr, order = hybrid_scores(jd_vec, lex_scores, alpha=alpha)
        arch = [_fuse_rounded(b, l, alpha) for b, l in zip(bert_arr, lex_arr)]
        top = np.argsort(-final)[: max(int(top_k), 0)]
        ranked = [
            {"resume_id": int(order[i]), "score": arch[i],
             "semantic": round(float(bert_arr[i]), 4), "lexical": round(float(lex_arr[i]), 4)}
            for i in top
        ]
        # T43 全量分数 + 候选人明细：先按 简历×分数 配对再降序，保证 scores 与
        # items 严格同序（前端点分布图柱子时按下标反查"这个分数段是谁"）。
        # 名字取 name 实体，缺失则占位 候选人{id}（与结果接口同口径）
        name_rows = conn.execute(
            "SELECT resume_id, field_value FROM entities WHERE field_key='name'"
        ).fetchall()
        names = {int(r["resume_id"]): r["field_value"] for r in name_rows}
        dist_items = sorted(
            ({"resume_id": int(rid), "score": arch[i],
              "name": names.get(int(rid), f"候选人{rid}")}
             for i, rid in enumerate(order)),
            key=lambda x: x["score"], reverse=True,
        )
        dist_scores = [x["score"] for x in dist_items]
        conn.execute(
            "INSERT INTO match_score_dist(task_id, n_candidates, scores_json, ids_json) VALUES(?,?,?,?) "
            "ON CONFLICT(task_id) DO UPDATE SET n_candidates=excluded.n_candidates, "
            "scores_json=excluded.scores_json, ids_json=excluded.ids_json",
            (task_id, len(dist_scores), json.dumps(dist_scores), json.dumps(dist_items, ensure_ascii=False)),
        )
        _set(conn, "running", 85)

        rows = []
        for rank, item in enumerate(ranked, start=1):
            ent_rows = conn.execute(
                "SELECT field_key, field_value, source FROM entities WHERE resume_id=?",
                (item["resume_id"],),
            ).fetchall()
            entities = [dict(r) for r in ent_rows]
            evidence = compute_evidence(req, entities)
            detail = {"semantic": item["semantic"], "lexical": item["lexical"],
                      "alpha": round(float(alpha), 4)}
            rows.append((task_id, item["resume_id"], rank, item["score"],
                         json.dumps(evidence, ensure_ascii=False), json.dumps(detail)))
        conn.execute("DELETE FROM match_results WHERE task_id=?", (task_id,))
        conn.executemany(
            "INSERT INTO match_results(task_id, resume_id, rank, score, evidence_json, detail_json) "
            "VALUES(?,?,?,?,?,?)",
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
