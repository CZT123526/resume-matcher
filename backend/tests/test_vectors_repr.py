"""结构化文本增强（T36 B3）单测：实体清单 + 经历要点 v2 表示。"""
from app.svc.vectors import REPR_VERSION, _work_lines, structured_text


def _resume(raw: str, entities: list[tuple[str, str]] | None = None) -> dict:
    return {"raw_text": raw, "entities": entities or []}


def test_work_lines_picks_bullets_and_verb_lines():
    raw = "姓名：王晓\n工作经历\n2020-2023 某公司\n1、负责交易服务开发，QPS 提升 3 倍\n主导缓存改造，P99 下降 60%\n电话：13800000000\n今天天气不错"
    got = _work_lines(raw)
    assert any("负责交易服务开发" in s for s in got)
    assert any("缓存改造" in s for s in got)
    assert all("13800000000" not in s for s in got)     # 字段行不收
    assert all("天气" not in s for s in got)            # 无动词的闲句不收


def test_work_lines_budget_truncates():
    raw = "".join(f"{i}、负责第{i}号产线的日常维护与巡检安排，保障连续稳定运行若干个日夜\n" for i in range(1, 30))
    got = _work_lines(raw)
    assert sum(len(s) for s in got) < 500               # 预算 400 + 一条余量
    assert len(got) < 30


def test_structured_text_appends_experience():
    ents = [("title", "视频剪辑师"), ("skill", "premiere")]
    raw = "求职意向：视频剪辑师\n工作经历\n1、负责短视频成片剪辑与包装，月产 30 条\n"
    text = structured_text(_resume(raw, ents))
    assert text.startswith("技能：premiere 职位：视频剪辑师")
    assert "经历：" in text and "短视频成片剪辑" in text


def test_structured_text_without_bullets_unchanged():
    ents = [("title", "会计"), ("degree", "本科")]
    text = structured_text(_resume("无要点的正文内容", ents))
    assert text == "职位：会计 学历：本科"
    assert "经历" not in text


def test_structured_text_fallback_intact():
    """实体缺失退回原文前缀（v1 行为保持，B3 不影响兜底）"""
    raw = "全文兜底" * 300
    assert structured_text(_resume(raw, [])) == raw[:1000]
    assert "经历：" not in structured_text(_resume(raw, []))


def test_repr_version_in_fingerprint():
    """表示版本必须进缓存指纹：格式改了而 raw_text 没变时仍能触发重建"""
    from app.svc import vectors

    fp = vectors._encoder_fingerprint()
    assert fp.endswith(f":{REPR_VERSION}")
    assert REPR_VERSION == "v2"
