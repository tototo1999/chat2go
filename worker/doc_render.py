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
