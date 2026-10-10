"""S01 文档解析测试。"""
import pytest
from io import BytesIO

from app.core.errors import AppError, ErrorCode
from app.svc.parsing import parse_document


def test_unsupported_ext_rejected():
    with pytest.raises(AppError) as ei:
        parse_document(b"x", "resume.txt")
    assert ei.value.code == ErrorCode.UNSUPPORTED_FILE


def test_empty_file_rejected():
    with pytest.raises(AppError) as ei:
        parse_document(b"", "a.pdf")
    assert ei.value.code == ErrorCode.BAD_PARAM


def test_docx_roundtrip():
    import docx

    buf = BytesIO()
    d = docx.Document()
    d.add_paragraph("姓名：张三")
    d.add_paragraph("硕士，5年工作经验")
    d.add_paragraph("技能：Python FastAPI MySQL")
    d.save(buf)
    result = parse_document(buf.getvalue(), "张三.docx")
    assert "张三" in result["text"]
    assert "FastAPI" in result["text"]


def test_pdf_roundtrip():
    from reportlab.pdfgen import canvas

    buf = BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(100, 700, "Hello Resume Text")
    c.drawString(100, 680, "Skills: Python")
    c.save()
    result = parse_document(buf.getvalue(), "resume.pdf")
    assert "Hello Resume Text" in result["text"]
    assert "Skills: Python" in result["text"]


def test_corrupt_pdf_rejected():
    with pytest.raises(AppError) as ei:
        parse_document(b"%PDF-1.4 garbage bytes", "broken.pdf")
    assert ei.value.code == ErrorCode.BAD_PARAM
