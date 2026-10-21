"""外校卷评测（T46）：全新岗位族、逐份手写语料——泄漏质疑的最终补验。

考卷：测试简历/外校卷50/（50 份 = 10 角色 × 5 份，全部逐份手写，不复用既有
生成器模板；配 10 条手写 JD）。与前两卷互补：
  T37 改写卷考**内容改写**（同岗位正文避词）——考的是词面依赖；
  T38 半规范卷考**版式**——考的是排版鲁棒性；
  T46 外校卷考**跨角色泛化**——岗位族在训练语料里从未出现，模型没见过这些
  人也没见过这些岗位。若对比微调（在主库 1062 份上转导微调、主卷 1.0000）
  在本卷仍站得住，则「准确度 1.0 = 背题」的质疑可以关闭。
**独立小考卷，不与 v4 主卷混算**（同 T37/T38 理由）。

组别（同一池、同一金标准，与 stress/semispec 完全同构）：
  TF-IDF 基线 / 底座 / DAPT / bert_pair / 本文方法(α=0.7) / 本文方法(自适应α)
DeepSeek 显式跳过：外部冻结模型不存在对我们语料的背题可能，非本卷审查对象。

用法（backend 目录下）：
  python tools/eval/fresh_eval.py [--manifest ../..../fresh_manifest.json]
产物：docs/eval/fresh_report.json
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # backend/

REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = REPO_ROOT / "docs" / "eval"
DEFAULT_MANIFEST = REPO_ROOT.parent / "测试简历" / "fresh_manifest.json"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="外校卷评测（全新岗位族）")
    ap.add_argument("--manifest", type=str, default=str(DEFAULT_MANIFEST))
    ap.add_argument("--neg-ratio", type=int, default=5)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    from tools.eval.stress_eval import build_stress_gold, load_pool
    from tools.eval.adaptive_alpha_check import BASE_ALPHA, rank_fusion_adaptive
    from tools.run_experiments import evaluate_group, load_corpus, rank_fusion, rank_with_encoder
    from tools.baselines.tfidf_baseline import rank_for_jds

    manifest_path = Path(args.manifest)
    assert manifest_path.exists(), f"manifest 不存在：{manifest_path}"

    pool, role_of, wanted_files = load_pool(manifest_path)
    assert len(pool) >= 50, f"考卷池过小：{len(pool)} 份（应 50），先上传解析"

    resume_texts, jd_texts, jd_meta = load_corpus()
    jd_titles = {jid: title for jid, (title, _) in jd_meta.items()}
    gold = build_stress_gold(pool, role_of, jd_titles, args.neg_ratio, args.seed)
    n_pos = sum(1 for p in gold if p["rel"] == 1)
    n_q = len({p["jd_id"] for p in gold})
    assert n_q >= 10, f"金标准查询数异常：{n_q}（应 10 条新 JD 各配出正样本）"
    log(f"考卷池 {len(pool)} 份 / 金标准 {len(gold)} 对 / 正样本 {n_pos} / {n_q} 个 JD 查询")

    sub_jds = {jid: jd_texts[jid] for jid in {p["jd_id"] for p in gold}}
    report: dict = {
        "design": "外校卷：50 份 = 10 全新岗位族 × 5 份，逐份手写不复用既有生成器模板；"
                  "考跨角色泛化——训练语料从未出现这些岗位（独立考卷，不与 v4 混算）",
        "manifest": str(manifest_path), "pool": len(pool),
        "gold": {"pairs": len(gold), "positives": n_pos, "queries": n_q,
                 "neg_ratio": args.neg_ratio, "seed": args.seed},
        "groups": {},
    }

    def run_group(tag: str, ranking: dict, note: str = "") -> None:
        ndcg, p5, n_eval = evaluate_group(ranking, gold)
        report["groups"][tag] = {"ndcg@10": round(ndcg, 4), "p@5": round(p5, 4),
                                 "queries": n_eval, "note": note}
        log(f"[{tag}] NDCG@10={ndcg:.4f}  P@5={p5:.4f}")

    log("组 1/6：TF-IDF")
    run_group("TF-IDF基线", rank_for_jds(sub_jds, pool), "词面法（字符 n-gram）")

    log("组 2/6：底座语义")
    run_group("底座", rank_with_encoder("bert-base-chinese", sub_jds, pool), "纯语义")

    log("组 3/6：DAPT")
    dapt_ranking = rank_with_encoder("models/bert_domain", sub_jds, pool)
    run_group("DAPT(bert_domain)", dapt_ranking, "纯语义，线上主链路编码器")

    log("组 4/6：bert_pair（对比微调；考卷岗位族后于训练出现——跨角色泛化结果）")
    run_group("bert_pair", rank_with_encoder("models/bert_pair", sub_jds, pool),
              "对比微调主卷 1.0000；本卷岗位族训练未见——泄漏质疑的审查对象")

    log("组 5/6：本文方法 α=0.7")
    run_group("本文方法", rank_fusion(jd_meta, pool, dapt_ranking, 0.7),
              "DAPT 语义 + 关键词重排 α=0.7")

    log("组 6/6：本文方法 自适应α")
    adaptive, stats = rank_fusion_adaptive(jd_meta, pool, dapt_ranking, BASE_ALPHA)
    covs = [s["coverage"] for s in stats]
    run_group("本文方法自适应α", adaptive,
              f"coverage 均值 {sum(covs) / len(covs):.4f}，线上默认配置")

    report["deepseek"] = {"skipped": True,
                          "reason": "外部冻结模型不存在对本项目语料的背题可能，非本卷审查对象"}
    (OUT_DIR / "fresh_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== 外校卷（全新岗位族，50 份）===")
    for tag, g in report["groups"].items():
        print(f"  {tag:<22} NDCG@10={g['ndcg@10']:.4f}  P@5={g['p@5']:.4f}")
    print(f"\n产物：{OUT_DIR / 'fresh_report.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
