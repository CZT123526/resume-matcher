"""契约层测试：统一响应包裹、异常体系、全局处理器。"""
from fastapi.testclient import TestClient

from app.common.response import ok
from app.core.errors import AppError, ErrorCode
from app.main import app

client = TestClient(app, raise_server_exceptions=False)


def test_ok_envelope_shape():
    """ok() 产出与 docs/backend-api.md 一致的成功包裹"""
    r = ok({"a": 1})
    assert r == {"code": 0, "message": "ok", "data": {"a": 1}}


def test_app_error_carries_status():
    e = AppError(ErrorCode.NOT_FOUND, "简历不存在")
    assert e.http_status == 404
    assert e.code.value == "E4041"


def test_global_handler_formats_envelope():
    """AppError → 统一失败包裹（注册临时路由验证全局处理器）"""
    @app.get("/boom-test")
    def boom():
        raise AppError(ErrorCode.NOT_FOUND, "简历不存在")

    r = client.get("/boom-test")
    assert r.status_code == 404
    assert r.json() == {"code": "E4041", "message": "简历不存在", "data": None}


def test_schemas_importable():
    """数据契约可导入且实体枚举与算法设计文档一致（7类）"""
    from app.schemas import ENTITY_KEYS, MatchTaskCreate, ResumeDetail

    assert ENTITY_KEYS == {"name", "degree", "school", "skill", "years", "company", "title"}
    t = MatchTaskCreate(jd_id=1)
    assert t.top_k == 10
    assert ResumeDetail(resume_id=1, file_name="a.pdf", parse_status="done",
                        created_at="2026-10-10").raw_text is None
