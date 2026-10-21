"""T45 增训语料收集工具的锚定/错例判别单测（离线工具，不碰业务库）。"""
from tools.collect_ner_hardcases import anchor_line, find_span, is_hard_fp, make_record


def test_is_hard_fp_matches_online_complaints():
    # 公司单字残渣（公司：校）与泛词
    assert is_hard_fp("company", "校") and is_hard_fp("company", "协会") and is_hard_fp("company", "zh")
    assert not is_hard_fp("company", "深圳恒信语言服务有限公司")  # 带后缀的正常公司不进负例
    # 证书当职位（二级笔译）
    assert is_hard_fp("title", "二级笔译") and is_hard_fp("title", "委") and is_hard_fp("title", "英语四级")
    assert not is_hard_fp("title", "翻译") and not is_hard_fp("title", "后端开发工程师")
    # 词典外常识词当技能（公式）
    assert is_hard_fp("skill", "公式")
    assert not is_hard_fp("skill", "trados") and not is_hard_fp("skill", "术语库")  # 长词/ascii 不误杀


def test_find_span_maps_collapsed_spaces_back():
    line = "担任 后 端开发工程师"  # BERT 字符聚合会在字间插空格
    assert find_span(line, "后端开发工程师") == (3, 11)
    assert find_span("技能：Python/Flask", "Python") == (3, 9)
    assert find_span("无关行", "校") is None


def test_anchor_line_tags_runtime_consistent_spans():
    a = anchor_line("姓名：张三")
    assert ("name", 3, 5) in a
    b = anchor_line("求职意向：后端开发工程师")
    assert ("title", 5, 12) in b
    c = anchor_line("技能：Python 与 MySQL")
    assert ("skill", 3, 9) in c and ("skill", 12, 17) in c
    d = anchor_line("2020.07-至今 深圳恒信语言服务有限公司 翻译")
    assert {f for f, _, _ in d} == {"company"}  # 裸"翻译"无锚点词不锚——远程监督只用高置信信号
    e = anchor_line("职位：Java开发工程师")
    assert ("title", 3, 12) in e


def test_make_record_emits_bio():
    line = "技能：Python"
    rec = make_record(line, anchor_line(line))
    assert rec["chars"] == list(line)
    assert rec["tags"][3] == "B-skill" and all(t == "I-skill" for t in rec["tags"][4:9])
    assert rec["tags"][0] == "O" and len(rec["chars"]) == len(rec["tags"])
