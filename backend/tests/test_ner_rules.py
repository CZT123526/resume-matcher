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


def test_intent_title_helper():
    """T35：求职意向锚定对外口——黑名单值返回 None，CJK英数交界空格归一"""
    from app.svc import ner_rules
    assert ner_rules.intent_title("求职意向：电商运营") == "电商运营"
    assert ner_rules.intent_title("应聘岗位： 数据工程师") == "数据工程师"
    assert ner_rules.intent_title("求职意向：ai 应用实习岗") == "ai应用实习岗"
    assert ner_rules.intent_title("姓名：张三\n电话：13800000000") is None


def test_bare_yingpin_intent_anchor():
    """T36：模板3写的是「应聘：XX」——裸「应聘」须被锚定，此前角色词整份丢失"""
    from app.svc import ner_rules
    assert ner_rules.intent_title("赵六\n应聘：游戏策划\n工作经历") == "游戏策划"
    ents = ner_rules.extract_entities("赵六\n应聘：电商运营\n杭州某电商公司")
    titles = {e["field_value"] for e in ents if e["field_key"] == "title"}
    assert "电商运营" in titles


def test_merge_rule_fallback_forces_intent_title():
    """T35：BERT 误标 title（证书词等）时，求职意向行的正主岗位仍要并入"""
    from app.svc.ner import _merge_rule_fallback
    text = "求职意向：电商运营\n技能证书\n生意参谋 千牛 Excel\n电子商务师（中级）"
    ents = [{"field_key": "title", "field_value": "电子商务师", "source": "bert"}]
    merged = _merge_rule_fallback(ents, text)
    titles = [e["field_value"] for e in merged if e["field_key"] == "title"]
    assert "电子商务师" in titles
    assert "电商运营" in titles


def test_merge_rule_fallback_no_duplicate():
    """求职意向值已存在（无论来源）时不重复并入"""
    from app.svc.ner import _merge_rule_fallback
    ents = [{"field_key": "title", "field_value": "电商运营", "source": "rule"}]
    merged = _merge_rule_fallback(ents, "求职意向：电商运营")
    assert [e["field_value"] for e in merged if e["field_key"] == "title"].count("电商运营") == 1


def test_industry_skill_words_boundaries():
    """T36：行业工具词入典——CJK 子串、ASCII 词边界，AutoCAD 不误切出 CAD"""
    from app.svc.ner_rules import match_skills
    got = {s.lower() for s in match_skills("熟练使用生意参谋与直通车，会AutoCAD和CAD制图，用Trados翻译")}
    assert "生意参谋" in got and "直通车" in got
    assert "autocad" in got and "cad" in got          # AutoCAD 整词命中
    assert "trados" in got
    # CAD 的 ASCII 词边界：AutoCAD 内部的 "cad" 前面是字母 o，不得单独计一次以外还漏
    got2 = {s.lower() for s in match_skills("只用AutoCAD")}
    assert "autocad" in got2 and "cad" not in got2     # 词边界挡住子串误切


def test_plural_skill_word_boundary():
    """回归（T51，简历 678 实况）：简历写复数 "Transformers" 也要认得词典词
    "Transformer"——空格分隔技能行整行此前只抽出 c++，证据链全标红的根因之一"""
    from app.svc.ner_rules import match_skills
    got = {s.lower() for s in match_skills("熟练使用 PyTorch Transformers Python C++，熟悉向量检索与模型部署")}
    assert {"pytorch", "transformer", "python", "c++"} <= got
    # 复数容错不越界：词中出现的 skill 子串依旧不收（sql 不得从 mysql 里切出）
    got2 = {s.lower() for s in match_skills("会 Golang 和 MySQL")}
    assert "golang" in got2 and "go" not in got2 and "sql" not in got2
    # 以 s 结尾的词典词（pandas/redis）不得匹配到再加 s 的写法
    assert "redis" in {s.lower() for s in match_skills("用 Redis 与 Pandas")}


def test_bert_merged_skill_span_dict_split(monkeypatch):
    """回归（T51，简历 678 实况）：BERT 把空格分隔技能粘成长串、词典护栏整串丢弃，
    而 skill 字段已被幸存的 c++ 占住——字段级兜底不再触发，PyTorch/Transformer/Python
    全丢。修复后 BERT 技能片段直接按词典拆分入库，粘连串消失、幸存值去重保留"""
    from app.svc import ner

    def fake_pipe(chunk):
        out = []
        for line in chunk.splitlines():
            if "职业技能" in line:
                out.append({"entity_group": "skill", "word": "C++"})                    # 单技能，幸存
                out.append({"entity_group": "skill", "word": "PyTorch Transformers Python"})  # 粘连长串
        return out

    monkeypatch.setattr(ner, "_get_bert_pipeline", lambda: fake_pipe)
    text = "职业技能：熟练使用 PyTorch Transformers Python C++，熟悉向量检索与模型部署\n"
    ents = ner.extract_entities_bert(text)
    skills = {e["field_value"] for e in ents if e["field_key"] == "skill"}
    assert skills == {"c++", "pytorch", "transformer", "python"}
    assert all(e["field_value"] != "pytorchtransformerspython" for e in ents)


