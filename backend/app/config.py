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

    # 关键词重排融合系数（T34，算法设计 §3.2）：final = α·语义分 + (1-α)·词面分
    # α=1.0 退化为纯语义（消融对照）；默认值在 v2.1 金标准上扫描选定（见 docs/eval/metrics.json）
    MATCH_ALPHA = float(os.getenv("MATCH_ALPHA", "0.7"))

    # 自适应 α 开关（T39，算法设计 §3.2b）：开=按 JD 关键词在语料中的词面覆盖率
    # 动态下调词面权重（coverage 低 → α_eff→1.0 纯语义；满格 → α_eff=base 行为不变）。
    # 默认开启：三池验证 v4 0.9305→0.9522 / 压力 0.8400→0.8589 / 半规范 0.9592→0.9826，
    # 全部向好且规则零自由参数（见 docs/eval/adaptive_alpha_report.json）；置 0 回到冻结口径
    MATCH_ADAPTIVE_ALPHA = os.getenv("MATCH_ADAPTIVE_ALPHA", "1") == "1"

    # 注：DeepSeek 相关配置只存在于 backend/tools/baselines/deepseek_zeroshot.py
    # （离线对照组，直接读环境变量）——运行时配置零外部 API 引用（TC-API-01 红线）。


settings = Settings()
