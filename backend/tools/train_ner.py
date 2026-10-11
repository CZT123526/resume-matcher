"""NER 微调训练脚本（算法设计 §2.3）：bert-base-chinese + 15 标签 BIO token 分类。

语料：tools/data/ner_{train,val,test}.jsonl（download_dataset.py 产出），
     每行 {"chars": [...], "tags": ["B-name"| "I-..." | "O", ...]}。
指标：实体级精确匹配 P/R/F1（§2.4：字段+值+位置全对才算 TP）。
产物：$NER_MODEL_DIR（默认 backend/models/ner/）= 模型 + tokenizer + metrics.json；
     放到位后 app/svc/ner.py 自动启用，零改码。

Colab T4 用法（推荐，本机 CPU 约 3~6 小时）：
    一键：Colab 打开同目录 train_colab.ipynb → 改运行时为 T4 → 全部运行，
         结束自动下载 ner_model.zip，解压到 backend/models/ner/ 即生效。
    手动（等价四步）：
    单元1  !pip -q install "transformers>=4.41" "datasets>=2.19" "accelerate>=1.1.0"
    单元2  上传 ner_train/val/test.jsonl（或整个 tools/data/ 目录）到 /content/
    单元3  !NER_DATA_DIR=/content NER_MODEL_DIR=/content/models_ner python train_ner.py
    单元4  把产物目录打 zip 下载，解压到 backend/models/ner/
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/

# 7 字段顺序固定（与 app/svc/ner_rules.ENTITY_KEYS_SET 一致的口径，label id 稳定）
FIELDS = ["name", "degree", "school", "skill", "years", "company", "title"]
LABELS = ["O"] + [f"{p}-{f}" for f in FIELDS for p in ("B", "I")]  # 15 标签
LABEL2ID = {l: i for i, l in enumerate(LABELS)}
ID2LABEL = {i: l for l, i in LABEL2ID.items()}

DATA_DIR = Path(os.getenv("NER_DATA_DIR", Path(__file__).resolve().parent / "data"))
MODEL_DIR = Path(os.getenv("NER_MODEL_DIR", Path(__file__).resolve().parents[1] / "models" / "ner"))


def load_corpus(split: str) -> list[dict]:
    path = DATA_DIR / f"ner_{split}.jsonl"
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not records:
        raise FileNotFoundError(f"语料为空: {path}——先运行 tools/data/download_dataset.py")
    return records


def decode_entities(chars: list[str], tags: list[str]) -> list[tuple[str, str, int]]:
    """BIO 解码 → [(field, value, 起始下标)]；非法序列宽容处理（I- 开头并入前实体或丢弃）"""
    entities: list[tuple[str, str, int]] = []
    cur_field: str | None = None
    cur_chars: list[str] = []
    cur_start = 0
    for i, tag in enumerate(tags):
        if tag == "O":
            prefix, field = "O", ""
        else:
            prefix, _, field = tag.partition("-")
        if prefix == "B" or (prefix == "I" and field != cur_field):
            if cur_field:
                entities.append((cur_field, "".join(cur_chars), cur_start))
            cur_field, cur_chars, cur_start = field, [chars[i]], i
        elif prefix == "I" and field == cur_field:
            cur_chars.append(chars[i])
        else:  # O
            if cur_field:
                entities.append((cur_field, "".join(cur_chars), cur_start))
            cur_field = None
    if cur_field:
        entities.append((cur_field, "".join(cur_chars), cur_start))
    return entities


def entity_prf(gold: list[list[tuple[str, str, int]]], pred: list[list[tuple[str, str, int]]]) -> dict:
    """实体级精确匹配 P/R/F1（§2.4），另返回各类字段 F1 便于报告"""
    tp = fp = fn = 0
    per_field: dict[str, dict[str, int]] = {}
    for g_sents, p_sents in zip(gold, pred):
        g, p = set(g_sents), set(p_sents)
        tp += len(g & p)
        fp += len(p - g)
        fn += len(g - p)
        for f, _, _ in g | p:
            stat = per_field.setdefault(f, {"tp": 0, "fp": 0, "fn": 0})
            stat["tp"] += len({x for x in g if x[0] == f} & {x for x in p if x[0] == f})
            stat["fp"] += len({x for x in p if x[0] == f} - {x for x in g if x[0] == f})
            stat["fn"] += len({x for x in g if x[0] == f} - {x for x in p if x[0] == f})
    p_ = tp / (tp + fp) if tp + fp else 0.0
    r_ = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p_ * r_ / (p_ + r_) if p_ + r_ else 0.0
    per_field_f1 = {
        f: round(2 * s["tp"] / (2 * s["tp"] + s["fp"] + s["fn"]), 4) if (2 * s["tp"] + s["fp"] + s["fn"]) else 0.0
        for f, s in sorted(per_field.items())
    }
    return {"precision": round(p_, 4), "recall": round(r_, 4), "f1": round(f1, 4), "per_field_f1": per_field_f1}


def train() -> Path:
    """重依赖在函数内导入：模块顶层保持轻量，指标函数可被单元测试直接导入"""
    import torch
    from datasets import Dataset
    from transformers import (
        AutoModelForTokenClassification,
        AutoTokenizer,
        DataCollatorForTokenClassification,
        Trainer,
        TrainingArguments,
    )

    base = "bert-base-chinese"
    tokenizer = AutoTokenizer.from_pretrained(base)
    model = AutoModelForTokenClassification.from_pretrained(
        base, num_labels=len(LABELS), id2label=ID2LABEL, label2id=LABEL2ID
    )

    def to_dataset(split: str) -> Dataset:
        recs = load_corpus(split)
        return Dataset.from_dict({"chars": [r["chars"] for r in recs], "tags": [r["tags"] for r in recs]})

    def tokenize(batch):
        # 字符级输入：每个汉字视作一个"词"，首子词带标签、其余 -100
        enc = tokenizer(batch["chars"], is_split_into_words=True, truncation=True, max_length=256)
        labels = []
        for i, tags in enumerate(batch["tags"]):
            word_ids = enc.word_ids(batch_index=i)
            prev = None
            lab = []
            for wid in word_ids:
                if wid is None:
                    lab.append(-100)
                elif wid != prev:
                    lab.append(LABEL2ID.get(tags[wid], 0))
                else:
                    lab.append(-100)
                prev = wid
            labels.append(lab)
        enc["labels"] = labels
        return enc

    train_ds = to_dataset("train").map(tokenize, batched=True, remove_columns=["chars", "tags"])
    val_raw = to_dataset("val")
    val_ds = val_raw.map(tokenize, batched=True, remove_columns=["chars", "tags"])

    def compute_metrics(eval_pred):
        preds = eval_pred.predictions.argmax(-1)
        gold_entities, pred_entities = [], []
        for i in range(len(val_raw)):
            chars = val_raw[i]["chars"]
            gold_tags = val_raw[i]["tags"]
            # 逐句重新分词，取每个字符首子词的预测作为该字符标签
            enc = tokenizer(chars, is_split_into_words=True, truncation=True, max_length=256)
            pred_tags, seen = [], set()
            for j, wid in enumerate(enc.word_ids()):
                if wid is None or wid in seen:
                    continue
                seen.add(wid)
                pred_tags.append(ID2LABEL.get(int(preds[i][j]), "O"))
            pred_tags += ["O"] * (len(gold_tags) - len(pred_tags))  # 截断尾部补 O
            gold_entities.append(decode_entities(chars, gold_tags))
            pred_entities.append(decode_entities(chars, pred_tags[: len(gold_tags)]))
        return entity_prf(gold_entities, pred_entities)

    args = TrainingArguments(
        output_dir=str(MODEL_DIR / "_ckpt"),
        num_train_epochs=4,                     # §2.3
        per_device_train_batch_size=16,         # §2.3
        per_device_eval_batch_size=32,
        learning_rate=2e-5,                     # §2.3
        warmup_ratio=0.1,                       # §2.3 前 10% 线性 warmup
        weight_decay=0.01,
        seed=42,                                # §2.3 写死可复现
        logging_steps=50,
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="f1",
        greater_is_better=True,
        save_total_limit=1,
        report_to=[],
        fp16=torch.cuda.is_available(),
    )

    trainer = Trainer(
        model=model, args=args, train_dataset=train_ds, eval_dataset=val_ds,
        data_collator=DataCollatorForTokenClassification(tokenizer),
        compute_metrics=compute_metrics,
    )
    trainer.train()

    metrics = trainer.evaluate()
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(MODEL_DIR)
    tokenizer.save_pretrained(MODEL_DIR)
    (MODEL_DIR / "metrics.json").write_text(json.dumps({
        "version": "v1",
        "f1": float(metrics.get("eval_f1", 0.0)),
        "precision": float(metrics.get("eval_precision", 0.0)),
        "recall": float(metrics.get("eval_recall", 0.0)),
        "per_field_f1": metrics.get("eval_per_field_f1", {}),
        "train_samples": len(train_ds),
        "trained_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "base_model": base,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n产物已保存: {MODEL_DIR}（放到 backend/models/ner/ 即自动启用）")
    return MODEL_DIR


if __name__ == "__main__":
    train()
