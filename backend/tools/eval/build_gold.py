"""金标准构造（算法设计 §5，D6；v2 规则见 T32）：期望岗位即免费监督信号。

正样本判定（按简历类型分路径）：
  模板简历（文件名「姓名_角色.docx」可解析）：用**文件名角色**做匹配依据——
    角色是批量生成器写入的真实岗位元数据，比 NER 实体可靠（T32 抽检发现
    实体层混有「负责人/队员/手册认证/软件设计师」等噪声，且语言前缀在实体中丢失）；
  其他简历（如真实上传）：沿用 title 实体匹配（v1 行为）。
匹配判定：核心语义互含（剥通用后缀）**且无技术栈冲突**——残留词互斥
  （如 python vs java）则判不匹配，杜绝「Python 简历 × Java 岗位」跨栈误配。

负采样：该 JD 下非正样本的简历随机抽 5×正样本数，seed=42 可复现；
产物：backend/tools/eval/gold.jsonl，每行 {"jd_id", "resume_id", "rel": 0|1}。

用法（backend 目录下）：python tools/eval/build_gold.py [--neg-ratio 5]
"""
import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # backend/

GOLD_FILE = Path(__file__).with_name("gold.jsonl")


def _title_map() -> tuple[dict[int, list[str]], dict[int, str], dict[int, str]]:
    """({resume_id: [title...]}, {jd_id: jd_title}, {resume_id: file_name})，来自库内已抽取实体"""
    from app.db import get_db

    conn = get_db()
    try:
        titles: dict[int, list[str]] = {}
        for r in conn.execute(
            "SELECT resume_id, field_value FROM entities WHERE field_key='title'"
        ):
            titles.setdefault(r["resume_id"], []).append(r["field_value"])
        jds = {
            r["id"]: r["title"]
            for r in conn.execute("SELECT id, title FROM jds")
        }
        files = {
            r["id"]: r["file_name"]
            for r in conn.execute("SELECT id, file_name FROM resumes")
        }
    finally:
        conn.close()
    return titles, jds, files


# 通用职位后缀词：剥离后再比对，避免"后端开发工程师/前端开发工程师"因
# 共享"开发"被误判同岗（长词先剥）
_GENERIC_TOKENS = ["工程师", "分析师", "设计师", "架构师", "开发", "专员", "经理", "助理", "主管", "总监"]

# 领域通用词：核心语义里再剥掉后仍互斥的，视为技术栈/方向冲突（T32 v2）
# 例：python后端 vs java后端 → 残留 python / java 互斥 → 不匹配；
#     算法 vs 大模型算法 → 残留 "" vs "大模型" → 空一侧不判冲突（通用角色可匹配细分岗）
_DOMAIN_GENERIC = ["后端", "前端", "算法", "数据", "测试", "运维", "分析", "设计", "内容", "运营", "开发"]


def _core(title: str) -> str:
    """剥离通用后缀词后的核心语义（如 后端开发工程师→后端、数据分析师→数据）"""
    t = title.lower().strip()
    for tok in _GENERIC_TOKENS:
        t = t.replace(tok, "")
    return t.strip()


def _residual(core: str) -> str:
    """核心语义再剥领域通用词后的"个性残留"（python后端→python）"""
    for tok in _DOMAIN_GENERIC:
        core = core.replace(tok, "")
    return core.strip()


def _conflict(a_core: str, b_core: str) -> bool:
    """两边个性残留都非空且互不包含 → 技术栈/方向冲突"""
    ra, rb = _residual(a_core), _residual(b_core)
    return bool(ra) and bool(rb) and ra not in rb and rb not in ra


_ROLE_RE = None  # 惰性编译：^[^_]+_(角色)\.(pdf|docx)$


def _filename_role(file_name: str) -> str | None:
    """模板简历文件名「姓名_角色.docx」→ 角色；解析失败返回 None"""
    global _ROLE_RE
    if _ROLE_RE is None:
        import re

        _ROLE_RE = re.compile(r"^[^_]+_(.+)\.(pdf|docx)$")
    m = _ROLE_RE.match(file_name or "")
    return m.group(1) if m else None


def _positive(jd_title: str, candidates: list[str]) -> bool:
    """核心语义互含（且无技术栈冲突）即匹配；再退化为无冲突的 bigram。

    课程级近似，人工抽检兜底（tools/eval/spotcheck_gold.py 全量复核）。
    """
    jc = _core(jd_title)
    jt = jd_title.lower()
    for t in candidates:
        t = t.lower()
        rc = _core(t)
        # 核心互含（"后端" ⊂ "Python后端"），但 python后端 × java后端 这类
        # 残留互斥的判不匹配（T32 v2 冲突否决）
        if rc and jc and (rc in jc or jc in rc) and not _conflict(rc, jc):
            return True
        # bigram 兜底同样过冲突检查
        for i in range(len(rc or t) - 1):
            if (rc or t)[i : i + 2] in (jc or jt) and not _conflict(rc or t, jc or jt):
                return True
    return False


def build(neg_ratio: int = 5, seed: int = 42) -> list[dict]:
    titles, jds, files = _title_map()
    pairs: list[dict] = []
    rng = random.Random(seed)

    # v2：模板简历用文件名角色（生成器写入的真实岗位元数据），
    #     其他简历退回 title 实体；无任何依据的简历不参与配对
    candidates: dict[int, list[str]] = {}
    for rid, fname in files.items():
        role = _filename_role(fname)
        candidates[rid] = [role] if role else titles.get(rid, [])

    for jd_id, jd_title in sorted(jds.items()):
        pos = sorted(rid for rid, cs in candidates.items() if cs and _positive(jd_title, cs))
        neg_pool = sorted(rid for rid, cs in candidates.items() if cs and rid not in set(pos))
        neg = rng.sample(neg_pool, min(len(neg_pool), neg_ratio * len(pos))) if pos else []
        pairs += [{"jd_id": jd_id, "resume_id": rid, "rel": 1} for rid in pos]
        pairs += [{"jd_id": jd_id, "resume_id": rid, "rel": 0} for rid in neg]
    return pairs


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows GBK 控制台打 ⚠ 会崩
    ap = argparse.ArgumentParser(description="构造金标准 gold.jsonl")
    ap.add_argument("--neg-ratio", type=int, default=5, help="负采样倍数（默认5，文档 §5）")
    args = ap.parse_args()

    pairs = build(neg_ratio=args.neg_ratio)
    if not pairs:
        print("库内没有 JD 或没有带 title 实体的简历——先上传简历并创建 JD 再构造金标准")
        return 1
    n_pos = sum(1 for p in pairs if p["rel"] == 1)
    n_jd = len({p["jd_id"] for p in pairs})
    with GOLD_FILE.open("w", encoding="utf-8") as f:
        for p in pairs:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    print(f"gold.jsonl 写入 {len(pairs)} 对（正样本 {n_pos}，覆盖 {n_jd} 个 JD）→ {GOLD_FILE}")
    if n_jd < 5:
        print(f"⚠ 只有 {n_jd} 个 JD 查询，NDCG 方差大——正式实验建议 ≥5 个不同岗位的 JD")
    print("提醒：文档 §5 要求人工抽检 100 对核对噪声率（课程演示至少抽 10 对人工确认）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
