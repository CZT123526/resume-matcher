"""T56 用户管理专项测试（契约 docs/backend-api.md §8 / api-schemas.md §6）。

跑法与 test_auth.py 同构：
    AUTH_ENABLED=1 python -m pytest tests/test_users.py -q
全量跑（conftest 默认 AUTH_ENABLED=0）时，守卫/会话类用例自动 skipif；
CRUD 业务规则（重名 409、参数 400、404）两种模式都执行——=0 时接口随
全站放行是 T54 既定取舍，CRUD 规则不受影响。

角色门控断言（403）、会话失效断言（删号/重置/改密后旧 token 必须死）只在
=1 下有意义：=0 时守卫不拦、/auth/me 对死会话也返回 200 null。
"""
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.core.security import hash_password
from app.main import app
from app.db import get_db
from app.svc.users import delete_user
from app.core.errors import AppError

client = TestClient(app)

_requires_auth = pytest.mark.skipif(
    not settings.AUTH_ENABLED,
    reason="AUTH_ENABLED=0（默认关鉴权）；需 AUTH_ENABLED=1 单独跑本卷",
)


def _login(username: str, password: str):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def _admin_token() -> str:
    r = _login("admin1", "adminpass1")
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
def _reset_users_state():
    """每用例前重建已知用户：admin1（管理员）+ hr1（普通角色）"""
    conn = get_db()
    try:
        for table in ("sessions", "audit_log", "users"):
            conn.execute(f"DELETE FROM {table}")
        conn.execute(
            "INSERT INTO users(username, password_hash, role) VALUES('admin1', ?, 'admin')",
            (hash_password("adminpass1"),),
        )
        conn.execute(
            "INSERT INTO users(username, password_hash, role) VALUES('hr1', ?, 'hr')",
            (hash_password("pw123456"),),
        )
        conn.commit()
    finally:
        conn.close()
    yield


# ---------- 列表（两种模式都执行） ----------

def test_list_users_shape():
    r = client.get("/api/users", headers=_auth_header(_admin_token()))
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["total"] == 2
    names = {item["username"] for item in data["items"]}
    assert names == {"admin1", "hr1"}
    item = data["items"][0]
    assert item["role"] in ("hr", "admin") and "T" in item["created_at"]


# ---------- 创建 ----------

def test_create_user_then_new_account_can_login():
    h = _auth_header(_admin_token())
    r = client.post("/api/users", headers=h,
                    json={"username": "wang_hr", "password": "wang123", "role": "hr"})
    assert r.status_code == 200, r.text
    assert r.json()["data"] == {"username": "wang_hr", "role": "hr"}
    login = _login("wang_hr", "wang123")
    assert login.status_code == 200
    assert login.json()["data"]["role"] == "hr"


def test_create_duplicate_conflict():
    h = _auth_header(_admin_token())
    body = {"username": "wang_hr", "password": "wang123", "role": "hr"}
    assert client.post("/api/users", headers=h, json=body).status_code == 200
    dup = client.post("/api/users", headers=h, json=body)
    assert dup.status_code == 409
    assert dup.json()["code"] == "E4091"
    assert "已存在" in dup.json()["message"]


def test_create_rejects_short_password():
    h = _auth_header(_admin_token())
    r = client.post("/api/users", headers=h,
                    json={"username": "ok_name", "password": "abc", "role": "hr"})
    assert r.status_code == 400 and r.json()["code"] == "E4001"


def test_create_rejects_bad_role():
    h = _auth_header(_admin_token())
    r = client.post("/api/users", headers=h,
                    json={"username": "ok_name", "password": "wang123", "role": "superadmin"})
    assert r.status_code == 400 and r.json()["code"] == "E4001"


def test_create_rejects_unsafe_username():
    """username 进 DELETE 路径：空格与 / ? # % 一律拒绝"""
    h = _auth_header(_admin_token())
    for bad in ("has space", "a/b", "a?b", "a#b"):
        r = client.post("/api/users", headers=h,
                        json={"username": bad, "password": "wang123", "role": "hr"})
        assert r.status_code == 400, f"{bad!r} 应被拒绝"
        assert r.json()["code"] == "E4001"


# ---------- 守卫（仅 AUTH_ENABLED=1） ----------

@_requires_auth
def test_users_api_requires_token():
    assert client.get("/api/users").status_code == 401
    assert client.get("/api/users").json()["code"] == "E4011"


@_requires_auth
def test_hr_role_forbidden_everywhere():
    h = _auth_header(_login("hr1", "pw123456").json()["data"]["token"])
    r = client.get("/api/users", headers=h)
    assert r.status_code == 403 and r.json()["code"] == "E4031"
    assert r.json()["message"] == "仅管理员可执行此操作"
    assert client.post("/api/users", headers=h,
                       json={"username": "x_user", "password": "wang123"}).status_code == 403
    assert client.delete("/api/users/hr1", headers=h).status_code == 403


# ---------- 删除 ----------

@_requires_auth
def test_delete_self_conflict():
    h = _auth_header(_admin_token())
    r = client.delete("/api/users/admin1", headers=h)
    assert r.status_code == 409
    assert "不能删除自己" in r.json()["message"]


