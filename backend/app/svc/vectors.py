"""简历向量缓存管理（technical.md D2：numpy 矩阵余弦，无独立向量库）。

缓存文件（db/ 下，.gitignore 排除）：
- vectors.npy      归一化向量矩阵，行序与 resume_ids.json 一致
- resume_ids.json  {"order": [resume_id...], "hashes": {id: md5(raw_text)}}
- tfidf_state.npz  降级模式的词表+IDF（保证建库/查询同一特征空间）

重建规则（算法设计 §3.3）：任一 done 简历的内容哈希与缓存不一致 → 全量重建。
"""
import hashlib
import json
import logging
import threading
from pathlib import Path

import numpy as np

from app.db import db_file, get_db

logger = logging.getLogger(__name__)

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


def structured_text(resume: dict, max_len: int = 1000) -> str:
    """编码对象（算法设计 §3.1）：结构化拼接，不用全文；实体缺失退回原文前缀。"""
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
    return text if text.strip() else resume["raw_text"][:max_len]


def _load_meta() -> dict:
    if IDS_FILE.exists():
        return json.loads(IDS_FILE.read_text(encoding="utf-8"))
    return {"order": [], "hashes": {}}


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

    if meta["order"] and meta["hashes"] == hashes and VEC_FILE.exists():
        return np.load(VEC_FILE), meta["order"]

    with _CACHE_LOCK:
        # 双重检查：等锁期间可能已被其他任务重建完成
        meta = _load_meta()
        if meta["order"] and meta["hashes"] == hashes and VEC_FILE.exists():
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
            json.dumps({"order": order, "hashes": hashes}, ensure_ascii=False), encoding="utf-8"
        )
        if progress_cb:
            progress_cb(60)
        logger.info(
            "向量缓存重建完成：%d × %d 维（编码器=%s）", matrix.shape[0], matrix.shape[1], encoder.kind
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
