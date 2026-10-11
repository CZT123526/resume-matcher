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
    # T29.2：判不出的学历返回 None（丢弃），不再归一成"其他"——那是一条原文里不存在的实体
    assert normalize_value("degree", "神秘学历") is None
    assert normalize_value("degree", "英语六级") is None


def test_degree_unknown_not_extracted():
    """全文没有可判定的学历词时，不得产出 degree 实体"""
    ents = extract_entities("姓名：张三\n热爱学习，精通易经")
    assert all(e["field_key"] != "degree" for e in ents)


def test_skill_word_boundary_no_substring_false_positive():
    """回归（T29.2）："SQL" 不得从 "MySQL" 里误切出来；单独出现时照常抽取"""
    ents = extract_entities("技能：MySQL Redis")
    skills = {e["field_value"] for e in ents if e["field_key"] == "skill"}
    assert skills == {"mysql", "redis"}

    ents2 = extract_entities("技能：SQL MySQL")
    skills2 = {e["field_value"] for e in ents2 if e["field_key"] == "skill"}
    assert skills2 == {"sql", "mysql"}

    # 词边界同样挡住 "Go" 误切 "Golang"
    ents3 = extract_entities("会 Golang")
    skills3 = {e["field_value"] for e in ents3 if e["field_key"] == "skill"}
    assert skills3 == {"golang"}


def test_jd_skills_same_boundary_rule():
    """JD 技能抽取与简历共用 match_skills，边界规则一致"""
    from app.svc.jd_parsing import _extract_skills

    assert _extract_skills("熟悉MySQL数据库") == ["MySQL"]
    assert _extract_skills("熟悉 SQL MySQL") == ["MySQL", "SQL"]  # 长词优先序


def test_normalize_value_strips_cjk_latin_boundary_spaces():
    """T29.2：CJK 与英数交界的空格同样去除，实体值与原文逐字一致"""
    assert normalize_value("title", "Java 开发工程师") == "Java开发工程师"
    assert normalize_value("title", "5 年经验相关职位") == "5年经验相关职位"
    assert normalize_value("skill", "Spring Boot") == "springboot"  # 纯英文内部空格保留再小写


def test_bert_spans_need_line_basis(monkeypatch):
    """回归（T29.2）：BERT 词碎片（##ot）与跨行粘连串不得落库，同行片段照常保留"""
    from app.svc import ner

    fake_spans = [
        {"entity_group": "company", "word": "##ot"},                      # 词碎片 → 丢
        {"entity_group": "title", "word": "文案策划剪映抖音小红书"},        # 跨行粘连 → 丢
        {"entity_group": "name", "word": "张 伟"},                         # 同行（含字间空格）→ 留
    ]
    monkeypatch.setattr(ner, "_get_bert_pipeline", lambda: lambda chunk: fake_spans)

    text = "姓名：张伟\n文案策划\n剪映\n抖音\n小红书"
    ents = ner.extract_entities_bert(text)

    assert all(not (e["field_key"] == "company") for e in ents)
    assert all(not (e["field_key"] == "title") for e in ents)
    names = [e["field_value"] for e in ents if e["field_key"] == "name"]
    assert names == ["张伟"]
    assert all(e["source"] == "bert" for e in ents)


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


def test_ner_model_dir_points_to_backend_models():
    """回归：NER_MODEL_DIR 必须指向 backend/models/ner（曾错指 app/models 导致微调模型永不生效）"""
    from app.svc.ner import METRICS_FILE, NER_MODEL_DIR

    assert NER_MODEL_DIR.parent.name == "models" and NER_MODEL_DIR.parent.parent.name == "backend"
    assert METRICS_FILE == NER_MODEL_DIR / "metrics.json"


def test_normalize_value_strips_cjk_inner_spaces():
    """回归：BERT 字符级聚合产生字间空格（"张 伟"/"后 端 开 发"），CJK 邻接处必须去空格"""
    from app.svc.ner_rules import normalize_value

    assert normalize_value("name", "张 伟") == "张伟"
    assert normalize_value("title", "后 端 开 发 工 程 师") == "后端开发工程师"
    assert normalize_value("company", "字 节 跳 动 科 技 有 限 公 司") == "字节跳动科技有限公司"
    assert normalize_value("name", "Jack Chen") is None  # 姓名字段本就只收中文（既有校验，非本次改动）


def test_bert_pipeline_concurrent_lazy_load(monkeypatch):
    """回归：并发上传的多个后台解析同时触发懒加载，慢加载期间其余线程
    不得误判"无模型"而静默走规则（T28 实测 12 份并发仅 1 份走到 BERT）"""
    import threading
    import time

    from app.svc import ner

    calls = {"n": 0}

    def slow_loader():
        calls["n"] += 1
        time.sleep(0.2)  # 模拟模型加载数秒的窗口期
        return "PIPELINE"

    monkeypatch.setattr(ner, "_model_checked", False)
    monkeypatch.setattr(ner, "_bert_pipeline", None)
    monkeypatch.setattr(ner, "_load_pipeline", slow_loader)

    results: list = []
    threads = [threading.Thread(target=lambda: results.append(ner._get_bert_pipeline()))
               for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert calls["n"] == 1                      # 只加载一次
    assert results == ["PIPELINE"] * 8          # 所有等待者都拿到模型，无人降级规则
