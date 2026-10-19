"""T39 反向推荐（优化#1）：给定一份简历，推荐最合适的 Top-K 岗位。

正向链路是「岗位找人」（run_match_pipeline：JD 向量 × 简历缓存矩阵，JD 内部排人）；
反向推荐把同一套组件反过来用——但评分必须**跨 JD 比较**，与正向不同：
裸余弦分有每岗位各自的基线（宽泛岗给谁都 0.98+，T32 分数聚集的镜像问题），
裸词面命中率在关键词稀疏的岗上虚高（实测 1 词岗位白拿 1.0）。因此反向侧做
双侧校准（§3.2c）：语义 = 池内百分位，词面 = 关键词稀疏时向中性收缩，融合
公式与 α 沿用 §3.2。正向链路不受影响（JD 内部排序对单调变换不敏感）。

与正向链路共用：
  - 编码对象构造（jd_encode_text / structured_text，§3.1 同源）；
  - 查询侧编码器（load_query_encoder，TF-IDF 降级时同一特征空间）;
  - 简历向量主缓存（ensure_cache，不另建第二份向量库）。

JD 向量按内容指纹做模块级缓存：指纹 = 编码器指纹 + 全部 JD 文本 md5——
JD 内容/数量/编码器任一变化即失效重编（课程规模 55 条 ≈ 2s，进程内复用后毫秒级）。
零外部 API（TC-API-01 红线）。
"""
import hashlib
import json
import logging

import numpy as np

from app.config import settings
from app.core.errors import AppError, ErrorCode
from app.db import get_db
from app.svc.evidence import compute_evidence
from app.svc.jd_parsing import build_jd_requirements
from app.svc.lexical import extract_jd_keywords, fuse, keyword_hit_score
from app.svc.match_pipeline import jd_encode_text
from app.svc.vectors import (
    _current_resume_data,
    _encoder_fingerprint,
    ensure_cache,
    load_query_encoder,
    structured_text,
)

logger = logging.getLogger(__name__)

# 模块级 JD 向量缓存：{"fp": 指纹, "matrix": N×D 归一化矩阵, "items": [{jd_id,title,req}]}
_JD_CACHE: dict = {"fp": None, "matrix": None, "items": []}


def _jd_vectors() -> tuple[np.ndarray, list[dict]]:
    """全量 JD 向量 + 结构化要求（指纹失效才重编码；req_json 缺失现场补抽并回写，同正向管道）"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, title, content, req_json FROM jds ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        raise AppError(ErrorCode.NOT_FOUND, "岗位库为空，请先导入 JD")

    items: list[dict] = []
    texts: list[str] = []
    dirty: list[tuple[int, str]] = []
    for r in rows:
        req = json.loads(r["req_json"]) if r["req_json"] else None
        if not req:
            req = build_jd_requirements(r["content"])
            dirty.append((r["id"], json.dumps(req, ensure_ascii=False)))
        items.append({"jd_id": r["id"], "title": r["title"], "req": req})
        texts.append(jd_encode_text(r["title"], req, r["content"]))

    fp = f"{_encoder_fingerprint()}:{hashlib.md5(' '.join(texts).encode('utf-8')).hexdigest()}:{len(texts)}"
    if _JD_CACHE["fp"] == fp and _JD_CACHE["matrix"] is not None:
        return _JD_CACHE["matrix"], _JD_CACHE["items"]

    if dirty:
        conn = get_db()
        try:
            conn.executemany("UPDATE jds SET req_json=? WHERE id=?", dirty)
            conn.commit()
        finally:
            conn.close()

    matrix = np.stack(load_query_encoder().encode(texts)).astype(np.float32)
    _JD_CACHE["fp"] = fp
    _JD_CACHE["matrix"] = matrix
    _JD_CACHE["items"] = items
    logger.info("JD 向量缓存构建：%d 条（指纹 %s…）", len(items), fp[:24])
    return matrix, items


def recommend_jds_for_resume(resume_id: int, top_k: int = 3) -> dict:
    """反向推荐主入口：{resume_id, items: [{jd_id, title, score, evidence}]}（score 降序）。

    简历必须 done 且已在向量缓存中；top_k 截断在融合**之后**（与正向同红线：
    词面分对全量 JD 算完再融合，不在语义 top-k 里补算）。
    """
    matrix, order = ensure_cache()
    if resume_id not in order:
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT parse_status FROM resumes WHERE id=?", (resume_id,)
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            raise AppError(ErrorCode.NOT_FOUND, f"简历 {resume_id} 不存在")
        raise AppError(
            ErrorCode.BAD_PARAM,
            f"简历 {resume_id} 尚未解析完成（状态 {row['parse_status']}），无法推荐岗位",
        )
    ridx = order.index(resume_id)

    jd_matrix, jd_items = _jd_vectors()
    resume_data = _current_resume_data()
    st_text = structured_text(resume_data[resume_id])

    # 反向推荐是**跨 JD 比较**，与正向（JD 内部排人）不同：裸余弦分有每岗位各自的
    # 基线与离散度（宽泛岗给谁都 0.98+），裸词面命中率在关键词稀疏的岗上虚高
    # （实测：网络工程师只抽出 1 个词白拿 1.0，Java 岗 8 词命中 0.5 反而吃亏）——
    # 直接融合会把 Java 简历推去「网络工程师」。双侧校准（§3.2c）：
    #   语义侧 = 简历语义分在该岗位全池分布中的百分位（"比池里 X% 的人更像本岗"）；
    #   词面侧 = 命中率向中性 0.5 收缩，关键词 <3 个按 n/3 折扣（证据不足少说话）；
    # 融合公式与 α 沿用 §3.2。正向链路不动（JD 内部排序对单调变换不敏感）。
    bert_pool = matrix @ jd_matrix.T                       # (n_resumes, n_jds) 全池×全岗
    sim_row = bert_pool[ridx]                              # 该简历对全部 JD 的语义分
    bert_cal = (bert_pool < sim_row).mean(axis=0)          # 每 JD 的池内百分位 ∈ [0,1]

    fused: list[dict] = []
    for i, item in enumerate(jd_items):
        keywords = extract_jd_keywords(item["title"], item["req"])
        lex = keyword_hit_score(keywords, st_text)
        lex_cal = 0.5 + (lex - 0.5) * min(1.0, len(keywords) / 3.0)
        score = float(np.clip(fuse(float(bert_cal[i]), lex_cal, settings.MATCH_ALPHA), 0.0, 1.0))
        fused.append({**item, "score": round(score, 4),
                      "semantic_percentile": round(float(bert_cal[i]), 4),
                      "keyword_hit": round(lex, 4), "n_keywords": len(keywords)})
    fused.sort(key=lambda x: -x["score"])
    top = fused[: max(min(int(top_k), 20), 1)]

    conn = get_db()
    try:
        ent_rows = conn.execute(
            "SELECT field_key, field_value, source FROM entities WHERE resume_id=?",
            (resume_id,),
        ).fetchall()
    finally:
        conn.close()
    entities = [dict(r) for r in ent_rows]

    return {
        "resume_id": resume_id,
        "items": [
            {
                "jd_id": t["jd_id"],
                "title": t["title"],
                "score": t["score"],
                "semantic_percentile": t["semantic_percentile"],
                "keyword_hit": t["keyword_hit"],
                "n_keywords": t["n_keywords"],
                "evidence": compute_evidence(t["req"], entities),
            }
            for t in top
        ],
    }
