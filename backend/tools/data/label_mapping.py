"""数据集标签 → 本项目 7 字段映射（算法设计 §2.1：字典显式维护，映射不到的丢弃并计数）。

数据集：ttxy/resume_ner（HF，源自 github.com/luopeixiang/named_entity_recognition，
BSD-2 协议；3821 训练 / 463 验证 / 477 测试句；字符级 BIOES 标注）。

数据集 8 类标签 → 7 字段：
    NAME  → name     姓名
    EDU   → degree   学历（"本科学历"等；院校在 ORG 里）
    TITLE → title    职位
    ORG   → company  单位（⚠ 学校在公司/单位同标签无法区分，默认归 company；
                        school 字段模型不覆盖，运行时由规则版兜底——ner.py 字段级合并）
    CONT/RACE/PRO/LOC → 丢弃（国籍/民族/专业/籍贯，不在 7 字段体系）
    ⚠ 数据集没有 skill/years/school 标签：技能走词典规则、年限走正则（运行时合并），
      这是数据集的客观限制，不阻塞主线（训练指标只对模型覆盖字段有意义）。
"""
from typing import Optional

# 大写数据集标签 → 7 字段或 None（丢弃）
LABEL_MAP: dict[str, Optional[str]] = {
    "NAME": "name",
    "EDU": "degree",
    "TITLE": "title",
    "ORG": "company",
    "CONT": None,
    "RACE": None,
    "PRO": None,
    "LOC": None,
}


def bioes_to_bio(tag: str) -> str:
    """BIOES → BIO：S-X→B-X，E-X→I-X，B-/I- 原样，O 原样"""
    if tag == "O" or not tag:
        return "O"
    prefix, _, label = tag.partition("-")
    if prefix == "S":
        return f"B-{label}"
    if prefix == "E":
        return f"I-{label}"
    return tag  # B-/I- 原样


def map_tag(tag: str) -> Optional[str]:
    """BIOES 标签 → 本项目 BIO 标签（字段名小写）；映射不到返回 None（调用方计丢弃）

    S-X→B-X、E-X→I-X（BIOES→BIO 归约），保证训练语料统一为 15 标签 BIO。
    """
    if tag == "O" or not tag:
        return "O"
    prefix, _, label = tag.partition("-")
    field = LABEL_MAP.get(label.upper())
    if field is None:
        return None
    bio_prefix = "B" if prefix in ("B", "S") else "I"
    return f"{bio_prefix}-{field}"


def drop_stats(tags: list[str]) -> dict[str, int]:
    """统计因映射不到而被丢弃的非 O 标签（按原标签计数）"""
    stats: dict[str, int] = {}
    for tag in tags:
        if tag and tag != "O" and map_tag(tag) is None:
            stats[tag] = stats.get(tag, 0) + 1
    return stats
