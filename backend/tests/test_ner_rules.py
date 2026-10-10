"""规则版实体抽取测试（S02 兜底实现）。"""
from app.svc.ner_rules import extract_entities, normalize_value

SAMPLE = """个人简历
姓名：张三
男，1998年生
教育经历
2016-2020 清华大学 计算机科学与技术 本科
2020-2023 北京大学 硕士
工作经历
2023-至今 字节跳动科技有限公司
担任后端开发工程师
5年工作经验（含实习）
技能：Python、FastAPI、MySQL、Redis、Docker
求职意向：后端开发工程师
"""


def test_full_resume_extraction():
    ents = {e["field_key"]: e for e in extract_entities(SAMPLE)}
    assert ents["name"]["field_value"] == "张三"
    assert ents["degree"]["field_value"] == "硕士"
    assert ents["years"]["field_value"] == "5"
    assert ents["title"]["field_value"] == "后端开发工程师"
    # school/company 是多值字段（同字段多值输出多条），按集合断言
    schools = {e["field_value"] for e in extract_entities(SAMPLE) if e["field_key"] == "school"}
    assert schools == {"清华大学", "北京大学"}
    companies = {e["field_value"] for e in extract_entities(SAMPLE) if e["field_key"] == "company"}
    assert {c for c in companies if c.startswith("字节跳动")}
    skills = {e["field_value"] for e in extract_entities(SAMPLE) if e["field_key"] == "skill"}
    assert {"python", "fastapi", "mysql", "redis", "docker"} <= skills
    assert all(e["source"] == "rule" for e in extract_entities(SAMPLE))


def test_degree_normalization():
    assert normalize_value("degree", "研究生") == "硕士"
    assert normalize_value("degree", "大学本科") == "本科"
    assert normalize_value("degree", "专科") == "大专"
    assert normalize_value("degree", "神秘学历") == "其他"


def test_years_bounds():
    assert normalize_value("years", "3年") == "3"
    assert normalize_value("years", "999年") == "50"   # 上限截断
    assert normalize_value("years", "abc") is None     # 无数字丢弃


def test_skill_normalization():
    assert normalize_value("skill", " Python ") == "python"


def test_empty_text_returns_empty():
    assert extract_entities("") == []


def test_name_requires_explicit_field():
    """没有"姓名："行时不猜名字（宁缺勿错）"""
    ents = extract_entities("张三是一位工程师")
    assert all(e["field_key"] != "name" for e in ents)
