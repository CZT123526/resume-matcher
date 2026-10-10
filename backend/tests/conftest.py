"""pytest 全局夹具：测试库与业务库隔离（必须在 app.config 导入前设置环境变量）。

注意：模块级 TestClient(app) 不触发 lifespan，所以这里显式建表。
"""
import os
import tempfile

import pytest

_TEST_DB = os.path.join(tempfile.gettempdir(), "resume_matcher_test.db")
os.environ["DB_PATH"] = _TEST_DB
# 测试强制 TF-IDF 降级编码（不加载 BERT，秒级跑完）；BERT 主路另有手动冒烟
os.environ["FORCE_TFIDF"] = "1"

# 会话开始前清掉旧测试库，保证用例互不污染
if os.path.exists(_TEST_DB):
    os.remove(_TEST_DB)


@pytest.fixture(scope="session", autouse=True)
def _init_test_db():
    from app.db import init_db

    init_db()
