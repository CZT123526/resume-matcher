"""输出格式化工具：契约规定时间统一 ISO 8601（T 分隔）。"""
from typing import Optional


def iso_time(sqlite_dt: Optional[str]) -> Optional[str]:
    """SQLite datetime('now','localtime') 产出 "2026-10-10 15:00:00"（空格分隔）
    → 统一转为 ISO 8601 "2026-10-10T15:00:00"（见 docs/api-schemas.md §0.4）"""
    if sqlite_dt is None:
        return None
    return sqlite_dt.replace(" ", "T", 1)
