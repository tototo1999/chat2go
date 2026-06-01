# worker/doc_render.py
"""品牌级单证渲染：结构化数据 → HTML 模板 → PDF（WeasyPrint）。"""
from __future__ import annotations

_DEFAULT_CURRENCY = "USD"


def prepare_context(doc_type: str, data: dict, profile: dict) -> dict:
    """归一化 AI 给的 data + 合并公司档案 → Jinja 上下文。纯函数、不碰 DB。"""
    items = []
    subtotal = 0.0
    for it in data.get("items", []):
        qty = float(it.get("qty", 0) or 0)
        price = float(it.get("unit_price", 0) or 0)
        amt = it.get("amount")
        amt = round(qty * price, 2) if amt is None else float(amt)
        subtotal += amt
        items.append({**it, "qty": qty, "unit_price": price, "amount": amt})

    extras = [{"label": e.get("label", ""), "amount": float(e.get("amount", 0) or 0)}
              for e in data.get("extra_charges", [])]
    total = round(subtotal + sum(e["amount"] for e in extras), 2)

    seller = dict(profile or {})
    seller.setdefault("bank", (profile or {}).get("bank", {}))

    return {
        "doc_type": doc_type,
        "title_cn": data.get("title_cn") or ("报价单" if doc_type == "quote" else "形式发票"),
        "doc_no": data.get("doc_no", ""),
        "date": data.get("date", ""),
        "currency": data.get("currency") or _DEFAULT_CURRENCY,
        "validity": data.get("validity", ""),
        "buyer": data.get("buyer", {}),
        "items": items,
        "extras": extras,
        "subtotal": round(subtotal, 2),
        "total": total,
        "trade_term": data.get("trade_term", ""),
        "terms": data.get("terms", {}),
        "seller": seller,
        "seal_img": None,
    }


import os
from jinja2 import Environment, FileSystemLoader, select_autoescape

DOCUMENT_TOOL_SCHEMA = {
    "name": "make_document",
    "description": ("生成品牌级外贸单证 PDF(报价单 quote / 形式发票 pi)。"
                    "只需给 buyer+items+条款,卖方抬头/银行/logo/公章由系统按公司档案自动填充。"
                    "要盖章传 stamp:true。必须真的调用本工具,严禁编造下载链接。"),
    "input_schema": {
        "type": "object",
        "properties": {
            "doc_type": {"type": "string", "enum": ["quote", "pi"]},
            "title_cn": {"type": "string"},
            "doc_no": {"type": "string"},
            "date": {"type": "string", "description": "YYYY-MM-DD,省略则用当天"},
            "currency": {"type": "string"},
            "validity": {"type": "string"},
            "buyer": {"type": "object", "properties": {
                "name": {"type": "string"}, "attn": {"type": "string"},
                "address": {"type": "string"}, "tel": {"type": "string"}},
                "required": ["name"]},
            "items": {"type": "array", "items": {"type": "object", "properties": {
                "name": {"type": "string"}, "spec": {"type": "string"},
                "qty": {"type": "number"}, "unit_price": {"type": "number"},
                "amount": {"type": "number"}}, "required": ["name", "qty", "unit_price"]}},
            "extra_charges": {"type": "array", "items": {"type": "object", "properties": {
                "label": {"type": "string"}, "amount": {"type": "number"}}}},
            "trade_term": {"type": "string"},
            "terms": {"type": "object", "additionalProperties": {"type": "string"}},
            "stamp": {"type": "boolean"},
        },
        "required": ["doc_type", "buyer", "items"],
    },
}

_TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
_DOC_EN = {"quote": "Quotation", "pi": "Proforma Invoice"}

_env = Environment(
    loader=FileSystemLoader(_TEMPLATE_DIR),
    autoescape=select_autoescape(["html"]),
)


def render_document(doc_type: str, data: dict, profile: dict,
                    seal_png: bytes | None = None) -> bytes:
    """结构化数据 → PDF bytes。doc_type ∈ {quote, pi}。"""
    from weasyprint import HTML
    import base64

    ctx = prepare_context(doc_type, data, profile)
    ctx["doc_en"] = _DOC_EN.get(doc_type, "")
    ctx["seller_label"] = "报价方 / From Seller" if doc_type == "quote" else "卖方 / From Seller"
    ctx["seller_seal_label"] = "报价方盖章：" if doc_type == "quote" else "卖方盖章："
    if seal_png and data.get("stamp"):
        ctx["seal_img"] = "data:image/png;base64," + base64.b64encode(seal_png).decode()

    template = _env.get_template(f"{doc_type}.html")
    html_str = template.render(**ctx)
    return HTML(string=html_str, base_url=_TEMPLATE_DIR).write_pdf()
