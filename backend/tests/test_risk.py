"""T55 风控体检测试（API-22 / svc/risk）：四类检测单测 + API 契约测试。

纪律对齐：信息不足不出行——凑不齐证据的检查项在 findings 里缺席，不硬造提示行。
共享测试库注：克隆检测断言用「同文本孪生」对（余弦恒 1.0，理论最大值）保证确定性，
不依赖库中其他测试数据；其余检测只断言本输入可控的 finding，不做全量 findings 相等断言。
"""
import sqlite3

from fastapi.testclient import TestClient

from app.core.errors import ErrorCode
from app.db import db_file, get_db
from app.main import app
from app.svc.risk import (
    _phone_findings,
    _skill_gap_findings,
    _timeline_findings,
    risk_check,
)

client = TestClient(app, raise_server_exceptions=False)


def _seed(text: str, skills: list[str] | None = None, name: str | None = None,
          parse_status: str = "done", source: str = "business") -> int:
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO resumes(file_name, file_type, parse_status, raw_text, source) "
            "VALUES('risk测试.docx','docx',?,?,?)",
            (parse_status, text, source),
        )
        rid = cur.lastrowid
        if name:
            conn.execute(
                "INSERT INTO entities(resume_id, field_key, field_value, source) "
                "VALUES(?,'name',?,'rule')", (rid, name),
            )
        for s in skills or []:
            conn.execute(
                "INSERT INTO entities(resume_id, field_key, field_value, source) "
                "VALUES(?,'skill',?,'rule')", (rid, s),
            )
        conn.commit()
    finally:
        conn.close()
    return rid


# ---------- 时间线（svc 单测） ----------

def test_timeline_overlap():
    text = "工作经历：\n2023.01-2024.05 负责后端开发工作\n2023.06-至今 主导平台重构开发"
    f = _timeline_findings(text)
    assert f and f[0]["level"] == "risk"
    assert "重叠" in f[0]["evidence"]


def test_timeline_inversion():
    f = _timeline_findings("2024.05-2023.01 负责项目维护与开发工作")
    assert f and f[0]["level"] == "risk"
    assert "结束早于开始" in f[0]["evidence"]


def test_timeline_insufficient_no_finding():
    # 信息不足不出行：单段（无重叠可判）与零段都缺席；同段重复出现只算一段
    assert _timeline_findings("2023.01-2024.05 负责后端开发工作") == []
    assert _timeline_findings("没有任何日期信息的简历正文") == []
    assert _timeline_findings(
        "2023.01-2024.05 负责后端开发工作\n2023.01-2024.05 负责后端开发工作（重复抄写）"
    ) == []


def test_timeline_split_formats():
    # 分隔符变体（/ 与 至 至今）同样可解析
    f = _timeline_findings("2022/03-2023/02 参与数据平台建设\n2023/01-至今 主导组内技术工作")
    assert f and f[0]["level"] == "risk"


# ---------- 技能脱节（svc 单测） ----------

def test_skill_gap_warns_missing_support():
    text = "技能：Python Docker\n\n1、负责后端开发使用Python完成接口开发工作"
    f = _skill_gap_findings(text, ["python", "docker"])
    assert [x["text"] for x in f] == ["技能 docker 无经历描述支撑"]
    assert all(x["level"] == "warn" for x in f)


def test_skill_gap_insufficient_no_finding():
    # 无经历行可比对 / 无技能实体 → 缺席
    assert _skill_gap_findings("只有技能清单没有经历正文", ["python"]) == []
    assert _skill_gap_findings("1、负责后端开发使用Python完成工作", []) == []


# ---------- 联系方式格式（svc 单测） ----------

def test_phone_format_anomaly():
    f = _phone_findings("联系电话13812345678，备用12345678901")
    assert len(f) == 1 and f[0]["level"] == "warn"
    assert "12345678901" in f[0]["text"]


def test_phone_valid_no_finding():
    # 合法手机号不提示；18 位身份证里的数字串不误报
    assert _phone_findings("电话13812345678，身份证110101199001011234") == []


# ---------- 主入口（svc 集成，含克隆检测真算） ----------

