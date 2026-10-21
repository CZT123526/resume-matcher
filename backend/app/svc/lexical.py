"""T34 关键词重排层（算法设计 §3.2 融合公式；§8 预案落地）。

动机（T32/T33 实测）：BERT 语义分在「同家族不同工种」上区分不开
（Java 岗 top1 可能是 Python 简历，分数聚集 0.954~0.967），而词面证据——
JD 里的技能词/岗位内容词在简历匹配文本中是否出现——恰好补这个短板。

设计约束：
  - 纯规则字符串处理，零外部 API（TC-API-01 红线）；
  - 证据链（§4）依旧只解释不打分：词面分属于**打分侧**（重排融合），
    与证据链互不掺和；
  - 词面核查对象与编码对象同源（structured_text），评测与运行时同口径；
  - JD 无关键词时词面分恒为 0.5（中性），融合后保序不扭曲语义排序。
"""
import re

from app.svc.ner_rules import match_skills, _skill_present

# 职位通用后缀/级别词：抽 JD 标题关键词时剔除（与金标准 build_gold 的
# _GENERIC_TOKENS 同理念；独立维护，避免 app/ 反向依赖 tools/）
_TITLE_SUFFIXES = [
    "工程师", "分析师", "设计师", "架构师", "专员", "经理", "助理", "主管", "总监",
    "高级", "资深", "中级", "初级", "实习", "校招", "应届", "方向", "岗",
]

# 纯领域通用词：中文段**全由这些拼成**时不成关键词（每份简历都有
# "开发/数据"，留着只稀释命中率；含内容词的整段如"大数据开发"保留）
_TITLE_GENERIC = {"后端", "前端", "测试", "运维", "运营", "数据", "算法",
                  "设计", "分析", "内容", "开发", "产品"}

# 词面切分：ASCII 词（java/c++/3d…）或连续中文段
_RUN_RE = re.compile(r"[.#]?[a-z0-9][a-z0-9+#.]*|[一-鿿]+")


def _present(keyword: str, text_lower: str) -> bool:
    """关键词是否出现在文本中：ASCII 词带边界，中文词子串（中文无词边界）。

    B1 挑刺修复：收敛到 ner_rules._skill_present 单一实现（含 T51 复数容错）——
    此前这里另有一份无复数容错的分叉实现，两处口径已经不一致。
    """
    return _skill_present(keyword, text_lower)


def _all_generic(run: str) -> bool:
    """中文段能否被通用词**完整覆盖**（递归，段长 ≤6 字，代价可忽略）。

    后端开发 = 后端+开发 → 全通用，丢弃；大数据开发覆盖不了"大" → 保留
    （整段成关键词，词面证据反而更完整：渗透测试、商业数据分析同理）。
    """
    if not run:
        return True
    return any(
        run.startswith(tok) and _all_generic(run[len(tok):])
        for tok in _TITLE_GENERIC
    )


def extract_jd_keywords(title: str, req: dict | None) -> list[str]:
    """JD 侧重排关键词：结构化技能词 + 标题内容词，去重保序（小写归一）。

    技能词来自 req["skills"]（build_jd_requirements → match_skills，简历/JD
    共用同一词典，T29.2）；标题剥通用后缀后取内容段，仅当整段全由通用词
    拼成时丢弃（「信息安全工程师（渗透测试方向）」→ 渗透测试/信息安全；
    「后端开发」→ 不成关键词；「大数据开发」→ 保留整段）。
    """
    keywords: list[str] = []
    seen: set[str] = set()

    def _add(kw: str) -> None:
        low = kw.lower().strip()
        if len(low) >= 2 and low not in seen:
            seen.add(low)
            keywords.append(low)

    for s in (req or {}).get("skills") or []:
        _add(str(s))

    t = (title or "").lower()
    for tok in _TITLE_SUFFIXES:
        t = t.replace(tok, "")
    for run in _RUN_RE.findall(t):
        if run.isascii() or not _all_generic(run):
            _add(run)
    return keywords


def keyword_hit_score(keywords: list[str], resume_text: str) -> float:
    """词面命中率 = 命中关键词数 / 关键词总数 ∈ [0,1]。

    无关键词时返回 0.5（中性）：没有词面证据就不奖不罚，
    融合后语义分的相对顺序保持不变。
    """
    if not keywords:
        return 0.5
    text_lower = (resume_text or "").lower()
    hits = sum(1 for kw in keywords if _present(kw, text_lower))
    return hits / len(keywords)


def fuse(bert_score: float, lex_score: float, alpha: float) -> float:
    """融合分 = α·语义分 + (1-α)·词面分（算法设计 §3.2，T34）。

    α 是唯一超参：1.0 退化为纯语义（消融对照），0.0 退化为纯词面。
    两输入都在 [0,1]，融合分天然 [0,1]。
    """
    return alpha * bert_score + (1.0 - alpha) * lex_score


def coverage_from_scores(lex_scores) -> float:
    """词面覆盖率：命中率 ≥0.5 的简历占比 ∈ [0,1]（T39 自适应 α 的输入）。

    0.5 是 keyword_hit_score 无关键词时的中性值——只统计"真有词面证据"的份。
    空池返回 1.0（无候选即无降权理由，α 保持基准不变）。
    """
    scores = list(lex_scores)
    if not scores:
        return 1.0
    return sum(1 for s in scores if s >= 0.5) / len(scores)


def adaptive_alpha(base_alpha: float, coverage: float) -> float:
    """自适应 α（T39，算法设计 §3.2b）：词面覆盖越低越靠语义。

    α_eff = base + (1-base)·(1-coverage)
      coverage=1 → α_eff=base（词面证据普遍可得，行为与固定 α 完全一致）；
      coverage=0 → α_eff=1.0（JD 关键词在语料里普遍找不到，词面分失去区分度，
                   退回纯语义，避免 T37 改写考卷上重排层拖累主链路的情形）。
    中间线性过渡，无需新超参。
    """
    return base_alpha + (1.0 - base_alpha) * (1.0 - coverage)
