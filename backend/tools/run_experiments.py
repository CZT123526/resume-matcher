"""M04 三组对比实验统一入口（算法设计 §7）。

同测试集、同金标准、固定 seed，唯一变量是方法：
  本文方法   BERT 语义匹配（svc 主链路同款编码器）
  对照组一   TF-IDF + 余弦（tools/baselines/tfidf_baseline.py）
  对照组二   DeepSeek 零样本（tools/baselines/deepseek_zeroshot.py，无 key 自动跳过）

用法（backend 目录下）：
  python tools/run_experiments.py
产物：
  docs/eval/metrics.json   各组 NDCG@10 / P@5 / 排序耗时
  docs/eval/ndcg_chart.png 对比柱状图
红线复查：实验代码只在 tools/ 下，backend/app/ 零外部 API 调用（TC-API-01）。
"""
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/

from tools.baselines.tfidf_baseline import rank_for_jds
from tools.eval.metrics import ndcg_at_k, precision_at_k

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "docs" / "eval"
GOLD_FILE = Path(__file__).resolve().parent / "eval" / "gold.jsonl"


def load_or_build_gold() -> list[dict]:
    if GOLD_FILE.exists():
        return [json.loads(line) for line in GOLD_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]
    print("gold.jsonl 不存在，自动按 §5 规则构造（之后可人工抽检修正）…")
    from tools.eval.build_gold import build, GOLD_FILE as GF

    pairs = build()
    GF.write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in pairs), encoding="utf-8")
    return pairs


def load_corpus() -> tuple[dict[int, str], dict[int, str]]:
    """与主系统完全一致的简历/JD 编码文本（唯一变量是编码器）"""
    from app.db import get_db
    from app.svc.match_pipeline import jd_encode_text
    from app.svc.vectors import _current_resume_data, structured_text

    data = _current_resume_data()
    resume_texts = {rid: structured_text(item) for rid, item in data.items()}

    conn = get_db()
    try:
        jd_rows = conn.execute("SELECT id, title, content, req_json FROM jds").fetchall()
    finally:
        conn.close()
    jd_texts = {
        r["id"]: jd_encode_text(r["title"], json.loads(r["req_json"] or "{}"), (r["content"] or "")[:500])
        for r in jd_rows
    }
    return resume_texts, jd_texts


def rank_bert(jd_texts: dict[int, str], resume_texts: dict[int, str]) -> tuple[dict[int, list[tuple[int, float]]], str, float]:
    """走主系统同款链路（向量缓存 + 查询编码器）；返回 (排序, 编码器名, 耗时秒)"""
    from app.svc.vectors import ensure_cache, load_query_encoder

    matrix, order = ensure_cache()
    encoder = load_query_encoder()
    rid_index = {rid: i for i, rid in enumerate(order)}

    t0 = time.perf_counter()
    q_mat = encoder.encode(list(jd_texts.values()))
    sims = q_mat @ matrix[[rid_index[r] for r in sorted(resume_texts)]].T
    elapsed = time.perf_counter() - t0

    rids = sorted(resume_texts)
    result: dict[int, list[tuple[int, float]]] = {}
    for row, jid in enumerate(jd_texts):
        scores = np.clip((1.0 + sims[row]) / 2.0, 0.0, 1.0)
        result[jid] = sorted(zip(rids, scores.round(4)), key=lambda p: p[1], reverse=True)
    return result, encoder.kind, elapsed


