"""人工标注核对脚本（T33 前置）。

读 docs/eval/human_labels.csv（队友人工判定），与规则金标准 gold.jsonl 对账：
  1. 按标注人统计填写数；
  2. 计算人工 vs 规则的一致率（总体 / 正样本侧 / 负样本侧）；
  3. 列出全部分歧明细；
  4. 报告落盘 docs/eval/human_check_report.md。

用法：
    cd backend && python tools/eval/check_human_labels.py

验收口径（docs/标注任务.md §6）：总体一致率 ≥ 95% 视为规则金标准可信。
只读两个数据文件，不碰业务库、不做任何写操作（报告 md 除外）。
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
LABELS_CSV = HERE.parent.parent.parent / "docs" / "eval" / "human_labels.csv"
GOLD_JSONL = HERE / "gold.jsonl"
REPORT_MD = HERE.parent.parent.parent / "docs" / "eval" / "human_check_report.md"

ACCEPT_LINE = 0.95  # 一致率验收线（docs/标注任务.md §6）


def load_gold() -> dict[tuple[int, int], int]:
    """gold.jsonl → {(jd_id, resume_id): rel}。"""
    gold = {}
    with open(GOLD_JSONL, encoding="utf-8") as f:
        for line in f:
            g = json.loads(line)
            gold[(g["jd_id"], g["resume_id"])] = g["rel"]
    return gold


def load_labels() -> list[dict]:
    """human_labels.csv → 已填判定的行（判定留空的跳过）。"""
    rows = []
    with open(LABELS_CSV, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            judge = (r.get("你的判定(1相关/0不相关/留空=拿不准)") or "").strip()
            if judge == "":
                continue
            if judge not in ("0", "1"):
                print(f"⚠ 非法判定值 {judge!r}（pair_id={r.get('pair_id')}），该行跳过")
                continue
            r["_judge"] = int(judge)
            r["_annotator"] = (r.get("标注人") or "").strip() or "（未署名）"
            rows.append(r)
    return rows


def main() -> None:
    gold = load_gold()
    rows = load_labels()
    if not rows:
        print("还没有任何人工判定——把 human_labels.csv 的「你的判定」列填上再来。")
        print(f"任务说明见 docs/标注任务.md；表共 100 行，当前已填 {len(rows)} 行。")
        return

    per_person: dict[str, list[dict]] = defaultdict(list)
    disagree: list[dict] = []
    unknown_pair = 0
    # 四格：一致正相关 / 一致负相关（真负例必须计数——首版漏计它，66.67% 假象即由此来）
    agree_pos = agree_neg = fp_rule = fn_rule = 0

    for r in rows:
        key = (int(r["jd_id"]), int(r["resume_id"]))
        if key not in gold:
            unknown_pair += 1
            print(f"⚠ pair_id={r['pair_id']} 的 (jd {key[0]}, 简历 {key[1]}) 不在金标准里，跳过")
            continue
        rel_rule = gold[key]
        per_person[r["_annotator"]].append(r)
        if r["_judge"] == rel_rule:
            if rel_rule == 1:
                agree_pos += 1
            else:
                agree_neg += 1
        else:
            disagree.append({**r, "_rule": rel_rule})
            if rel_rule == 1:
                fp_rule += 1  # 规则误报：规则说相关，人说无关
            else:
                fn_rule += 1  # 规则漏报：规则说无关，人说相关

    n = agree_pos + agree_neg + fp_rule + fn_rule
    agree = (agree_pos + agree_neg) / n if n else 0.0

    lines = [
        "# 人工标注核对报告",
        "",
        f"- 核对日期：{date.today().isoformat()}",
        f"- 表内总行数：100 · 已填判定：{n} 行 · 拿不准留空：{100 - n - unknown_pair} 行"
        + (f" · 对不上金标准：{unknown_pair} 行" if unknown_pair else ""),
        "",
        "## 一致率",
        "",
        "| 口径 | 数值 |",
        "|---|---|",
        f"| 总体一致率 | **{agree:.2%}**（{agree_pos + agree_neg}/{n}） |",
        f"| 规则误报（规则=相关，人=无关） | {fp_rule} |",
        f"| 规则漏报（规则=无关，人=相关） | {fn_rule} |",
        f"| 验收线 | ≥ {ACCEPT_LINE:.0%} → {'✅ 达标' if agree >= ACCEPT_LINE else '❌ 未达标，需修规则重建金标准'} |",
        "",
        "## 按标注人",
        "",
        "| 标注人 | 填写数 | 与规则一致 | 一致率 |",
        "|---|---|---|---|",
    ]
    for name, rs in sorted(per_person.items(), key=lambda kv: -len(kv[1])):
        ok = sum(1 for r in rs if r["_judge"] == gold[(int(r["jd_id"]), int(r["resume_id"]))])
        lines.append(f"| {name} | {len(rs)} | {ok} | {ok / len(rs):.2%} |")

    if disagree:
        lines += [
            "",
            "## 分歧明细（人工为准逐条复核）",
            "",
            "| pair_id | JD | 简历 | 规则 | 人工 | 标注人 |",
            "|---|---|---|---|---|---|",
        ]
        for r in sorted(disagree, key=lambda x: x["pair_id"]):
            lines.append(
                f"| {r['pair_id']} | {r['jd_岗位名称']} | {r['resume_文件名']} "
                f"| {r['_rule']} | {r['_judge']} | {r['_annotator']} |"
            )
    else:
        lines += ["", "## 分歧明细", "", "无分歧。"]

    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"已填 {n}/100 · 总体一致率 {agree:.2%}（误报 {fp_rule} / 漏报 {fn_rule}）"
          f" · 验收线 {ACCEPT_LINE:.0%} {'达标' if agree >= ACCEPT_LINE else '未达标'}")
    print(f"报告 → {REPORT_MD}")


if __name__ == "__main__":
    main()
