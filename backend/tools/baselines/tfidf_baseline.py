"""对照组一：TF-IDF + 余弦（算法设计 §7 M04 实验协议）。

公平性原则——同测试集、同金标准，唯一变量是方法：
- 简历侧与 JD 侧的文本构造完全复用主系统（vectors.structured_text /
  match_pipeline.jd_encode_text），本模块只把编码器从 BERT 换成 TF-IDF；
- 词表在当前简历库上独立拟合，不依赖运行时向量缓存，可单独复现。
"""
import numpy as np


def rank_for_jds(
    jd_texts: dict[int, str], resume_texts: dict[int, str]
) -> dict[int, list[tuple[int, float]]]:
    """对每个 JD 返回按相关度降序的 [(resume_id, score)]，score=(1+cos)/2 与主系统同口径。

    jd_texts: {jd_id: 查询文本}；resume_texts: {resume_id: 结构化文本}
    """
    from app.svc.embedding import _TfidfEncoder

    if not jd_texts or not resume_texts:
        return {jid: [] for jid in jd_texts}

    rids = sorted(resume_texts)
    corpus = [resume_texts[rid] for rid in rids]
    encoder = _TfidfEncoder().fit(corpus)
    resume_mat = encoder.encode(corpus)
    jd_mat = encoder.encode([jd_texts[jid] for jid in jd_texts])

    # 归一化向量内积即余弦
    sims = jd_mat @ resume_mat.T  # (J, R)
    result: dict[int, list[tuple[int, float]]] = {}
    for row, jid in enumerate(jd_texts):
        scores = np.clip((1.0 + sims[row]) / 2.0, 0.0, 1.0)
        pairs = sorted(zip(rids, scores.round(4)), key=lambda p: p[1], reverse=True)
        result[jid] = [(int(rid), float(s)) for rid, s in pairs]
    return result