def test_bert_unmatchable_skill_span_dropped(monkeypatch):
    """T51：词典查不到的粘连碎片依旧丢弃（宁缺勿错），且不产出词典外的技能值"""
    from app.svc import ner

    def fake_pipe(chunk):
        return [{"entity_group": "skill", "word": "tradosmemoqxbench"}]

    monkeypatch.setattr(ner, "_get_bert_pipeline", lambda: fake_pipe)
    ents = ner.extract_entities_bert("职业技能：tradosmemoqxbench\n")
    assert all(e["field_key"] != "skill" for e in ents)


def test_merge_rule_fallback_skill_value_union():
    """回归（T51）：skill 兜底从字段级升级为值级并集——BERT 只抽出部分技能时
    （字段已被占住），全文词典匹配命中的其余技能仍要补上，口径与词典契约一致"""
    from app.svc.ner import _merge_rule_fallback
    ents = [{"field_key": "skill", "field_value": "c++", "source": "bert"}]
    merged = _merge_rule_fallback(ents, "职业技能：熟练使用 PyTorch 与 MySQL\n")
    skills = {e["field_value"] for e in merged if e["field_key"] == "skill"}
    assert skills == {"c++", "pytorch", "mysql"}


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
    # T36 行业词典扩容后，文本里的「剪映」会被规则层合法补成 skill(source=rule)——
    # 碎片/粘连过滤管的是 BERT 侧；断言收窄为：不存在 company/title，name 正确。
    assert all(e["field_key"] in ("name", "skill") for e in ents)
    assert all(e["field_value"] in ("张伟", "剪映") for e in ents)


def test_school_not_from_contest_lines():
    """回归（T30）："大学生"的"生"须被排除，竞赛/活动行不得产出虚假学校名"""
    ents = extract_entities("获奖情况：2018 年安徽省大学生程序设计竞赛银奖")
    schools = {e["field_value"] for e in ents if e["field_key"] == "school"}
    assert schools == set()
    ents2 = extract_entities("2023 年获全国大学生数学建模竞赛一等奖")
    assert all(e["field_key"] != "school" for e in ents2)


def test_title_normalization_strips_spaces_and_blocks_non_titles():
    """回归（T30.2）：title 去 BERT 插入空格还原原文写法；政治面貌/语言等级不是职位"""
    from app.svc.ner_rules import normalize_value as nv

    assert nv("title", "C + + 开发工程师") == "C++开发工程师"
    assert nv("title", "后 端 开 发 工 程 师") == "后端开发工程师"
    assert nv("title", "共青团员") is None
    assert nv("title", "中共党员") is None
    assert nv("title", "英语六级") is None
    assert nv("title", "语四级") is None       # 四/六级尾缀一律拦截
    assert nv("title", "后端开发工程师") == "后端开发工程师"  # 正常职位不受影响


def test_title_company_school_fragments_dropped():
    """回归（T30.2）：同字段子串碎片与单字残渣整条丢弃；skill 不参与（sql/mysql 是不同技能）"""
    from app.svc.ner import _drop_fragments

    ents = [
        {"field_key": "title", "field_value": "开发工程师", "source": "bert"},
        {"field_key": "title", "field_value": "程师", "source": "bert"},      # 子串残渣 → 丢
        {"field_key": "title", "field_value": "专", "source": "bert"},        # 单字 → 丢
        {"field_key": "title", "field_value": "产品经理", "source": "bert"},  # 无包含关系 → 留
        {"field_key": "company", "field_value": "阿里云ACP", "source": "bert"},
        {"field_key": "company", "field_value": "里云", "source": "bert"},    # 子串残渣 → 丢
        {"field_key": "company", "field_value": "天津", "source": "bert"},    # 两字截断残渣（T45）→ 丢
        {"field_key": "skill", "field_value": "mysql", "source": "rule"},
        {"field_key": "skill", "field_value": "sql", "source": "rule"},       # 技能互不吞 → 都留
    ]
    out = _drop_fragments(ents)
    titles = [e["field_value"] for e in out if e["field_key"] == "title"]
    comps = [e["field_value"] for e in out if e["field_key"] == "company"]
    skills = {e["field_value"] for e in out if e["field_key"] == "skill"}
    assert titles == ["开发工程师", "产品经理"]
    assert comps == ["阿里云ACP"]
    assert skills == {"mysql", "sql"}


