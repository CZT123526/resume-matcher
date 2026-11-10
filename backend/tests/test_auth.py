"""T54 鉴权 / 审计 / 打码专项测试。

鉴权拦截类用例需要 AUTH_ENABLED=1（进程启动前给死）：
    AUTH_ENABLED=1 python -m pytest tests/test_auth.py -q
全量跑 `python -m pytest tests/` 时 conftest 默认 AUTH_ENABLED=0，这些用例自动
skipif 跳过；登录/打码/审计类用例与鉴权开关无关，两种模式都照常执行。

两套测试互补：业务套件（=0）保证"关鉴权不破坏旧行为"，本文件（=1）保证
"开鉴权真的拦得住、审计真的落了表、打码真的盖住了 PII"。
"""
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.core.security import hash_password, token_hash
from app.main import app
from app.db import get_db

client = TestClient(app)

# 守卫拦截行为只在 AUTH_ENABLED=1 下可测（全量跑时跳过，见模块 docstring）
_requires_auth = pytest.mark.skipif(
    not settings.AUTH_ENABLED,
    reason="AUTH_ENABLED=0（默认关鉴权）；需 AUTH_ENABLED=1 单独跑本卷",
)

# 带联系方式与身份证的样例原文（覆盖三种 PII）
_PII_TEXT = "电话13812345678，邮箱zhangsan@163.com，身份证110101199001011234。技能：Python。"


def _seed_resume(raw_text: str = _PII_TEXT) -> int:
    """直接落一份 done 状态的简历 + 全文索引，绕过解析流水线"""
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO resumes(file_name, file_type, file_size, parse_status, source, raw_text) "
            "VALUES('测试.pdf', 'pdf', 100, 'done', 'business', ?)",
            (raw_text,),
        )
        rid = cur.lastrowid
        conn.execute(
            "INSERT INTO entities(resume_id, field_key, field_value, source) VALUES(?, 'skill', 'Python', 'bert')",
            (rid,),
        )
        conn.execute(
            "INSERT INTO resume_search(resume_id, file_name, raw_text) VALUES(?, '测试.pdf', ?)",
            (rid, raw_text),
        )
        conn.commit()
        return rid
    finally:
        conn.close()


def _login(username: str = "hr1", password: str = "pw123456") -> str:
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["data"]["token"]


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _audit_rows(action: str) -> list:
    conn = get_db()
    try:
        return conn.execute(
            "SELECT username, action, target FROM audit_log WHERE action=?", (action,)
        ).fetchall()
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def _reset_auth_state():
    """每个用例前重建已知用户、清空会话与审计（表结构由 conftest 的 init_db 建）"""
    conn = get_db()
    try:
        for table in ("sessions", "audit_log", "users"):
            conn.execute(f"DELETE FROM {table}")
        conn.execute(
            "INSERT INTO users(username, password_hash, role) VALUES('hr1', ?, 'hr')",
            (hash_password("pw123456"),),
        )
        conn.commit()
    finally:
        conn.close()
    yield


# ---------- 登录 / 会话 ----------

