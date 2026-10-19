"""简历向量缓存管理（technical.md D2：numpy 矩阵余弦，无独立向量库）。

缓存文件（db/ 下，.gitignore 排除）：
- vectors.npy      归一化向量矩阵，行序与 resume_ids.json 一致
- resume_ids.json  {"order": [resume_id...], "hashes": {id: md5(raw_text)}}
- tfidf_state.npz  降级模式的词表+IDF（保证建库/查询同一特征空间）

重建规则（算法设计 §3.3）：任一 done 简历的内容哈希与缓存不一致 → 全量重建；
编码器身份变化（如 BERT_MODEL_PATH 指向领域微调版）同样触发重建——否则查询向量与
库向量不同源，余弦分数会静默错乱（T25 教训）。
"""
import hashlib
import json
import logging
import os
import re
import threading
from pathlib import Path

import numpy as np

from app.db import db_file, get_db

logger = logging.getLogger(__name__)

# 编码对象表示版本：结构化文本格式变化必须换版本——缓存指纹含此版本（T36 B3），
# 旧缓存自动失效重建（raw_text 哈希不变，不换版本会静默沿用旧表示的向量）
REPR_VERSION = "v2"

# 经历要点行：编号要点（1、xxx）或工作动词开头的陈述行；字段行（前6字符内带冒号）跳过
_BULLET_RE = re.compile(r"^\d{1,2}[、.．]")
_WORK_LEAD_RE = re.compile(
    r"^(?:负责|主导|参与|协助|独立|配合|使用|基于|通过|搭建|优化|维护|熟悉|精通|跟进|沉淀)"
)
_WORK_BUDGET = 400  # 经历要点追加预算（字符），实体清单+要点控制在 BERT 512 token 输入内

DB_DIR = db_file().parent
VEC_FILE = DB_DIR / "vectors.npy"
IDS_FILE = DB_DIR / "resume_ids.json"
TFIDF_STATE_FILE = DB_DIR / "tfidf_state.npz"

# 并发匹配任务同时触发重建会互踩缓存文件，全局锁串行化（课程规模足够）
_CACHE_LOCK = threading.Lock()


def _current_resume_data() -> dict[int, dict]:
    """当前库内全部 done 简历 {id: {"raw_text", "entities": [(key, value)...]}}"""
    conn = get_db()
    try:
        resume_rows = conn.execute(
            "SELECT id, raw_text FROM resumes WHERE parse_status='done' AND raw_text IS NOT NULL"
        ).fetchall()
        entity_rows = conn.execute(
            "SELECT e.resume_id, e.field_key, e.field_value FROM entities e "
            "JOIN resumes r ON r.id = e.resume_id WHERE r.parse_status='done'"
        ).fetchall()
    finally:
        conn.close()

    data = {r["id"]: {"raw_text": r["raw_text"], "entities": []} for r in resume_rows}
    for e in entity_rows:
        if e["resume_id"] in data:
            data[e["resume_id"]]["entities"].append((e["field_key"], e["field_value"]))
    return data


def _work_lines(raw_text: str) -> list[str]:
    """工作经历要点行（T36 B3 结构化文本增强）：实体清单丢失的语境信号从原文补回。

    口语化简历的辨析信息藏在经历句里（"负责直播带货全流程"vs"负责剪辑成片"），
    只编实体清单会让不同工种的向量挤在一起（T32 实测分数聚集 0.95~0.97）。
    """
    picked: list[str] = []
    total = 0
    for line in raw_text.splitlines():
        s = line.strip()
        if len(s) < 8 or "：" in s[:6] or ":" in s[:6]:
            continue  # 字段行（姓名：/电话：等）不是经历
        if _BULLET_RE.match(s) or _WORK_LEAD_RE.match(s):
            picked.append(s)
            total += len(s)
            if total >= _WORK_BUDGET:
                break
    return picked


