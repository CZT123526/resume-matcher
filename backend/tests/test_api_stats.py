"""主页统计接口测试（API-19，T48）。

用例自足：简历走真实上传链路（匹配池条件为 parse_status='done' 且 raw_text 非空，
直接 INSERT 空壳行进不了池）；JD 用接口创建。既有用例可能已写入同类数据，
计数断言一律 >=，排名断言用本用例独有的标志性数据验证口径与排序。
"""
from io import BytesIO

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)

# 标志性岗位名：正常业务不会出现，避免与既有测试数据撞名
T_A = "统计员甲专属岗位"
T_B = "统计员乙专属岗位"


def _make_docx(text: str) -> bytes:
    import docx

    buf = BytesIO()
    d = docx.Document()
    for line in text.splitlines():
        d.add_paragraph(line)
    d.save(buf)
    return buf.getvalue()


def _upload(name: str, text: str) -> int:
    r = client.post(
        "/api/resumes/upload",
        files={"file": (name, _make_docx(text), "application/octet-stream")},
    )
    return r.json()["data"]["resume_id"]


def test_home_stats_counts_and_title_rank():
    """总量计数守恒 + 应聘岗位排名按简历数降序"""
    ids = [
        _upload("统计甲一.docx", "姓名：贾一\n技能：Python 统计"),
        _upload("统计甲二.docx", "姓名：贾二\n技能：Python 统计"),
        _upload("统计乙一.docx", "姓名：贾三\n技能：Python 统计"),
    ]
    client.post("/api/jds", json={"title": "统计甲专属岗位JD", "content": "要求：统计。"})
    jid = client.post("/api/jds", json={"title": "统计乙专属岗位JD", "content": "要求：统计。"}).json()["data"]["jd_id"]
    # 跑一个真实匹配任务：上面 3 份已解析简历即匹配池，保证本用例自足
    tid = client.post("/api/match-tasks", json={"jd_id": jid, "top_k": 2}).json()["data"]["task_id"]
    assert client.get(f"/api/match-tasks/{tid}").json()["data"]["status"] == "done"

    # 岗位实体：甲岗位 2 份简历、乙岗位 1 份（直插实体，走解析链路抽不出专属岗位名）
    from app.db import get_db

    conn = get_db()
    try:
        for rid in ids[:2]:
            conn.execute(
                "INSERT INTO entities(resume_id, field_key, field_value, source) VALUES(?, 'title', ?, 'rule')",
                (rid, T_A),
            )
        conn.execute(
            "INSERT INTO entities(resume_id, field_key, field_value, source) VALUES(?, 'title', ?, 'rule')",
            (ids[2], T_B),
        )
        conn.commit()
    finally:
        conn.close()

    d = client.get("/api/stats/home").json()["data"]

    # 简历五类计数守恒（与列表页同一口径）
    c = d["resumes"]
    assert c["all"] >= 3
    assert c["all"] == c["business"] + c["rewrite"] + c["semispec"] + c["fresh"]
    assert c["parsed_done"] >= 3 and c["parsed_done"] <= c["all"]

    # 岗位库与匹配覆盖
    assert d["jd_count"] >= 2
    assert d["match_done"] >= 1 and d["jd_covered"] <= d["jd_count"]

    # 应聘岗位排名：甲岗位 2 份在前、乙岗位 1 份在后，降序且带 LIMIT
    tr = {x["title"]: x["n"] for x in d["title_rank"]}
    assert tr[T_A] >= 2 and tr[T_B] >= 1
    ns = [x["n"] for x in d["title_rank"]]
    assert ns == sorted(ns, reverse=True)
    assert len(d["title_rank"]) <= 10
    assert d["title_kinds"] >= 2 and d["title_resumes"] >= 3


def test_home_stats_jd_rank_latest_task_recall():
    """岗位储备排名：每岗位取最近一次 done 任务，召回数=当次 top_k 截断后的结果行数"""
    # 保证匹配池非空：本用例自己上传 3 份真解析简历
    for i in range(3):
        _upload(f"储备池简历{i}.docx", "姓名：储备员\n技能：Python FastAPI")

    jid_a = client.post("/api/jds", json={"title": "储备排名甲岗位", "content": "要求：Python。"}).json()["data"]["jd_id"]
    jid_b = client.post("/api/jds", json={"title": "储备排名乙岗位", "content": "要求：Python。"}).json()["data"]["jd_id"]
    ta = client.post("/api/match-tasks", json={"jd_id": jid_a, "top_k": 3}).json()["data"]["task_id"]
    tb = client.post("/api/match-tasks", json={"jd_id": jid_b, "top_k": 1}).json()["data"]["task_id"]
    assert client.get(f"/api/match-tasks/{ta}").json()["data"]["status"] == "done"
    assert client.get(f"/api/match-tasks/{tb}").json()["data"]["status"] == "done"

    d = client.get("/api/stats/home").json()["data"]
    jr = {x["jd_id"]: x for x in d["jd_rank"]}
    assert jr[jid_a]["recalled"] == 3
    assert jr[jid_b]["recalled"] == 1
    assert jr[jid_a]["task_count"] >= 1 and jr[jid_a]["title"] == "储备排名甲岗位"
    assert jr[jid_a]["last_run_at"] and "T" in jr[jid_a]["last_run_at"]
    ns = [x["recalled"] for x in d["jd_rank"]]
    assert ns == sorted(ns, reverse=True)
    assert len(d["jd_rank"]) <= 10
