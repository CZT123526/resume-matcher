"""端到端冒烟：起真实后端后运行本脚本，验证 上传→解析→建JD→匹配→结果 全链路。

用法：
    1. 先起服务: uvicorn app.main:app --port 8000
    2. 再跑:  python scripts/smoke_e2e.py http://127.0.0.1:8000
"""
import sys
import tempfile
import time
from io import BytesIO
from pathlib import Path

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"

RESUMES = [
    ("张三.docx", ["姓名：张三", "硕士", "5年工作经验", "技能：Python FastAPI MySQL Docker", "担任后端开发工程师"]),
    ("李四.docx", ["姓名：李四", "本科", "3年工作经验", "技能：Python Django MySQL"]),
    ("王五.docx", ["姓名：王五", "本科", "1年工作经验", "技能：Photoshop", "担任平面设计师"]),
]
JD = {
    "title": "Python后端工程师",
    "content": "负责后端服务开发。要求：3年以上Python经验，熟悉FastAPI，本科及以上。",
}


def make_docx(lines: list[str]) -> bytes:
    import docx

    buf = BytesIO()
    d = docx.Document()
    for line in lines:
        d.add_paragraph(line)
    d.save(buf)
    return buf.getvalue()


def wait_parse(client: httpx.Client, resume_id: int, timeout: int = 120) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        d = client.get(f"/api/resumes/{resume_id}").json()["data"]
        if d["parse_status"] in {"done", "failed"}:
            return d
        time.sleep(1)
    raise TimeoutError(f"简历 {resume_id} 解析超时")


def main() -> int:
    client = httpx.Client(base_url=BASE, timeout=120)
    health = client.get("/api/health").json()
    assert health["status"] == "ok", f"探活失败: {health}"
    print("[1/5] 探活 OK")

    ids = []
    for name, lines in RESUMES:
        tmp = Path(tempfile.gettempdir()) / name
        tmp.write_bytes(make_docx(lines))
        with open(tmp, "rb") as f:
            r = client.post("/api/resumes/upload", files={"file": (name, f.read())})
        assert r.status_code == 202, r.text
        ids.append(r.json()["data"]["resume_id"])
        wait_parse(client, ids[-1])
    print(f"[2/5] 上传解析 OK: 简历 {ids}")

    r = client.post("/api/jds", json=JD)
    jd_id = r.json()["data"]["jd_id"]
    print(f"[3/5] 建JD OK: jd_id={jd_id}")

    r = client.post("/api/match-tasks", json={"jd_id": jd_id, "top_k": 3})
    assert r.status_code == 202, r.text
    task_id = r.json()["data"]["task_id"]
    while True:
        st = client.get(f"/api/match-tasks/{task_id}").json()["data"]
        if st["status"] in {"done", "failed"}:
            break
        time.sleep(1)
    assert st["status"] == "done", f"任务失败: {st}"
    print(f"[4/5] 匹配任务 OK: task_id={task_id}")

    data = client.get(f"/api/match-tasks/{task_id}/results").json()["data"]
    print(f"[5/5] 结果（{data['jd_title']}）:")
    for item in data["items"]:
        print(f"  #{item['rank']} {item['candidate_name']:<8} score={item['score']:<7} {item['evidence']}")
    top = data["items"][0]
    assert top["candidate_name"] in {"张三", "李四"}, f"排序异常，后端开发岗第一名竟是: {top['candidate_name']}"
    print("冒烟通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
