"""外贸会计核算 — 7 个确定性计算工具 (子项目②)。

设计: docs/superpowers/specs/2026-05-30-外贸会计核算技能-design.md
原则: 金额全部 Decimal, 禁用 float 运算; 默认金额 2 位 ROUND_HALF_UP, 单价/汇率 4 位。
每个函数返回 dict(最终值 str + breakdown), 供 Claude tool-use 回灌 + 审计。
被 chat2go_worker.py import; 纯函数, 可 unittest 单测。
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

# ── 精度 helpers ────────────────────────────────────────────────────────────

_MONEY = Decimal("0.01")   # 金额 2 位
_UNIT = Decimal("0.0001")  # 单价/汇率 4 位


def _d(x: Any) -> Decimal:
    """任意数值 → Decimal (经 str 转, 避免 float 二进制误差)。"""
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def _money(x: Decimal) -> str:
    return str(x.quantize(_MONEY, rounding=ROUND_HALF_UP))


def _unit(x: Decimal) -> str:
    return str(x.quantize(_UNIT, rounding=ROUND_HALF_UP))


def _pct(x: Decimal) -> str:
    """比率 (0.4) → 百分比字符串 ('40.00')。"""
    return str((x * 100).quantize(_MONEY, rounding=ROUND_HALF_UP))


# ── 1. 单位成本 ──────────────────────────────────────────────────────────────

def calc_unit_cost(purchase_total, freight, duty, misc_fees, quantity) -> dict:
    """采购+运费+关税+杂费 → 总成本 + 单位成本。"""
    qty = _d(quantity)
    if qty <= 0:
        raise ValueError("quantity 必须 > 0")
    pt, fr, du, mc = _d(purchase_total), _d(freight), _d(duty), _d(misc_fees)
    total = pt + fr + du + mc
    unit = total / qty
    return {
        "total_cost": _money(total),
        "unit_cost": _unit(unit),
        "breakdown": {
            "purchase_total": _money(pt), "freight": _money(fr),
            "duty": _money(du), "misc_fees": _money(mc),
            "quantity": str(qty), "formula": "(采购+运费+关税+杂费)/数量",
        },
    }


# ── 2. 按目标利润率倒推报价 + 贸易术语 ──────────────────────────────────────

def quote_from_margin(unit_cost, target_margin, incoterm="FOB",
                      freight=0, insurance=0) -> dict:
    """报价 = 成本/(1-利润率); CFR=FOB+运费; CIF=FOB+运费+保费。"""
    cost = _d(unit_cost)
    margin = _d(target_margin)
    if margin >= 1 or margin < 0:
        raise ValueError("target_margin 必须在 [0, 1) 区间 (小数, 如 0.2 表示 20%)")
    fob = cost / (Decimal(1) - margin)
    inc = (incoterm or "FOB").upper()
    fr, ins = _d(freight), _d(insurance)
    if inc == "CIF":
        price = fob + fr + ins
    elif inc == "CFR":
        price = fob + fr
    else:  # FOB
        inc = "FOB"
        price = fob
    return {
        "quote_price": _money(price),
        "incoterm": inc,
        "breakdown": {
            "unit_cost": _money(cost), "target_margin": _pct(margin),
            "fob": _money(fob), "freight": _money(fr), "insurance": _money(ins),
            "formula": "报价=成本/(1-利润率); CFR=FOB+运费; CIF=FOB+运费+保费",
        },
    }


# ── 3. 单笔订单损益 ──────────────────────────────────────────────────────────

def order_pnl(revenue, cost, expenses=0, commission=0, tax=0) -> dict:
    """收入-成本=毛利; 毛利-费用-佣金-税=净利。"""
    rev, cst = _d(revenue), _d(cost)
    exp, com, tx = _d(expenses), _d(commission), _d(tax)
    gross = rev - cst
    net = gross - exp - com - tx
    gross_margin = (gross / rev) if rev != 0 else Decimal(0)
    net_margin = (net / rev) if rev != 0 else Decimal(0)
    return {
        "gross_profit": _money(gross),
        "net_profit": _money(net),
        "gross_margin": _pct(gross_margin),
        "net_margin": _pct(net_margin),
        "breakdown": {
            "revenue": _money(rev), "cost": _money(cst), "expenses": _money(exp),
            "commission": _money(com), "tax": _money(tx),
            "formula": "毛利=收入-成本; 净利=毛利-费用-佣金-税",
        },
    }


# ── 4. 汇率换算 ──────────────────────────────────────────────────────────────

def fx_convert(amount, from_ccy, to_ccy, rate) -> dict:
    """amount(from_ccy) * rate → to_ccy。rate = 1 from_ccy 兑多少 to_ccy。"""
    amt, rt = _d(amount), _d(rate)
    converted = amt * rt
    return {
        "converted": _money(converted),
        "from_ccy": from_ccy, "to_ccy": to_ccy, "rate": _unit(rt),
        "breakdown": {
            "amount": _money(amt), "rate": _unit(rt),
            "formula": f"{from_ccy} {_money(amt)} × {_unit(rt)} = {to_ccy} {_money(converted)}",
        },
    }


# ── 5. 出口退税 ──────────────────────────────────────────────────────────────

def export_rebate(purchase_amount, vat_rate, rebate_rate) -> dict:
    """退税额 = 含税采购额 / (1+增值税率) × 退税率。"""
    pa, vat, reb = _d(purchase_amount), _d(vat_rate), _d(rebate_rate)
    if vat < 0:
        raise ValueError("vat_rate 不能为负")
    rebate = pa / (Decimal(1) + vat) * reb
    return {
        "rebate_amount": _money(rebate),
        "breakdown": {
            "purchase_amount": _money(pa), "vat_rate": _pct(vat),
            "rebate_rate": _pct(reb),
            "formula": "退税额=含税采购额/(1+增值税率)×退税率",
        },
    }


# ── 6. 佣金核算 ──────────────────────────────────────────────────────────────

def commission(base_amount, net_before, commission_rate=None,
               commission_fixed=None) -> dict:
    """佣金 = base×rate 或 fixed; 净利 = net_before - 佣金。"""
    base, nb = _d(base_amount), _d(net_before)
    if commission_fixed is not None:
        com = _d(commission_fixed)
    elif commission_rate is not None:
        com = base * _d(commission_rate)
    else:
        raise ValueError("需提供 commission_rate 或 commission_fixed 之一")
    net_after = nb - com
    return {
        "commission_amount": _money(com),
        "net_after": _money(net_after),
        "breakdown": {
            "base_amount": _money(base), "net_before": _money(nb),
            "commission_rate": _pct(_d(commission_rate)) if commission_rate is not None else None,
            "commission_fixed": _money(_d(commission_fixed)) if commission_fixed is not None else None,
            "formula": "佣金=base×费率 或 固定额; 净利=原净利-佣金",
        },
    }


# ── 7. 对账 / 账期 aging ─────────────────────────────────────────────────────

def _parse_date(s) -> date:
    if isinstance(s, date):
        return s
    y, m, d = str(s).split("-")
    return date(int(y), int(m), int(d))


def _aging_bucket(days_overdue: int) -> str:
    if days_overdue <= 30:
        return "0-30"
    if days_overdue <= 60:
        return "31-60"
    if days_overdue <= 90:
        return "61-90"
    return "90+"


def reconcile(receivables=None, payables=None, as_of_date=None) -> dict:
    """应收应付汇总 + 账期 aging 分桶 (仅对未付应收按 due_date 距 as_of 的天数分桶)。"""
    receivables = receivables or []
    payables = payables or []
    as_of = _parse_date(as_of_date) if as_of_date else date.today()

    buckets = {"0-30": Decimal(0), "31-60": Decimal(0), "61-90": Decimal(0), "90+": Decimal(0)}
    total_recv = Decimal(0)
    for r in receivables:
        if r.get("paid"):
            continue
        amt = _d(r["amount"])
        total_recv += amt
        due = _parse_date(r["due_date"])
        days = (as_of - due).days
        buckets[_aging_bucket(days)] += amt

    total_pay = sum((_d(p["amount"]) for p in payables if not p.get("paid")), Decimal(0))
    balance = total_recv - total_pay
    return {
        "total_recv": _money(total_recv),
        "total_pay": _money(total_pay),
        "balance": _money(balance),
        "aging_buckets": {k: _money(v) for k, v in buckets.items()},
        "as_of_date": str(as_of),
    }


# ── Claude tool-use 接线 ─────────────────────────────────────────────────────

_NUM = {"type": "number"}

TOOL_SCHEMAS = [
    {
        "name": "calc_unit_cost",
        "description": "计算单位成本: (采购总额+运费+关税+杂费)/数量。需要算货物到岸/单件成本时用。",
        "input_schema": {"type": "object", "properties": {
            "purchase_total": _NUM, "freight": _NUM, "duty": _NUM,
            "misc_fees": _NUM, "quantity": _NUM,
        }, "required": ["purchase_total", "quantity"]},
    },
    {
        "name": "quote_from_margin",
        "description": "按目标利润率倒推报价并换算贸易术语。报价=成本/(1-利润率); CFR=FOB+运费; CIF=FOB+运费+保费。target_margin 用小数(0.2=20%)。incoterm: FOB/CIF/CFR。",
        "input_schema": {"type": "object", "properties": {
            "unit_cost": _NUM, "target_margin": _NUM,
            "incoterm": {"type": "string", "enum": ["FOB", "CIF", "CFR"]},
            "freight": _NUM, "insurance": _NUM,
        }, "required": ["unit_cost", "target_margin"]},
    },
    {
        "name": "order_pnl",
        "description": "单笔订单损益: 毛利=收入-成本; 净利=毛利-费用-佣金-税。算订单赚多少/利润率时用。",
        "input_schema": {"type": "object", "properties": {
            "revenue": _NUM, "cost": _NUM, "expenses": _NUM,
            "commission": _NUM, "tax": _NUM,
        }, "required": ["revenue", "cost"]},
    },
    {
        "name": "fx_convert",
        "description": "汇率换算: amount(from_ccy)×rate→to_ccy。rate=1单位from_ccy兑多少to_ccy。",
        "input_schema": {"type": "object", "properties": {
            "amount": _NUM, "from_ccy": {"type": "string"},
            "to_ccy": {"type": "string"}, "rate": _NUM,
        }, "required": ["amount", "from_ccy", "to_ccy", "rate"]},
    },
    {
        "name": "export_rebate",
        "description": "出口退税额=含税采购额/(1+增值税率)×退税率。税率用小数(0.13=13%)。",
        "input_schema": {"type": "object", "properties": {
            "purchase_amount": _NUM, "vat_rate": _NUM, "rebate_rate": _NUM,
        }, "required": ["purchase_amount", "vat_rate", "rebate_rate"]},
    },
    {
        "name": "commission",
        "description": "佣金核算: 佣金=base×费率 或 固定额; 净利=原净利-佣金。费率用小数。commission_rate 与 commission_fixed 二选一。",
        "input_schema": {"type": "object", "properties": {
            "base_amount": _NUM, "net_before": _NUM,
            "commission_rate": _NUM, "commission_fixed": _NUM,
        }, "required": ["base_amount", "net_before"]},
    },
    {
        "name": "reconcile",
        "description": "对账: 应收应付汇总+账期aging分桶(0-30/31-60/61-90/90+天)。receivables/payables 每条 {amount, due_date:'YYYY-MM-DD', paid:bool}。",
        "input_schema": {"type": "object", "properties": {
            "receivables": {"type": "array", "items": {"type": "object"}},
            "payables": {"type": "array", "items": {"type": "object"}},
            "as_of_date": {"type": "string"},
        }, "required": []},
    },
]

_DISPATCH = {
    "calc_unit_cost": calc_unit_cost,
    "quote_from_margin": quote_from_margin,
    "order_pnl": order_pnl,
    "fx_convert": fx_convert,
    "export_rebate": export_rebate,
    "commission": commission,
    "reconcile": reconcile,
}


def dispatch(name: str, tool_input: dict) -> dict:
    """按工具名调对应函数; 出错返回 {error} 而非抛, 让 AI 能看到错误并修正。"""
    fn = _DISPATCH.get(name)
    if fn is None:
        return {"error": f"unknown tool: {name}"}
    try:
        return fn(**(tool_input or {}))
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}
