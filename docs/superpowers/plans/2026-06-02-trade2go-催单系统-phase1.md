# Trade2GO 催单系统 Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Trade2GO 后端定时主动催单 —— AI 跟单时记下带日期的待办,Modal Cron 每天扫描临近/逾期项,自动在房间里留催单消息。

**Architecture:** 通道无关的催单引擎(新表 `tradego_reminders` + 纯逻辑模块 `trade_reminders.py` + Modal Cron 扫描器),派发层 `dispatch_reminder(reminder, channels)` 是可插拔插槽,Phase 1 只实现 `in_room` 适配器(往 messages 表写一条 role=ai 消息)。

**Tech Stack:** Python 3.14、Supabase(supabase-py,service-role)、Modal(`modal.Cron`)、pytest;沿用 `worker/trade_memory.py` 的「纯函数可单测 + DB 薄封装部署后真实验」模式。

设计依据:`docs/superpowers/specs/2026-06-02-trade2go-催单系统-design.md`

**关键现有约定(实现时必须遵守):**
- AI 消息用大咖账号 `expert_id` 写入,`role='ai'`,前端永远显示「AI 助手」。
- `messages` 列:`room_id, user_id, role('user'|'expert'|'ai'), content, type('text'|'markdown'), attachments, channel, created_at`。主线程 `channel='main'`。
- 外贸房工具在 `_run_completion`(`worker/chat2go_worker.py`)的 tool-use 循环里分派(elif 链 line ~771)。
- 外贸 prompt 在 `ingest` 里拼装(line ~896-901):`system + TRADE_ACCOUNTING_GUIDE + format_memory_block(...) + format_orders_for_prompt(...)`。
- `_now_iso()`(`trade_memory.py`)给 timestamptz;`date.fromisoformat` / `date.today()` 处理 date。
- Modal:`app = modal.App("chat2go-worker")`,`image`(line 54)用 `.add_local_python_source(...)`,`secrets`(line 91)含 `SUPABASE_URL`/`SUPABASE_SERVICE_ROLE_KEY`/`ANTHROPIC_API_KEY`。`_sb_client()`(line 243)建 service-role 客户端。
- 部署:`cd worker && ~/.venv-c2g/bin/modal deploy chat2go_worker.py`。单测:`~/.venv-c2g/bin/python -m pytest`。

---

### Task 1: 建表 migration `tradego_reminders`

**Files:**
- Create: `supabase/migrations/20260602120000_tradego_reminders.sql`
- 应用方式:Supabase MCP `apply_migration`(preview-then-go),或本文件入库后由用户在 MCP 跑。

- [ ] **Step 1: 写 migration SQL**

`supabase/migrations/20260602120000_tradego_reminders.sql`:
```sql
-- Trade2GO 催单系统 Phase 1:提醒表(每个订单可挂多条带日期的待办)
create table if not exists tradego_reminders (
  id            uuid primary key default gen_random_uuid(),
  room_id       uuid not null references rooms(id) on delete cascade,
  order_id      uuid references tradego_orders(id) on delete set null,
  expert_id     uuid not null,
  product       text not null default 'tradego',
  kind          text not null,            -- 尾款/船期/交期/定金/跟进/自定义
  note          text not null,            -- 催单内容
  due_date      date not null,            -- 到期日
  lead_days     int  not null default 2,  -- 提前几天开始提醒
  status        text not null default 'pending',  -- pending|done|dismissed|snoozed
  last_fired_on date,                      -- 去重:最近一次已发催单的日期
  fire_count    int  not null default 0,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
create index if not exists idx_tradego_reminders_scan
  on tradego_reminders(status, due_date) where status = 'pending';
create index if not exists idx_tradego_reminders_room
  on tradego_reminders(room_id) where status = 'pending';

alter table tradego_reminders enable row level security;
-- 读:登录用户可读本房提醒(沿用 messages/orders 的「房可读」口径)。
create policy tradego_reminders_read on tradego_reminders
  for select using (true);
-- 写:仅 service-role(worker)。anon/authenticated 无写策略 = 默认拒。
```

- [ ] **Step 2: 应用 migration(preview-then-go)**

用 Supabase MCP `apply_migration`(name=`tradego_reminders`,query=上面 SQL)。
跑前把 SQL 贴给用户 preview,确认后执行(跨 4 产品共用 project,DDL 必须 preview)。

- [ ] **Step 3: 验证表已建**

MCP `execute_sql`:
```sql
select column_name, data_type from information_schema.columns
where table_name = 'tradego_reminders' order by ordinal_position;
```
Expected: 13 列,`due_date`/`last_fired_on` 为 `date`,`created_at`/`updated_at` 为 `timestamp with time zone`。

