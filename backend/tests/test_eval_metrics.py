"""M04 评测指标与 TF-IDF 基线单元测试（对拍算法设计 §6 公式）。"""
import pytest

from tools.baselines.tfidf_baseline import rank_for_jds
from tools.eval.build_gold import _core, _positive
from tools.eval.metrics import ndcg_at_k, precision_at_k


class TestGoldPositive:
    """金标准正样本判定：剥通用词后比核心语义，防'后端/前端'共享'开发'误判同岗"""

    def test_core_strips_generic(self):
        assert _core("后端开发工程师") == "后端"
        assert _core("前端开发工程师") == "前端"
        assert _core("数据分析师") == "数据"
        assert _core("平面设计师") == "平面"
        assert _core("Python后端工程师") == "python后端"  # 保留技能词，剥职位通用词

    def test_backend_not_frontend(self):
        assert not _positive("前端开发工程师", ["后端开发工程师"])
        assert not _positive("Python后端工程师", ["前端开发工程师"])

    def test_backend_matches(self):
        assert _positive("Python后端工程师", ["后端开发工程师"])
        assert _positive("Python后端工程师", ["Python后端开发"])

    def test_designer_vs_data(self):
        assert not _positive("数据分析师", ["平面设计师"])
        assert _positive("数据分析师", ["数据分析师", "数据分析专员"])

    def test_pure_generic_core_needs_specialization(self):
        # T33 v2.1：短核心纯通用时必须过细分白名单——同家族不同工种不再误配
        assert not _positive("大数据开发工程师", ["数据分析师"])      # 数据 ⊂ 大数据 ≠ 同岗
        assert not _positive("数据仓库工程师", ["数据分析师"])        # 数仓是工程岗
        assert not _positive("信息安全工程师（渗透测试方向）", ["测试开发工程师"])  # 安全≠测试
        assert not _positive("硬件测试工程师", ["测试开发工程师"])    # 硬件≠软件测试
        assert not _positive("开发工程师", ["开发"])                  # 全通用 title 无核心，不配

    def test_specialization_whitelist(self):
        # 白名单内的合法 specialization 保留
        assert _positive("大模型算法工程师", ["算法工程师"])          # 算法→大模型
        assert _positive("推荐算法工程师", ["算法工程师"])            # 算法→推荐
        assert _positive("前端开发工程师（React方向）", ["前端开发工程师"])  # 前端→react
        assert _positive("数据分析师", ["商业数据分析师"])            # 数据→商业
        assert not _positive("大数据开发工程师", ["算法工程师"])      # 白名单外修饰词判否


class TestNdcg:
    def test_perfect_order(self):
        assert ndcg_at_k([1, 1, 0], k=10) == pytest.approx(1.0)
        assert ndcg_at_k([1, 1, 0, 0, 0], k=3) == pytest.approx(1.0)

    def test_hand_computed(self):
        # DCG([1,0,1]) = 1 + 1/log2(4) = 1.5；IDCG = 1 + 1/log2(3) → 0.9197
        assert ndcg_at_k([1, 0, 1]) == pytest.approx(0.9197, abs=1e-4)
        # DCG([0,1,1]) = 1/log2(3) + 1/log2(4) → 0.6934
        assert ndcg_at_k([0, 1, 1]) == pytest.approx(0.6934, abs=1e-4)

    def test_k_truncates(self):
        # 前 2 位全对 → K=2 时满分，即使后面是 0
        assert ndcg_at_k([1, 1, 0], k=2) == pytest.approx(1.0)

    def test_no_positive_is_zero(self):
        assert ndcg_at_k([0, 0, 0]) == 0.0
        assert ndcg_at_k([]) == 0.0


class TestPrecision:
    def test_basic(self):
        assert precision_at_k([1, 0, 1, 1, 0], k=5) == pytest.approx(0.6)
        assert precision_at_k([0, 0, 1], k=3) == pytest.approx(1 / 3)

    def test_denominator_min_k_len(self):
        # 列表短于 K：分母取实际长度
        assert precision_at_k([1, 1], k=5) == pytest.approx(1.0)

    def test_empty(self):
        assert precision_at_k([], k=5) == 0.0


class TestTfidfBaseline:
    def test_skill_relevant_ranks_first(self):
        jd_texts = {1: "Python后端开发 FastAPI MySQL"}
        resume_texts = {
            10: "技能：Python/FastAPI/MySQL 职位：后端开发工程师 学历：本科 经验：3年",
            20: "技能：Photoshop 职位：平面设计师 学历：本科 经验：2年",
            30: "技能：Java/Spring 职位：Java开发工程师 学历：本科 经验：4年",
        }
        ranking = rank_for_jds(jd_texts, resume_texts)
        top = ranking[1][0]
        assert top[0] in {10, 30}  # 技能相关的两份排在设计师前
        assert ranking[1][0][0] != 20  # 设计师绝不排第一
        assert all(0.0 <= s <= 1.0 for _, s in ranking[1])

    def test_scores_sorted_desc(self):
        ranking = rank_for_jds({7: "数据分析 Python"}, {1: "技能：Python/数据分析", 2: "技能：Excel"})
        scores = [s for _, s in ranking[7]]
        assert scores == sorted(scores, reverse=True)
