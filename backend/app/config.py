"""全局配置：从环境变量 / backend/.env 读取。

纪律：真实密钥只放 backend/.env（已被 .gitignore 排除，永不提交）；
模板见仓库根目录 .env.example。
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# 加载 backend/.env（如存在）
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


class Settings:
    """集中管理配置项，代码中一律 from app.config import settings 取值"""

    APP_NAME = "recruiter-agent-backend"
    VERSION = "0.1.0"

    # 服务端口（与前端 5173 错开）
    BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8000"))

    # DeepSeek（OpenAI 兼容接口）
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4.1-flash")

    # SQLite 业务库文件路径（相对 backend/ 目录）
    DB_PATH = os.getenv("DB_PATH", "../db/recruiter.db")

    # ChromaDB 向量库持久化目录
    CHROMA_DIR = os.getenv("CHROMA_DIR", "../db/chroma")


settings = Settings()
