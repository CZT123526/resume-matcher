"""排序质量指标（算法设计 §6）：二值增益 NDCG@K 与 P@K。

口径与文档一致：
- DCG = Σ rel_i / log2(i+1)（i 从 1 起）；
- NDCG = DCG / IDCG（理想排序）；无正样本的查询（IDCG=0）由调用方剔除；
- P@K 分母取 min(k, 列表实际长度)。
"""
import math


def _dcg(ranked_rels: list[int]) -> float:
    return sum(rel / math.log2(i + 2) for i, rel in enumerate(ranked_rels))


def ndcg_at_k(ranked_rels: list[int], k: int = 10) -> float:
    """二值增益 NDCG@K；空列表或无正样本返回 0.0"""
    ranked = ranked_rels[:k]
    ideal = sorted(ranked_rels, reverse=True)[:k]
    idcg = _dcg(ideal)
    if idcg <= 0:
        return 0.0
    return _dcg(ranked) / idcg


def precision_at_k(ranked_rels: list[int], k: int = 5) -> float:
    """前 K 命中率，分母 min(k, len)"""
    if not ranked_rels:
        return 0.0
    top = ranked_rels[:k]
    return sum(1 for r in top if r > 0) / len(top)
