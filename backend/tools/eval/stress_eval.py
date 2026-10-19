"""改写压力考卷评测（T37）：正文避开角色词的简历上，各方法还剩几成功力。

考卷：测试简历/压力考卷160/（160 份，20 角色 × 8 人），正文逐字避开本角色岗位词
（生成时断言，见 stress_manifest.json 的 banned 列表）——角色信号只藏在"干了什么、
会什么"的经历与技能里，文件名保留「姓名_角色.docx」作金标准判定依据（§5 路径一）。
**独立小考卷，不与 v4 主考卷混算**（正样本数 8≤10，NDCG@10 对漏检敏感，混入主卷
反而稀释信号；DeepSeek 也只需小subset 花费）。

组别（同一子集、同一子集金标准）：
  TF-IDF 基线          词面法
  底座                 bert-base-chinese 纯语义
  DAPT                 bert_domain 纯语义（线上主链路编码器）
  bert_pair            对比微调（转导设定，如实标注）
  本文方法             DAPT 语义 + 关键词重排 α=0.7（线上主链路）
  DeepSeek 零样本      LLM 对照（约 queries×48 次调用，命中缓存不重复计费）

用法（backend 目录下）：
  python tools/eval/stress_eval.py [--manifest ../..../stress_manifest.json] [--skip-deepseek]
产物：docs/eval/stress_report.json
"""
import argparse
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # backend/

REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = REPO_ROOT / "docs" / "eval"
DEFAULT_MANIFEST = REPO_ROOT.parent / "测试简历" / "stress_manifest.json"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def load_pool(manifest_path: Path) -> tuple[dict[int, str], dict[int, str], list[str]]:
    """留出考卷池：({rid: 结构化文本}, {rid: 角色角色}, [文件名])，只含 manifest 内简历"""
    from tools.run_experiments import load_corpus
    from app.db import get_db

    man = json.loads(manifest_path.read_text(encoding="utf-8"))
    wanted = {m["file_name"]: m["role"] for m in man["files"]}
    conn = get_db()
    try:
        rid_file = {r["id"]: r["file_name"] for r in conn.execute("SELECT id, file_name FROM resumes")}
    finally:
        conn.close()
    resume_texts, jd_texts, jd_meta = load_corpus()
    pool = {rid: resume_texts[rid] for rid, fn in rid_file.items() if fn in wanted}
    role_of = {rid: wanted[rid_file[rid]] for rid in pool}
    missing = set(wanted) - set(rid_file.values())
    if missing:
        log(f"⚠ {len(missing)} 份考卷简历不在库内（未上传或未解析）：{sorted(missing)[:3]}…")
    return pool, role_of, sorted(wanted)


def build_stress_gold(pool: dict[int, str], role_of: dict[int, str],
                      jd_titles: dict[int, str], neg_ratio: int, seed: int) -> list[dict]:
    """考卷金标准：正样本 = 文件名角色过 §5 三层判定；负采样 5:1（seed 同主实验）"""
    from tools.eval.build_gold import _positive

    pos_by_jd: dict[int, list[int]] = {}
    for jid, title in sorted(jd_titles.items()):
        pos = sorted(rid for rid in pool if _positive(title, [role_of[rid]]))
        if pos:
            pos_by_jd[jid] = pos
    rng = random.Random(seed)
    pairs: list[dict] = []
    for jid, pos in pos_by_jd.items():
        pos_set = set(pos)
        neg_pool = sorted(rid for rid in pool if rid not in pos_set)
        neg = rng.sample(neg_pool, min(len(neg_pool), neg_ratio * len(pos)))
        pairs += [{"jd_id": jid, "resume_id": rid, "rel": 1} for rid in pos]
        pairs += [{"jd_id": jid, "resume_id": rid, "rel": 0} for rid in neg]
    return pairs


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="改写压力考卷评测")
    ap.add_argument("--manifest", type=str, default=str(DEFAULT_MANIFEST))
    ap.add_argument("--neg-ratio", type=int, default=5)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--skip-deepseek", action="store_true")
    args = ap.parse_args()

    from tools.run_experiments import evaluate_group, load_corpus, rank_fusion, rank_with_encoder
    from tools.baselines.tfidf_baseline import rank_for_jds

    manifest_path = Path(args.manifest)
    assert manifest_path.exists(), f"manifest 不存在：{manifest_path}"
    pool, role_of, wanted_files = load_pool(manifest_path)
    assert len(pool) >= 100, f"考卷池过小：{len(pool)} 份（应 ~160），先完成上传解析"

    resume_texts, jd_texts, jd_meta = load_corpus()
    jd_titles = {jid: title for jid, (title, _) in jd_meta.items()}
    gold = build_stress_gold(pool, role_of, jd_titles, args.neg_ratio, args.seed)
    n_pos = sum(1 for p in gold if p["rel"] == 1)
    n_q = len({p["jd_id"] for p in gold})
    log(f"考卷池 {len(pool)} 份 / 金标准 {len(gold)} 对 / 正样本 {n_pos} / {n_q} 个 JD 查询")

    sub_jds = {jid: jd_texts[jid] for jid in {p["jd_id"] for p in gold}}
    report: dict = {
        "design": "改写压力考卷：160 份简历正文逐字避开本角色岗位词（独立考卷，不与 v4 混算）",
        "manifest": str(manifest_path), "pool": len(pool),
        "gold": {"pairs": len(gold), "positives": n_pos, "queries": n_q, "neg_ratio": args.neg_ratio},
        "groups": {},
    }

    def run_group(tag: str, ranking: dict, note: str = "") -> None:
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
              "对比微调；本考卷简历后于训练生成，模型从未见过这些文本——跨语料泛化结果")
    run_group("本文方法", rank_fusion(jd_meta, pool, dapt_ranking, 0.7),
              "DAPT 语义 + 关键词重排 α=0.7，线上主链路")
    (OUT_DIR / "stress_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

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
            log(f"DeepSeek：{len(all_pairs)} 对，6 线程并发打分（新文本全部现算，约 2~3 元）…")
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

    (OUT_DIR / "stress_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== 改写压力考卷（正文无角色词，160 份）===")
    for tag, g in report["groups"].items():
        if "ndcg@10" in g:
            print(f"  {tag:<22} NDCG@10={g['ndcg@10']:.4f}  P@5={g['p@5']:.4f}")
        else:
            print(f"  {tag:<22} 跳过：{g.get('reason', '')}")
    print(f"\n产物：{OUT_DIR / 'stress_report.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
