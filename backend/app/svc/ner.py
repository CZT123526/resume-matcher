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
        lines = chunk.splitlines()
        sections = _line_sections(lines)
        try:
            for item in pipe(chunk):
                field_key = _map_label(item["entity_group"])
                if field_key is None:
                    continue
                if not _has_line_basis(item["word"], chunk):
                    continue
                if field_key == "title" and _is_project_line(item["word"], lines, sections):
                    # 项目栏目里的"职位"多为项目名/项目内角色（"AI 日程管家/项目负责人"），
                    # 不是求职岗位——原文有据但字段错，宁缺勿错（T30.3）
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

    return _merge_rule_fallback(entities, text)


def _merge_rule_fallback(entities: list[dict[str, str]], text: str) -> list[dict[str, str]]:
    """字段级兜底合并：BERT 没抽到的字段用规则补（同字段同值去重）。

    例外（T35）：求职意向显式字段行不受"字段已被覆盖"限制，强制并入。
    BERT 常把证书/工具误标成 title（有据但字段错），只要它产出过任意 title，
    字段级兜底就会把「求职意向：XX」这条最准的岗位信号整体挡掉——口语化简历
    上高发（证书行密集），症状是结构化文本里连求职岗位四个字都没有。
    """
    covered = {e["field_key"] for e in entities}
    for e in ner_rules.extract_entities(text):
        if e["field_key"] not in covered:
            entities.append(e)
    it = ner_rules.intent_title(text)
    if it and it not in {e["field_value"] for e in entities if e["field_key"] == "title"}:
        entities.append({"field_key": "title", "field_value": it, "source": "rule"})
    return entities


def _drop_fragments(entities: list[dict[str, str]]) -> list[dict[str, str]]:
    """同字段碎片过滤（T30.2）：BERT 字符级聚合常把一个长实体截短另出一条
    （"程师"⊂"开发工程师"、"里云"⊂"阿里云ACP"、单字"专/委/级"）——
    短值是长值的残渣，页面上就是明显的坏词条，按"宁缺勿错"整条丢弃。
    只作用于 title/company/school 三个多值文本字段；skill 不参与
    （"sql" 确实是 "mysql" 的子串但两者是不同技能，不能互吞）。"""
    by_field: dict[str, list[str]] = {}
    for e in entities:
        by_field.setdefault(e["field_key"], []).append(e["field_value"])

    def is_fragment(field: str, value: str) -> bool:
        vals = by_field.get(field, [])
        return len(value) < 2 or any(value != v and value in v for v in vals)

    return [
        e for e in entities
        if e["field_key"] not in {"title", "company", "school"}
        or not is_fragment(e["field_key"], e["field_value"])
    ]


def _map_label(label: str) -> str | None:
    """模型标签 → 7 字段。Colab 训练脚本直接以 7 字段名保存 id2label。"""
    label = label.lower().replace("b-", "").replace("i-", "").replace("e-", "").replace("s-", "")
    return label if label in ner_rules.ENTITY_KEYS_SET else None


_SECTION_HEADER_RE = re.compile(
    r"^(项目(经历|经验|背景|实践|情况)|教育(经历|背景)|工作(经历|经验)|实习(经历|经验)"
    r"|校园经历|社团经历|职业技能|技能特长|专业技能|技能|荣誉奖项|获奖情况|证书"
    r"|自我评价|个人优势|语言能力|兴趣爱好|培训经历|基本信息)\s*[:：]?\s*$"
)
# 项目头行的"形"特征：破折号+竖线+日期段（如"AI 日程管家 — 智能日程规划 Agent | 项目负责人 2026.04-至今"）。
# PDF 文字层顺序乱时栏目归属会失效（"项目经历"标题与内容被拆开），用行形兜底（T30.3）
_DASH_RE = re.compile(r"—|–|--|─")
_DATE_RANGE_RE = re.compile(r"\d{4}\.\d{1,2}|\d{4}/\d{1,2}|\d{4}-\d{1,2}|至今")


def _line_sections(lines: list[str]) -> list[str | None]:
    """给每行标所属栏目：栏目头行之后归属该栏目，直到下一个栏目头。
    只有"项目*"栏目返回 '项目'，其余栏目返回 '其他'，无栏目为 None。"""
    sections, cur = [], None
    for line in lines:
        s = line.strip()
        if s and _SECTION_HEADER_RE.match(s):
            cur = "项目" if s.startswith("项目") else "其他"
        sections.append(cur)
    return sections


def _is_project_line(span: str, lines: list[str], sections: list[str | None]) -> bool:
    """title 片段所在行是否属于项目语境：栏目为"项目"，或行形是项目头（破折号+竖线+日期段）"""
    v = re.sub(r"\s+", "", span)
    if not v:
        return False
    for i, line in enumerate(lines):
        if v in re.sub(r"\s+", "", line):
            if sections[i] == "项目":
                return True
            stripped = line.strip()
            if "|" in stripped and _DASH_RE.search(stripped) and _DATE_RANGE_RE.search(stripped):
                return True
    return False


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
