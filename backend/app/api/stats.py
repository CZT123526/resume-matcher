"""主页统计接口（API-19，T48）：库规模总览与两类排名，契约见 docs/backend-api.md §6。

纪律：本层只读聚合、无写入；全部查询是本地 SQLite 千行级小计数，
排名类查询带 LIMIT。语料时间窗复用简历模块的 _corpus_conds（单一数据源，不复制常量）。
"""
from fastapi import APIRouter

from app.api.resumes import _corpus_conds
from app.common.format import iso_time
from app.common.response import ok
from app.db import get_db

router = APIRouter(tags=["stats"])

TITLE_RANK_LIMIT = 10  # 应聘岗位排名条数
JD_RANK_LIMIT = 10     # 岗位储备排名条数


@router.get("/api/stats/home")
def home_stats():
    """主页总览：简历五类计数、岗位库规模、解析与匹配覆盖，及两类排名。

    - title_rank（简历应聘岗位排名）：按解析出的任职/应聘岗位名称统计简历数，
      一份简历可命中多个岗位名、均计入；
    - jd_rank（岗位人才储备排名）：每个岗位取最近一次完成的匹配任务，
      召回简历数按当次任务的召回设置如实记录（不同任务的召回人数设置不同，
      历史数据只展示不补算）；从未跑过匹配的岗位不进榜，用 jd_covered 如实披露覆盖面。
    """
    biz_cond = _corpus_conds("business")[0]
    rw_cond = _corpus_conds("rewrite")[0]
    sw_cond = _corpus_conds("semispec")[0]
    fr_cond = _corpus_conds("fresh")[0]

    conn = get_db()
    try:
        n_all, n_biz, n_rw, n_sw, n_fr, n_done = conn.execute(
            f"SELECT COUNT(*),"
            f" SUM(CASE WHEN {biz_cond} THEN 1 ELSE 0 END),"
            f" SUM(CASE WHEN {rw_cond} THEN 1 ELSE 0 END),"
            f" SUM(CASE WHEN {sw_cond} THEN 1 ELSE 0 END),"
            f" SUM(CASE WHEN {fr_cond} THEN 1 ELSE 0 END),"
            f" SUM(CASE WHEN parse_status='done' THEN 1 ELSE 0 END)"
            " FROM resumes"
        ).fetchone()
        jd_count = conn.execute("SELECT COUNT(*) FROM jds").fetchone()[0]
        match_done, jd_covered = conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT jd_id) FROM match_tasks WHERE status='done'"
        ).fetchone()
        title_kinds, title_resumes = conn.execute(
            "SELECT COUNT(DISTINCT field_value), COUNT(DISTINCT resume_id) FROM entities "
            "WHERE field_key='title' AND TRIM(COALESCE(field_value,''))!=''"
        ).fetchone()
        title_rows = conn.execute(
            "SELECT field_value AS title, COUNT(DISTINCT resume_id) AS n "
            "FROM entities WHERE field_key='title' AND TRIM(COALESCE(field_value,''))!='' "
            "GROUP BY field_value ORDER BY n DESC, title LIMIT ?",
            (TITLE_RANK_LIMIT,),
        ).fetchall()
        jd_rows = conn.execute(
            "SELECT t.jd_id, j.title, t.finished_at AS last_run_at,"
            " (SELECT COUNT(*) FROM match_results m WHERE m.task_id=t.id) AS recalled,"
            " (SELECT COUNT(*) FROM match_tasks t2 WHERE t2.jd_id=t.jd_id AND t2.status='done') AS task_count"
            " FROM match_tasks t JOIN jds j ON j.id=t.jd_id"
            " WHERE t.status='done' AND t.id=("
            "   SELECT MAX(t3.id) FROM match_tasks t3 WHERE t3.jd_id=t.jd_id AND t3.status='done')"
            " ORDER BY recalled DESC, t.jd_id LIMIT ?",
            (JD_RANK_LIMIT,),
        ).fetchall()
    finally:
        conn.close()

    return ok({
        "resumes": {
            "all": n_all,
            "business": n_biz or 0,
            "rewrite": n_rw or 0,
            "semispec": n_sw or 0,
            "fresh": n_fr or 0,
            "parsed_done": n_done or 0,
        },
        "jd_count": jd_count,
        "jd_covered": jd_covered,
        "match_done": match_done,
        "title_kinds": title_kinds or 0,
        "title_resumes": title_resumes or 0,
        "title_rank": [{"title": r["title"], "n": r["n"]} for r in title_rows],
        "jd_rank": [
            {
                "jd_id": r["jd_id"],
                "title": r["title"],
                "recalled": r["recalled"],
                "task_count": r["task_count"],
                "last_run_at": iso_time(r["last_run_at"]),
            }
            for r in jd_rows
        ],
    })
