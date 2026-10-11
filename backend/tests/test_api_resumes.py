"""简历模块接口测试（API-01/02/03/04）。

TestClient 会在响应返回前执行完 BackgroundTasks，
因此上传后立即可断言 parse_status 已流转完成。
"""
from io import BytesIO

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)


def _make_docx(text: str) -> bytes:
    import docx

    buf = BytesIO()
    d = docx.Document()
    for line in text.splitlines():
        d.add_paragraph(line)
    d.save(buf)
    return buf.getvalue()


RESUME_TEXT = "姓名：李四\n清华大学 本科\n3年工作经验\n技能：Python FastAPI"


def test_upload_and_parse_done():
    r = client.post("/api/resumes/upload", files={"file": ("李四.docx", _make_docx(RESUME_TEXT), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
    assert r.status_code == 202
    body = r.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["file_name"] == "李四.docx"
    rid = data["resume_id"]

    # TestClient 下后台任务已执行完
    d = client.get(f"/api/resumes/{rid}").json()["data"]
    assert d["parse_status"] == "done"
    assert d["raw_text"] and "李四" in d["raw_text"]
    ekeys = {e["field_key"] for e in d["entities"]}
    assert {"name", "degree", "skill"} <= ekeys
    assert d["created_at"].startswith("2026-") and "T" in d["created_at"]  # ISO 格式


def test_upload_unsupported_type():
    r = client.post("/api/resumes/upload", files={"file": ("x.txt", b"hello", "text/plain")})
    assert r.status_code == 400
    assert r.json()["code"] == "E4002"


def test_upload_empty_file():
    r = client.post("/api/resumes/upload", files={"file": ("empty.pdf", b"", "application/pdf")})
    assert r.status_code == 400
    assert r.json()["code"] == "E4001"


def test_list_pagination_and_filter():
    for i in range(3):
        client.post("/api/resumes/upload", files={"file": (f"r{i}.docx", _make_docx(RESUME_TEXT), "application/octet-stream")})

    r = client.get("/api/resumes", params={"page": 1, "page_size": 2}).json()["data"]
    assert len(r["items"]) == 2
    assert r["total"] >= 3

    r2 = client.get("/api/resumes", params={"parse_status": "done", "page_size": 100}).json()["data"]
    assert all(i["parse_status"] == "done" for i in r2["items"])
    assert all("raw_text" not in i for i in r2["items"])  # 列表不带大字段

    r3 = client.get("/api/resumes", params={"parse_status": "bogus"})
    assert r3.status_code == 400 and r3.json()["code"] == "E4001"


def test_detail_404():
    r = client.get("/api/resumes/999999")
    assert r.status_code == 404 and r.json()["code"] == "E4041"


def test_delete_then_404():
    rid = client.post("/api/resumes/upload", files={"file": ("d.docx", _make_docx(RESUME_TEXT), "application/octet-stream")}).json()["data"]["resume_id"]
    r = client.delete(f"/api/resumes/{rid}")
    assert r.status_code == 200 and r.json()["data"]["deleted"] is True
    assert client.get(f"/api/resumes/{rid}").status_code == 404
    assert client.delete(f"/api/resumes/{rid}").status_code == 404


def test_delete_resume_referenced_by_match_results():
    """回归：简历被匹配结果引用时也可删（match_results.resume_id 级联，schema 漏标曾致 500）"""
    rid = client.post("/api/resumes/upload", files={"file": ("r.docx", _make_docx(RESUME_TEXT), "application/octet-stream")}).json()["data"]["resume_id"]
    jid = client.post("/api/jds", json={"title": "Python后端工程师", "content": "要求：Python经验。"}).json()["data"]["jd_id"]
    tid = client.post("/api/match-tasks", json={"jd_id": jid, "top_k": 5}).json()["data"]["task_id"]
    st = client.get(f"/api/match-tasks/{tid}").json()["data"]["status"]
    assert st == "done"  # TestClient 同步执行后台任务
    r = client.delete(f"/api/resumes/{rid}")
    assert r.status_code == 200 and r.json()["data"]["deleted"] is True
