"""M05 报告导出集成测试（API-11 / S11 / TC-05-01）。"""
import sqlite3
from io import BytesIO

from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.db import db_file
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


def _make_done_task() -> int:
    """上传一份匹配的简历 + 建 JD + 跑完匹配任务，返回 task_id"""
    r = client.post(
        "/api/resumes/upload",
        files={"file": ("r.docx", _docx(["姓名：赵六", "本科", "4年工作经验",
                                        "技能：Python FastAPI", "担任后端开发工程师"]))},
    )
    assert r.status_code == 202
    jd = client.post(
        "/api/jds",
        json={"title": "Python后端工程师", "content": "要求：3年以上Python经验，熟悉FastAPI。"},
    ).json()["data"]["jd_id"]
    task = client.post("/api/match-tasks", json={"jd_id": jd, "top_k": 5}).json()["data"]["task_id"]
    st = client.get(f"/api/match-tasks/{task}").json()["data"]
    assert st["status"] == "done", st
    return task


def test_export_report_pdf():
    task_id = _make_done_task()
    r = client.get(f"/api/reports/{task_id}/export")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.content.startswith(b"%PDF")  # PDF 魔数

    # 反读 PDF：标题、候选人、证据链文案真实存在（TC-05-01）
    text = "".join(page.extract_text() or "" for page in PdfReader(BytesIO(r.content)).pages)
    assert "简历匹配评估报告" in text
    assert "赵六" in text
    assert "证据链" in text or "技能重叠" in text


def test_export_report_conflict_on_pending():
    """未完成任务导出 → 409 E4091（直接插库造 pending，绕过同步后台任务）"""
    jd = client.post("/api/jds", json={"title": "x", "content": "y"}).json()["data"]["jd_id"]
    conn = sqlite3.connect(db_file())
    try:
        cur = conn.execute(
            "INSERT INTO match_tasks(jd_id, top_k, status) VALUES(?,?,'pending')", (jd, 5)
        )
        conn.commit()
        task_id = cur.lastrowid
    finally:
        conn.close()
    r = client.get(f"/api/reports/{task_id}/export")
    assert r.status_code == 409 and r.json()["code"] == "E4091"


def test_export_report_404():
    r = client.get("/api/reports/999999/export")
    assert r.status_code == 404 and r.json()["code"] == "E4041"
