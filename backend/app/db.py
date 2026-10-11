"""SQLite 访问层（轻量，不引入 ORM）。

纪律：
- svc 层统一经 get_db() 取连接，行以字典形式读写（row_factory）；
- 外键约束需显式 PRAGMA foreign_keys=ON（SQLite 默认关闭）；
- 建表唯一来源是 db/schema.sql（init_db 执行它），禁止代码里手写 DDL。
"""
import sqlite3
from pathlib import Path
from typing import Any, Optional

from app.config import settings

BACKEND_DIR = Path(__file__).resolve().parent.parent  # backend/
REPO_ROOT = BACKEND_DIR.parent


def db_file() -> Path:
    """业务库文件绝对路径：DB_PATH 支持绝对路径或相对 backend/ 的相对路径"""
    p = Path(settings.DB_PATH)
    return p if p.is_absolute() else (BACKEND_DIR / p).resolve()


def upload_dir() -> Path:
    """简历原件保存目录绝对路径（UPLOAD_DIR，规则同 DB_PATH），不存在则创建。

    文件以 {resume_id}.{ext} 命名避免重名冲突，原文件名保存在 resumes.file_name。
    """
    p = Path(settings.UPLOAD_DIR)
    d = p if p.is_absolute() else (BACKEND_DIR / p).resolve()
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_db() -> sqlite3.Connection:
    """新建连接（调用方负责 close）。SQLite 文件库，不做连接池。"""
    conn = sqlite3.connect(db_file(), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db(path: Optional[Path] = None) -> None:
    """执行 db/schema.sql 建表（全部 IF NOT EXISTS，可重复执行）。

    path 参数仅供测试注入临时库文件。
    """
    schema = (REPO_ROOT / "db" / "schema.sql").read_text(encoding="utf-8")
    target = path or db_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target)
    try:
        conn.executescript(schema)
        conn.commit()
    finally:
        conn.close()


def rows_to_dicts(rows: list) -> list[dict[str, Any]]:
    """sqlite3.Row 列表 → 字典列表（组装响应体用）"""
    return [dict(r) for r in rows]


def backfill_search_index() -> int:
    """把已有解析完成的简历补进全文索引（幂等：只补缺失的）。返回本次补的条数。

    增量同步点在解析流水线（done 时写入）与删除接口（级联清除）；本函数只管存量回填。
    """
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO resume_search(resume_id, file_name, raw_text) "
            "SELECT id, file_name, raw_text FROM resumes "
            "WHERE parse_status='done' AND raw_text IS NOT NULL "
            "AND id NOT IN (SELECT CAST(resume_id AS INTEGER) FROM resume_search)"
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()
