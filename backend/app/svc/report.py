"""S11 评估报告生成（M05）：任务结果 → PDF（排名、证据链、匹配分布）。

中文字体策略：优先内嵌系统 TrueType 字体（微软雅黑/黑体/Noto CJK）——内嵌后 PDF
自包含，任何查看器都能正确显示中文；都找不到再退回 reportlab 内置 CID 字体
STSong-Light（文字层不丢，但部分查看器渲染空白，仅兜底）。
"""
import io
import json
import os
from datetime import datetime

_FONT_NAME = "CJK"  # 注册名，全局仅注册一次
_FONT_CANDIDATES = [
    "C:/Windows/Fonts/msyh.ttc",        # Windows 微软雅黑
    "C:/Windows/Fonts/simhei.ttf",      # Windows 黑体
    "C:/Windows/Fonts/simsun.ttc",      # Windows 宋体
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",  # Linux/Colab
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/PingFang.ttc",  # macOS
]


def _ensure_font() -> str:
    """返回可用的中文字体注册名；一个都内嵌不了则退回 CID 字体"""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont

    if _FONT_NAME in pdfmetrics.getRegisteredFontNames():
        return _FONT_NAME
    for path in _FONT_CANDIDATES:
        if not os.path.exists(path):
            continue
        try:
            from reportlab.pdfbase.ttfonts import TTFont

            pdfmetrics.registerFont(TTFont(_FONT_NAME, path, subfontIndex=0))
            return _FONT_NAME
        except Exception:
            continue
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    return "STSong-Light"

from app.core.errors import AppError, ErrorCode
from app.db import get_db

_SCORE_BUCKETS = [(0.9, 1.01, "0.90~1.00"), (0.8, 0.9, "0.80~0.89"),
                  (0.7, 0.8, "0.70~0.79"), (0.5, 0.7, "0.50~0.69"),
                  (0.0, 0.5, "0.00~0.49")]


def _fetch_report_data(task_id: int) -> dict:
    """任务 + JD + 排名结果 + 候选人名（与 results 端点同一口径）"""
    conn = get_db()
    try:
        task = conn.execute(
            "SELECT id, status, jd_id, top_k, created_at FROM match_tasks WHERE id=?", (task_id,)
        ).fetchone()
        if task is None:
            raise AppError(ErrorCode.NOT_FOUND, f"任务 {task_id} 不存在")
        if task["status"] != "done":
            raise AppError(ErrorCode.CONFLICT, f"任务尚未完成（当前 {task['status']}），完成后再导出报告")

        jd = conn.execute("SELECT title, content FROM jds WHERE id=?", (task["jd_id"],)).fetchone()
        rows = conn.execute(
            "SELECT resume_id, rank, score, evidence_json FROM match_results "
            "WHERE task_id=? ORDER BY rank",
            (task_id,),
        ).fetchall()
        names = {
            r["resume_id"]: r["field_value"]
            for r in conn.execute(
                "SELECT e.resume_id, e.field_value FROM entities e "
                "JOIN match_results m ON m.resume_id = e.resume_id "
                "WHERE m.task_id=? AND e.field_key='name'",
                (task_id,),
            )
        }
    finally:
        conn.close()

    items = [
        {
            "rank": r["rank"],
            "candidate_name": names.get(r["resume_id"], f"候选人{r['resume_id']}"),
            "score": r["score"],
            "evidence": json.loads(r["evidence_json"] or "[]"),
        }
        for r in rows
    ]
    return {
        "task_id": task_id,
        "top_k": task["top_k"],
        "created_at": task["created_at"],
        "jd_title": jd["title"] if jd else "",
        "jd_content": (jd["content"] or "") if jd else "",
        "items": items,
    }


def _score_distribution(scores: list[float]) -> list[tuple[str, int]]:
    out = []
    for lo, hi, label in _SCORE_BUCKETS:
        n = sum(1 for s in scores if lo <= s < hi)
        if n:
            out.append((label, n))
    return out or [("—", 0)]