- [ ] **Step 4: Commit**

```bash
git add supabase/migrations/20260602120000_tradego_reminders.sql
git commit -m "feat(db): tradego_reminders 表(催单系统 Phase 1)"
```

---

### Task 2: `trade_reminders.py` 纯逻辑 —— select_due + 文案

**Files:**
- Create: `worker/trade_reminders.py`
- Test: `worker/test_trade_reminders.py`

- [ ] **Step 1: 写失败测试 `select_due`**

`worker/test_trade_reminders.py`:
```python
from datetime import date
import trade_reminders as trem


def _r(**kw):
    base = {"id": "x", "status": "pending", "due_date": "2026-06-10",
            "lead_days": 2, "last_fired_on": None, "fire_count": 0,
            "kind": "尾款", "note": "催 ACME 尾款 $5000"}
    base.update(kw)
    return base


def test_select_due_within_lead_window():
    # 6/8 = 到期日(6/10) - lead(2),刚进窗口 → 命中
    assert trem.select_due([_r()], date(2026, 6, 8)) == [_r()]


def test_select_due_before_window_skips():
    # 6/7 还没到「提前 2 天」窗口 → 不命中
    assert trem.select_due([_r()], date(2026, 6, 7)) == []


def test_select_due_overdue_hits():
    assert len(trem.select_due([_r()], date(2026, 6, 15))) == 1


def test_select_due_already_fired_today_skips():
    r = _r(last_fired_on="2026-06-09")
    assert trem.select_due([r], date(2026, 6, 9)) == []


def test_select_due_fired_yesterday_hits_again():
    r = _r(last_fired_on="2026-06-08")
    assert len(trem.select_due([r], date(2026, 6, 9))) == 1


def test_select_due_non_pending_skips():
    assert trem.select_due([_r(status="done")], date(2026, 6, 15)) == []


def test_select_due_lead_days_missing_defaults_2():
    r = _r(lead_days=None)
    assert len(trem.select_due([r], date(2026, 6, 8))) == 1
    assert trem.select_due([r], date(2026, 6, 7)) == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd worker && ~/.venv-c2g/bin/python -m pytest test_trade_reminders.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'trade_reminders'`）

- [ ] **Step 3: 实现 `select_due`**

`worker/trade_reminders.py`:
```python
# worker/trade_reminders.py
"""催单系统 Phase 1 纯逻辑:扫描选择 / 文案 / prompt 注入 / 工具 schema + DB 薄封装。
纯函数可本地单测;DB 封装(load_*/dispatch_*)部署后真实验,沿用 trade_memory.py 模式。"""
from datetime import date, timedelta

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
            continue  # 还没到提醒窗
        last = r.get("last_fired_on")
        if last and date.fromisoformat(last) == today:
            continue  # 今天已发,去重
        out.append(r)
    return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd worker && ~/.venv-c2g/bin/python -m pytest test_trade_reminders.py -v`
Expected: 7 passed

- [ ] **Step 5: 写 `format_reminder_message` 失败测试(追加到测试文件)**

```python
def test_format_message_upcoming():
    msg = trem.format_reminder_message(_r(), date(2026, 6, 8))
    assert "🔔" in msg and "还有 2 天" in msg and "尾款" in msg


def test_format_message_today():
    msg = trem.format_reminder_message(_r(), date(2026, 6, 10))
    assert "今天" in msg


def test_format_message_overdue():
    msg = trem.format_reminder_message(_r(), date(2026, 6, 13))
    assert "🔴" in msg and "逾期 3 天" in msg
```

- [ ] **Step 6: 跑测试确认失败**

Run: `cd worker && ~/.venv-c2g/bin/python -m pytest test_trade_reminders.py -v`
Expected: FAIL（`AttributeError: module 'trade_reminders' has no attribute 'format_reminder_message'`）

- [ ] **Step 7: 实现 `format_reminder_message`**

追加到 `worker/trade_reminders.py`:
```python
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
```

- [ ] **Step 8: 跑测试确认通过**

Run: `cd worker && ~/.venv-c2g/bin/python -m pytest test_trade_reminders.py -v`
Expected: 10 passed

- [ ] **Step 9: Commit**

```bash
git add worker/trade_reminders.py worker/test_trade_reminders.py
git commit -m "feat(reminders): select_due + 催单文案(纯逻辑+单测)"
```

---

### Task 3: prompt 注入 `format_reminders_for_prompt`

