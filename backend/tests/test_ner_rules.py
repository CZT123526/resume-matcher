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
