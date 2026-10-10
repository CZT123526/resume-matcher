"""应用入口：FastAPI 实例、全局异常处理与健康检查路由。

启动：uvicorn app.main:app --port 8000 --reload

分层纪律：本文件与 api/ 路由层只做参数校验和调用 svc/，业务逻辑一律下沉 svc/。
"""
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.core.errors import AppError, ErrorCode, HTTP_STATUS

app = FastAPI(title="resume-matcher", version=settings.VERSION)


# ---------- 全局异常处理：所有错误统一为 {"code","message","data"} 包裹 ----------
@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    """业务异常：svc 层 raise AppError，这里统一转响应（api 层无需 try/except）"""
    return JSONResponse(
        status_code=exc.http_status,
        content={"code": exc.code.value, "message": exc.message, "data": None},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    """参数校验失败：FastAPI 默认 422，按契约统一为 400 + E4001"""
    return JSONResponse(
        status_code=HTTP_STATUS[ErrorCode.BAD_PARAM],
        content={"code": ErrorCode.BAD_PARAM.value, "message": "参数错误", "data": None},
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    """兜底：未预期异常统一为 500 + E5001，不向前端泄露堆栈"""
    return JSONResponse(
        status_code=HTTP_STATUS[ErrorCode.INTERNAL],
        content={"code": ErrorCode.INTERNAL.value, "message": "服务内部错误", "data": None},
    )

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
