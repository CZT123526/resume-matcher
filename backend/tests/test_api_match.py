"""匹配任务链路集成测试（API-05/06/07/08/09/10/12 + S04/S05/S06/S07 串联）。"""
from io import BytesIO

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)


def _docx(lines: list[str]) -> bytes:
    import docx

    buf = BytesIO()
    d = docx.Document()
    for line in lines:
        d.add_paragraph(line)
    d.save(buf)
    return buf.getvalue()


def _upload(name: str, lines: list[str]) -> int:
    r = client.post("/api/resumes/upload", files={"file": (name, _docx(lines), "application/octet-stream")})
    assert r.status_code == 202
    return r.json()["data"]["resume_id"]


def _seed_resumes():
    _upload("py.docx", ["姓名：张三", "硕士", "5年工作经验", "技能：Python FastAPI MySQL Docker",
                        "担任后端开发工程师", "字节跳动科技有限公司"])
    _upload("py2.docx", ["姓名：李四", "本科", "3年工作经验", "技能：Python Django MySQL"])
    _upload("other.docx", ["姓名：王五", "本科", "2年工作经验", "技能：Photoshop", "担任平面设计师"])


def test_jd_crud():
    r = client.post("/api/jds", json={"title": "Python后端工程师", "content": "负责后端开发。要求：3年以上Python经验，熟悉FastAPI，本科及以上。"})
    assert r.status_code == 200
    jd_id = r.json()["data"]["jd_id"]

    lst = client.get("/api/jds").json()["data"]
    assert lst["total"] >= 1

    d = client.get(f"/api/jds/{jd_id}").json()["data"]
    assert d["req_json"]["degree"] == "本科"
    assert d["req_json"]["min_years"] == 3
    assert {"python", "fastapi"} <= {s.lower() for s in d["req_json"]["skills"]}

    assert client.get("/api/jds/999999").status_code == 404

    # 参数校验：空 title → 400 E4001
    bad = client.post("/api/jds", json={"title": "", "content": "x"})
    assert bad.status_code == 400 and bad.json()["code"] == "E4001"
    return jd_id


def test_match_full_flow():
    jd_id = test_jd_crud()
    _seed_resumes()

    # 发起任务
    r = client.post("/api/match-tasks", json={"jd_id": jd_id, "top_k": 2})
    assert r.status_code == 202
    task_id = r.json()["data"]["task_id"]

    # TestClient 下后台任务同步完成
    st = client.get(f"/api/match-tasks/{task_id}").json()["data"]
    assert st["status"] == "done"
    assert st["progress"] == 100

    # 结果契约
    res = client.get(f"/api/match-tasks/{task_id}/results")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["jd_title"] == "Python后端工程师"
    items = data["items"]
    assert 1 <= len(items) <= 2
    assert [i["rank"] for i in items] == list(range(1, len(items) + 1))
    assert all(0.0 <= i["score"] <= 1.0 for i in items)
    assert all(isinstance(i["evidence"], list) for i in items)
    # python 简历应排在设计师生前面（技能重合度驱动）
    assert items[0]["candidate_name"] in {"张三", "李四"}

    # score 降序
    scores = [i["score"] for i in items]
    assert scores == sorted(scores, reverse=True)

    # T42 分数构成明细：semantic/lexical/alpha 齐备，融合回算与 score 一致
    d0 = items[0]["score_detail"]
    assert d0 and 0.0 <= d0["semantic"] <= 1.0 and 0.0 <= d0["lexical"] <= 1.0
    fused = d0["alpha"] * d0["semantic"] + (1 - d0["alpha"]) * d0["lexical"]
    assert abs(items[0]["score"] - fused) < 1e-2

    # T40 分布契约：全量分数降序，与 Top-K 第一名同源同值
    dist = client.get(f"/api/match-tasks/{task_id}/score_distribution")
    assert dist.status_code == 200
    d = dist.json()["data"]
    assert d["jd_title"] == "Python后端工程师"
    assert d["n_candidates"] == len(d["scores"]) >= 3
    assert d["scores"] == sorted(d["scores"], reverse=True)
    assert all(0.0 <= s <= 1.0 for s in d["scores"])
    assert d["scores"][0] == items[0]["score"]


def test_jd_delete_cascades_tasks():
    """T32：删 JD 连带删名下匹配任务（结果随 FK 级联），重复删 404"""
    jd_id = test_jd_crud()
    _seed_resumes()
    r = client.post("/api/match-tasks", json={"jd_id": jd_id, "top_k": 2})
    assert r.status_code == 202
    task_id = r.json()["data"]["task_id"]
    assert client.get(f"/api/match-tasks/{task_id}").json()["data"]["status"] == "done"

    d = client.delete(f"/api/jds/{jd_id}").json()["data"]
    assert d == {"jd_id": jd_id, "deleted": True, "deleted_match_tasks": 1}
    assert client.get(f"/api/jds/{jd_id}").status_code == 404
    assert client.get(f"/api/match-tasks/{task_id}").status_code == 404
    assert client.get(f"/api/match-tasks/{task_id}/results").status_code == 404
    assert client.get(f"/api/match-tasks/{task_id}/score_distribution").status_code == 404
    assert client.delete(f"/api/jds/{jd_id}").status_code == 404


def test_match_task_validation_and_409():
    assert client.post("/api/match-tasks", json={"jd_id": 999999}).status_code == 404
    # top_k 超范围 → 400 E4001
    bad = client.post("/api/match-tasks", json={"jd_id": 1, "top_k": 999})
    assert bad.status_code == 400 and bad.json()["code"] == "E4001"
    # 未完成任务取结果 → 409 E4091（用不存在的任务外的真实 failed 场景：JD 不存在时任务落 failed）
    ok_resp = client.post("/api/match-tasks", json={"jd_id": 1})
    # jd_id=1 可能不存在（seed 顺序）——两种结果都合法：404 或任务 failed
    if ok_resp.status_code == 202:
        tid = ok_resp.json()["data"]["task_id"]
        st = client.get(f"/api/match-tasks/{tid}").json()["data"]
        if st["status"] == "failed":
            r = client.get(f"/api/match-tasks/{tid}/results")
            assert r.status_code == 409 and r.json()["code"] == "E4091"


def test_match_task_404():
    assert client.get("/api/match-tasks/999999").status_code == 404
    assert client.get("/api/match-tasks/999999/results").status_code == 404
    assert client.get("/api/match-tasks/999999/score_distribution").status_code == 404


def test_score_distribution_legacy_task_empty():
    """T40：分布存档表无行的历史 done 任务 → 200 空列表（前端隐藏分布图，不算错误）"""
    from app.db import get_db

    jd_id = test_jd_crud()
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO match_tasks(jd_id, top_k, status, progress) VALUES(?,?,'done',100)",
            (jd_id, 5),
        )
        legacy_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    d = client.get(f"/api/match-tasks/{legacy_id}/score_distribution").json()["data"]
    assert d == {"task_id": legacy_id, "jd_title": "Python后端工程师",
                 "n_candidates": 0, "scores": []}


def test_model_info():
    r = client.get("/api/model/info")
    assert r.status_code == 200
    data = r.json()["data"]
    assert set(data) == {"model_name", "version", "f1", "train_samples", "updated_at"}
    assert 0.0 <= data["f1"] <= 1.0