def evaluate_group(ranking: dict[int, list[tuple[int, float]]], gold: list[dict], k_ndcg: int = 10, k_p: int = 5) -> tuple[float, float, int]:
    """在金标准判定集上求平均 NDCG@10 与 P@5；无正样本的查询剔除"""
    by_jd: dict[int, dict[int, int]] = {}
    for p in gold:
        by_jd.setdefault(p["jd_id"], {})[p["resume_id"]] = p["rel"]

    ndcgs, ps = [], []
    for jd_id, judged in by_jd.items():
        if not any(rel > 0 for rel in judged.values()):
            continue
        scored = ranking.get(jd_id, [])
        rels = [judged[rid] for rid, _ in scored if rid in judged]
        # 金标准里可能混入当次未入排序库的简历——补在尾部（系统给不出分 = 最差）
        missing = [rel for rid, rel in judged.items() if rid not in {r for r, _ in scored}]
        rels += missing
        ndcgs.append(ndcg_at_k(rels, k_ndcg))
        ps.append(precision_at_k(rels, k_p))
    n = len(ndcgs) or 1
    return sum(ndcgs) / n, sum(ps) / n, len(ndcgs)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows GBK 控制台打 ⚠ 会崩
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    gold = load_or_build_gold()
    if not gold:
        print("金标准为空：库内缺 JD 或缺带 title 实体的简历")
        return 1
    resume_texts, jd_texts = load_corpus()
    n_queries = len({p["jd_id"] for p in gold})
    print(f"金标准 {len(gold)} 对 / {n_queries} 个 JD 查询 / 简历库 {len(resume_texts)} 份")
    if n_queries < 5:
        print("⚠ 查询数 <5，NDCG 结果方差大，仅作链路演示——正式实验请构造多岗位 JD 后重建金标准\n")

    metrics: dict = {"n_pairs": len(gold), "n_queries": n_queries, "n_resumes": len(resume_texts), "groups": {}}

    # 本文方法：BERT（或其降级路径，如实记录）
    bert_ranking, encoder_kind, elapsed = rank_bert(jd_texts, resume_texts)
    ndcg, p5, n_eval = evaluate_group(bert_ranking, gold)
    metrics["groups"]["BERT语义匹配"] = {
        "ndcg@10": round(ndcg, 4), "p@5": round(p5, 4), "queries": n_eval,
        "encoder": encoder_kind, "rank_seconds": round(elapsed, 3),
        "note": "" if encoder_kind == "bert" else "BERT 不可用，主链路已降级 TF-IDF——如实记录",
    }
    print(f"本文方法({encoder_kind}): NDCG@10={ndcg:.4f}  P@5={p5:.4f}  排序耗时 {elapsed:.2f}s")

    # 对照组一：TF-IDF
    t0 = time.perf_counter()
    tfidf_ranking = rank_for_jds(jd_texts, resume_texts)
    tfidf_elapsed = time.perf_counter() - t0
    ndcg, p5, n_eval = evaluate_group(tfidf_ranking, gold)
    metrics["groups"]["TF-IDF基线"] = {
        "ndcg@10": round(ndcg, 4), "p@5": round(p5, 4), "queries": n_eval,
        "rank_seconds": round(tfidf_elapsed, 3),
    }
    print(f"对照组一(TF-IDF): NDCG@10={ndcg:.4f}  P@5={p5:.4f}  排序耗时 {tfidf_elapsed:.2f}s")

    # 对照组二：DeepSeek（无 key 干净跳过）
    from tools.baselines.deepseek_zeroshot import DeepSeekScorer

    scorer = DeepSeekScorer()
    if scorer.available():
        by_jd: dict[int, dict[int, int]] = {}
        for p in gold:
            by_jd.setdefault(p["jd_id"], {})[p["resume_id"]] = p["rel"]
        ds_ranking: dict[int, list[tuple[int, float]]] = {}
        n_fail = 0
        for jd_id, judged in by_jd.items():
            scored = []
            for rid in judged:
                s = scorer.score(jd_texts[jd_id], resume_texts[rid])
                if s is None:
                    n_fail += 1
                    s = 0.0
                scored.append((rid, s))
            ds_ranking[jd_id] = sorted(scored, key=lambda x: x[1], reverse=True)
        ndcg, p5, n_eval = evaluate_group(ds_ranking, gold)
        metrics["groups"]["DeepSeek零样本"] = {
            "ndcg@10": round(ndcg, 4), "p@5": round(p5, 4), "queries": n_eval,
            "model": scorer.model, "failed_calls": n_fail,
            "cost_note": f"约 {len(gold)} 次调用（命中缓存不重复计费）",
        }
        print(f"对照组二(DeepSeek): NDCG@10={ndcg:.4f}  P@5={p5:.4f}  失败 {n_fail} 条")
    else:
        metrics["groups"]["DeepSeek零样本"] = {"skipped": True, "reason": "未配置 DEEPSEEK_API_KEY（见工作日志待拍板 #1）"}
        print("对照组二(DeepSeek): 跳过——未配置 DEEPSEEK_API_KEY")

    (OUT_DIR / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _plot(metrics)
    print(f"\n产物：{OUT_DIR / 'metrics.json'}\n      {OUT_DIR / 'ndcg_chart.png'}")
    return 0


def _plot(metrics: dict) -> None:
    """对比柱状图（中文字体走 Windows 微软雅黑）"""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
    plt.rcParams["axes.unicode_minus"] = False

    groups = [(name, g) for name, g in metrics["groups"].items() if "ndcg@10" in g]
    names = [name for name, _ in groups]
    ndcg_vals = [g["ndcg@10"] for _, g in groups]
    p_vals = [g["p@5"] for _, g in groups]

    x = range(len(names))
    width = 0.35
    fig, ax = plt.subplots(figsize=(7, 4.2))
    ax.bar([i - width / 2 for i in x], ndcg_vals, width, label="NDCG@10", color="#4C72B0")
    ax.bar([i + width / 2 for i in x], p_vals, width, label="P@5", color="#DD8452")
    for i, (n, p) in enumerate(zip(ndcg_vals, p_vals)):
        ax.text(i - width / 2, n + 0.01, f"{n:.3f}", ha="center", fontsize=9)
        ax.text(i + width / 2, p + 0.01, f"{p:.3f}", ha="center", fontsize=9)
    ax.set_xticks(list(x))
    ax.set_xticklabels(names)
    ax.set_ylim(0, 1.05)
    ax.set_title("匹配排序质量对比（同金标准）")
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUT_DIR / "ndcg_chart.png", dpi=150)


if __name__ == "__main__":
    sys.exit(main())
