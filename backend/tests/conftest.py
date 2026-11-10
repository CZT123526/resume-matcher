"""pytest 全局夹具：测试库与业务库隔离（必须在 app.config 导入前设置环境变量）。

注意：模块级 TestClient(app) 不触发 lifespan，所以这里显式建表。
"""
import os
import tempfile

import pytest

_TEST_DB = os.path.join(tempfile.gettempdir(), "resume_matcher_test.db")
os.environ["DB_PATH"] = _TEST_DB
# 原件落盘同样隔离到临时目录，不污染 db/uploads/
os.environ["UPLOAD_DIR"] = os.path.join(tempfile.gettempdir(), "resume_matcher_test_uploads")
# 测试强制 TF-IDF 降级编码（不加载 BERT，秒级跑完）；BERT 主路另有手动冒烟
os.environ["FORCE_TFIDF"] = "1"
# T54：业务测试一键关闭鉴权（仿 FORCE_TFIDF 先例——env 必须在 import app 之前生效），
# 153 条既有测试零改动；鉴权/打码专项由 test_auth.py 在 AUTH_ENABLED=1 环境下单独覆盖。
# setdefault：命令行显式给 AUTH_ENABLED=1 时（单跑 test_auth.py）以外部为准
os.environ.setdefault("AUTH_ENABLED", "0")

# 会话开始前清掉旧测试库，保证用例互不污染
if os.path.exists(_TEST_DB):
    os.remove(_TEST_DB)


@pytest.fixture(scope="session", autouse=True)
def _init_test_db():
    from app.db import init_db

    init_db()
