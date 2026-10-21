"""S07 证据链生成：只解释分数，绝不参与打分（算法设计 §4 红线）。

T50 起按「JD 的每条要求一个标签」出文案（全角冒号），前端按文案着色（符合=绿/不符合=红）：
- 符合：Python ／ 不符合：Docker（每条技能要求一个标签，按 JD 原始顺序）
- 符合：学历 本科≥大专 ／ 不符合：学历 大专<硕士（任一侧认不出就不出现，T49 同口径）
- 符合：经验 5年≥3年 ／ 不符合：经验 1年<3年（任一侧认不出就不出现，T49）
历史任务的旧文案（技能重叠/缺少技能/学历满足…）为任务时点存档，原样保留，前端着色兼容。
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

    # 1. 技能：每条要求一个标签，符合绿/不符合红（匹配忽略大小写，展示保留 JD 原始写法）
    resume_skills = {s.lower() for s in by_key.get("skill", [])}
    for s in jd_reqs.get("skills") or []:
        if s.lower() in resume_skills:
            evidence.append(f"符合：{s}")
        else:
            evidence.append(f"不符合：{s}")

    # 2. 学历：认不出就不出现本行（T49 同口径，不再有「未识别」占位）
    jd_degree = jd_reqs.get("degree")
    resume_degree = (by_key.get("degree") or [None])[0]
    if jd_degree is not None and resume_degree is not None:
        jd_rank = _DEGREE_RANK.get(jd_degree, -1)
        r_rank = _DEGREE_RANK.get(resume_degree, -1)
        if r_rank >= jd_rank >= 0:
            evidence.append(f"符合：学历 {resume_degree}≥{jd_degree}")
        else:
            evidence.append(f"不符合：学历 {resume_degree}<{jd_degree}")

    # 3. 年限：任一侧认不出就不出现本行（T49 用户裁决——
    #    库内简历原文 0/1372 有显式年限句式，占位行没有信息量）
    jd_years = jd_reqs.get("min_years")
    resume_years_raw = (by_key.get("years") or [None])[0]
    try:
        resume_years = int(str(resume_years_raw)) if resume_years_raw is not None else None
    except ValueError:
        resume_years = None
    if jd_years is not None and resume_years is not None:
        if resume_years >= jd_years:
            evidence.append(f"符合：经验 {resume_years}年≥{jd_years}年")
        else:
            evidence.append(f"不符合：经验 {resume_years}年<{jd_years}年")

    return evidence