def generate_report(task_id: int) -> io.BytesIO:
    """生成 PDF 评估报告，返回字节流（api 层以 application/pdf 响应）"""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    font = _ensure_font()

    data = _fetch_report_data(task_id)
    now = datetime.now().isoformat(timespec="seconds")

    title_style = ParagraphStyle("t", fontName=font, fontSize=16, leading=22, spaceAfter=4)
    head_style = ParagraphStyle("h", fontName=font, fontSize=12, leading=18,
                                spaceBefore=10, spaceAfter=4, textColor=colors.HexColor("#1a3c6e"))
    body_style = ParagraphStyle("b", fontName=font, fontSize=9.5, leading=14)
    meta_style = ParagraphStyle("m", fontName=font, fontSize=9, leading=13,
                                textColor=colors.HexColor("#555555"))
    cell_style = ParagraphStyle("c", fontName=font, fontSize=9, leading=12)
    cell_head = ParagraphStyle("ch", fontName=font, fontSize=9.5, leading=13,
                               textColor=colors.white)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, top_margin=18 * mm, bottom_margin=18 * mm,
                            left_margin=16 * mm, right_margin=16 * mm,
                            title=f"简历匹配评估报告-{data['jd_title']}")
    story: list = []

    story.append(Paragraph("简历匹配评估报告", title_style))
    story.append(Paragraph(
        f"任务 ID：{data['task_id']}　｜　生成时间：{now}　｜　"
        f"岗位：{data['jd_title']}　｜　返回 Top-{data['top_k']}",
        meta_style,
    ))
    story.append(Paragraph(f"JD 摘要：{data['jd_content'][:120]}…", meta_style))

    # 一、排名与证据链
    story.append(Paragraph("一、候选排名与证据链", head_style))
    table_data = [[Paragraph(h, cell_head) for h in ("排名", "候选人", "匹配分", "证据链")]]
    for item in data["items"]:
        table_data.append([
            Paragraph(str(item["rank"]), cell_style),
            Paragraph(item["candidate_name"], cell_style),
            Paragraph(f"{item['score']:.4f}", cell_style),
            Paragraph("；".join(item["evidence"]) or "—", cell_style),
        ])
    col_w = [16 * mm, 26 * mm, 20 * mm, 100 * mm]
    table = Table(table_data, colWidths=col_w, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a3c6e")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#bbbbbb")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f6fb")]),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(table)

    # 二、匹配分布
    story.append(Paragraph("二、匹配分分布", head_style))
    scores = [i["score"] for i in data["items"]]
    total = len(scores) or 1
    dist_rows = [[Paragraph(h, cell_head) for h in ("分数区间", "人数", "占比")]]
    for label, n in _score_distribution(scores):
        bar = "█" * max(1, round(n / total * 20))
        dist_rows.append([Paragraph(label, cell_style), Paragraph(str(n), cell_style),
                          Paragraph(f"{n / total:.0%}　{bar}", cell_style)])
    dist_table = Table(dist_rows, colWidths=[34 * mm, 20 * mm, 108 * mm])
    dist_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a3c6e")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#bbbbbb")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(dist_table)

    # 三、方法说明
    story.append(Paragraph("三、方法说明", head_style))
    story.append(Paragraph(
        "匹配分由语义编码余弦相似度归一而来：score=(1+cos)/2 ∈ [0,1]，保留四位小数；"
        "证据链只做解释、不参与打分（打分与解释分离）。实体抽取与语义编码全部本地推理，"
        "无外部 API 依赖。NER 与编码模型版本见「模型信息」接口。", body_style,
    ))
    story.append(Spacer(1, 6))
    story.append(Paragraph("本报告由系统自动生成。", meta_style))

    doc.build(story)
    buf.seek(0)
    return buf
