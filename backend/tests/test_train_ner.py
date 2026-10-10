"""T18 训练物料单元测试：标签映射（BIOES→BIO+7字段）、BIO解码、实体级P/R/F1。"""
import pytest

from tools.data.label_mapping import bioes_to_bio, drop_stats, map_tag
from tools.train_ner import LABELS, decode_entities, entity_prf


class TestLabelMapping:
    def test_bioes_to_bio(self):
        assert bioes_to_bio("B-NAME") == "B-NAME"
        assert bioes_to_bio("S-ORG") == "B-ORG"
        assert bioes_to_bio("E-ORG") == "I-ORG"
        assert bioes_to_bio("I-TITLE") == "I-TITLE"
        assert bioes_to_bio("O") == "O"

    def test_map_tag_to_fields(self):
        assert map_tag("B-NAME") == "B-name"
        assert map_tag("S-NAME") == "B-name"
        assert map_tag("E-EDU") == "I-degree"
        assert map_tag("I-TITLE") == "I-title"
        assert map_tag("B-ORG") == "B-company"

    def test_map_tag_drops_unmapped(self):
        # 国籍/民族/专业/籍贯不在 7 字段体系
        for label in ("CONT", "RACE", "PRO", "LOC"):
            assert map_tag(f"B-{label}") is None
        assert map_tag("O") == "O"

    def test_no_bioes_leakage(self):
        """训练语料是 15 标签 BIO：任何映射输出不得带 S-/E- 前缀"""
        for tag in ("B-NAME", "S-NAME", "E-NAME", "I-NAME", "S-EDU", "E-TITLE", "S-ORG", "E-ORG"):
            mapped = map_tag(tag)
            assert mapped is None or mapped.split("-")[0] in {"B", "I"}

    def test_drop_stats_counts(self):
        stats = drop_stats(["B-PRO", "I-PRO", "B-NAME", "O", "B-PRO"])
        assert stats == {"B-PRO": 2, "I-PRO": 1}

    def test_label_set_is_15(self):
        assert len(LABELS) == 15
        assert len(set(LABELS)) == 15


class TestDecode:
    def test_decode_basic(self):
        chars = list("张三北京大学")
        tags = ["B-name", "I-name", "B-company", "I-company", "I-company", "I-company"]
        assert decode_entities(chars, tags) == [("name", "张三", 0), ("company", "北京大学", 2)]

    def test_decode_dangling_i(self):
        # 非法序列：I- 开头按宽容规则当新实体起点
        chars = list("张三")
        tags = ["I-name", "I-name"]
        assert decode_entities(chars, tags) == [("name", "张三", 0)]

    def test_decode_consecutive_entities(self):
        chars = list("硕士五年")
        tags = ["B-degree", "I-degree", "O", "O"]
        assert decode_entities(chars, tags) == [("degree", "硕士", 0)]


class TestPrf:
    def test_perfect(self):
        gold = [[("name", "张三", 0)], [("degree", "本科", 3)]]
        assert entity_prf(gold, gold)["f1"] == 1.0

    def test_partial(self):
        gold = [[("name", "张三", 0), ("degree", "本科", 5)]]
        pred = [[("name", "张三", 0), ("degree", "硕士", 5)]]  # degree 值不对 → FN+FP
        m = entity_prf(gold, pred)
        assert m["precision"] == 0.5 and m["recall"] == 0.5
        assert m["f1"] == pytest.approx(0.5)

    def test_position_matters(self):
        # §2.4 精确匹配：同值不同位置不算 TP
        gold = [[("name", "张三", 0)]]
        pred = [[("name", "张三", 7)]]
        m = entity_prf(gold, pred)
        assert m["f1"] == 0.0

    def test_empty(self):
        assert entity_prf([], [])["f1"] == 0.0
