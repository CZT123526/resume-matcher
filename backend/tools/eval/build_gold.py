"""金标准构造（算法设计 §5，D6）：期望岗位即免费监督信号。

正样本：简历 title 实体（求职意向/职称）与 JD 标题有 ≥2 字公共子串 → rel=1；
负采样：该 JD 下非正样本的简历随机抽 5×正样本数，seed=42 可复现；
产物：backend/tools/eval/gold.jsonl，每行 {"jd_id", "resume_id", "rel": 0|1}。

用法（backend 目录下）：python tools/eval/build_gold.py [--neg-ratio 5]
"""
import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # backend/

GOLD_FILE = Path(__file__).with_name("gold.jsonl")


def _title_map() -> tuple[dict[int, list[str]], dict[int, str]]:
    """({resume_id: [title...]}, {jd_id: jd_title})，来自库内已抽取实体"""
    from app.db import get_db

    conn = get_db()
    try:
        titles: dict[int, list[str]] = {}
        for r in conn.execute(
            "SELECT resume_id, field_value FROM entities WHERE field_key='title'"
        ):
            titles.setdefault(r["resume_id"], []).append(r["field_value"])
        jds = {
            r["id"]: r["title"]
            for r in conn.execute("SELECT id, title FROM jds")
        }
    finally:
        conn.close()
    return titles, jds


def _positive(jd_title: str, resume_titles: list[str]) -> bool:
    """JD 标题与简历期望岗位共享 ≥2 字连续子串即视为匹配（课程级近似，人工抽检兜底）"""
    jt = jd_title.lower()
    for t in resume_titles:
        t = t.lower()
        for i in range(len(t) - 1):
            if t[i : i + 2] in jt:
                return True
    return False


def build(neg_ratio: int = 5, seed: int = 42) -> list[dict]:
    titles, jds = _title_map()
    pairs: list[dict] = []
    rng = random.Random(seed)

    for jd_id, jd_title in sorted(jds.items()):
        pos = sorted(rid for rid, ts in titles.items() if _positive(jd_title, ts))
        neg_pool = sorted(set(titles) - set(pos))
        neg = rng.sample(neg_pool, min(len(neg_pool), neg_ratio * len(pos))) if pos else []
        pairs += [{"jd_id": jd_id, "resume_id": rid, "rel": 1} for rid in pos]
        pairs += [{"jd_id": jd_id, "resume_id": rid, "rel": 0} for rid in neg]
    return pairs


def main() -> int:
    ap = argparse.ArgumentParser(description="构造金标准 gold.jsonl")
    ap.add_argument("--neg-ratio", type=int, default=5, help="负采样倍数（默认5，文档 §5）")
    args = ap.parse_args()

    pairs = build(neg_ratio=args.neg_ratio)
    if not pairs:
        print("库内没有 JD 或没有带 title 实体的简历——先上传简历并创建 JD 再构造金标准")
        return 1
    n_pos = sum(1 for p in pairs if p["rel"] == 1)
    n_jd = len({p["jd_id"] for p in pairs})
    with GOLD_FILE.open("w", encoding="utf-8") as f:
        for p in pairs:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    print(f"gold.jsonl 写入 {len(pairs)} 对（正样本 {n_pos}，覆盖 {n_jd} 个 JD）→ {GOLD_FILE}")
    if n_jd < 5:
        print(f"⚠ 只有 {n_jd} 个 JD 查询，NDCG 方差大——正式实验建议 ≥5 个不同岗位的 JD")
    print("提醒：文档 §5 要求人工抽检 100 对核对噪声率（课程演示至少抽 10 对人工确认）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