**Files:**
- Modify: `worker/trade_reminders.py`
- Test: `worker/test_trade_reminders.py`

- [ ] **Step 1: 写失败测试(追加)**

```python
def test_format_for_prompt_empty():
    assert trem.format_reminders_for_prompt([]) == ""
    assert trem.format_reminders_for_prompt([_r(status="done")]) == ""


def test_format_for_prompt_sorts_by_due():
    rows = [_r(due_date="2026-06-20", kind="船期", note="问船期"),
            _r(due_date="2026-06-10", kind="尾款", note="催尾款")]
    out = trem.format_reminders_for_prompt(rows)
    assert out.index("2026-06-10") < out.index("2026-06-20")  # 早的在前
    assert "待催事项" in out
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd worker && ~/.venv-c2g/bin/python -m pytest test_trade_reminders.py::test_format_for_prompt_empty -v`
Expected: FAIL（no attribute `format_reminders_for_prompt`）

- [ ] **Step 3: 实现**

追加到 `worker/trade_reminders.py`:
```python
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd worker && ~/.venv-c2g/bin/python -m pytest test_trade_reminders.py -v`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
git add worker/trade_reminders.py worker/test_trade_reminders.py
git commit -m "feat(reminders): pending 提醒注入 prompt"
```

---

### Task 4: 工具 schema + DB 派发(set_reminder / complete_reminder / load)

**Files:**
- Modify: `worker/trade_reminders.py`
- Test: `worker/test_trade_reminders.py`(只单测纯校验分支;DB 调用部署后 E2E 验)

- [ ] **Step 1: 写失败测试(纯校验分支:坏输入不碰 DB)**

`dispatch_reminder_tool` 在坏输入时应在碰 DB 之前返回错误。传 `sb=None`,坏输入不应抛(走不到 DB);测两条:
```python
def test_set_reminder_missing_fields_errors_before_db():
    out = trem.dispatch_reminder_tool(None, "room1", "exp1", "set_reminder",
                                      {"kind": "尾款"})  # 缺 note/due_date
    assert out["ok"] is False and "due_date" in out["error"]


def test_set_reminder_bad_date_errors_before_db():
    out = trem.dispatch_reminder_tool(None, "room1", "exp1", "set_reminder",
                                      {"kind": "尾款", "note": "催", "due_date": "6月10"})
    assert out["ok"] is False and "YYYY-MM-DD" in out["error"]


def test_unknown_tool_errors():
    out = trem.dispatch_reminder_tool(None, "room1", "exp1", "nope", {})
    assert out["ok"] is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd worker && ~/.venv-c2g/bin/python -m pytest test_trade_reminders.py::test_set_reminder_missing_fields_errors_before_db -v`
Expected: FAIL（no attribute `dispatch_reminder_tool`）

- [ ] **Step 3: 实现 schema + 派发 + load**

追加到 `worker/trade_reminders.py`:
```python
from datetime import datetime, timezone

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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd worker && ~/.venv-c2g/bin/python -m pytest test_trade_reminders.py -v`
Expected: 15 passed

- [ ] **Step 5: Commit**

```bash
git add worker/trade_reminders.py worker/test_trade_reminders.py
git commit -m "feat(reminders): set_reminder/complete_reminder 工具 + DB 派发"
```

---

### Task 5: 接进 worker(import / image / tools / 分派 / prompt 注入)

**Files:**
- Modify: `worker/chat2go_worker.py`(多处)

- [ ] **Step 1: import + image source**

在 import 区(`import trade_memfs as tmf` 附近)加:
```python
import trade_reminders as trem
```
在 image 链(`.add_local_python_source("trade_memfs")` 之后,line ~82)加:
```python
    .add_local_python_source("trade_reminders")
```

- [ ] **Step 2: 挂工具 schema**

`_run_completion` 里组装 `tools`(line ~716)处,在 `tm.ORDER_TOOL_SCHEMAS` 之后追加:
```python
    tools = (ta.TOOL_SCHEMAS + dg.DOC_TOOL_SCHEMAS + tm.ORDER_TOOL_SCHEMAS
             + trem.REMINDER_TOOL_SCHEMAS + [tm.REMEMBER_TOOL_SCHEMA])
```
（即把原 `tools = ta.TOOL_SCHEMAS + dg.DOC_TOOL_SCHEMAS + tm.ORDER_TOOL_SCHEMAS + [tm.REMEMBER_TOOL_SCHEMA]` 一行替换为上面这行。）

- [ ] **Step 3: 工具分派 elif**

在分派链(line ~771,`elif tu.name in tm.ORDER_TOOLS:` 之后)加一支:
```python
            elif tu.name in trem.REMINDER_TOOLS:
                out = trem.dispatch_reminder_tool(sb, room_id, expert_id,
                                                  tu.name, tu.input or {}, product=product)
