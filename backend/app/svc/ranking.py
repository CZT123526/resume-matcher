"""S06 余弦相似度排名（向量已 L2 归一化，点积即余弦）。"""
import numpy as np

from app.svc import vectors as vectors_mod


def cosine_rank(jd_vector: np.ndarray, top_k: int) -> list[dict]:
    """岗位向量 × 简历缓存矩阵 → Top-K [{resume_id, score}]。

    score = (1 + cos) / 2 归一到 0~1，4 位小数（算法设计 §3.2）。
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