def test_delete_last_admin_guard_at_svc_level():
    """最后一个管理员保护：走 svc 直调（API 层 actor==target 时先被「删自己」拦住，
    该分支防御的是未来新增的改角色等路径——纵深防御，契约语义不变）"""
    with pytest.raises(AppError) as ei:
        delete_user("admin2", "admin1")  # admin2 是假想操作者：库里没有它也不影响判定
    assert ei.value.code == "E4091"
    assert "至少保留一个管理员" in ei.value.message


@_requires_auth
def test_delete_user_kills_their_sessions():
    h = _auth_header(_admin_token())
    client.post("/api/users", headers=h,
                json={"username": "wang_hr", "password": "wang123", "role": "hr"})
    token_w = _login("wang_hr", "wang123").json()["data"]["token"]
    assert client.get("/api/auth/me", headers=_auth_header(token_w)).status_code == 200

    r = client.delete("/api/users/wang_hr", headers=h)
    assert r.status_code == 200
    assert r.json()["data"]["deleted"] is True
    assert r.json()["data"]["deleted_sessions"] >= 1
    # 被删用户的浏览器下一次请求即 401，前端自动回登录页
    assert client.get("/api/auth/me", headers=_auth_header(token_w)).status_code == 401


def test_delete_missing_user_404():
    h = _auth_header(_admin_token())
    r = client.delete("/api/users/ghost", headers=h)
    assert r.status_code == 404 and r.json()["code"] == "E4041"


# ---------- 重置密码（仅 AUTH_ENABLED=1：会话失效断言） ----------

@_requires_auth
def test_reset_password_flow():
    h = _auth_header(_admin_token())
    token_hr = _login("hr1", "pw123456").json()["data"]["token"]

    r = client.post("/api/users/hr1/reset_password", headers=h,
                    json={"new_password": "brandnew1"})
    assert r.status_code == 200 and r.json()["data"] == {"reset": True}
    # 旧会话全死，新密码可登录
    assert client.get("/api/auth/me", headers=_auth_header(token_hr)).status_code == 401
    assert _login("hr1", "brandnew1").status_code == 200
    assert _login("hr1", "pw123456").status_code == 401


@_requires_auth
def test_reset_own_password_conflict():
    """对自己重置 = 把自己登出，服务端拒绝并指路修改密码"""
    h = _auth_header(_admin_token())
    r = client.post("/api/users/admin1/reset_password", headers=h,
                    json={"new_password": "brandnew1"})
    assert r.status_code == 409
    assert "修改密码" in r.json()["message"]


def test_reset_missing_user_404():
    h = _auth_header(_admin_token())
    r = client.post("/api/users/ghost/reset_password", headers=h,
                    json={"new_password": "brandnew1"})
    assert r.status_code == 404 and r.json()["code"] == "E4041"


# ---------- 修改自己的密码（仅 AUTH_ENABLED=1：当前会话保留断言） ----------

@_requires_auth
def test_change_password_flow_keeps_current_session():
    t1 = _login("hr1", "pw123456").json()["data"]["token"]
    t2 = _login("hr1", "pw123456").json()["data"]["token"]  # 第二台「浏览器」
    h1 = _auth_header(t1)

    # 旧密码错：400 而非 401（401 在前端契约里等于自动登出），当前会话必须还活着
    bad = client.post("/api/auth/password", headers=h1,
                      json={"old_password": "wrong!", "new_password": "brandnew1"})
    assert bad.status_code == 400 and bad.json()["code"] == "E4001"
    assert client.get("/api/auth/me", headers=h1).status_code == 200

    ok_r = client.post("/api/auth/password", headers=h1,
                       json={"old_password": "pw123456", "new_password": "brandnew1"})
    assert ok_r.status_code == 200 and ok_r.json()["data"] == {"changed": True}
    # 当前会话保留，其他会话全下线，新密码生效
    assert client.get("/api/auth/me", headers=h1).status_code == 200
    assert client.get("/api/auth/me", headers=_auth_header(t2)).status_code == 401
    assert _login("hr1", "brandnew1").status_code == 200
    assert _login("hr1", "pw123456").status_code == 401


# ---------- 审计 ----------

def test_audit_actions_recorded():
    expected_user = "admin1" if settings.AUTH_ENABLED else "-"
    h = _auth_header(_admin_token())
    client.post("/api/users", headers=h,
                json={"username": "wang_hr", "password": "wang123", "role": "hr"})
    client.post("/api/users/wang_hr/reset_password", headers=h,
                json={"new_password": "wang456"})
    client.delete("/api/users/wang_hr", headers=h)

    created = _audit_rows("user_create")
    assert len(created) == 1 and created[0]["target"] == "wang_hr"
    reset = _audit_rows("user_reset_password")
    assert len(reset) == 1 and reset[0]["target"] == "wang_hr"
    deleted = _audit_rows("user_delete")
    assert len(deleted) == 1 and deleted[0]["target"] == "wang_hr"
    assert all(row["username"] == expected_user for row in created + reset + deleted)
