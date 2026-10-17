"""金标准构造（算法设计 §5，D6；v2 规则见 T32，v2.1 细分白名单见 T33）：期望岗位即免费监督信号。

正样本判定（按简历类型分路径）：
  模板简历（文件名「姓名_角色.docx」可解析）：用**文件名角色**做匹配依据——
    角色是批量生成器写入的真实岗位元数据，比 NER 实体可靠（T32 抽检发现
    实体层混有「负责人/队员/手册认证/软件设计师」等噪声，且语言前缀在实体中丢失）；
  其他简历（如真实上传）：沿用 title 实体匹配（v1 行为）。
匹配判定（三层递进）：
  ① 核心语义相等；
  ② 互含且短核心带个性词（java ⊂ java后端）——冲突否决兜底（python vs java 互斥判否）；
  ③ 互含但短核心纯通用（数据 ⊂ 大数据 / 算法 ⊂ 大模型算法）——必须过**细分白名单**：
    长核心去掉短核心后的修饰词 ∈ _SPECIALIZATION[短核心] 才认。v2 的教训：
    纯通用短核心的字符串互含会把「数据分析师×大数据开发」「测试开发×渗透测试」
    这类同家族不同工种误配（T33 人工标注 100 对实锤 7 处，全部属于此病灶），
    白名单让「算法×大模型算法」这类合法 specialization 保留、其余一律判否；
  bigram 弱匹配层仅当**两侧个性残留都非空**才启用（新媒体运营×新媒体内容运营）。
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

# 细分白名单（T33 v2.1）：短核心纯通用时，长核心去掉短核心后的修饰词必须在此表内
# 才算合法 specialization。人工标注 100 对校准：修「数据分析师×大数据开发」
# 「测试开发×渗透测试/硬件测试」同家族不同工种误配，同时保留「算法×大模型算法」。
_SPECIALIZATION = {
    "算法": ["大模型", "推荐", "机器学习", "深度学习", "图像", "nlp", "风控", "ai"],
    "数据": ["商业"],
    "后端": ["java", "python", "go", "golang", "c++", "php", ".net", "node", "web"],
    "前端": ["web", "h5", "js", "react", "vue"],
    "测试": ["性能", "自动化", "功能", "软件"],
    "运维": ["sre", "网络", "系统", "linux"],
    "运营": ["新媒体", "内容", "用户"],
    "产品": ["助理", "实习"],
    "设计": ["ui", "ux", "视觉", "交互"],
}


def _specializes(long_core: str, short_core: str) -> bool:
    """长核心去掉短核心后的修饰词是否属于短核心的合法细分（白名单）。"""
    extra = long_core.replace(short_core, "", 1).strip("（）()方向-—· ")
    return extra in _SPECIALIZATION.get(short_core, [])


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


def _match_core(rc: str, jc: str) -> bool:
    """核心层匹配（v2.1）：相等 / 带个性短核心互含（冲突否决）/ 纯通用短核心走白名单。"""
    if rc == jc:
        return True
    if rc in jc:
        short, long_ = rc, jc
    elif jc in rc:
        short, long_ = jc, rc
    else:
        return False
    if _residual(short):
        # 短核心带个性词（java ⊂ java后端）：冲突否决兜底即可
        return not _conflict(rc, jc)
    # 短核心纯通用（数据 ⊂ 大数据）：必须过细分白名单
    return _specializes(long_, short)


def _positive(jd_title: str, candidates: list[str]) -> bool:
    """三层递进：核心相等 → 互含（冲突否决/细分白名单）→ 双个性残留的 bigram。

    课程级近似，人工抽检兜底（tools/eval/spotcheck_gold.py 全量复核 +
    docs/eval/human_check_report.md 人工一致率报告）。
    """
    jc = _core(jd_title)
    jt = jd_title.lower()
    for t in candidates:
        t = t.lower()
        rc = _core(t)
        if not rc or not jc:
            continue
        if _match_core(rc, jc):
            return True
        # bigram 兜底仅当两侧个性残留都非空（纯通用核心的 bigram 就是通用词本身，
        # 会复现「测试 ⊂ 渗透测试」误配——T33 起禁用）
        rb, jb = _residual(rc), _residual(jc)
        if rb and jb:
            for i in range(len(rb) - 1):
                if rb[i : i + 2] in jb and not _conflict(rc, jc):
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
