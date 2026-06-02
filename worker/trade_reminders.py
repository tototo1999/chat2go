# worker/trade_reminders.py
"""催单系统 Phase 1 纯逻辑:扫描选择 / 文案 / prompt 注入 / 工具 schema + DB 薄封装。
纯函数可本地单测;DB 封装(load_*/dispatch_*)部署后真实验,沿用 trade_memory.py 模式。"""
from datetime import date, timedelta, datetime, timezone

DEFAULT_LEAD_DAYS = 2


def _lead(r: dict) -> int:
    v = r.get("lead_days")
    return v if isinstance(v, int) and v >= 0 else DEFAULT_LEAD_DAYS


def select_due(rows: list[dict], today: date) -> list[dict]:
    """从 pending 提醒里挑「今天该催」的:进入提前窗口或已逾期,且今天还没发过。"""
    out = []
    for r in rows:
        if r.get("status") != "pending":
            continue
        try:
            due = date.fromisoformat(r["due_date"])
        except (ValueError, KeyError, TypeError):
            continue
        if today < due - timedelta(days=_lead(r)):
            continue
        last = r.get("last_fired_on")
        if last and date.fromisoformat(last) == today:
            continue
        out.append(r)
    return out


def format_reminder_message(r: dict, today: date) -> str:
    """生成房间内催单文案(模板,不调 LLM)。逾期标红。"""
    kind = r.get("kind") or "提醒"
    note = r.get("note") or ""
    due_str = r.get("due_date") or ""
    try:
        delta = (date.fromisoformat(due_str) - today).days
    except (ValueError, TypeError):
        delta = 0
    if delta < 0:
        return f"🔔🔴 逾期催单:{kind} —— {note},已逾期 {-delta} 天({due_str} 到期)!"
    if delta == 0:
        return f"🔔 催单提醒:{kind} —— {note},**今天**到期({due_str})。"
    return f"🔔 催单提醒:{kind} —— {note},{due_str} 到期(还有 {delta} 天)。"


def format_reminders_for_prompt(rows: list[dict]) -> str:
    """把 pending 提醒注入 system prompt(按到期日升序)。空 → 空串。"""
    pend = [r for r in rows if r.get("status") == "pending"]
    if not pend:
        return ""
    pend.sort(key=lambda r: r.get("due_date") or "9999-12-31")
    lines = ["", "## 当前待催事项(提醒,以此为准;用户问『同步进度』时一并汇总)"]
    for r in pend:
        lines.append(f"- {r.get('due_date')} · {r.get('kind')}:{r.get('note')}")
    return "\n".join(lines) + "\n"


REMINDER_TOOL_SCHEMAS = [
    {
        "name": "set_reminder",
        "description": "为跟单挂一条带到期日的催单提醒。聊到任何有时间点的待办"
                       "(尾款/定金到期、船期、交期、约定的跟进日等)就调用,系统会到点"
                       "主动在房间里提醒用户。同一订单可挂多条。",
        "input_schema": {"type": "object", "properties": {
            "customer": {"type": "string", "description": "客户名/代号(可选,用于关联到对应活跃订单)"},
            "kind": {"type": "string", "description": "催什么:尾款/定金/船期/交期/跟进/自定义"},
            "note": {"type": "string", "description": "催单内容,如『催 ACME 付尾款 $5000』"},
            "due_date": {"type": "string", "description": "到期日,ISO 格式 YYYY-MM-DD。不要编日期,缺就追问"},
            "lead_days": {"type": "integer", "description": "提前几天开始提醒(可选,默认 2)"},
        }, "required": ["kind", "note", "due_date"]},
    },
    {
        "name": "complete_reminder",
        "description": "把一条催单提醒标记为完成(如用户说『尾款收到了』『已发货』)。"
                       "按 kind +(可选)customer 匹配当前 pending 提醒。",
        "input_schema": {"type": "object", "properties": {
            "kind": {"type": "string", "description": "要完成的提醒类型(尾款/船期…)"},
            "customer": {"type": "string", "description": "客户名(可选,note 含该名时优先匹配)"},
        }, "required": ["kind"]},
    },
]
REMINDER_TOOLS = {"set_reminder", "complete_reminder"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_pending_reminders(sb, room_id: str) -> list[dict]:
    """读本房 pending 提醒(注入 prompt 用)。"""
    return sb.table("tradego_reminders").select("*") \
        .eq("room_id", room_id).eq("status", "pending").execute().data or []


def _find_active_order_id(sb, room_id: str, customer: str) -> str | None:
    rows = sb.table("tradego_orders").select("id") \
        .eq("room_id", room_id).eq("customer", customer).is_("valid_to", "null") \
        .order("valid_from", desc=True).limit(1).execute().data or []
    return rows[0]["id"] if rows else None


def dispatch_reminder_tool(sb, room_id: str, expert_id: str,
                           name: str, tool_input: dict, product: str = "tradego") -> dict:
    """执行催单工具,返回给 LLM 的 tool_result dict。坏输入在碰 DB 前返回错误。"""
    ti = tool_input or {}
    if name == "set_reminder":
        kind = (ti.get("kind") or "").strip()
        note = (ti.get("note") or "").strip()
        due = (ti.get("due_date") or "").strip()
        if not kind or not note or not due:
            return {"ok": False, "error": "缺 kind / note / due_date"}
        try:
            date.fromisoformat(due)
        except ValueError:
            return {"ok": False, "error": f"due_date 必须 YYYY-MM-DD,收到『{due}』"}
        lead = ti.get("lead_days")
        order_id = None
        cust = (ti.get("customer") or "").strip()
        if cust:
            order_id = _find_active_order_id(sb, room_id, cust)
        sb.table("tradego_reminders").insert({
            "room_id": room_id, "expert_id": expert_id, "product": product,
            "order_id": order_id, "kind": kind, "note": note, "due_date": due,
            "lead_days": lead if isinstance(lead, int) and lead >= 0 else DEFAULT_LEAD_DAYS,
        }).execute()
        return {"ok": True, "kind": kind, "due_date": due, "linked_order": bool(order_id)}

    if name == "complete_reminder":
        kind = (ti.get("kind") or "").strip()
        cust = (ti.get("customer") or "").strip()
        if not kind:
            return {"ok": False, "error": "缺 kind"}
        rows = sb.table("tradego_reminders").select("id, kind, note, due_date") \
            .eq("room_id", room_id).eq("status", "pending").eq("kind", kind) \
            .execute().data or []
        if cust:
            narrowed = [r for r in rows if cust in (r.get("note") or "")]
            if narrowed:
                rows = narrowed
        if not rows:
            return {"ok": False, "error": f"没找到 kind={kind} 的待办提醒"}
        if len(rows) > 1:
            return {"ok": False, "error": "匹配到多条,请在 customer/note 上消歧",
                    "candidates": [{"note": r["note"], "due_date": r["due_date"]} for r in rows]}
        sb.table("tradego_reminders").update({
            "status": "done", "updated_at": _now_iso(),
        }).eq("id", rows[0]["id"]).execute()
        return {"ok": True, "completed": rows[0]["note"]}

    return {"ok": False, "error": f"未知催单工具 {name}"}
