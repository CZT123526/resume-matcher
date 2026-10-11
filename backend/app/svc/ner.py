"""S02 实体抽取调度：BERT NER（模型就位时）→ 规则兜底（source=rule）。

模型接入约定：把 Colab 训练产物（config.json / model.safetensors / vocab.txt）
放到 backend/models/ner/ 即自动启用 BERT 推理，无需改任何代码——
这就是面向接口编程的好处：调用方不关心背后是谁在抽取。
"""
import logging
import re
import threading
from pathlib import Path

from app.svc import ner_rules

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parents[2]  # app/svc/ner.py → backend/
NER_MODEL_DIR = BACKEND_DIR / "models" / "ner"
METRICS_FILE = NER_MODEL_DIR / "metrics.json"

_bert_pipeline = None       # 已加载的 transformers pipeline
_model_checked = False      # 是否已尝试加载（失败不再重试，避免每请求开销）
_init_lock = threading.Lock()  # 并发上传时多个后台任务同时触发加载，只允许加载一次


def _load_pipeline():
    """加载 NER 模型；不可用时返回 None（规则兜底）。只应被 _get_bert_pipeline 调用。"""
    if not (NER_MODEL_DIR / "config.json").exists():
        logger.info("NER 模型未就位(%s)，实体抽取走规则兜底(source=rule)", NER_MODEL_DIR)
        return None
    try:
        from transformers import (
            AutoModelForTokenClassification,
            AutoTokenizer,
            pipeline,
        )

        tokenizer = AutoTokenizer.from_pretrained(str(NER_MODEL_DIR))
        model = AutoModelForTokenClassification.from_pretrained(str(NER_MODEL_DIR))
        pipe = pipeline(
            "token-classification",
            model=model,
            tokenizer=tokenizer,
            aggregation_strategy="simple",
        )
        logger.info("NER 模型已加载: %s", NER_MODEL_DIR)
        return pipe
    except Exception as exc:  # 模型损坏等异常不阻断服务
        logger.warning("NER 模型加载失败，降级规则抽取: %s", exc)
        return None


def _get_bert_pipeline():
    """懒加载 NER 模型（双检锁：加载期间到达的其他请求等待而非误判为无模型）"""
    global _bert_pipeline, _model_checked
    if _model_checked:  # 快路径无锁
        return _bert_pipeline
    with _init_lock:
        if not _model_checked:
            _bert_pipeline = _load_pipeline()  # 先加载完再置位：等待者醒来才能拿到结果而非 None
            _model_checked = True
    return _bert_pipeline


def extract_entities_bert(text: str) -> list[dict[str, str]]:
    """抽取简历实体（契约见 svc/contracts.py S02）。

    出参: [{"field_key", "field_value", "source"}]，source ∈ {bert, rule}

    字段级合并：微调数据集只有 NAME/EDU/ORG/TITLE 等标签、没有 skill/years/school，
    BERT 只覆盖它擅长的字段；其余字段由规则补齐（source=rule），证据链不受影响。
    """
    pipe = _get_bert_pipeline()
    if pipe is None:
        return ner_rules.extract_entities(text)

    entities: list[dict[str, str]] = []
    # 句级切分与算法设计 §2.2 一致：长文本按行分批，防截断丢实体
    for chunk in _split_sentences(text):
        try:
            for item in pipe(chunk):
                field_key = _map_label(item["entity_group"])
                if field_key is None:
                    continue
                if not _has_line_basis(item["word"], chunk):
                    continue
                value = ner_rules.normalize_value(field_key, item["word"])
                if value and not any(
                    e["field_key"] == field_key and e["field_value"] == value for e in entities
                ):
                    entities.append(
                        {"field_key": field_key, "field_value": value, "source": "bert"}
                    )
        except Exception as exc:
            logger.warning("BERT 抽取分句失败，跳过该句: %s", exc)

    # 字段级兜底合并：BERT 没抽到的字段用规则补（同字段同值去重）
    covered = {e["field_key"] for e in entities}
    for e in ner_rules.extract_entities(text):
        if e["field_key"] not in covered:
            entities.append(e)
    return entities


def _map_label(label: str) -> str | None:
    """模型标签 → 7 字段。Colab 训练脚本直接以 7 字段名保存 id2label。"""
    label = label.lower().replace("b-", "").replace("i-", "").replace("e-", "").replace("s-", "")
    return label if label in ner_rules.ENTITY_KEYS_SET else None


def _has_line_basis(span: str, chunk: str) -> bool:
    """原文依据校验（T29.2）：实体片段去空白后必须逐字出现在原件的同一行里。

    挡两类 BERT 聚合噪声——跨行粘连的长串（把两行技能拼成"文案策划剪映抖音小红书"）
    和词碎片（"##ot"）：它们在页面上就是"查无原文"的假实体，宁可丢弃。
    """
    if "##" in span:
        return False
    v = re.sub(r"\s+", "", span)
    if not v:
        return False
    return any(v in re.sub(r"\s+", "", line) for line in chunk.splitlines())


def _split_sentences(text: str, max_len: int = 400) -> list[str]:
    """按行切句并合并到 max_len 内（推理批次单位）"""
    chunks, buf = [], ""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if len(buf) + len(line) + 1 > max_len:
            if buf:
                chunks.append(buf)
            buf = line[:max_len]
        else:
            buf = f"{buf}\n{line}" if buf else line
    if buf:
        chunks.append(buf)
    return chunks
