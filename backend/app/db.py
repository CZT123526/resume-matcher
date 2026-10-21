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
        # 轻量列迁移：CREATE TABLE IF NOT EXISTS 不会给已存在的表补新列，
        # 这里按 PRAGMA 检查、缺则 ALTER（幂等；T42 分数构成明细 / T43 候选人明细）
        cols = {r[1] for r in conn.execute("PRAGMA table_info(match_results)")}
        if cols and "detail_json" not in cols:
            conn.execute("ALTER TABLE match_results ADD COLUMN detail_json TEXT")
        cols = {r[1] for r in conn.execute("PRAGMA table_info(match_score_dist)")}
        if cols and "ids_json" not in cols:
            conn.execute("ALTER TABLE match_score_dist ADD COLUMN ids_json TEXT")
        # T53 挑刺修复：语料来源显式列（此前按 created_at 硬编码时间窗判定，
        # 窗口一过口径静默漂移）+ 在途任务属主进程（启动清扫只清死进程的行，B2）
        cols = {r[1] for r in conn.execute("PRAGMA table_info(resumes)")}
        if cols and "source" not in cols:
            conn.execute("ALTER TABLE resumes ADD COLUMN source TEXT")
        if cols and "owner_pid" not in cols:
            conn.execute("ALTER TABLE resumes ADD COLUMN owner_pid INTEGER")
        cols = {r[1] for r in conn.execute("PRAGMA table_info(match_tasks)")}
        if cols and "owner_pid" not in cols:
            conn.execute("ALTER TABLE match_tasks ADD COLUMN owner_pid INTEGER")
        _backfill_corpus_source(conn)
        conn.commit()
    finally:
        conn.close()


# 一次性回填用的历史批量导入区间（2026-10-19 两批评测加试简历 + 2026-10-21 外校卷）。
# 为什么当初用时间窗：改写简历 286~341 字、半规范简历 148~322 字，字数区间重叠分不开。
# T53 起新上传一律在写入时显式标 source='business'；本表只服务 init_db 对存量行的一次性
# 归类（source IS NULL 的行），不再参与任何运行时过滤——加新考卷批次请直接 UPDATE source。
LEGACY_CORPUS_WINDOWS = {
    "rewrite": ("2026-10-19 13:30:00", "2026-10-19 14:30:00"),   # T37 正文避词改写简历 160 份
    "semispec": ("2026-10-19 15:00:00", "2026-10-19 16:00:00"),  # T38 半规范排版简历 100 份
    "fresh": ("2026-10-21 00:00:00", "2026-10-22 00:00:00"),     # T46 外校卷全新岗位简历 50 份
}


def _backfill_corpus_source(conn) -> None:
    """存量行一次性归类（幂等）：落在历史导入窗内的标对应语料，其余（NULL）按业务简历。

    注意：init_db 的连接未设 row_factory，行按位置取（id, created_at）。
    """
    for rid, created_at in conn.execute(
        "SELECT id, created_at FROM resumes WHERE source IS NULL"
    ).fetchall():
        src = "business"
        for name, (start, end) in LEGACY_CORPUS_WINDOWS.items():
            if start <= (created_at or "") < end:
                src = name
                break
        conn.execute("UPDATE resumes SET source=? WHERE id=?", (src, rid))


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
