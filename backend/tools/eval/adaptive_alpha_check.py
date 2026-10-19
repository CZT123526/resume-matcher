"""自适应 α 验证（T39/B2，算法设计 §3.2b）：回答"开开关后主卷动不动、压力卷救不救"。

背景（T37 结论）：改写压力考卷上关键词重排层是**拖累**——DAPT 纯语义 0.8774 →
融合 0.8400。原因是正文避开岗位词后，词面命中率整体塌到低位、失去区分度，
(1-α) 权重反而放大噪声。自适应 α 的对策：词面覆盖率（命中率≥0.5 的简历占比）
低 → α_eff = base + (1-base)·(1-coverage) 线性退向纯语义；覆盖满格 → α_eff=base
行为不变。本脚本在同一 DAPT 编码上对比三个池：

  池           固定 α=0.7        自适应 α         语义上限(α=1)
  v4 主卷      必须≈0.9305       应≈0.9305        0.7483
  压力考卷     必须≈0.8400       预期↑向 0.8774   0.8774
  半规范考卷   （T38 新增基线）   （观察）          （观察）

v4 池精确重建：当前库简历 − 压力 manifest − 半规范 manifest = 当时的 1062 份；
金标准读冻结的 gold.jsonl（§5 v4 口径，8142 对/1357 正/46 查询）——固定 α 复现
0.9305 即证明"重建池 = 冻结池"，且开关默认关时线上行为零扰动。

用法（backend 目录下）：
  python tools/eval/adaptive_alpha_check.py [--expect-v4 0.9305] [--expect-stress 0.8400]
产物：docs/eval/adaptive_alpha_report.json
不需要 DeepSeek key（纯融合层对比，语义分全部复用 DAPT 一次编码）。
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # backend/

REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = REPO_ROOT / "docs" / "eval"
STRESS_MANIFEST = REPO_ROOT.parent / "测试简历" / "stress_manifest.json"
SEMISPEC_MANIFEST = REPO_ROOT.parent / "测试简历" / "semispec_manifest.json"
BASE_ALPHA = 0.7


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def manifest_names(path: Path) -> set[str]:
    return {m["file_name"] for m in json.loads(path.read_text(encoding="utf-8"))["files"]}


def role_of_by_filename(pool_rids, rid_file: dict[int, str]) -> dict[int, str]:
    """文件名「姓名_角色.docx」→ 角色（与金标准 §5 路径一同依据）"""
    out = {}
    for rid in pool_rids:
        m = re.match(r"^(.*)_(.+)\.docx$", rid_file.get(rid, ""))
        out[rid] = m.group(2) if m else ""
    return out


def rank_fusion_adaptive(jd_meta: dict, resume_texts: dict, bert_ranking: dict,
                         base_alpha: float) -> tuple[dict, list[dict]]:
    """自适应 α 融合（与 rank_fusion 同口径，唯一差异是 α_eff 按 JD 逐个算）"""
    from app.svc.lexical import (
        adaptive_alpha,
        coverage_from_scores,
        extract_jd_keywords,
        fuse,
        keyword_hit_score,
    )

    out: dict = {}
    stats: list[dict] = []
    for jid, scored in bert_ranking.items():
        title, req = jd_meta.get(jid, ("", {}))
        kws = extract_jd_keywords(title, req)
        lex = {rid: keyword_hit_score(kws, resume_texts[rid]) for rid, _ in scored}
        cov = coverage_from_scores(lex.values())
        a_eff = adaptive_alpha(base_alpha, cov)
        stats.append({"jd_id": jid, "n_keywords": len(kws),
                      "coverage": round(cov, 4), "alpha_eff": round(a_eff, 4)})
        fused = [(rid, round(fuse(b, lex[rid], a_eff), 4)) for rid, b in scored]
        out[jid] = sorted(fused, key=lambda p: p[1], reverse=True)
    return out, stats


def alpha_stats_summary(stats: list[dict]) -> dict:
    covs = [s["coverage"] for s in stats]
    alphas = [s["alpha_eff"] for s in stats]
    return {
        "n_jds": len(stats),
        "coverage": {"min": min(covs), "mean": round(sum(covs) / len(covs), 4), "max": max(covs)},
        "alpha_eff": {"min": min(alphas), "mean": round(sum(alphas) / len(alphas), 4), "max": max(alphas)},
        "jds_alpha_moved": sum(1 for a in alphas if abs(a - BASE_ALPHA) > 1e-9),
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="自适应 α 验证")
    ap.add_argument("--expect-v4", type=float, default=None, help="v4 固定 α 复现值（给了就硬断言）")
    ap.add_argument("--expect-stress", type=float, default=None, help="压力卷固定 α 复现值（给了就硬断言）")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    from app.db import get_db
    from tools.eval.stress_eval import build_stress_gold, load_pool
    from tools.run_experiments import evaluate_group, load_corpus, load_or_build_gold, rank_fusion, rank_with_encoder

    # ---- 全库语料（structured_text 与线上同源）与三个池 ----
    resume_texts, jd_texts, jd_meta = load_corpus()
    jd_titles = {jid: title for jid, (title, _) in jd_meta.items()}

    conn = get_db()
    try:
        all_rid_file = {r["id"]: r["file_name"] for r in
                        conn.execute("SELECT id, file_name FROM resumes WHERE parse_status='done'")}
    finally:
        conn.close()

    excluded = manifest_names(STRESS_MANIFEST) | manifest_names(SEMISPEC_MANIFEST)
    v4_rids = [rid for rid, fn in all_rid_file.items() if fn not in excluded]
    n_excluded = len(all_rid_file) - len(v4_rids)
    log(f"v4 池重建：全库 {len(all_rid_file)} − 考卷 {n_excluded} = {len(v4_rids)} 份（应 1062）")

    stress_pool, stress_role, _ = load_pool(STRESS_MANIFEST)
    semispec_pool, _, _ = load_pool(SEMISPEC_MANIFEST)
    semispec_role = role_of_by_filename(semispec_pool, all_rid_file)

    pools: dict[str, dict] = {
        "v4主卷": {"pool": {rid: resume_texts[rid] for rid in v4_rids}},
        "压力考卷": {"pool": stress_pool},
        "半规范考卷": {"pool": semispec_pool},
    }

    # ---- 金标准：v4 用冻结 gold.jsonl；两份考卷按文件名角色现造（seed 同主实验）----
    pools["v4主卷"]["gold"] = load_or_build_gold()
    pools["压力考卷"]["gold"] = build_stress_gold(stress_pool, stress_role, jd_titles, 5, args.seed)
    pools["半规范考卷"]["gold"] = build_stress_gold(semispec_pool, semispec_role, jd_titles, 5, args.seed)

    report: dict = {
        "design": "自适应 α 验证：同一 DAPT 编码上对比 固定α=0.7 / 自适应α / 纯语义上限；"
                  "v4 池 = 全库 − 压力 − 半规范 manifest（冻结 gold 复现）",
        "base_alpha": BASE_ALPHA, "pools": {},
    }

    for name, spec in pools.items():
        pool, gold = spec["pool"], spec["gold"]
        sub_jds = {jid: jd_texts[jid] for jid in {p["jd_id"] for p in gold}}
        log(f"[{name}] 池 {len(pool)} 份，金标准 {len(gold)} 对 / "
            f"{sum(1 for p in gold if p['rel'] == 1)} 正 / {len(sub_jds)} 查询")

        ranking = rank_with_encoder("models/bert_domain", sub_jds, pool)
        ndcg_dapt, p5_dapt, n_eval = evaluate_group(ranking, gold)

        fixed = rank_fusion(jd_meta, pool, ranking, BASE_ALPHA)
        ndcg_fixed, p5_fixed, _ = evaluate_group(fixed, gold)

        adaptive, stats = rank_fusion_adaptive(jd_meta, pool, ranking, BASE_ALPHA)
        ndcg_adapt, p5_adapt, _ = evaluate_group(adaptive, gold)

        report["pools"][name] = {
            "pool": len(pool), "gold_pairs": len(gold), "queries": n_eval,
            "DAPT纯语义": {"ndcg@10": round(ndcg_dapt, 4), "p@5": round(p5_dapt, 4)},
            "固定α=0.7": {"ndcg@10": round(ndcg_fixed, 4), "p@5": round(p5_fixed, 4)},
            "自适应α": {"ndcg@10": round(ndcg_adapt, 4), "p@5": round(p5_adapt, 4)},
            "alpha_stats": alpha_stats_summary(stats),
        }
        log(f"[{name}] DAPT={ndcg_dapt:.4f}  固定α={ndcg_fixed:.4f}  自适应α={ndcg_adapt:.4f}  "
            f"（coverage 均值 {report['pools'][name]['alpha_stats']['coverage']['mean']}，"
            f"α 移动 JD 数 {report['pools'][name]['alpha_stats']['jds_alpha_moved']}）")
        (OUT_DIR / "adaptive_alpha_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- 复现断言 ----
    if args.expect_v4 is not None:
        got = report["pools"]["v4主卷"]["固定α=0.7"]["ndcg@10"]
        assert abs(got - args.expect_v4) < 0.0015, f"v4 固定α 复现失败：{got} ≠ {args.expect_v4}"
        log(f"✓ v4 固定α 复现通过（{got} ≈ {args.expect_v4}）——开关默认关时主卷零扰动")
    if args.expect_stress is not None:
        got = report["pools"]["压力考卷"]["固定α=0.7"]["ndcg@10"]
        assert abs(got - args.expect_stress) < 0.0015, f"压力卷固定α 复现失败：{got} ≠ {args.expect_stress}"
        log(f"✓ 压力卷固定α 复现通过（{got} ≈ {args.expect_stress}）")

    v4 = report["pools"]["v4主卷"]
    st = report["pools"]["压力考卷"]
    report["conclusion_note"] = (
        f"三池对比（先验→实测）：v4 固定 {v4['固定α=0.7']['ndcg@10']} → 自适应 "
        f"{v4['自适应α']['ndcg@10']}；压力卷固定 {st['固定α=0.7']['ndcg@10']} → 自适应 "
        f"{st['自适应α']['ndcg@10']}（向纯语义 {st['DAPT纯语义']['ndcg@10']} 回收）；"
        f"规则零自由参数（阈值 0.5 沿用 keyword_hit_score 中性值约定，线性形状无超参），"
        f"方向由压力卷拖累现象启发，未经金标准调参"
    )
    (OUT_DIR / "adaptive_alpha_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== 自适应 α 验证 ===")
    for name, p in report["pools"].items():
        print(f"  [{name}] 纯语义={p['DAPT纯语义']['ndcg@10']:.4f}  "
              f"固定α={p['固定α=0.7']['ndcg@10']:.4f}  自适应α={p['自适应α']['ndcg@10']:.4f}")
    print(f"\n{report['conclusion_note']}")
    print(f"产物：{OUT_DIR / 'adaptive_alpha_report.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
