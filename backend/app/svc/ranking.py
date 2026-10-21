"""S06 余弦相似度排名 + S06b 关键词重排（向量已 L2 归一化，点积即余弦）。"""
import numpy as np

from app.svc import vectors as vectors_mod


def cosine_rank(jd_vector: np.ndarray, top_k: int) -> list[dict]:
    """岗位向量 × 简历缓存矩阵 → Top-K [{resume_id, score}]。

    score = (1 + cos) / 2 归一到 0~1，4 位小数（算法设计 §3.2）。
    T34 起作为纯语义消融对照路保留（对照 hybrid_rank）。
    """
    cached = vectors_mod.load_cache()
    if cached is None:
        cached = vectors_mod.ensure_cache()
    matrix, order = cached

    sims = matrix @ jd_vector.reshape(-1)          # 归一化后点积 ∈ [-1, 1]
    scores = np.clip((1.0 + sims) / 2.0, 0.0, 1.0)

    top = np.argsort(-scores)[: max(int(top_k), 0)]
    return [
        {"resume_id": int(order[i]), "score": round(float(scores[i]), 4)}
        for i in top
    ]


def hybrid_scores(jd_vector: np.ndarray, lex_scores: dict[int, float],
                  alpha: float) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """S06b 全量融合分（T40 抽出共用）：返回 (final, bert, lex, order)，均为缓存顺序。

    hybrid_rank 与匹配任务的分布存档（match_score_dist）共用本函数，
    保证 Top-K 排名与分布图**同一批分数**——两处各自实现必然漂移。
    T42 起同时返回构成明细：final = α·bert + (1−α)·lex，供结果卡展示分数来源。
    lex_scores 缺失的简历按中性 0.5 计（与 keyword_hit_score 无关键词口径一致）。
    """
    cached = vectors_mod.load_cache()
    if cached is None:
        cached = vectors_mod.ensure_cache()
    matrix, order = cached

    sims = matrix @ jd_vector.reshape(-1)
    bert = np.clip((1.0 + sims) / 2.0, 0.0, 1.0)
    lex = np.array(
        [lex_scores.get(int(rid), 0.5) for rid in order], dtype=float
    )
    final = np.clip(alpha * bert + (1.0 - alpha) * lex, 0.0, 1.0)
    return final, bert, lex, order


def hybrid_rank(jd_vector: np.ndarray, lex_scores: dict[int, float],
                top_k: int, alpha: float) -> list[dict]:
    """S06b 关键词重排（T34）：融合分 = α·语义分 + (1-α)·词面分 后取 Top-K。

    词面分必须对**全部**缓存简历算好再融合——若先 top-k 再补词面分，
    语义分挤掉的正确候选人永远进不了候选集。
    """
    final, _bert, _lex, order = hybrid_scores(jd_vector, lex_scores, alpha)
    top = np.argsort(-final)[: max(int(top_k), 0)]
    return [
        {"resume_id": int(order[i]), "score": round(float(final[i]), 4)}
        for i in top
    ]
