"""人工标注核对脚本（T33 前置引入，T33 升级多标注人版）。

读 docs/eval/human_labels*.csv（可多轮/多人：human_labels.csv 为主表，
human_labels_r2.csv 等为后续轮次），与规则金标准 gold.jsonl 对账：
  1. 按标注人统计填写数与「人工 vs 规则」一致率（验收线 95%）；
  2. **标间一致性**：多位标注人对同一对的判定是否相同（评测可信度的第二重证据）；
  3. 标注人间分歧 → 仲裁表（规则 + 各标注人票数，多数决，规则票如实展示）；
  4. 报告落盘 docs/eval/human_check_report.md。

用法：
    cd backend && python tools/eval/check_human_labels.py

只读数据文件，不碰业务库（报告 md 除外）。
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
LABEL_GLOB = HERE.parent.parent.parent / "docs" / "eval" / "human_labels*.csv"
GOLD_JSONL = HERE / "gold.jsonl"
REPORT_MD = HERE.parent.parent.parent / "docs" / "eval" / "human_check_report.md"

ACCEPT_LINE = 0.95  # 与规则一致率验收线
JUDGE_KEY = "你的判定(1相关/0不相关/留空=拿不准)"


def load_gold() -> dict[tuple[int, int], int]:
    """gold.jsonl → {(jd_id, resume_id): rel}。"""
    gold = {}
    with open(GOLD_JSONL, encoding="utf-8") as f:
        for line in f:
            g = json.loads(line)
            gold[(g["jd_id"], g["resume_id"])] = g["rel"]
    return gold


def load_labels() -> list[dict]:
    """扫描全部 human_labels*.csv，返回已填判定且对得上金标准的行。

    每行附带 _annotator / _judge / _sheet；判定列非法或留空的行跳过。
    """
    rows: list[dict] = []
    for path in sorted(LABEL_GLOB.parent.glob(LABEL_GLOB.name)):
        sheet = path.stem  # human_labels / human_labels_r2 …
        with open(path, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                judge = (r.get(JUDGE_KEY) or "").strip()
                if judge == "":
                    continue
                if judge not in ("0", "1"):
                    print(f"⚠ {path.name} 非法判定值 {judge!r}（pair_id={r.get('pair_id')}），该行跳过")
                    continue
                rows.append({
                    "pair_id": r.get("pair_id", ""),
                    "jd_id": int(r["jd_id"]),
                    "resume_id": int(r["resume_id"]),
                    "jd_title": r.get("jd_岗位名称", ""),
                    "resume_file": r.get("resume_文件名", ""),
                    "_judge": int(judge),
                    "_annotator": (r.get("标注人") or "").strip() or "（未署名）",
                    "_sheet": sheet,
                })
    return rows


def main() -> int:
    if hasattr(__import__("sys").stdout, "reconfigure"):
        import sys
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows GBK 控制台
    gold = load_gold()
    rows = load_labels()
    if not rows:
        print("还没有任何人工判定——把 human_labels.csv 的「你的判定」列填上再来。")
        print("任务说明见 docs/标注任务.md；表共 100 行，当前已填 0 行。")
        return 0

    per_person: dict[str, list[dict]] = defaultdict(list)
    unknown = 0
    for r in rows:
        if (r["jd_id"], r["resume_id"]) not in gold:
            unknown += 1  # 金标准重建后未再采到的对：不参与对规则的一致率，仍参与标间一致性
            continue
        per_person[r["_annotator"]].append(r)

    # —— 每位标注人 vs 规则 ——
    stats: dict[str, dict] = {}
    total_voted = 0
    for name, rs in per_person.items():
        ok = sum(1 for r in rs if r["_judge"] == gold[(r["jd_id"], r["resume_id"])])
        stats[name] = {"n": len(rs), "ok": ok, "rate": ok / len(rs) if rs else 0.0}
        total_voted += len(rs)

    # —— 标间一致性（同一对 ≥2 人判定）——
    by_pair: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for r in rows:
        by_pair[(r["jd_id"], r["resume_id"])].append(r)
    inter_same = inter_diff = 0
    disputes: list[dict] = []
    for key, rs in by_pair.items():
        named = [r for r in rs if len({x["_judge"] for x in rs}) > 1]
        if len(rs) >= 2 and len({x["_judge"] for x in rs}) > 1:
            inter_diff += 1
            disputes.append({"key": key, "rows": rs, "rule": gold.get(key)})
        elif len(rs) >= 2:
            inter_same += 1

    lines = [
        "# 人工标注核对报告（多标注人版）",
        "",
        f"- 核对日期：{date.today().isoformat()} · 金标准：gold.jsonl（{len(gold)} 对）",
        f"- 判定总票数：{len(rows)}（其中对得上金标准 {total_voted} 票，金标准重建后未采到 {unknown} 票）",
        "",
        "## 一、各标注人 vs 规则金标准（验收线 ≥95%）",
        "",
        "| 标注人 | 对得上金标准的判定数 | 与规则一致 | 一致率 | 达标 |",
        "|---|---|---|---|---|",
    ]
    for name, s in sorted(stats.items(), key=lambda kv: -kv[1]["n"]):
        lines.append(
            f"| {name} | {s['n']} | {s['ok']} | {s['rate']:.1%} | "
            f"{'✅' if s['rate'] >= ACCEPT_LINE else '❌'} |"
        )
    overall_ok = sum(s["ok"] for s in stats.values())
    overall_rate = overall_ok / total_voted if total_voted else 0.0
    lines += [
        f"| **合计** | **{total_voted}** | **{overall_ok}** | **{overall_rate:.1%}** | "
        f"{'✅' if overall_rate >= ACCEPT_LINE else '❌'} |",
        "",
        "## 二、标注人之间的一致性（同一对两人都判）",
        "",
        f"- 一致 **{inter_same}** 对 / 分歧 **{inter_diff}** 对"
        + (f" → 标间一致率 **{inter_same / (inter_same + inter_diff):.1%}**" if inter_same + inter_diff else ""),
        "",
    ]

    if disputes:
        lines += [
            "## 三、标注人间分歧仲裁（规则票如实展示，多数决仅供参考）",
            "",
            "| pair_id | JD | 简历 | 规则 | 票型 | 仲裁参考 |",
            "|---|---|---|---|---|---|",
        ]
        for d in sorted(disputes, key=lambda x: x["rows"][0]["pair_id"]):
            votes = "、".join(f"{r['_annotator']}={r['_judge']}" for r in d["rows"])
            # 仲裁参考 = 规则票 + 各标注人票的多数（不含未采到的对）
            if d["rule"] is not None:
                allvotes = [d["rule"]] + [r["_judge"] for r in d["rows"]]
                outcome = max(set(allvotes), key=allvotes.count)
                ref = f"{outcome}（含规则票）"
            else:
                ref = "金标准重建后未采到，不仲裁"
            r0 = d["rows"][0]
            lines.append(
                f"| {r0['pair_id']} | {r0['jd_title']} | {r0['resume_file']} "
                f"| {d['rule'] if d['rule'] is not None else '—'} | {votes} | {ref} |"
            )
        lines.append("")

    # —— 附：与规则有出入的明细（按人）——
    lines += ["## 四、与规则不一致的判定明细", ""]
    any_diff = False
    for name, s in sorted(stats.items()):
        diffs = [r for r in per_person[name] if r["_judge"] != gold[(r["jd_id"], r["resume_id"])]]
        lines.append(f"### {name}（{len(diffs)} 处）" if diffs else f"### {name}（0 处）")
        lines.append("")
        if diffs:
            any_diff = True
            lines += ["| pair_id | JD | 简历 | 规则 | 人工 |", "|---|---|---|---|---|"]
            for r in sorted(diffs, key=lambda x: x["pair_id"]):
                lines.append(
                    f"| {r['pair_id']} | {r['jd_title']} | {r['resume_file']} "
                    f"| {gold[(r['jd_id'], r['resume_id'])]} | {r['_judge']} |"
                )
            lines.append("")
    if not any_diff:
        lines += ["无分歧。", ""]

    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"判定 {len(rows)} 票 · 对规则总体一致率 {overall_rate:.1%}"
          f" · 标间一致率 {inter_same}/{inter_same + inter_diff}"
          f" · 验收线 {ACCEPT_LINE:.0%} {'达标' if overall_rate >= ACCEPT_LINE else '未达标'}")
    print(f"报告 → {REPORT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
