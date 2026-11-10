"""报告导出接口（API-11），契约见 docs/backend-api.md §4：200 PDF 文件流。"""
from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from app.svc.audit import log_request_action
from app.svc.report import generate_report

router = APIRouter(tags=["reports"])


@router.get("/api/reports/{task_id}/export")
def export_report(task_id: int, request: Request, reveal: bool = Query(False)):
    """任务完成后导出 PDF 评估报告（未完成 409 / 任务不存在 404，由服务层抛出）。

    T54 隐私：候选人姓名默认打码（张*），?reveal=1 显示全名并记审计。
    """
    buf = generate_report(task_id, reveal=reveal)
    log_request_action(request, "export_pdf", f"task_id={task_id}",
                       "reveal" if reveal else "masked")
    return Response(
        content=buf.getvalue(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="match_report_{task_id}.pdf"'},
    )