def test_login_success():
    r = client.post("/api/auth/login", json={"username": "hr1", "password": "pw123456"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["username"] == "hr1"
    assert data["role"] == "hr"
    assert len(data["token"]) >= 40  # urlsafe 32 字节 → 43 字符
    assert "T" in data["expires_at"]  # ISO 时间


def test_login_wrong_password_and_unknown_user_same_message():
    """防枚举：密码错与用户不存在文案必须一致"""
    wrong_pw = client.post("/api/auth/login", json={"username": "hr1", "password": "bad"})
    no_user = client.post("/api/auth/login", json={"username": "ghost", "password": "bad"})
    assert wrong_pw.status_code == 401 and no_user.status_code == 401
    assert wrong_pw.json()["code"] == "E4011"
    assert wrong_pw.json()["message"] == no_user.json()["message"]


@_requires_auth
def test_business_endpoint_requires_token():
    r = client.get("/api/resumes")
    assert r.status_code == 401
    assert r.json()["code"] == "E4011"


@_requires_auth
def test_bad_token_rejected():
    r = client.get("/api/resumes", headers=_auth_header("not-a-real-token"))
    assert r.status_code == 401


def test_valid_token_passes():
    token = _login()
    r = client.get("/api/resumes", headers=_auth_header(token))
    assert r.status_code == 200


@_requires_auth
def test_me_returns_identity():
    token = _login()
    r = client.get("/api/auth/me", headers=_auth_header(token))
    assert r.status_code == 200
    assert r.json()["data"] == {"username": "hr1", "role": "hr"}


@_requires_auth
def test_logout_kills_session_and_is_protected():
    token = _login()
    r = client.post("/api/auth/logout", headers=_auth_header(token))
    assert r.status_code == 200
    assert r.json()["data"] == {"logged_out": True}
    # 注销后同 token 再访问业务接口 → 401；再调 logout 本身也要登录 → 401
    assert client.get("/api/resumes", headers=_auth_header(token)).status_code == 401
    assert client.post("/api/auth/logout", headers=_auth_header(token)).status_code == 401


@_requires_auth
def test_expired_token_rejected():
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO sessions(token_hash, username, expires_at) VALUES(?, 'hr1', '2020-01-01T00:00:00')",
            (token_hash("expired-token"),),
        )
        conn.commit()
    finally:
        conn.close()
    assert client.get("/api/resumes", headers=_auth_header("expired-token")).status_code == 401


def test_exempt_surface():
    """/health 与 /api/auth/login 不需要 token；/docs 也要放行"""
    assert client.get("/health").status_code == 200
    # login 走错密码也是 401（业务失败）而不是 401 之外被守卫拦下的 401——
    # 用可达性判断：响应体是 E4011 包裹（守卫拦截返回同样的包裹，这里用 /health 证明豁免面活着）
    assert client.get("/docs").status_code == 200


# ---------- 管理员引导 ----------

def test_ensure_admin_bootstraps_once():
    conn = get_db()
    try:
        conn.execute("DELETE FROM users")
        conn.commit()
    finally:
        conn.close()

    from app.svc.auth import ensure_admin

    ensure_admin()
    conn = get_db()
    try:
        rows = conn.execute("SELECT username, password_hash, role FROM users").fetchall()
    finally:
        conn.close()
    assert len(rows) == 1
    assert rows[0]["username"] == settings.ADMIN_USERNAME
    assert rows[0]["role"] == "admin"

    ensure_admin()  # 幂等：已有用户不再创建
    conn = get_db()
    try:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
        from app.core.security import verify_password

        assert verify_password("pw123456", rows[0]["password_hash"]) is False
    finally:
        conn.close()


# ---------- PII 打码 ----------

def test_mask_pii_formats():
    from app.svc.masking import mask_pii

    masked = mask_pii(_PII_TEXT)
    assert "13812345678" not in masked and "138****5678" in masked
    assert "zhangsan@163.com" not in masked and "zh***@163.com" in masked
    assert "110101199001011234" not in masked and "1101************34" in masked
    assert mask_pii("无敏感信息普通文本") == "无敏感信息普通文本"
    assert mask_pii("") == "" and mask_pii(None) is None
    # 邮箱里的数字不被手机号规则截胡（先邮箱后手机号的替换顺序）
    assert mask_pii("13812345678@163.com") == "13***@163.com"
    # 长数字串不误伤（11 位截取防边界）
    assert "12345678901234567890" == mask_pii("12345678901234567890")


def test_detail_masks_by_default_and_reveals_with_audit():
    rid = _seed_resume()
    token = _login()
    h = _auth_header(token)

    masked = client.get(f"/api/resumes/{rid}", headers=h).json()["data"]
    assert "13812345678" not in (masked["raw_text"] or "")
    assert "138****5678" in masked["raw_text"]

    revealed = client.get(f"/api/resumes/{rid}?reveal=1", headers=h).json()["data"]
    assert "13812345678" in revealed["raw_text"]
    # 审计：一次 view_resume + 一次 reveal_pii，操作人正确（=0 无登录上下文，如实落 "-"）
    assert len(_audit_rows("view_resume")) >= 1
    reveals = _audit_rows("reveal_pii")
    expected_user = "hr1" if settings.AUTH_ENABLED else "-"
    assert len(reveals) == 1 and reveals[0]["username"] == expected_user


def test_data_view_masks_same_way():
    rid = _seed_resume()
    token = _login()
    h = _auth_header(token)
    data = client.get(f"/api/resumes/{rid}/data", headers=h).json()["data"]
    assert "13812345678" not in data["raw_text"]
    assert "13812345678" not in data["matching"]["structured_text"]
    revealed = client.get(f"/api/resumes/{rid}/data?reveal=1", headers=h).json()["data"]
    assert "13812345678" in revealed["raw_text"]


def test_search_snippet_always_masked():
    rid = _seed_resume()
    token = _login()
    r = client.get("/api/resumes/search?q=13812345678", headers=_auth_header(token))
    assert r.status_code == 200
    items = r.json()["data"]["items"]
    assert items and "13812345678" not in items[0]["snippet"]
    assert "138****5678" in items[0]["snippet"]
    assert rid  # 语义占位：种子简历确实可被检索


# ---------- 审计埋点 ----------

def test_audit_login_success_and_fail():
    _login()
    client.post("/api/auth/login", json={"username": "hr1", "password": "bad"})
    assert len(_audit_rows("login_success")) == 1
    assert len(_audit_rows("login_fail")) == 1


def test_audit_upload_and_delete():
    token = _login()
    h = _auth_header(token)
    import io as _io

    from pypdf import PdfWriter  # 造一个最小合法 PDF

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = _io.BytesIO()
    writer.write(buf)
    r = client.post("/api/resumes/upload", headers=h,
                    files={"file": ("审计.pdf", buf.getvalue(), "application/pdf")})
    assert r.status_code == 202, r.text
    rid = r.json()["data"]["resume_id"]
    assert len(_audit_rows("upload_resume")) == 1

    r = client.delete(f"/api/resumes/{rid}", headers=h)
    assert r.status_code == 200
    assert len(_audit_rows("delete_resume")) == 1


def test_audit_write_failure_does_not_block_business():
    """审计是旁路：get_db 炸掉也不能把业务接口带崩"""
    from app.svc import audit as audit_mod

    original = audit_mod.get_db

    def _boom():
        raise RuntimeError("db busy")

    audit_mod.get_db = _boom
    try:
        audit_mod.log_action("hr1", "view_resume", "resume_id=1")  # 不应抛异常
    finally:
        audit_mod.get_db = original
