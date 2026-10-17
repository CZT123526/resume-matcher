"""T34 关键词重排层单测：关键词抽取 / 词面命中率 / 融合 / hybrid_rank 重排效果。"""
import math

import numpy as np
import pytest

from app.svc.lexical import extract_jd_keywords, fuse, keyword_hit_score
from app.svc import vectors as vectors_mod
from app.svc.ranking import hybrid_rank


# ---------- extract_jd_keywords ----------

def test_keywords_from_title_strips_generic_suffix():
    """「信息安全工程师（渗透测试方向）」→ 内容词留下，通用后缀剔除"""
    kws = extract_jd_keywords("信息安全工程师（渗透测试方向）", None)
    assert "渗透测试" in kws
    assert "信息安全" in kws
    assert "工程师" not in kws and "方向" not in kws


def test_keywords_stack_prefix_kept_generic_dropped():
    """「Java后端开发工程师」→ 只留技术栈词 java，「后端开发」全通用不成关键词"""
    assert extract_jd_keywords("Java后端开发工程师", None) == ["java"]


def test_keywords_content_word_kept():
    """「大数据开发工程师」→ 含内容词的整段保留（完整词面证据更强）"""
    assert extract_jd_keywords("大数据开发工程师", None) == ["大数据开发"]


def test_keywords_merge_req_skills_dedupe_case():
    """req 技能词与标题词合并，大小写不敏感去重、保序"""
    kws = extract_jd_keywords("Java后端开发工程师", {"skills": ["Java", "spring", "redis"]})
    assert kws == ["java", "spring", "redis"]


# ---------- keyword_hit_score ----------

def test_hit_score_perfect_partial_none():
    kws = ["java", "redis"]
    assert keyword_hit_score(kws, "技能：java/redis/spring") == 1.0
    assert keyword_hit_score(kws, "技能：java/spring") == 0.5
    assert keyword_hit_score(kws, "技能：python/go") == 0.0


def test_hit_score_neutral_when_no_keywords():
    """无关键词 → 0.5 中性（无词面证据不奖不罚，融合保序）"""
    assert keyword_hit_score([], "任何文本") == 0.5


def test_present_boundary_java_not_javascript():
    """ASCII 词带边界：java 不命中 javascript"""
    kws = ["java"]
    assert keyword_hit_score(kws, "技能：javascript/vue") == 0.0
    assert keyword_hit_score(kws, "技能：java/vue") == 1.0


def test_present_boundary_dotnet_not_aspdotnet():
    """.net 不命中 asp.net（词面前有字母即拒绝）"""
    kws = [".net"]
    assert keyword_hit_score(kws, "技能：asp.net/c#") == 0.0
    assert keyword_hit_score(kws, "技能：.net/c#") == 1.0


def test_present_boundary_c_not_cpp():
    """c 不命中 c++（边界类含 + 号）"""
    kws = ["c"]
    assert keyword_hit_score(kws, "技能：c++/python") == 0.0
    assert keyword_hit_score(kws, "技能：c/python") == 1.0


# ---------- fuse ----------

def test_fuse_linear_and_degenerate_cases():
    assert fuse(0.8, 1.0, 0.7) == pytest.approx(0.86)
    assert fuse(0.8, 1.0, 1.0) == 0.8        # α=1 退化纯语义
    assert fuse(0.8, 1.0, 0.0) == 1.0        # α=0 退化纯词面


# ---------- hybrid_rank ----------

def _fake_cache(monkeypatch):
    """三份简历的语义分固定为 1.0 / 0.85 / 0.5（构造归一化向量精确控制余弦）。"""
    order = [101, 102, 103]
    r2 = math.sqrt(1 - 0.7 ** 2)
    matrix = np.array([
        [1.0, 0.0, 0.0],           # cos=1.0 → bert=1.0
        [0.7, r2, 0.0],            # cos=0.7 → bert=0.85
        [0.0, 0.0, 1.0],           # cos=0.0 → bert=0.5
    ], dtype=float)
    jd_vector = np.array([1.0, 0.0, 0.0])
    monkeypatch.setattr(vectors_mod, "load_cache", lambda: (matrix, order))
    return jd_vector


def test_hybrid_rank_reranks_by_lexical(monkeypatch):
    """词面证据能压过语义分：高语义零词面 vs 中语义高词面，α=0.5 时后者登顶"""
    jd_vector = _fake_cache(monkeypatch)
    lex = {101: 0.0, 102: 0.9, 103: 0.9}
    ranked = hybrid_rank(jd_vector, lex, top_k=3, alpha=0.5)
    finals = {r["resume_id"]: r["score"] for r in ranked}
    # 融合分：101=0.50、102=0.875、103=0.70 → 词面证据把 102 从第二顶到第一
    assert ranked[0]["resume_id"] == 102
    assert finals[102] > finals[103] > finals[101]


def test_hybrid_rank_alpha_one_degenerates_to_semantic(monkeypatch):
    """α=1.0 退化为纯语义排序，与余弦分一致"""
    jd_vector = _fake_cache(monkeypatch)
    lex = {101: 0.0, 102: 0.9, 103: 0.9}
    ranked = hybrid_rank(jd_vector, lex, top_k=3, alpha=1.0)
    assert [r["resume_id"] for r in ranked] == [101, 102, 103]
    assert ranked[0]["score"] == 1.0 and ranked[1]["score"] == 0.85


def test_hybrid_rank_missing_lex_is_neutral(monkeypatch):
    """lex_scores 缺失的简历按中性 0.5 计，不炸不偏"""
    jd_vector = _fake_cache(monkeypatch)
    ranked = hybrid_rank(jd_vector, {}, top_k=3, alpha=0.5)
    finals = {r["resume_id"]: r["score"] for r in ranked}
    # 全 0.5 词面 → 融合分 = 0.5·bert + 0.25，保序
    assert finals[101] > finals[102] > finals[103]
