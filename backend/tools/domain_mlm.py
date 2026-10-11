"""匹配编码器领域自适应预训练（DAPT，算法设计 §3.2 扩展实验 T25）。

动机：三组对比显示未微调 BERT 编码器 NDCG(0.784) 逊于 TF-IDF(1.000)——通用预训练
语料与简历领域有分布差距。做法：用简历语料对 bert-base-chinese 做掩码语言建模
（MLM 15%）继续预训练，再作为语义编码器重跑三组对比，验证领域适配收益。

语料：tools/data/ner_{train,val}.jsonl 逐行拼接（约 4.3k 条简历句，与抽取侧同源，
     不含 test 防泄漏）。
产物：$MLM_MODEL_DIR（默认 backend/models/bert_domain/）；
     评测时 BERT_MODEL_PATH=<该目录> python tools/run_experiments.py 即用领域版编码。

用法（backend 目录下）：python tools/domain_mlm.py
env：MLM_MAX_LINES 限制语料行数（冒烟用）；MLM_EPOCHS 覆盖轮数（默认 3）
"""
import json
import os
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows GBK 控制台兜底

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/

DATA_DIR = Path(__file__).resolve().parent / "data"
MODEL_DIR = Path(os.getenv("MLM_MODEL_DIR", Path(__file__).resolve().parents[1] / "models" / "bert_domain"))


def load_corpus() -> list[str]:
    """train+val 句子拼接成行（test 留作 NER 评测，防泄漏）"""
    lines: list[str] = []
    for split in ("train", "val"):
        path = DATA_DIR / f"ner_{split}.jsonl"
        for l in path.read_text(encoding="utf-8").splitlines():
            if not l.strip():
                continue
            rec = json.loads(l)
            text = "".join(rec["chars"]).strip()
            if text:
                lines.append(text)
    return lines


def main() -> int:
    import torch
    from datasets import Dataset
    from transformers import (
        AutoModelForMaskedLM,
        AutoTokenizer,
        DataCollatorForLanguageModeling,
        Trainer,
        TrainingArguments,
    )

    corpus = load_corpus()
    limit = os.getenv("MLM_MAX_LINES")
    if limit:
        corpus = corpus[: int(limit)]
    epochs = int(os.getenv("MLM_EPOCHS", "3"))
    print(f"领域语料 {len(corpus)} 行，MLM 继续预训练 {epochs} 轮 → {MODEL_DIR}")

    tokenizer = AutoTokenizer.from_pretrained("bert-base-chinese")
    model = AutoModelForMaskedLM.from_pretrained("bert-base-chinese")

    ds = Dataset.from_dict({"text": corpus})
    ds = ds.map(
        lambda b: tokenizer(b["text"], padding="max_length", truncation=True, max_length=128),
        batched=True,
        remove_columns=["text"],
    )
    collator = DataCollatorForLanguageModeling(tokenizer, mlm=True, mlm_probability=0.15)

    args = TrainingArguments(
        output_dir=str(MODEL_DIR / "_ckpt"),
        num_train_epochs=epochs,
        per_device_train_batch_size=16,
        learning_rate=5e-5,
        warmup_ratio=0.1,
        weight_decay=0.01,
        seed=42,
        logging_steps=50,
        save_strategy="no",
        report_to=[],
        fp16=torch.cuda.is_available(),
    )
    trainer = Trainer(model=model, args=args, train_dataset=ds, data_collator=collator)
    t0 = time.time()
    trainer.train()

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    trainer.save_model(MODEL_DIR)
    tokenizer.save_pretrained(MODEL_DIR)
    (MODEL_DIR / "train_meta.json").write_text(json.dumps({
        "corpus_lines": len(corpus), "epochs": epochs, "minutes": round((time.time() - t0) / 60, 1),
        "trained_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "base": "bert-base-chinese",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"领域编码器已保存: {MODEL_DIR}")
    print(f"复测: BERT_MODEL_PATH={MODEL_DIR} python tools/run_experiments.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