def test_risk_check_clean_shape():
    rid = _seed("姓名：风测甲\n2020.09-2024.06 就读某大学计算机专业方向", name="风测甲")
    out = risk_check(rid)
    assert out["resume_id"] == rid and out["checked_at"]
    # 本输入可控的三类检测都必须缺席（克隆项取决于全库，不在断言范围）
    for f in out["findings"]:
        if f["level"] != "ok":
            assert "时间线" not in f["text"]
            assert "无经历描述支撑" not in f["text"]
            assert "格式异常" not in f["text"]
    if out["findings"][0]["level"] == "ok":
        assert len(out["findings"]) == 1
        assert out["summary"] == "未发现明显矛盾点"


def test_risk_check_timeline_risk_and_summary():
    rid = _seed(
        "2023.01-2024.05 负责后端开发工作\n2023.06-至今 主导平台重构开发", name="风测乙"
    )
    out = risk_check(rid)
    tl = [f for f in out["findings"] if "时间线" in f["text"]]
    assert tl and tl[0]["level"] == "risk" and "重叠" in tl[0]["evidence"]
    assert "风险信号" in out["summary"] and "人工复核" in out["summary"]


def test_risk_check_clone_twins():
    twin = "姓名：占位\n1、负责风控策略模块开发与维护工作，精通Scala与Kafka消息队列"
    rid_a = _seed(twin, name="克隆甲")
    rid_b = _seed(twin, name="克隆乙")
    # 克隆检测只读缓存（视图端点不内联重建），测试先显式建库
    from app.svc.vectors import ensure_cache

    ensure_cache()
    out = risk_check(rid_a)
    cl = [f for f in out["findings"] if "疑似重复投递" in f["text"]]
    assert cl and cl[0]["level"] == "warn"
    assert "克隆乙" in cl[0]["text"]
    assert f"resume_id={rid_b}" in cl[0]["evidence"]


def test_risk_check_clone_skips_when_cache_stale():
    # 契约口径：缓存不可得 → 克隆项整项缺席，且不触发重建（秒级返回）
    rid = _seed("1、负责缓存陈旧场景验证的开发与测试工作", name="陈旧验证")
    out = risk_check(rid)  # 刚插入未建库，load_cache 必然失效
    assert all("疑似重复投递" not in f["text"] for f in out["findings"])


def test_risk_check_clone_pool_business_only():
    # 比对池只收业务投递（source='business'）：评测语料的模板孪生不构成「重复投递」
    twin = "姓名：占位\n1、负责语料池隔离验证的开发与维护工作，精通Rust与Wasm运行时"
    _seed(twin, name="语料甲", source="rewrite")
    rid_biz = _seed(twin, name="语料乙")  # business，与语料甲文本全同（余弦 1.0）
    from app.svc.vectors import ensure_cache

    ensure_cache()
    out = risk_check(rid_biz)
    assert all("疑似重复投递" not in f["text"] for f in out["findings"])


# ---------- API 契约 ----------

def test_risk_api_contract_and_audit():
    rid = _seed(
        "2023.01-2024.05 负责后端开发工作\n2023.06-至今 主导平台重构开发", name="风测丙"
    )
    r = client.get(f"/api/resumes/{rid}/risk")
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["resume_id"] == rid
    assert isinstance(d["findings"], list) and d["findings"]
    for f in d["findings"]:
        assert f["level"] in {"ok", "warn", "risk"}
        assert isinstance(f["text"], str) and f["text"]
    assert d["summary"] and d["checked_at"]
    # 查看风控必记审计（T54 审计清单里的 view_risk）
    conn = sqlite3.connect(db_file())
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM audit_log WHERE action='view_risk' AND target=?",
            (f"resume_id={rid}",),
        ).fetchone()[0]
    finally:
        conn.close()
    assert n >= 1


def test_risk_api_404_unknown_id():
    r = client.get("/api/resumes/9999999/risk")
    assert r.status_code == 404
    assert r.json()["code"] == ErrorCode.NOT_FOUND


def test_risk_api_400_not_done():
    rid = _seed("任意正文", parse_status="pending")
    r = client.get(f"/api/resumes/{rid}/risk")
    assert r.status_code == 400
    assert r.json()["code"] == ErrorCode.BAD_PARAM
