# worker/trade_memory.py
"""Trade2GO 记忆 P0:订单状态机 + 冻结规则注入。
纯逻辑(迁移校验/双时序当前态/prompt 格式化)可本地单测;
DB I/O(load/dispatch)是薄封装,由 worker 传入 sb(service-role)。
"""
from __future__ import annotations

from typing import Any

# 订单状态(P0 默认 6 段;后续按真实跟单流程加值需同步 migration 的 enum)
ORDER_STATUSES = ["报价", "待PI", "已付定金", "生产中", "已发货", "收尾"]


def is_valid_transition(old: str | None, new: str) -> bool:
    """新建(old=None)可落任意已知状态(支持补录);已有订单只能前进(可跳级),
    不许回退、同态(同态=NOOP 不更新)、未知状态。"""
    if new not in ORDER_STATUSES:
        return False
    if old is None:
        return True
    if old not in ORDER_STATUSES:
        return False
    return ORDER_STATUSES.index(new) > ORDER_STATUSES.index(old)


def current_orders_from_rows(rows: list[dict] | None) -> list[dict]:
    """双时序:当前态 = valid_to 为空的行。"""
    return [r for r in (rows or []) if r.get("valid_to") in (None, "")]


def format_rules_for_prompt(rules: list[dict]) -> str:
    """冻结规则注入(权威)。rules: [{content, version}]。空 → 空串。"""
    if not rules:
        return ""
    lines = ["", "## 已固化口径/规则(冻结,权威,必须遵守;勿私自推翻)"]
    for r in rules:
        v = r.get("version")
        tag = f"[v{v}] " if v is not None else ""
        lines.append(f"- {tag}{(r.get('content') or '').strip()}")
    return "\n".join(lines) + "\n"


def format_orders_for_prompt(orders: list[dict]) -> str:
    """活跃订单注入(跟单进度,以此为准)。空 → 空串。"""
    if not orders:
        return ""
    lines = ["", "## 当前活跃订单(跟单进度,以此为准)"]
    for o in orders:
        cust = o.get("customer") or "?"
        desc = o.get("product_desc") or ""
        amt = o.get("amount")
        cur = o.get("currency") or ""
        money = f" · {amt}{cur}" if amt is not None else ""
        sep = ":" if desc else ""
        lines.append(f"- [{o.get('status', '?')}] {cust}{sep}{desc}{money}")
    return "\n".join(lines) + "\n"


# ── 工具 schema(挂进 tool-use 循环)──────────────────────────────────────────
ORDER_TOOL_SCHEMAS = [
    {
        "name": "update_order_status",
        "description": "新建或推进一个客户订单/跟单的状态。客户订单首次出现就新建;"
                       "状态向前推进就更新(只能前进、不能回退)。涉及订单进度变化时必须调用。",
        "input_schema": {"type": "object", "properties": {
            "customer": {"type": "string", "description": "客户名或代号"},
            "new_status": {"type": "string", "enum": ORDER_STATUSES},
            "product_desc": {"type": "string", "description": "货物描述(可选)"},
            "amount": {"type": "number", "description": "金额(可选)"},
            "currency": {"type": "string", "description": "币种,如 USD(可选)"},
        }, "required": ["customer", "new_status"]},
    },
    {
        "name": "query_orders",
        "description": "查当前活跃订单(可按客户名过滤)。需要确认某客户当前进度时调用。",
        "input_schema": {"type": "object", "properties": {
            "customer": {"type": "string", "description": "客户名(可选,过滤)"},
        }},
    },
]
ORDER_TOOLS = {"update_order_status", "query_orders"}
