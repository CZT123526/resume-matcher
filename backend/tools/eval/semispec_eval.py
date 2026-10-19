"""半规范考卷评测（T38）：表格排版/栏目乱序/缺栏目/流水账版式下，各方法还稳不稳。

考卷：测试简历/半规范考卷100/（100 份 = 20 角色 × 5 版式）。与 T37 改写考卷互补：
那份考**内容**（正文避开角色词），这份考**版式**——岗位词都在正文里，但排版是
现实里最常见的"规范模板与口语散文之间的中间态"。现有主卷只有规范/口语两档，
版式鲁棒性此前从未被量过。文件名保留「姓名_角色.docx」作金标准依据（§5 路径一），
manifest 记录每份的版式标签——总表之外再按版式分解（同一 ranking、按版式过滤
金标准子集重算 NDCG/P@5，定位"哪一种版式最掉分"）。
**独立小考卷，不与 v4 主卷混算**（同 T37 理由）。

组别（同一池、同一金标准，与 stress_eval 完全同构）：
  TF-IDF 基线 / 底座 / DAPT / bert_pair / 本文方法(α=0.7) / DeepSeek 零样本

用法（backend 目录下）：
  python tools/eval/semispec_eval.py [--manifest ../..../semispec_manifest.json] [--skip-deepseek]
产物：docs/eval/semispec_report.json
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # backend/

REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = REPO_ROOT / "docs" / "eval"
DEFAULT_MANIFEST = REPO_ROOT.parent / "测试简历" / "semispec_manifest.json"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="半规范考卷评测")
    ap.add_argument("--manifest", type=str, default=str(DEFAULT_MANIFEST))
    ap.add_argument("--neg-ratio", type=int, default=5)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--skip-deepseek", action="store_true")
    args = ap.parse_args()

    from tools.eval.stress_eval import build_stress_gold, load_pool
    from tools.run_experiments import evaluate_group, load_corpus, rank_fusion, rank_with_encoder
    from tools.baselines.tfidf_baseline import rank_for_jds
    from app.db import get_db

    manifest_path = Path(args.manifest)
    assert manifest_path.exists(), f"manifest 不存在：{manifest_path}"
    man = json.loads(manifest_path.read_text(encoding="utf-8"))
    layout_of_name = {m["file_name"]: m["layout"] for m in man["files"]}

    pool, role_of, wanted_files = load_pool(manifest_path)
    assert len(pool) >= 90, f"考卷池过小：{len(pool)} 份（应 ~100），先完成上传解析"

    # rid → 版式（金标准子集过滤用）
    conn = get_db()
    try:
        rid_file = {r["id"]: r["file_name"] for r in conn.execute("SELECT id, file_name FROM resumes")}
    finally:
        conn.close()
    layout_of = {rid: layout_of_name[rid_file[rid]] for rid in pool}

    resume_texts, jd_texts, jd_meta = load_corpus()
    jd_titles = {jid: title for jid, (title, _) in jd_meta.items()}
    gold = build_stress_gold(pool, role_of, jd_titles, args.neg_ratio, args.seed)
    n_pos = sum(1 for p in gold if p["rel"] == 1)
    n_q = len({p["jd_id"] for p in gold})
    log(f"考卷池 {len(pool)} 份 / 金标准 {len(gold)} 对 / 正样本 {n_pos} / {n_q} 个 JD 查询")

    sub_jds = {jid: jd_texts[jid] for jid in {p["jd_id"] for p in gold}}
    layouts = sorted({m["layout"] for m in man["files"]})
    report: dict = {
        "design": "半规范考卷：100 份 = 20 角色 × 5 版式（表格/乱序/缺栏目/流水账/表格乱序），"
                  "岗位词都在正文里，考版式鲁棒性（独立考卷，不与 v4 混算）",
        "manifest": str(manifest_path), "pool": len(pool),
        "gold": {"pairs": len(gold), "positives": n_pos, "queries": n_q, "neg_ratio": args.neg_ratio},
        "groups": {}, "by_layout": {},
    }

    rankings: dict[str, dict] = {}

    def run_group(tag: str, ranking: dict, note: str = "") -> None:
        rankings[tag] = ranking
        ndcg, p5, n_eval = evaluate_group(ranking, gold)
        report["groups"][tag] = {"ndcg@10": round(ndcg, 4), "p@5": round(p5, 4),
                                 "queries": n_eval, "note": note}
        log(f"[{tag}] NDCG@10={ndcg:.4f}  P@5={p5:.4f}")

    t0 = time.perf_counter()
    run_group("TF-IDF基线", rank_for_jds(sub_jds, pool), "词面法（字符 n-gram）")
    log(f"TF-IDF 排序耗时 {time.perf_counter() - t0:.1f}s")

    run_group("底座", rank_with_encoder("bert-base-chinese", sub_jds, pool), "纯语义")
    dapt_ranking = rank_with_encoder("models/bert_domain", sub_jds, pool)
    run_group("DAPT(bert_domain)", dapt_ranking, "纯语义，线上主链路编码器")
    run_group("bert_pair", rank_with_encoder("models/bert_pair", sub_jds, pool),
              "对比微调；考卷简历后于训练生成——跨语料泛化结果")
    run_group("本文方法", rank_fusion(jd_meta, pool, dapt_ranking, 0.7),
              "DAPT 语义 + 关键词重排 α=0.7，线上主链路")
    (OUT_DIR / "semispec_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # 按版式分解：同一 ranking，金标准按版式过滤后重算（缺失候选补尾部=最差，
    # 衡量"该版式的正样本能否进 top-10"）
    for tag, ranking in rankings.items():
        report["by_layout"][tag] = {}
        for lay in layouts:
            sub_gold = [p for p in gold if layout_of.get(p["resume_id"]) == lay]
            ndcg, p5, n_eval = evaluate_group(ranking, sub_gold)
            report["by_layout"][tag][lay] = {"ndcg@10": round(ndcg, 4), "p@5": round(p5, 4),
                                             "queries": n_eval}
        row = "  ".join(f"{lay}={report['by_layout'][tag][lay]['ndcg@10']:.4f}" for lay in layouts)
        log(f"[版式分解 {tag}] {row}")

    # DeepSeek 零样本（可选，真金白银）
    if args.skip_deepseek:
        report["groups"]["DeepSeek零样本"] = {"skipped": True, "reason": "--skip-deepseek"}
        log("DeepSeek：跳过（--skip-deepseek）")
    else:
        from tools.baselines.deepseek_zeroshot import DeepSeekScorer

        scorer = DeepSeekScorer()
        if scorer.available():
            by_jd: dict[int, dict[int, int]] = {}
            for p in gold:
                by_jd.setdefault(p["jd_id"], {})[p["resume_id"]] = p["rel"]
            all_pairs = [(jid, rid) for jid, judged in by_jd.items() for rid in judged]
            log(f"DeepSeek：{len(all_pairs)} 对，6 线程并发打分…")
            from concurrent.futures import ThreadPoolExecutor

            n_fail, done = 0, 0
            tmp: dict[int, list[tuple[int, float]]] = {jid: [] for jid in by_jd}

            def _one(pair):
                jid, rid = pair
                return jid, rid, scorer.score(sub_jds[jid], pool[rid])

            t0 = time.perf_counter()
            with ThreadPoolExecutor(max_workers=6) as ex:
                for jid, rid, s in ex.map(_one, all_pairs):
                    done += 1
                    if s is None:
                        n_fail += 1
                        s = 0.0
                    tmp[jid].append((rid, s))
                    if done % 300 == 0:
                        log(f"  DeepSeek {done}/{len(all_pairs)}（失败 {n_fail}）")
            ds_ranking = {jid: sorted(v, key=lambda x: x[1], reverse=True) for jid, v in tmp.items()}
            ndcg, p5, n_eval = evaluate_group(ds_ranking, gold)
            report["groups"]["DeepSeek零样本"] = {
                "ndcg@10": round(ndcg, 4), "p@5": round(p5, 4), "queries": n_eval,
                "model": scorer.model, "failed_calls": n_fail,
                "seconds": round(time.perf_counter() - t0, 1),
                "note": f"约 {len(all_pairs)} 次调用（命中缓存不重复计费）"}
            log(f"[DeepSeek零样本] NDCG@10={ndcg:.4f}  P@5={p5:.4f}  失败 {n_fail}")
        else:
            report["groups"]["DeepSeek零样本"] = {"skipped": True, "reason": "未配置 DEEPSEEK_API_KEY"}
            log("DeepSeek：跳过（无 key）")

    (OUT_DIR / "semispec_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== 半规范考卷（版式中间态，100 份）===")
    for tag, g in report["groups"].items():
        if "ndcg@10" in g:
            lay = report["by_layout"].get(tag, {})
            lay_s = "  ".join(f"{l[:2]}={lay[l]['ndcg@10']:.3f}" for l in layouts if l in lay)
            print(f"  {tag:<22} NDCG@10={g['ndcg@10']:.4f}  P@5={g['p@5']:.4f}   [{lay_s}]")
        else:
            print(f"  {tag:<22} 跳过：{g.get('reason', '')}")
    print(f"\n产物：{OUT_DIR / 'semispec_report.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
