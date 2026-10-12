"""金标准人工抽检表生成（算法设计 §5 第 3 步的制度化，T32 v2）。

对 gold.jsonl 逐对给出"判定依据"：
  正样本：匹配来源（文件名角色 / 职位实体 × 核心互含 / bigram 弱匹配），
          并复算冲突否决——程序无法复现该对的记"失效"，进入人工重点核对；
  负样本：随机抽样列出，供人工过目。

产物 docs/eval/gold_spotcheck.md，随金标准一起入库，团队人工核对后在本文件
打印的统计上确认噪声率 <5%（文档 §5 验收线）。

用法（backend 目录下）：python tools/eval/spotcheck_gold.py [--neg-sample 30]
"""
import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # backend/

from tools.eval.build_gold import (  # 复用同一套判定规则，避免口径漂移
    _conflict,
    _core,
    _filename_role,
    _positive,
)

GOLD_FILE = Path(__file__).with_name("gold.jsonl")
OUT_FILE = Path(__file__).resolve().parents[3] / "docs" / "eval" / "gold_spotcheck.md"


def _load_db() -> tuple[dict[int, list[str]], dict[int, str], dict[int, str]]:
    from app.db import get_db

    conn = get_db()
    try:
        titles: dict[int, list[str]] = {}
        for r in conn.execute("SELECT resume_id, field_value FROM entities WHERE field_key='title'"):
            titles.setdefault(r["resume_id"], []).append(r["field_value"])
        jds = {r["id"]: r["title"] for r in conn.execute("SELECT id, title FROM jds")}
        files = {r["id"]: r["file_name"] for r in conn.execute("SELECT id, file_name FROM resumes")}
    finally:
        conn.close()
    return titles, jds, files


def _trigger(jd_title: str, candidates: list[str], from_role: bool) -> str:
    """人话版判定依据；复现不了返回空串（进失效清单）"""
    jc = _core(jd_title)
    jt = jd_title.lower()
    for t in candidates:
        tl = t.lower()
        rc = _core(t)
        if rc and jc and (rc in jc or jc in rc) and not _conflict(rc, jc):
            src = "文件名角色" if from_role else "职位实体"
            return f"{src}「{t}」核心互含（{rc} ⊆ {jc}）"
        for i in range(len(rc or tl) - 1):
            if (rc or tl)[i : i + 2] in (jc or jt) and not _conflict(rc or t, jc or jt):
                src = "文件名角色" if from_role else "职位实体"
                return f"{src}「{t}」bigram弱匹配"
    return ""


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows GBK 控制台打 ⚠ 会崩
    ap = argparse.ArgumentParser(description="生成金标准人工抽检表")
    ap.add_argument("--neg-sample", type=int, default=30, help="负样本抽样展示条数（默认30）")
    args = ap.parse_args()

    gold = [json.loads(l) for l in GOLD_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]
    titles, jds, files = _load_db()
    rng = random.Random(42)

    pos = [g for g in gold if g["rel"] == 1]
    neg = [g for g in gold if g["rel"] == 0]

    rows, invalid = [], []
    mode_count = {"核心互含": 0, "bigram弱匹配": 0}
    for g in pos:
        jd_title = jds.get(g["jd_id"], f"JD{g['jd_id']}(已删)")
        rfile = files.get(g["resume_id"], f"简历{g['resume_id']}(已删)")
        role = _filename_role(rfile)
        from_role = role is not None
        candidates = [role] if from_role else titles.get(g["resume_id"], [])
        basis = _trigger(jd_title, candidates, from_role)
        if not basis:
            invalid.append((g["jd_id"], jd_title, g["resume_id"], rfile))
            continue
        mode_count["核心互含" if "核心互含" in basis else "bigram弱匹配"] += 1
        rows.append((g["jd_id"], jd_title, g["resume_id"], rfile, basis))

    neg_sample = rng.sample(neg, min(len(neg), args.neg_sample))

    lines = [
        "# 金标准人工抽检表（gold v2，T32）",
        "",
        f"- 正样本 **{len(pos)}** 对全量列出（逐对给出判定依据）；负样本 {len(neg)} 对抽样 {len(neg_sample)} 对",
        "- 判定规则与 build_gold.py v2 同源：模板简历按文件名角色匹配 + 技术栈冲突否决，"
        "其余简历按职位实体（tools/eval/spotcheck_gold.py 可复跑）",
        f"- 程序无法复现的对：**{len(invalid)}** 个（金标准生成后库内实体/文件变更所致，人工重点核对）",
        "",
        "## 正样本（rel=1，全量）",
        "",
        "| jd | JD 标题 | resume | 简历文件 | 判定依据 |",
        "|---|---|---|---|---|",
    ]
    for jid, jt, rid, rf, basis in rows:
        lines.append(f"| {jid} | {jt} | {rid} | {rf} | {basis} |")

    lines += [
        "",
        "## 负样本（rel=0，抽样）",
        "",
        "| jd | JD 标题 | resume | 简历文件 |",
        "|---|---|---|---|",
    ]
    for g in neg_sample:
        lines.append(
            f"| {g['jd_id']} | {jds.get(g['jd_id'], '?')} | {g['resume_id']} "
            f"| {files.get(g['resume_id'], '?')} |"
        )

    lines += [
        "",
        "## 人工核对结论（团队填写）",
        "",
        "- 抽检日期：____；核对人：____",
        f"- 无法复现对（{len(invalid)} 个）逐条结论：____",
        f"- 抽样负样本（{len(neg_sample)} 对）中误标：____",
        f"- 噪声率 = 确认误标对数 / {len(pos)} = ____%（验收线 <5%，§5）",
    ]
    OUT_FILE.write_text("\n".join(lines), encoding="utf-8")

    print(f"抽检表已写入 {OUT_FILE}")
    print(f"正样本 {len(pos)} 对全量复核：核心互含 {mode_count['核心互含']} 对，"
          f"bigram弱匹配 {mode_count['bigram弱匹配']} 对，无法复现 {len(invalid)} 对")
    for jid, jt, rid, rf in invalid[:20]:
        print(f"  ⚠ jd{jid}({jt}) × 简历{rid}({rf})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
