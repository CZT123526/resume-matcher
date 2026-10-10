"""S07 证据链生成：只解释分数，绝不参与打分（算法设计 §4 红线）。

文案格式为契约定稿（全角冒号），前端原样展示：
- 技能重叠：Python/FastAPI (2/2)
- 缺少技能：Docker
- 学历满足：硕士≥本科 ｜ 学历不满足：本科<硕士 ｜ 学历：未识别
- 经验满足：5年≥3年 ｜ 经验不足：1年<3年 ｜ 经验：未识别
"""
# 学历序（算法设计 §4）：显式映射，绝不复用 ner_rules 的匹配优先级顺序
_DEGREE_RANK = {"大专": 0, "其他": 0, "本科": 1, "硕士": 2, "博士": 3}


def compute_evidence(jd_reqs: dict, resume_entities: list[dict]) -> list[str]:
    """入参 S04 输出的 req_json 与该简历实体列表；出参证据文本数组"""
    evidence: list[str] = []

    by_key: dict[str, list[str]] = {}
    for e in resume_entities:
        if e.get("field_value"):
            by_key.setdefault(e["field_key"], []).append(e["field_value"])

    # 1. 技能（匹配忽略大小写；展示保留 JD 原始写法，与契约示例一致）
    jd_pairs = [(s, s.lower()) for s in (jd_reqs.get("skills") or [])]
    if jd_pairs:
        resume_skills = {s.lower() for s in by_key.get("skill", [])}
        overlap = [orig for orig, lo in jd_pairs if lo in resume_skills]
        if overlap:
            evidence.append(
                f"技能重叠：{'/'.join(overlap)} ({len(overlap)}/{len(jd_pairs)})"
            )
        missing = [orig for orig, lo in jd_pairs if lo not in resume_skills]
        if missing:
            evidence.append(f"缺少技能：{'、'.join(missing)}")

    # 2. 学历
    jd_degree = jd_reqs.get("degree")
    resume_degree = (by_key.get("degree") or [None])[0]
    if jd_degree is None or resume_degree is None:
        evidence.append("学历：未识别")
    else:
        jd_rank = _DEGREE_RANK.get(jd_degree, -1)
        r_rank = _DEGREE_RANK.get(resume_degree, -1)
        if r_rank >= jd_rank >= 0:
            evidence.append(f"学历满足：{resume_degree}≥{jd_degree}")
        else:
            evidence.append(f"学历不满足：{resume_degree}<{jd_degree}")

    # 3. 年限
    jd_years = jd_reqs.get("min_years")
    resume_years_raw = (by_key.get("years") or [None])[0]
    if jd_years is None or resume_years_raw is None:
        evidence.append("经验：未识别")
    else:
        try:
            resume_years = int(str(resume_years_raw))
        except ValueError:
            evidence.append("经验：未识别")
        else:
            if resume_years >= jd_years:
                evidence.append(f"经验满足：{resume_years}年≥{jd_years}年")
            else:
                evidence.append(f"经验不足：{resume_years}年<{jd_years}年")

    return evidence
