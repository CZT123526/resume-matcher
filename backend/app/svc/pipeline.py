"""简历解析流水线（后台任务）：processing → 抽取 → 入库 done/failed。

调用方：api 层上传接口（FastAPI BackgroundTasks），不在请求链路内同步执行。
"""
import logging
import os
import re
import threading

from app.db import get_db
from app.svc.ner import extract_entities_bert
from app.svc.parsing import parse_document

logger = logging.getLogger(__name__)

# BERT 解析是 CPU 密集（每份秒级），并发不限会互相挤兑拖慢全部——
# 用信号量限流（默认 2 路），其余任务在 pending 排队（T29）
_PARSE_SLOTS = threading.BoundedSemaphore(int(os.getenv("PARSE_CONCURRENCY", "2")))

# 文件名兜底姓名（T45）：上传文件名约定「姓名_岗位.docx」。批量重解析实测
# 姓名「静姝」⊂「杨静姝」类截断 113 份——文件名前缀是比模型更可信的姓名来源
_NAME_FROM_FILENAME_RE = re.compile(r"^([一-龥]{2,4})[_\-－·—]")
_FILENAME_GENERIC_RE = re.compile(r"^(简历|resume|cv|最终|新版|最新|我的|终稿|修改)", re.I)


def _fix_name_from_filename(entities: list[dict], filename: str) -> list[dict]:
    """姓名与文件名前缀对不上时的兜底纠正：漏抽补上、截断纠正；
    抽出的名字与文件名完全不同则不动（文件名不一定是姓名，宁缺勿错）。"""
    m = _NAME_FROM_FILENAME_RE.match(filename or "")
    if not m or _FILENAME_GENERIC_RE.match(m.group(1)):
        return entities
    prefix = m.group(1)
    mine = [e for e in entities if e["field_key"] == "name"]
    if not mine:
        return entities + [{"field_key": "name", "field_value": prefix, "source": "rule"}]
    if mine[0]["field_value"] != prefix and mine[0]["field_value"] in prefix:
        mine[0]["field_value"] = prefix  # 截断残名（乔鹏⊂乔鹏飞）整值纠正
        mine[0]["source"] = "rule"
    return entities


def run_parse_pipeline(resume_id: int, file_bytes: bytes, filename: str) -> None:
    """后台执行：解析 → 实体抽取 → 写库。任何异常落为 parse_status=failed，不抛出。"""
    with _PARSE_SLOTS:
        _run_parse(resume_id, file_bytes, filename)


def _run_parse(resume_id: int, file_bytes: bytes, filename: str) -> None:
    conn = get_db()
    try:
        # 认领时盖属主 pid（B2）：另一进程启动清扫时探活跳过，不误杀在途解析
        conn.execute(
            "UPDATE resumes SET parse_status='processing', owner_pid=? WHERE id=?",
            (os.getpid(), resume_id),
        )
        conn.commit()
        try:
            text = parse_document(file_bytes, filename)["text"]
            entities = _fix_name_from_filename(extract_entities_bert(text), filename)

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
            # 全文索引同步（重建式写入，保证幂等；FTS5 的 UNINDEXED 列无类型亲和，
            # 历史数据 int/str 混存，必须 CAST 后比较才能删干净——T32）
            conn.execute(
                "DELETE FROM resume_search WHERE CAST(resume_id AS INTEGER)=?", (resume_id,)
            )
            conn.execute(
                "INSERT INTO resume_search(resume_id, file_name, raw_text) VALUES(?,?,?)",
                (int(resume_id), filename, text),
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
