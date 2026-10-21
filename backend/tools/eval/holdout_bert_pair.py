"""留出法补验 bert_pair 泛化性（T37）：回答"1.0000 里有多少是背题"。

§7.1 诚实口径的疑点：bert_pair 训练语料即评测语料库，金标准 NDCG 1.0000 可能含
记忆成分。本脚本把文件名角色配对按角色分层切 85/15（seed=42）：只用 85% 训练
对比微调模型，金标准正负样本也只在 15% 留出池内构造——四种编码器在**同一留出
子集**上对比：
  底座 bert-base-chinese    没见过任何角色信号的下限
  DAPT bert_domain          线上主链路编码器
  bert_pair 全量            见过留出池（转导对照 = §7 编码器消融复刻）
  bert_pair 留出            没见过留出池（真泛化）
全量−留出 的差值 = "背题"成分；留出若仍明显高于 DAPT，说明对比微调学到的是
"简历↔岗位描述"的对齐能力而非样本记忆。

训练主循环复用 tools/train_contrastive.train_contrastive（与全量训练唯一差异是
数据切分），超参完全一致（4 epoch / batch 32 / lr 3e-5 / temp 0.05 / max_len 256）。

用法（backend 目录下）：python tools/eval/holdout_bert_pair.py [--hold-ratio 0.15]
产物：models/bert_pair_holdout/（模型，gitignore）+ docs/eval/holdout_report.json
不需要 DeepSeek key（纯编码器对比）。
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
HOLDOUT_MODEL_DIR = Path(__file__).resolve().parents[2] / "models" / "bert_pair_holdout"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def load_tagged() -> list[tuple[int, str, str]]:
    """[(rid, 结构化文本, 角色)]——文件名可判角色且角色在 ROLE_JDS 的全部简历"""
    from tools.train_contrastive import _ROLE_RE, ROLE_JDS
    from app.svc.vectors import _current_resume_data, structured_text
    from app.db import get_db

    data = _current_resume_data()
    conn = get_db()
    try:
        files = {r["id"]: r["file_name"] for r in conn.execute("SELECT id, file_name FROM resumes")}
    finally:
        conn.close()
    out = []
    for rid, item in data.items():
        m = _ROLE_RE.match(files.get(rid, ""))
        role = m.group(1) if m else None
        if role in ROLE_JDS:
            out.append((rid, structured_text(item), role))
    return out


def stratified_split(tagged: list[tuple[int, str, str]], hold_ratio: float, seed: int) -> set[int]:
    """按角色分层切留出集：每个角色内部 shuffle 后取前 hold_ratio 份（至少 1 份）"""
    rng = random.Random(seed)
    by_role: dict[str, list[int]] = {}
    for rid, _, role in tagged:
        by_role.setdefault(role, []).append(rid)
    held: set[int] = set()
    for role in sorted(by_role):
        rids = sorted(by_role[role])
        rng.shuffle(rids)
        n_hold = max(1, round(len(rids) * hold_ratio))
        held.update(rids[:n_hold])
    return held


def build_holdout_gold(held_rids: list[int], role_of: dict[int, str],
                       jd_titles: dict[int, str], neg_ratio: int, seed: int) -> list[dict]:
    """留出池内的金标准：正样本 = 文件名角色过 §5 三层判定；负采样 5:1（seed 同主实验）"""
    from tools.eval.build_gold import _positive

    pos_by_jd: dict[int, list[int]] = {}
    for jid, title in sorted(jd_titles.items()):
        pos = sorted(rid for rid in held_rids if _positive(title, [role_of[rid]]))
        if pos:
            pos_by_jd[jid] = pos
    rng = random.Random(seed)
    pairs: list[dict] = []
    for jid, pos in pos_by_jd.items():
        pos_set = set(pos)
        neg_pool = sorted(rid for rid in held_rids if rid not in pos_set)
        neg = rng.sample(neg_pool, min(len(neg_pool), neg_ratio * len(pos)))
        pairs += [{"jd_id": jid, "resume_id": rid, "rel": 1} for rid in pos]
        pairs += [{"jd_id": jid, "resume_id": rid, "rel": 0} for rid in neg]
    return pairs


def eval_encoder(tag: str, model_path: str, jd_texts: dict, resume_texts: dict, gold: list[dict]) -> dict:
    from tools.run_experiments import evaluate_group, rank_with_encoder

    t0 = time.perf_counter()
    ranking = rank_with_encoder(model_path, jd_texts, resume_texts)
    elapsed = time.perf_counter() - t0
    ndcg, p5, n_eval = evaluate_group(ranking, gold)
    log(f"[{tag}] NDCG@10={ndcg:.4f}  P@5={p5:.4f}  （{n_eval} 查询，{elapsed:.0f}s）")
    return {"ndcg@10": round(ndcg, 4), "p@5": round(p5, 4), "queries": n_eval,
            "model_path": model_path, "seconds": round(elapsed, 1)}


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="bert_pair 留出法补验")
    ap.add_argument("--hold-ratio", type=float, default=0.15)
    ap.add_argument("--neg-ratio", type=int, default=5)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    from tools.train_contrastive import ROLE_JDS, check_pool_manifest, train_contrastive

    tagged = load_tagged()
    # B8 同源核对：全量训练的 manifest 记录的是 train_contrastive 的池；留出法取数
    # 路相同，池对不上同样意味着"留出从未参与训练"的口径要对时间
    check_pool_manifest(Path(__file__).resolve().parents[2] / "models" / "bert_pair", len(tagged))
    held = stratified_split(tagged, args.hold_ratio, args.seed)
    held_rids = sorted(held)
    role_of = {rid: role for rid, _, role in tagged}
    log(f"角色简历 {len(tagged)} 份 → 训练 {len(tagged) - len(held)} / 留出 {len(held)}"
        f"（{len({role_of[r] for r in held_rids})} 个角色均有留出）")

    from tools.run_experiments import load_corpus

    resume_texts, jd_texts, jd_meta = load_corpus()
    jd_titles = {jid: title for jid, (title, _) in jd_meta.items()}

    gold = build_holdout_gold(held_rids, role_of, jd_titles, args.neg_ratio, args.seed)
    n_pos = sum(1 for p in gold if p["rel"] == 1)
    n_q = len({p["jd_id"] for p in gold})
    log(f"留出池金标准：{len(gold)} 对 / 正样本 {n_pos} / {n_q} 个 JD 查询")

    # 子集语料：候选 = 仅留出池；查询 = 仅金标准覆盖的 JD
    sub_resumes = {rid: resume_texts[rid] for rid in held_rids}
    sub_jds = {jid: jd_texts[jid] for jid in {p["jd_id"] for p in gold}}

    report: dict = {
        "design": "留出法补验：角色分层 85/15（seed=42），bert_pair 只用 85% 训练，评测仅在 15% 留出池",
        "seed": args.seed, "hold_ratio": args.hold_ratio, "neg_ratio": args.neg_ratio,
        "pool": {"tagged": len(tagged), "train": len(tagged) - len(held), "held_out": len(held)},
        "gold": {"pairs": len(gold), "positives": n_pos, "queries": n_q},
        "groups": {},
    }

    # 先跑三个现成编码器（训练挂了也有基线数字）
    for tag, path in [
        ("底座", "bert-base-chinese"),
        ("DAPT(bert_domain)", "models/bert_domain"),
        ("bert_pair全量(转导对照)", "models/bert_pair"),
    ]:
        report["groups"][tag] = eval_encoder(tag, path, sub_jds, sub_resumes, gold)
        (OUT_DIR / "holdout_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # 训练留出模型（超参与全量训练完全一致，唯一变量是数据切分）
    import torch
    from transformers import AutoModel, AutoTokenizer

    torch.manual_seed(args.seed)
    train_pairs = [(txt, ROLE_JDS[role]) for rid, txt, role in tagged if rid not in held]
    log(f"开始训练留出模型：{len(train_pairs)} 正对，起点 models/bert_domain（CPU，约 25~30 分钟）")
    t0 = time.perf_counter()
    tok = AutoTokenizer.from_pretrained("models/bert_domain")
    model = AutoModel.from_pretrained("models/bert_domain")
    model = train_contrastive(model, tok, train_pairs, epochs=4, batch=32, lr=3e-5,
                              temp=0.05, max_len=256, seed=args.seed, device="cpu")
    train_seconds = round(time.perf_counter() - t0, 1)
    HOLDOUT_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(HOLDOUT_MODEL_DIR)
    tok.save_pretrained(HOLDOUT_MODEL_DIR)
    (HOLDOUT_MODEL_DIR / "metrics.json").write_text(json.dumps({
        "encoder_id": "bert_pair-holdout", "base_model": "models/bert_domain",
        "train_pairs": len(train_pairs), "held_out": len(held),
        "hold_ratio": args.hold_ratio, "seed": args.seed,
        "epochs": 4, "batch": 32, "lr": 3e-5, "temperature": 0.05, "max_len": 256,
        "train_seconds": train_seconds, "trained_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "note": "留出法补验：85% 角色分层训练，留出 15% 从未参与训练",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"留出模型已存 {HOLDOUT_MODEL_DIR}/（训练 {train_seconds:.0f}s）")

    report["groups"]["bert_pair留出(真泛化)"] = eval_encoder(
        "bert_pair留出(真泛化)", str(HOLDOUT_MODEL_DIR), sub_jds, sub_resumes, gold)

    report["conclusion_note"] = "全量−留出 = 记忆成分；留出−DAPT = 对比微调的泛化增益"
    (OUT_DIR / "holdout_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== 留出法补验结果（同一留出子集）===")
    for tag, g in report["groups"].items():
        print(f"  {tag:<24} NDCG@10={g['ndcg@10']:.4f}  P@5={g['p@5']:.4f}")
    print(f"\n产物：{OUT_DIR / 'holdout_report.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
