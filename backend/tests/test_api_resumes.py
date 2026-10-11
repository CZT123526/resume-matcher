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


def test_upload_saves_original_and_download():
    """API-13：上传原件落盘，GET /file 拿回字节一致 + 原文件名（中文按 RFC 5987 百分号编码）"""
    import urllib.parse

    payload = _make_docx(RESUME_TEXT)
    rid = client.post("/api/resumes/upload", files={"file": ("原件测试.docx", payload, "application/octet-stream")}).json()["data"]["resume_id"]

    r = client.get(f"/api/resumes/{rid}/file")
    assert r.status_code == 200
    assert r.content == payload
    cd = r.headers.get("content-disposition", "")
    assert "attachment" in cd
    assert "原件测试" in urllib.parse.unquote(cd)


def test_download_file_unknown_id_404():
    r = client.get("/api/resumes/999999/file")
    assert r.status_code == 404 and r.json()["code"] == "E4041"


def test_download_file_missing_on_disk():
    """行存在但原件已缺失 → 404（覆盖早于落盘功能的历史数据）"""
    from app.db import upload_dir

    rid = client.post("/api/resumes/upload", files={"file": ("nofile.docx", _make_docx(RESUME_TEXT), "application/octet-stream")}).json()["data"]["resume_id"]
    for f in upload_dir().glob(f"{rid}.*"):
        f.unlink()

    r = client.get(f"/api/resumes/{rid}/file")
    assert r.status_code == 404 and r.json()["code"] == "E4041"


def test_delete_removes_saved_file():
    """删除简历时原件一并清理，之后 /file 404"""
    rid = client.post("/api/resumes/upload", files={"file": ("tobedeleted.docx", _make_docx(RESUME_TEXT), "application/octet-stream")}).json()["data"]["resume_id"]
    assert client.get(f"/api/resumes/{rid}/file").status_code == 200

    client.delete(f"/api/resumes/{rid}")
    assert client.get(f"/api/resumes/{rid}/file").status_code == 404


def test_search_fulltext_and_short_keyword():
    """API-15：FTS 中文子串检索 + <3字符 LIKE 降级 + 空白词 400"""
    client.post("/api/resumes/upload", files={"file": ("搜索测试.docx", _make_docx("姓名：王五\n技能：区块链风控平台开发"), "application/octet-stream")})

    r = client.get("/api/resumes/search", params={"q": "风控平台"})
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["total"] >= 1
    hit = next(i for i in d["items"] if i["file_name"] == "搜索测试.docx")
    assert "风控" in hit["snippet"]

    r2 = client.get("/api/resumes/search", params={"q": "李四"})  # 2字 → LIKE 路径
    assert r2.status_code == 200 and r2.json()["data"]["total"] >= 1

    assert client.get("/api/resumes/search", params={"q": "   "}).status_code == 400


def test_detail_quality_signal():
    """T29：详情带 quality（像不像简历/实体数/正文字数）"""
    rid = client.post("/api/resumes/upload", files={"file": ("质检.docx", _make_docx(RESUME_TEXT), "application/octet-stream")}).json()["data"]["resume_id"]
    q = client.get(f"/api/resumes/{rid}").json()["data"]["quality"]
    assert q["like_resume"] is True
    assert q["entity_count"] > 0 and q["text_chars"] > 0


def test_reparse_roundtrip():
    """API-14：重解析走已落盘原件，实体重建后依旧可用；不存在/无原件 404"""
    payload = _make_docx(RESUME_TEXT)
    rid = client.post("/api/resumes/upload", files={"file": ("重解析.docx", payload, "application/octet-stream")}).json()["data"]["resume_id"]

    r = client.post(f"/api/resumes/{rid}/reparse")
    assert r.status_code == 202 and r.json()["data"]["parse_status"] == "pending"
    d = client.get(f"/api/resumes/{rid}").json()["data"]  # TestClient 同步执行后台任务
    assert d["parse_status"] == "done" and d["entities"]

    assert client.post("/api/resumes/999999/reparse").status_code == 404


def test_data_view():
    """API-16：解析数据视图——全文/实体/匹配输入/向量预览全链路可见"""
    rid = client.post("/api/resumes/upload", files={"file": ("数据视图.docx", _make_docx(RESUME_TEXT), "application/octet-stream")}).json()["data"]["resume_id"]
    d = client.get(f"/api/resumes/{rid}/data").json()["data"]

    assert d["stats"]["text_chars"] > 0 and d["stats"]["entity_count"] > 0
    assert d["stats"]["bert_count"] + d["stats"]["rule_count"] == d["stats"]["entity_count"]
    assert "李四" in d["raw_text"]
    assert d["matching"]["structured_text"].strip()
    # 维度不做下限断言：测试环境为未拟合 TF-IDF 降级（dim=0），dev 为 BERT 768 维
    assert d["matching"]["vector_dim"] >= 0
    assert 0 <= len(d["matching"]["vector_preview"]) <= 8
