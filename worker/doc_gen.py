"""Excel / PDF 服务端生成 — 子项目③。

设计: docs/superpowers/specs/2026-05-30-excel-pdf-多模态生成-design.md
硬指标: PDF 中文不能出豆腐块 → reportlab 内置 STSong-Light (Adobe-GB1) CID 字体。
纯函数(build_excel/build_pdf 返回 bytes, 不碰网络/存储), 可单测; worker 负责上传。
"""
from __future__ import annotations

import io
import uuid

# ── 中文字体: reportlab 内置 CID 字体, 自带简体中文, 无需打包字体文件 ──────────
_CN_FONT = "STSong-Light"
_font_ready = False


def _ensure_cn_font():
    """注册中文 CID 字体(只注册一次)。"""
    global _font_ready
    if _font_ready:
        return
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    pdfmetrics.registerFont(UnicodeCIDFont(_CN_FONT))
    _font_ready = True


# ── 文件名 / 存储路径 ────────────────────────────────────────────────────────

def storage_path(filename: str, ext: str) -> str:
    """中文显示名 → ASCII storage 路径 (中文路径 Supabase Storage 返回 400, 踩过坑)。
    用 uuid 保唯一; 中文名只用于 attachment.name 展示。"""
    return f"gen/{uuid.uuid4().hex}.{ext}"


# ── Excel ────────────────────────────────────────────────────────────────────

def build_excel(spec: dict) -> bytes:
    """结构化数据 → .xlsx bytes。
    spec: {filename, sheet_name?, title?, headers[], rows[][], summary?[][] }
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = (spec.get("sheet_name") or "Sheet1")[:31]

    bold = Font(bold=True)
    r = 1
    title = spec.get("title")
    if title:
        ws.cell(row=r, column=1, value=title).font = Font(bold=True, size=14)
        r += 2

    headers = spec.get("headers") or []
    if headers:
        for c, h in enumerate(headers, start=1):
            ws.cell(row=r, column=c, value=h).font = bold
        r += 1

    for row in (spec.get("rows") or []):
        for c, v in enumerate(row, start=1):
            ws.cell(row=r, column=c, value=v)
        r += 1

    for row in (spec.get("summary") or []):
        for c, v in enumerate(row, start=1):
            cell = ws.cell(row=r, column=c, value=v)
            cell.font = bold
        r += 1

    # 自适应列宽(粗略)
    for col in ws.columns:
        width = max((len(str(c.value)) for c in col if c.value is not None), default=8)
        ws.column_dimensions[col[0].column_letter].width = min(max(width + 2, 10), 50)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── PDF ──────────────────────────────────────────────────────────────────────

def build_pdf(spec: dict) -> bytes:
    """结构化文档 → .pdf bytes (中文用 STSong-Light, 无豆腐块)。
    spec: {filename, title?, blocks[]}
    blocks: [{type:'paragraph', text}, {type:'table', headers[], rows[][]}]
    """
    _ensure_cn_font()
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    )

    styles = getSampleStyleSheet()
    body = ParagraphStyle("CNBody", parent=styles["Normal"],
                          fontName=_CN_FONT, fontSize=11, leading=18)
    h1 = ParagraphStyle("CNTitle", parent=styles["Title"],
                        fontName=_CN_FONT, fontSize=18, leading=24)

    story = []
    title = spec.get("title")
    if title:
        story.append(Paragraph(title, h1))
        story.append(Spacer(1, 6 * mm))

    for blk in (spec.get("blocks") or []):
        btype = blk.get("type")
        if btype == "paragraph":
            story.append(Paragraph(str(blk.get("text", "")), body))
            story.append(Spacer(1, 3 * mm))
        elif btype == "table":
            headers = blk.get("headers") or []
            rows = blk.get("rows") or []
            data = ([headers] if headers else []) + [list(map(str, r)) for r in rows]
            if not data:
                continue
            # 用 Paragraph 包裹单元格以支持中文字体
            cell_style = ParagraphStyle("CNCell", parent=body, fontSize=10, leading=14)
            wrapped = [[Paragraph(str(c), cell_style) for c in row] for row in data]
            tbl = Table(wrapped, hAlign="LEFT")
            ts = [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F0F0F0")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
            tbl.setStyle(TableStyle(ts))
            story.append(tbl)
            story.append(Spacer(1, 4 * mm))

    if not story:
        story.append(Paragraph(" ", body))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            topMargin=20 * mm, bottomMargin=20 * mm,
                            leftMargin=18 * mm, rightMargin=18 * mm)
    doc.build(story)
    return buf.getvalue()


# ── Claude tool schemas (dispatch 在 worker 层, 因需上传副作用) ────────────────

DOC_TOOL_SCHEMAS = [
    {
        "name": "make_excel",
        "description": "把结构化数据生成可下载的 Excel(.xlsx)文件。算完账/整理好表格后, 用户要下载表格时用。filename 用中文(无扩展名)。",
        "input_schema": {"type": "object", "properties": {
            "filename": {"type": "string", "description": "中文文件名, 无扩展名, 如 '订单核算表'"},
            "title": {"type": "string", "description": "表内大标题(可选)"},
            "sheet_name": {"type": "string"},
            "headers": {"type": "array", "items": {"type": "string"}},
            "rows": {"type": "array", "items": {"type": "array"}},
            "summary": {"type": "array", "items": {"type": "array"},
                        "description": "汇总行(可选), 会加粗"},
        }, "required": ["filename", "headers", "rows"]},
    },
    {
        "name": "make_pdf",
        "description": "把结构化文档生成可下载的 PDF 文件(中文正常显示)。报价单/合同/PI/正式文件用。filename 用中文(无扩展名)。",
        "input_schema": {"type": "object", "properties": {
            "filename": {"type": "string", "description": "中文文件名, 无扩展名, 如 '报价单'"},
            "title": {"type": "string"},
            "blocks": {"type": "array", "items": {"type": "object"},
                       "description": "文档块: {type:'paragraph',text} 或 {type:'table',headers[],rows[][]}"},
        }, "required": ["filename", "blocks"]},
    },
]

# 文件类型 → (build 函数, 扩展名, mime)
DOC_BUILDERS = {
    "make_excel": (build_excel, "xlsx",
                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "make_pdf": (build_pdf, "pdf", "application/pdf"),
}
