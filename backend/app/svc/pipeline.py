"""简历解析流水线（后台任务）：processing → 抽取 → 入库 done/failed。

调用方：api 层上传接口（FastAPI BackgroundTasks），不在请求链路内同步执行。
"""
import logging
import os
import threading

from app.db import get_db
from app.svc.ner import extract_entities_bert
from app.svc.parsing import parse_document

logger = logging.getLogger(__name__)

# BERT 解析是 CPU 密集（每份秒级），并发不限会互相挤兑拖慢全部——
# 用信号量限流（默认 2 路），其余任务在 pending 排队（T29）
_PARSE_SLOTS = threading.BoundedSemaphore(int(os.getenv("PARSE_CONCURRENCY", "2")))


def run_parse_pipeline(resume_id: int, file_bytes: bytes, filename: str) -> None:
    """后台执行：解析 → 实体抽取 → 写库。任何异常落为 parse_status=failed，不抛出。"""
    with _PARSE_SLOTS:
        _run_parse(resume_id, file_bytes, filename)


def _run_parse(resume_id: int, file_bytes: bytes, filename: str) -> None:
    conn = get_db()
    try:
        conn.execute("UPDATE resumes SET parse_status='processing' WHERE id=?", (resume_id,))
        conn.commit()
        try:
            text = parse_document(file_bytes, filename)["text"]
            entities = extract_entities_bert(text)

            conn.execute(
                "UPDATE resumes SET raw_text=?, parse_status='done', parse_error=NULL WHERE id=?",
                (text, resume_id),
            )
            # 重跑幂等：先清旧实体再插入
            conn.execute("DELETE FROM entities WHERE resume_id=?", (resume_id,))
            conn.executemany(
                "INSERT INTO entities(resume_id, field_key, field_value, source) VALUES(?,?,?,?)",
                [(resume_id, e["field_key"], e["field_value"], e["source"]) for e in entities],
            )
            # 全文索引同步（重建式写入，保证幂等）
            conn.execute("DELETE FROM resume_search WHERE resume_id=?", (str(resume_id),))
            conn.execute(
                "INSERT INTO resume_search(resume_id, file_name, raw_text) VALUES(?,?,?)",
                (str(resume_id), filename, text),
            )
            conn.commit()
            logger.info("简历 %s 解析完成，抽取实体 %d 条", resume_id, len(entities))
        except Exception as exc:
            conn.rollback()
            conn.execute(
                "UPDATE resumes SET parse_status='failed', parse_error=? WHERE id=?",
                (str(exc)[:500], resume_id),
            )
            conn.commit()
            logger.warning("简历 %s 解析失败: %s", resume_id, exc)
    finally:
        conn.close()