def test_name_fixed_from_filename_prefix():
    """回归（T45，批量重解析实测 113 份）：文件名前缀兜底姓名——漏抽补上、
    截断纠正（乔鹏→乔鹏飞），完全对不上与通用词文件名不动"""
    from app.svc.pipeline import _fix_name_from_filename as fix

    assert fix([], "乔鹏飞_翻译.docx") == [
        {"field_key": "name", "field_value": "乔鹏飞", "source": "rule"}]
    ents = [{"field_key": "name", "field_value": "静姝", "source": "bert"}]
    fixed = fix(ents, "杨静姝_翻译.docx")
    assert fixed[0]["field_value"] == "杨静姝" and fixed[0]["source"] == "rule"
    ents2 = [{"field_key": "name", "field_value": "李雷", "source": "bert"}]
    assert fix(ents2, "韩梅梅_翻译.docx")[0]["field_value"] == "李雷"   # 完全不同 → 不动
    assert fix([], "简历_终稿.docx") == []                              # 通用词文件名 → 不动


def test_bert_garbage_skills_and_company_fragments_filtered(monkeypatch):
    """回归（T45，乔鹏飞_翻译 实况）：BERT 粘连技能与两字公司残渣被护栏拦下，
    丢空字段由规则词典兜底补齐——护栏先过、兜底后补，顺序不能反"""
    from app.svc import ner

    def fake_pipe(chunk):
        out = []
        for line in chunk.splitlines():
            if "职业技能" in line:
                out.append({"entity_group": "skill", "word": "Trados memoQ Xbench"})  # 粘连长串
            if "语言服务" in line:
                out.append({"entity_group": "company", "word": "深圳恒信语言服务有限公司"})
            if "理工" in line:
                out.append({"entity_group": "company", "word": "天津"})   # 校名截断成公司
                out.append({"entity_group": "school", "word": "理"})      # 单字校名残渣
        return out

    monkeypatch.setattr(ner, "_get_bert_pipeline", lambda: fake_pipe)
    text = ("姓名：乔鹏飞\n职业技能：Trados memoQ Xbench（术语检查）\n"
            "天津理工大学\n深圳恒信语言服务有限公司 翻译\n")
    ents = ner.extract_entities_bert(text)
    vals = {(e["field_key"], e["field_value"]) for e in ents}

    assert ("company", "天津") not in vals and ("school", "理") not in vals
    assert ("company", "深圳恒信语言服务有限公司") in vals
    assert ("school", "天津理工大学") in vals                      # 规则兜底补回
    skills = {v for k, v in vals if k == "skill"}
    assert skills == {"trados", "memoq", "xbench"}                 # 词典兜底，粘连串消失


def test_bert_title_not_from_project_sections(monkeypatch):
    """回归（T30.3）：项目栏目/项目头行里的 title 标注丢弃（项目名≠求职岗位），工作栏目保留"""
    from app.svc import ner

    def fake_pipe(chunk):
        out = []
        for line in chunk.splitlines():
            if "日程管家" in line:
                out.append({"entity_group": "title", "word": "智能日程规划"})
            if "担任" in line and "后端" in line:
                out.append({"entity_group": "title", "word": "后端开发工程师"})
        return out

    monkeypatch.setattr(ner, "_get_bert_pipeline", lambda: fake_pipe)

    # 乱序 PDF（#160 实况）："项目经历"标题与内容被拆开，标题行靠行形规则识别
    text = "项目经历\n职业技能\n教育背景\nAI 日程管家 — 智能日程规划 Agent | 项目负责人 2026.04-至今\n"
    ents = ner.extract_entities_bert(text)
    assert all(e["field_value"] != "智能日程规划" for e in ents)

    # 正常顺序：工作经历栏目下的真职位不受影响
    text2 = "工作经历\n2023-2024 某公司 担任后端开发工程师\n"
    ents2 = ner.extract_entities_bert(text2)
    assert any(e["field_value"] == "后端开发工程师" for e in ents2)


def test_title_from_intent_line_without_known_suffix():
    """回归（T30.3）：求职意向/应聘岗位是显式字段行，无已知后缀也能抽出岗位（ai 应用实习岗）"""
    ents = extract_entities("求职意向： ai 应用实习岗\n姓名：陈泽天")
    titles = [e["field_value"] for e in ents if e["field_key"] == "title"]
    assert titles == ["ai应用实习岗"]  # normalize 去 CJK-latin 交界空格


def test_school_not_as_company():
    """回归（T30.3）：校名结尾的值不再出现在公司字段（佛山大学曾被 BERT 标成 company）"""
    from app.svc.ner_rules import normalize_value as nv

    assert nv("company", "佛山大学") is None
    assert nv("company", "北京理工大学") is None
    assert nv("company", "字节跳动科技有限公司") == "字节跳动科技有限公司"
    assert nv("company", "成都澄海数据服务有限公司") == "成都澄海数据服务有限公司"


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