def structured_text(resume: dict, max_len: int = 1000) -> str:
    """编码对象（算法设计 §3.1）：结构化拼接，不用全文；实体缺失退回原文前缀。

    v2（T36 B3）：实体清单之后追加工作经历要点行（编号要点/工作动词句，截断至预算），
    与查询侧同源增强语义与词面信号；格式变更已计入缓存指纹（REPR_VERSION）。
    """
    grouped: dict[str, list[str]] = {}
    for key, value in resume["entities"]:
        if value:
            grouped.setdefault(key, []).append(value)
    parts = [
        f"技能：{'/'.join(grouped.get('skill', []))}" if grouped.get("skill") else "",
        f"职位：{'/'.join(grouped.get('title', []))}" if grouped.get("title") else "",
        f"公司：{'/'.join(grouped.get('company', []))}" if grouped.get("company") else "",
        f"学历：{grouped['degree'][0]}" if grouped.get("degree") else "",
        f"经验：{grouped['years'][0]}年" if grouped.get("years") else "",
    ]
    text = " ".join(p for p in parts if p)
    if not text.strip():
        return resume["raw_text"][:max_len]
    lines = _work_lines(resume.get("raw_text", ""))
    if lines:
        text = f"{text} 经历：{'；'.join(lines)}"[:max_len]
    return text


def _load_meta() -> dict:
    meta = json.loads(IDS_FILE.read_text(encoding="utf-8")) if IDS_FILE.exists() else {"order": [], "hashes": {}}
    meta.setdefault("encoder", "")  # 旧缓存无此字段 → 指纹不匹配触发重建
    return meta


def _encoder_fingerprint() -> str:
    """编码器身份指纹：缓存跨编码器不可复用（换模型必须重建，保证查询/文档同源）。

    含表示版本 REPR_VERSION：结构化文本格式变化同样触发全量重建（T36 B3）。
    """
    from app.svc.embedding import _BERT_MODEL

    kind = "tfidf" if os.getenv("FORCE_TFIDF") == "1" else "bert"
    return f"{kind}:{_BERT_MODEL}:{REPR_VERSION}"


def ensure_cache(progress_cb=None) -> tuple[np.ndarray, list[int]]:
    """确保缓存最新，返回 (矩阵, 对应 resume_id 列表)。

    progress_cb(percent) 供匹配任务上报重建进度（重建是主要耗时）。
    """
    data = _current_resume_data()
    hashes = {
        rid: hashlib.md5(item["raw_text"].encode("utf-8")).hexdigest()
        for rid, item in data.items()
    }
    meta = _load_meta()
    fp = _encoder_fingerprint()

    if meta["order"] and meta["hashes"] == hashes and meta["encoder"] == fp and VEC_FILE.exists():
        return np.load(VEC_FILE), meta["order"]

    with _CACHE_LOCK:
        # 双重检查：等锁期间可能已被其他任务重建完成
        meta = _load_meta()
        if meta["order"] and meta["hashes"] == hashes and meta["encoder"] == fp and VEC_FILE.exists():
            return np.load(VEC_FILE), meta["order"]

        logger.info("向量缓存失效（简历 %d 份），开始全量重建", len(data))
        from app.svc.embedding import get_encoder, save_tfidf_state

        order = sorted(data)
        corpus = [structured_text(data[rid]) for rid in order]

        encoder = get_encoder()
        if encoder.kind == "tfidf":
            encoder = encoder.fit(corpus)
            save_tfidf_state(encoder, TFIDF_STATE_FILE)
            if progress_cb:
                progress_cb(50)
            matrix = encoder.encode(corpus)
        else:
            if progress_cb:
                progress_cb(30)
            matrix = encoder.encode(corpus)

        np.save(VEC_FILE, matrix)
        IDS_FILE.write_text(
            json.dumps({"order": order, "hashes": hashes, "encoder": fp}, ensure_ascii=False), encoding="utf-8"
        )
        if progress_cb:
            progress_cb(60)
        logger.info(
            "向量缓存重建完成：%d × %d 维（编码器=%s 指纹=%s）", matrix.shape[0], matrix.shape[1], encoder.kind, fp
        )
        return matrix, order


def load_cache() -> tuple[np.ndarray, list[int]] | None:
    """只读缓存；失效返回 None，由调用方触发 ensure_cache"""
    meta = _load_meta()
    if not meta["order"] or not VEC_FILE.exists():
        return None
    return np.load(VEC_FILE), meta["order"]


def load_query_encoder():
    """查询侧编码器：BERT 直接用；TF-IDF 必须加载建库时的词表/IDF（同空间可比）"""
    from app.svc.embedding import _TfidfEncoder, get_encoder, load_tfidf_state

    encoder = get_encoder()
    if encoder.kind == "tfidf":
        state = load_tfidf_state(TFIDF_STATE_FILE)
        if state is None:
            return _TfidfEncoder(vocab={}, idf=np.zeros(0, dtype=np.float32))
        return state
    return encoder
