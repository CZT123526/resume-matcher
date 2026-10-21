"""JD 结构化抽取（S04）与证据链（S07）单元测试。"""
from app.svc.evidence import compute_evidence
from app.svc.jd_parsing import build_jd_requirements


def test_jd_basic_extraction():
    req = build_jd_requirements("要求：3年以上Python开发经验，本科及以上学历，熟悉FastAPI、MySQL，有Docker经验优先")
    assert req["degree"] == "本科"
    assert req["min_years"] == 3
    assert {"python", "fastapi", "mysql", "docker"} <= {s.lower() for s in req["skills"]}


def test_jd_skills_display_case():
    """req_json 技能保留词典展示大小写（证据链显示 "符合：Python" 而非全小写）"""
    req = build_jd_requirements("熟悉Python与FastAPI")
    assert "Python" in req["skills"]
    assert "FastAPI" in req["skills"]


def test_jd_year_range_takes_lower():
    req = build_jd_requirements("经验：3-5年，硕士优先")
    assert req["min_years"] == 3
    assert req["degree"] == "硕士"


def test_jd_chinese_numeral_years():
    req = build_jd_requirements("三年以上相关经验")
    assert req["min_years"] == 3


def test_jd_empty_fields():
    req = build_jd_requirements("负责产品运营")
    assert req["degree"] is None
    assert req["min_years"] is None
    assert req["skills"] == []


def test_evidence_full_match():
    ents = [
        {"field_key": "skill", "field_value": "python"},
        {"field_key": "skill", "field_value": "fastapi"},
        {"field_key": "skill", "field_value": "docker"},
        {"field_key": "degree", "field_value": "硕士"},
        {"field_key": "years", "field_value": "5"},
    ]
    ev = compute_evidence({"skills": ["Python", "FastAPI", "Go"], "degree": "本科", "min_years": 3}, ents)
    # T50：每条 JD 要求一个标签，符合/不符合各一行
    assert "符合：Python" in ev and "符合：FastAPI" in ev and "不符合：Go" in ev
    assert "符合：学历 硕士≥本科" in ev
    assert "符合：经验 5年≥3年" in ev
    assert len(ev) == 5  # 3 技能 + 1 学历 + 1 经验


def test_evidence_deficient():
    ents = [
        {"field_key": "skill", "field_value": "python"},
        {"field_key": "degree", "field_value": "大专"},
        {"field_key": "years", "field_value": "1"},
    ]
    ev = compute_evidence({"skills": ["Python"], "degree": "硕士", "min_years": 3}, ents)
    assert "符合：Python" in ev
    assert "不符合：学历 大专<硕士" in ev
    assert "不符合：经验 1年<3年" in ev


def test_evidence_unknown_fields():
    """T49/T50：学历或年限任一侧认不出 → 该标签不出现，不再有「未识别」占位"""
    ev = compute_evidence({"skills": [], "degree": None, "min_years": None}, [])
    assert not any("学历" in e for e in ev)
    assert not any("经验" in e for e in ev)
    assert not any("技能" in e for e in ev)


def test_evidence_years_unknown_omitted():
    """T49：任一侧年限认不出 → 经验行整行不出现，不再输出「经验：未识别」占位"""
    # 双侧都缺
    ev = compute_evidence({"min_years": None}, [])
    assert not any("经验" in e for e in ev)
    # 简历侧缺
    ev2 = compute_evidence({"min_years": 3}, [{"field_key": "degree", "field_value": "本科"}])
    assert not any("经验" in e for e in ev2)
    # JD 侧缺
    ev3 = compute_evidence({"min_years": None}, [{"field_key": "years", "field_value": "5"}])
    assert not any("经验" in e for e in ev3)
    # years 值非数字（历史脏数据）
    ev4 = compute_evidence({"min_years": 3}, [{"field_key": "years", "field_value": "多年"}])
    assert not any("经验" in e for e in ev4)
    # 双侧齐全仍然正常给结论
    ev5 = compute_evidence({"min_years": 3}, [{"field_key": "years", "field_value": "5"}])
    assert "符合：经验 5年≥3年" in ev5


def test_duty_label_masked_from_skills():
    """T35：行首职责标签（"1、数据分析：…"）是栏目名不是技能，不进 req_json"""
    req = build_jd_requirements(
        "岗位职责：\n"
        "1、数据分析：每日盯店铺核心数据，输出周报与复盘\n"
        "2、活动策划：参与大促方案制定\n"
        "任职要求：\n"
        "1、会看生意参谋等数据后台，能从数据里发现问题"
    )
    assert "数据分析" not in req["skills"]


def test_prose_skill_mention_kept():
    """正文里的真实技能提及不受标签遮蔽影响：职责行冒号后的内容、要求段正文都保留"""
    req = build_jd_requirements(
        "岗位职责：\n"
        "1、数据分析：基于SQL与Python开展客群分析\n"
        "任职要求：\n"
        "1、SQL必须熟练，会Python者优先\n"
        "2、有风控策略、数据分析或反欺诈相关实习经验者优先"
    )
    assert "SQL" in req["skills"] and "Python" in req["skills"]
    assert "数据分析" in req["skills"]  # 要求段正文提及保留，只有行首标签被遮
