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

    APP_NAME = "resume-matcher-backend"
    VERSION = "0.1.0"

    # 服务端口（与前端 5173 错开）
    BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8000"))

    # SQLite 业务库文件路径（相对 backend/ 目录）
    DB_PATH = os.getenv("DB_PATH", "../db/recruiter.db")

    # 简历原件保存目录（相对 backend/ 目录；整个目录不入 git，删除简历时原件一并清理）
    UPLOAD_DIR = os.getenv("UPLOAD_DIR", "../db/uploads")

    # 注：DeepSeek 相关配置只存在于 backend/tools/baselines/deepseek_zeroshot.py
    # （离线对照组，直接读环境变量）——运行时配置零外部 API 引用（TC-API-01 红线）。


settings = Settings()
