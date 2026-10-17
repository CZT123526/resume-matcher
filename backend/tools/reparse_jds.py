"""用当前 jd_parsing 逻辑重导出全部 JD 的 req_json（T35 离线工具）。

背景：T35 修复"行首职责标签被当技能"（jd_parsing._extract_skills 遮蔽标签段），
存量 JD 的 req_json 是旧逻辑产物，需重导出。API 无 JD 重解析端点，
本工具用与线上完全相同的 build_jd_requirements 重算后直接写 SQLite（项目自有库）。

只改 req_json，不动 content/title/id；逐条打印 skills 前后差异。

用法：cd backend && python -X utf8 -I tools/reparse_jds.py [--dry]
"""
import json
import sys
from collections import Counter

sys.path.insert(0, ".")
from app.config import settings  # noqa: E402
from app.svc.jd_parsing import build_jd_requirements  # noqa: E402
from app.db import get_db  # noqa: E402


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    dry = "--dry" in sys.argv
    conn = get_db()
    try:
        rows = conn.execute("SELECT id, title, content, req_json FROM jds ORDER BY id").fetchall()
        changed = 0
        diff_titles: list[str] = []
        for jid, title, content, req_raw in rows:
            old = json.loads(req_raw) if req_raw else {}
            new = build_jd_requirements(content)
            if new != old:
                changed += 1
                d = set(new["skills"]) - set(old["skills"])
                r = set(old["skills"]) - set(new["skills"])
                tag = f"jd{jid} {title}: "
                if d or r:
                    tag += f"skills +{sorted(d)} -{sorted(r)}"
                if old["degree"] != new["degree"]:
                    tag += f" degree {old['degree']}→{new['degree']}"
                if old["min_years"] != new["min_years"]:
                    tag += f" years {old['min_years']}→{new['min_years']}"
                diff_titles.append(tag)
                if not dry:
                    conn.execute(
                        "UPDATE jds SET req_json=? WHERE id=?", (json.dumps(new, ensure_ascii=False), jid)
                    )
        if not dry:
            conn.commit()
        print(f"共 {len(rows)} 条 JD，req_json 变化 {changed} 条{'（dry-run 未写入）' if dry else '，已写入'}")
        for t in diff_titles:
            print(" ", t)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
