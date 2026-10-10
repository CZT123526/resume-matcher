"""报告导出接口（API-11），契约见 docs/backend-api.md §4：200 PDF 文件流。"""
from fastapi import APIRouter
from fastapi.responses import Response

from app.svc.report import generate_report

router = APIRouter(tags=["reports"])


@router.get("/api/reports/{task_id}/export")
def export_report(task_id: int):
    """任务完成后导出 PDF 评估报告（未完成 409 / 任务不存在 404，由服务层抛出）"""
    buf = generate_report(task_id)
    return Response(
        content=buf.getvalue(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="match_report_{task_id}.pdf"'},
    )
