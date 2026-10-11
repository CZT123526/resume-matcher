"""库内一致性审计（T29.2 起常设）：简历数据必须有原文依据。

查两类问题：
1. 库存解析文本 vs 硬盘原件（db/uploads/{id}.{ext}）是否一致——防"文件与数据张冠李戴"；
2. 每条实体是否能在原件里逐字找到（去空白比对；学历按归一表别名认定；
   年限按"{n}年"上下文认定）——防"查无原文"的假实体。

只读操作（SQLite mode=ro），不改任何数据。用法：
    cd backend && python tools/audit_consistency.py
退出码：发现问题时 1（可接 CI）。
"""
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.svc.parsing import parse_document  # noqa: E402  与线上解析同一实现

DB = BACKEND.parent / "db" / "recruiter.db"
UPLOADS = BACKEND.parent / "db" / "uploads"

# 与 ner_rules._DEGREE_PATTERNS 同源的别名表（归一值 → 可接受的原文写法）
_DEGREE_ALIASES = {
    "博士": ("博士", "博士研究生"),
    "硕士": ("硕士", "硕士研究生", "研究生", "mba"),
    "本科": ("本科", "大学本科", "学士学位", "bachelor"),
    "大专": ("大专", "专科", "高职"),
}


def _strip(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def has_basis(fk: str, fv: str, text: str) -> bool:
    """实体值是否有原文依据（去空白逐字比对；学历/年限按各自归一规则认定）"""
    t, tl = _strip(text), text.lower()
    if fk == "degree":
        aliases = _DEGREE_ALIASES.get(fv)
        return bool(aliases) and any(a in tl for a in aliases)
    if fk == "years":
        return re.search(rf"{fv}\s*年", text) is not None
    fv_stripped = _strip(fv)
    if fk == "skill":
        return fv_stripped in tl.replace(" ", "")
    if fk == "company":  # 允许省略"有限公司"后缀的核心名匹配
        core = fv.replace("有限公司", "").replace("股份有限公司", "")
        return fv_stripped in t or (len(core) >= 2 and core in t)
    return fv_stripped in t


def main() -> int:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, file_name, parse_status, raw_text FROM resumes ORDER BY id"
    ).fetchall()
    ent_map: dict[int, list[tuple]] = defaultdict(list)
    for e in conn.execute(
        "SELECT resume_id, field_key, field_value, source FROM entities"
    ):
        ent_map[e["resume_id"]].append((e["field_key"], e["field_value"], e["source"]))

    mismatch = missing = total_bad = 0
    clean = 0
    print(f"{'id':>3} {'状态':>6} {'文本一致':>6}  无依据实体")
    for r in rows:
        rid = r["id"]
        src = next(UPLOADS.glob(f"{rid}.*"), None)
        same, bad = "原件缺失", []
        if src is None:
            missing += 1
        else:
            try:
                t = parse_document(src.read_bytes(), src.name)["text"]
                same = "一致" if _strip(r["raw_text"]) == _strip(t) else "不一致"
                if same == "不一致":
                    mismatch += 1
                bad = [
                    f"{fk}={fv}({s})"
                    for fk, fv, s in ent_map.get(rid, [])
                    if not has_basis(fk, fv, t)
                ]
            except Exception as exc:  # 原件损坏等
                same = f"读取失败: {exc}"
        total_bad += len(bad)
        if same == "一致" and not bad:
            clean += 1
            continue
        print(f"{rid:>3} {r['parse_status']:>6} {same:>6}  {'; '.join(bad) if bad else ''}")

    print(
        f"\n=== 汇总：{len(rows)} 份 | 干净 {clean} | 原件缺失 {missing} "
        f"| 文本不一致 {mismatch} | 无依据实体 {total_bad} 条 ==="
    )
    return 1 if (mismatch or total_bad) else 0


if __name__ == "__main__":
    sys.exit(main())
