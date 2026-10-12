"""S04 JD 结构化要求抽取：规则 + 技能词典（离线，无外部 API）。

出参契约（与 docs/api-schemas.md §2 req_json 一致）：
    {"degree": "本科" | None, "min_years": 3 | None, "skills": ["Python", ...]}
"""
import re

from app.svc.ner_rules import match_skills, normalize_value

# JD 里学历要求的常见表述
_DEGREE_RE = re.compile(r"(博士|硕士|研究生|本科|大专|专科|学历不限)")
# 年限要求："3年以上Python开发经验" / "经验：3-5年" / "三年以上相关经验"
# 数字/中文与"经验"之间允许 ≤10 字修饰（以上/的相关/开发等）
_YEARS_RES = [
    re.compile(r"(\d{1,2})\s*[-~至]\s*(\d{1,2})\s*年"),      # 区间取下限
    re.compile(r"(\d{1,2})\s*年(?:及以上|以上)?[^0-9]{0,10}?(?:经验|经历)"),
    re.compile(r"(?:经验|经历)\s*[:：]?\s*(\d{1,2})\s*年"),
    re.compile(r"([一二三四五六七八九十]{1,2})\s*年(?:及以上|以上)?[^0-9]{0,10}?(?:经验|经历)"),
]
_CN_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def build_jd_requirements(jd_text: str) -> dict:
    """入参 JD 原文；出参 {degree, min_years, skills}"""
    degree = _extract_degree(jd_text)
    min_years = _extract_min_years(jd_text)
    skills = _extract_skills(jd_text)
    return {"degree": degree, "min_years": min_years, "skills": skills}


def _extract_degree(text: str) -> str | None:
    m = _DEGREE_RE.search(text)
    if m is None:
        return None
    return normalize_value("degree", m.group(1))


def _extract_min_years(text: str) -> int | None:
    years: list[int] = []
    for i, pat in enumerate(_YEARS_RES):
        for m in pat.finditer(text):
            if i == 0:  # 区间取下限
                years.append(int(m.group(1)))
            elif m.lastindex and m.group(1) in _CN_NUM:
                years.append(_CN_NUM[m.group(1)])
            elif m.lastindex:
                try:
                    years.append(int(m.group(1)))
                except ValueError:
                    continue
    if not years:
        return None
    return min(max(min(years), 0), 30)  # 下限语义，异常大值截断


def _extract_skills(text: str) -> list[str]:
    """匹配忽略大小写，存储保留词典展示大小写（证据链显示效果与契约示例一致）"""
    return match_skills(text)[:20]
