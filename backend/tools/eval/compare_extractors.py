"""规则抽取 vs 微调 BERT 抽取：同一 NER 测试集上的实体级对比（供报告引用）。

口径：宽松匹配——(字段, 值) 二元组相等即 TP，不比对位置（rules 版契约不含位置）；
BERT 的严格口径（字段+值+位置）见 models/ner/metrics.json（F1=0.953）。
每句独立统计后做微平均。

用法（backend 目录下）：python tools/eval/compare_extractors.py
"""
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows GBK 控制台兜底

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # backend/

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def relaxed_prf(gold: list[set], pred: list[set]) -> dict:
    tp = sum(len(g & p) for g, p in zip(gold, pred))
    fp = sum(len(p - g) for g, p in zip(gold, pred))
    fn = sum(len(g - p) for g, p in zip(gold, pred))
    p_ = tp / (tp + fp) if tp + fp else 0.0
    r_ = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p_ * r_ / (p_ + r_) if p_ + r_ else 0.0
    return {"precision": round(p_, 4), "recall": round(r_, 4), "f1": round(f1, 4)}


def _gold_spans(chars: list[str], tags: list[str]) -> set:
    """BIO 标签 → {(字段, 实体值)}：B- 起头，连续同字段 I- 归入同一 span"""
    out: set = set()
    i = 0
    while i < len(tags):
        if tags[i].startswith("B-"):
            field = tags[i][2:]
            j = i + 1
            while j < len(tags) and tags[j] == f"I-{field}":
                j += 1
            out.add((field, "".join(chars[i:j])))
            i = j
        else:
            i += 1
    return out


def main() -> int:
    from app.svc import ner, ner_rules

    records = [json.loads(l) for l in (DATA_DIR / "ner_test.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    gold_sets, rule_sets, bert_sets = [], [], []
    for rec in records:
        text = "".join(rec["chars"])
        gold_sets.append(_gold_spans(rec["chars"], rec["tags"]))
        rule_sets.append({(e["field_key"], e["field_value"]) for e in ner_rules.extract_entities(text)})
        bert_sets.append({(e["field_key"], e["field_value"]) for e in ner.extract_entities_bert(text)})

    print(f"测试集 {len(records)} 句，宽松口径（字段+值，微平均）：")
    for name, sets in [("规则版", rule_sets), ("微调BERT", bert_sets)]:
        m = relaxed_prf(gold_sets, sets)
        print(f"  {name:8s} P={m['precision']:.4f}  R={m['recall']:.4f}  F1={m['f1']:.4f}")
    print("注：规则版按显式'字段：值'行文设计，自然行文召回低属预期；BERT 严格口径 F1=0.953 见 models/ner/metrics.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