```

- [ ] **Step 4: prompt 注入**

`ingest` 里(line ~898-901)外贸 prompt 拼装处,把:
```python
            orders = tm.load_active_orders(sb, room_id)
            system = system + tm.format_memory_block(frozen, cands) + tm.format_orders_for_prompt(orders)
```
改成:
```python
            orders = tm.load_active_orders(sb, room_id)
            reminders = trem.load_pending_reminders(sb, room_id)
            system = (system + tm.format_memory_block(frozen, cands)
                      + tm.format_orders_for_prompt(orders)
                      + trem.format_reminders_for_prompt(reminders))
```

- [ ] **Step 5: 语法 + 全单测**

Run:
```bash
cd worker && ~/.venv-c2g/bin/python -c "import ast; ast.parse(open('chat2go_worker.py').read()); print('ok')" \
  && ~/.venv-c2g/bin/python -m pytest -q
```
Expected: `ok` + 全部测试 passed(含原有回归)。

- [ ] **Step 6: Commit**

```bash
git add worker/chat2go_worker.py
git commit -m "feat(reminders): 催单工具接进外贸房 tool-use + prompt 注入"
```

---

### Task 6: Modal Cron 扫描器 + 派发层 + in_room 适配器

**Files:**
- Modify: `worker/chat2go_worker.py`(在 `ingest` 函数定义之后追加)

- [ ] **Step 1: 实现派发层 + in_room 适配器 + cron 扫描器**

在 `chat2go_worker.py` 末尾(`ingest` 之后)追加:
```python
def _deliver_in_room(sb, reminder: dict, message_text: str) -> None:
    """房间内留言适配器:往该提醒的房间写一条 AI 催单消息(主线程)。"""
    sb.table("messages").insert({
        "room_id": reminder["room_id"],
        "user_id": reminder["expert_id"],  # 沿用「AI 消息用大咖账号写入」惯例
        "role": "ai",
        "type": "markdown",
        "content": message_text,
        "channel": "main",
    }).execute()


def dispatch_reminder(sb, reminder: dict, message_text: str, channels: list[str]) -> None:
    """催单派发层(可插拔)。Phase 1 只实现 in_room;email/wechat/sms 为后续插槽。"""
    for ch in channels:
        if ch == "in_room":
            _deliver_in_room(sb, reminder, message_text)
        # elif ch == "email":  # Phase 2
        # elif ch in ("wechat", "sms"):  # Phase 3


@app.function(image=image, secrets=secrets, schedule=modal.Cron("0 0 * * *"), timeout=600)
def scan_reminders() -> dict:
    """每天 00:00 UTC(= 08:00 北京)扫描 pending 提醒,临近/逾期的主动催单。"""
    from datetime import date
    sb = _sb_client()
    rows = sb.table("tradego_reminders").select("*").eq("status", "pending").execute().data or []
    today = date.today()
    due = trem.select_due(rows, today)
    fired = 0
    for r in due:
        try:
            msg = trem.format_reminder_message(r, today)
            dispatch_reminder(sb, r, msg, channels=["in_room"])
            sb.table("tradego_reminders").update({
                "last_fired_on": today.isoformat(),
                "fire_count": (r.get("fire_count") or 0) + 1,
                "updated_at": tm._now_iso(),
            }).eq("id", r["id"]).execute()
            fired += 1
        except Exception as e:  # noqa: BLE001
            print(f"[reminders] dispatch failed for {r.get('id')}: {type(e).__name__}: {e}")
    print(f"[reminders] scanned {len(rows)} pending, fired {fired}")
    return {"scanned": len(rows), "fired": fired}
