"""应用入口：FastAPI 实例与健康检查路由。

启动：uvicorn app.main:app --port 8000 --reload
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings

app = FastAPI(title="resume-matcher", version=settings.VERSION)

# 允许前端开发服务器(5173)跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    """服务信息；接口自助文档见 /docs (Swagger UI)"""
    return {"service": settings.APP_NAME, "version": settings.VERSION, "docs": "/docs"}


@app.get("/health")
@app.get("/api/health")
def health():
    """探活接口：前端联调、冒烟测试、部署健康检查统一用它。

    /health 供直连探活；/api/health 供 Vite 代理路径（前端统一走 /api 前缀）。
    """
    return {"status": "ok"}