```

- [ ] **Step 2: 语法检查**

Run: `cd worker && ~/.venv-c2g/bin/python -c "import ast; ast.parse(open('chat2go_worker.py').read()); print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add worker/chat2go_worker.py
git commit -m "feat(reminders): Modal Cron 扫描器 + 派发层 + 房间内留言适配器"
```

---

### Task 7: 部署 + E2E 真实验证

**Files:** 无(部署 + 验证)

- [ ] **Step 1: 部署 worker**

Run: `cd worker && ~/.venv-c2g/bin/modal deploy chat2go_worker.py`
Expected: `✓ App deployed`,且输出含 `Created function scan_reminders`(新定时函数)+ mount `trade_reminders`。

- [ ] **Step 2: 插一条今天到期的 pending 提醒(用真实外贸房)**

外贸房 `room_id = 0ac15b5b-...`、`expert_id = 5dcec9b4-18a8-405b-837b-10bc27de114c`(见记忆 [[project_tradego_memory_ceiling_p1]];实现时用 MCP `execute_sql` 查确认当前值)。MCP `execute_sql`:
```sql
insert into tradego_reminders (room_id, expert_id, kind, note, due_date, lead_days)
values ('<外贸房 room_id>', '<expert_id>', '尾款', '催 E2E 测试客户尾款 $1000', current_date, 2)
returning id;
```

- [ ] **Step 3: 手动触发扫描器**

Run: `cd worker && ~/.venv-c2g/bin/modal run chat2go_worker.py::scan_reminders`
Expected: 日志 `[reminders] scanned N pending, fired ≥1`,返回 `{'scanned': N, 'fired': ...}`。

- [ ] **Step 4: 验催单消息已落房间 + 去重字段更新**

MCP `execute_sql`:
```sql
select content, role, type from messages
where room_id = '<外贸房 room_id>' and role = 'ai' and content like '🔔%'
order by created_at desc limit 1;
select status, last_fired_on, fire_count from tradego_reminders
where note = '催 E2E 测试客户尾款 $1000';
```
Expected: 出现 🔔 开头的 markdown AI 催单消息;提醒 `last_fired_on = 今天`、`fire_count = 1`。

- [ ] **Step 5: 验去重(同日再触发不重复发)**

Run: `cd worker && ~/.venv-c2g/bin/modal run chat2go_worker.py::scan_reminders`
再查 messages 🔔 数量与 `fire_count`:
```sql
select count(*) from messages where room_id='<外贸房 room_id>' and content like '🔔 催单提醒:尾款 —— 催 E2E 测试客户尾款%';
select fire_count from tradego_reminders where note = '催 E2E 测试客户尾款 $1000';
```
Expected: 🔔 该条数量仍为 1,`fire_count` 仍为 1(今天已发,去重生效)。

- [ ] **Step 6: 清理测试数据**

MCP `execute_sql`:
```sql
delete from tradego_reminders where note = '催 E2E 测试客户尾款 $1000';
delete from messages where room_id='<外贸房 room_id>' and content like '🔔 催单提醒:尾款 —— 催 E2E 测试客户尾款%';
```

- [ ] **Step 7: (可选)AI 端真机验**

在外贸房发:「ACME 这单 6 月 10 号要付尾款 5000 美金,记得提醒我」→ 验证 AI 调 `set_reminder` 落库(查 tradego_reminders 新行)。再发「ACME 尾款收到了」→ 验证 `complete_reminder` 把它标 done。

---

## Self-Review

**1. Spec coverage:**
- ① 数据模型 `tradego_reminders` → Task 1 ✓
- ② AI 记提醒(set_reminder/complete_reminder)+ 注入 prompt → Task 4(工具)+ Task 3(注入)+ Task 5(接线)✓
- ③ 定时扫描器 Modal Cron → Task 6 ✓
- ④ 催单规则(提前 lead_days / 逾期 / 每天去重)→ Task 2 `select_due` ✓
- ⑤ 派发层 dispatch + in_room 适配器 → Task 6 ✓
- ⑥ 测试(纯函数单测 + E2E)→ Task 2/3/4 单测 + Task 7 E2E ✓
- 验收标准 1-5 → 全部有对应 Task ✓

**2. Placeholder scan:** 无 TBD/TODO;每个代码步骤都给了完整代码;E2E 里的 `<外贸房 room_id>`/`<expert_id>` 是运行时真实值(已给出已知值 + 让实现者用 MCP 确认),非代码占位。

**3. Type consistency:**
- `select_due(rows, today: date)` / `format_reminder_message(r, today: date)` / `format_reminders_for_prompt(rows)` / `dispatch_reminder_tool(sb, room_id, expert_id, name, tool_input, product)` / `load_pending_reminders(sb, room_id)` —— 签名在 Task 2/3/4 定义,Task 5/6 调用一致。
- `dispatch_reminder(sb, reminder, message_text, channels)` / `_deliver_in_room(sb, reminder, message_text)`(Task 6)调用一致。
- 表/列名(`tradego_reminders` 的 status/due_date/last_fired_on/fire_count/lead_days)在 Task 1 建、Task 2/4/6 用,一致。
- `REMINDER_TOOL_SCHEMAS` / `REMINDER_TOOLS`(Task 4 定义)在 Task 5 引用,一致。
