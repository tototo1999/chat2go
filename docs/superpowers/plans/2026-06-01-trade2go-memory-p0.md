# Trade2GO 记忆系统 P0 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 Trade2GO(外贸跟单)落地记忆系统最小闭环:结构化订单状态机 + 冻结规则纯文本注入 + tradego 直连 Anthropic 路由,跑通"AI 推进订单 / 遵守固化口径"的真实体验。

**Architecture:** 共用的 `chat2go-worker`(Modal)里,对 `industry='外贸跟单'` 的房:① 从新 `tradego_orders` 表(双时序)读活跃订单、② 从新 `tradego_memory_rules` 表读冻结规则,都注入 system prompt;挂 `update_order_status`/`query_orders` 两个工具进既有 tool-use 循环;client 强制直连 Anthropic(绕 OpenRouter,为 P1 的 memory tool 铺路)。纯逻辑(状态迁移校验/双时序当前态/prompt 格式化)抽到 `worker/trade_memory.py` 可本地单测,DB I/O 是薄封装。

**Tech Stack:** Python 3.11 · Modal · Supabase(Postgres,`supabase-py`)· Anthropic SDK · unittest

---

## 文件结构

| 文件 | 职责 | 新建/修改 |
|---|---|---|
| `supabase/migrations/20260601120000_tradego_memory_p0.sql` | `tradego_orders`(enum+双时序+RLS)+ `tradego_memory_rules`(冻结规则+RLS)+ 种子规则 | 新建 |
| `worker/trade_memory.py` | 纯逻辑(状态迁移/当前态/格式化)+ 订单工具 schema + DB 薄封装 + dispatch | 新建 |
| `worker/test_trade_memory.py` | 纯逻辑单测 | 新建 |
| `worker/chat2go_worker.py` | `_anthropic_client(force_direct)` · `DIRECT_MODEL` · `_room_meta` · ingest 注入规则/订单 + 强制直连 · `_run_completion` 挂订单工具+dispatch | 修改 |

测试现实:本地 `worker/.venv` 无 `supabase/postgrest`,DB I/O 不可本地单测 → 纯逻辑放 `trade_memory.py` 单测,DB 链路靠 Task 6 部署后真实 E2E 验。

---

## Task 1: DB migration —— 订单表 + 规则表 + 种子

**Files:**
- Create: `supabase/migrations/20260601120000_tradego_memory_p0.sql`

- [ ] **Step 1: 写 migration**

```sql
-- Trade2GO 记忆 P0:订单状态机(双时序)+ 冻结规则表
-- 仅服务 tradego(product='tradego');worker 用 service-role 读写,RLS 给大咖自己读。

-- 订单状态枚举(P0 默认 6 段,后续按真实跟单流程可加值)
do $$ begin
  create type tradego_order_status as enum
    ('报价','待PI','已付定金','生产中','已发货','收尾');
exception when duplicate_object then null; end $$;

create table if not exists tradego_orders (
  id uuid primary key default gen_random_uuid(),
  room_id uuid not null references rooms(id) on delete cascade,
  expert_id uuid not null,
  customer text,
  product_desc text,
  amount numeric,
  currency text,
  status tradego_order_status not null,
  valid_from timestamptz not null default now(),
  valid_to   timestamptz,                 -- 双时序:当前态 = valid_to is null
  source_message_id uuid,
  created_at timestamptz not null default now()
);
create index if not exists idx_tradego_orders_room_active
  on tradego_orders(room_id) where valid_to is null;

create table if not exists tradego_memory_rules (
  id uuid primary key default gen_random_uuid(),
  expert_id uuid not null,
  product text not null default 'tradego',
  content text not null,
  status text not null default 'frozen',   -- 'frozen' | 'candidate'(P0 只用 frozen)
  version int not null default 1,
  source_message_id uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists idx_tradego_rules_lookup
  on tradego_memory_rules(expert_id, product, status);

alter table tradego_orders enable row level security;
alter table tradego_memory_rules enable row level security;

-- 大咖只读自己的(写入走 service-role,绕 RLS)
create policy tradego_orders_read_own on tradego_orders
  for select to authenticated using (expert_id = auth.uid());
create policy tradego_rules_read_own on tradego_memory_rules
  for select to authenticated using (expert_id = auth.uid());

-- 种子:给外贸大咖(388388, expert_id=5dcec9b4-18a8-405b-837b-10bc27de114c)种两条冻结规则,验注入
insert into tradego_memory_rules (expert_id, product, content, status, version) values
  ('5dcec9b4-18a8-405b-837b-10bc27de114c','tradego',
   '默认报价币种用 USD;客户没指定 Incoterm 时默认按 FOB 深圳报。','frozen',1),
  ('5dcec9b4-18a8-405b-837b-10bc27de114c','tradego',
   '报价默认在成本价基础上加 12% 利润;低于此需大咖确认。','frozen',1);
```

- [ ] **Step 2: 应用 migration(Supabase MCP)**

用 Supabase MCP `apply_migration`(name=`tradego_memory_p0`,query=上面 SQL)。预期:无错误返回。

- [ ] **Step 3: 验证表与种子**

用 MCP `execute_sql`:`select status, content, version from tradego_memory_rules where expert_id='5dcec9b4-18a8-405b-837b-10bc27de114c';`
预期:2 行 frozen 规则。再 `select count(*) from tradego_orders;` 预期:0。

- [ ] **Step 4: Commit**

```bash
git add supabase/migrations/20260601120000_tradego_memory_p0.sql
git commit -m "feat(tradego-memory): P0 migration — 订单状态机+冻结规则表+种子"
```

---

## Task 2: `trade_memory.py` 纯逻辑 + 单测(TDD)

**Files:**
- Create: `worker/trade_memory.py`
- Test: `worker/test_trade_memory.py`

- [ ] **Step 1: 写失败测试**

```python
# worker/test_trade_memory.py
"""Trade2GO 记忆 P0 纯逻辑单测(不碰 DB)。run: python3 -m unittest test_trade_memory -v"""
import unittest
import trade_memory as tm


class TestTransition(unittest.TestCase):
    def test_new_order_any_status_ok(self):
        self.assertTrue(tm.is_valid_transition(None, "报价"))
        self.assertTrue(tm.is_valid_transition(None, "已发货"))  # 可补录

    def test_forward_ok_including_jump(self):
        self.assertTrue(tm.is_valid_transition("报价", "待PI"))
        self.assertTrue(tm.is_valid_transition("报价", "已发货"))  # 跳级允许

    def test_backward_rejected(self):
        self.assertFalse(tm.is_valid_transition("已发货", "报价"))

    def test_same_status_rejected_as_noop(self):
        self.assertFalse(tm.is_valid_transition("生产中", "生产中"))

    def test_unknown_status_rejected(self):
        self.assertFalse(tm.is_valid_transition("报价", "天马行空"))
        self.assertFalse(tm.is_valid_transition("瞎写", "报价"))


class TestBitemporal(unittest.TestCase):
    def test_current_orders_filters_closed(self):
        rows = [
            {"customer": "A", "status": "报价", "valid_to": "2026-06-01T00:00:00+00"},
            {"customer": "A", "status": "待PI", "valid_to": None},
            {"customer": "B", "status": "生产中", "valid_to": None},
        ]
        cur = tm.current_orders_from_rows(rows)
        self.assertEqual({(o["customer"], o["status"]) for o in cur},
                         {("A", "待PI"), ("B", "生产中")})

    def test_empty(self):
        self.assertEqual(tm.current_orders_from_rows(None), [])


class TestFormat(unittest.TestCase):
    def test_rules_prompt(self):
        out = tm.format_rules_for_prompt([{"content": "默认 USD", "version": 2}])
        self.assertIn("默认 USD", out)
        self.assertIn("v2", out)
        self.assertIn("冻结", out)

    def test_rules_empty_returns_blank(self):
        self.assertEqual(tm.format_rules_for_prompt([]), "")

    def test_orders_prompt(self):
        out = tm.format_orders_for_prompt([
            {"customer": "印度客户", "product_desc": "LED灯", "amount": 40000,
             "currency": "USD", "status": "已发货"}])
        self.assertIn("已发货", out)
        self.assertIn("印度客户", out)
        self.assertIn("40000", out)

    def test_orders_empty_returns_blank(self):
        self.assertEqual(tm.format_orders_for_prompt([]), "")


class TestToolSchemas(unittest.TestCase):
    def test_order_tools_shape(self):
        names = {t["name"] for t in tm.ORDER_TOOL_SCHEMAS}
        self.assertEqual(names, {"update_order_status", "query_orders"})
        upd = next(t for t in tm.ORDER_TOOL_SCHEMAS if t["name"] == "update_order_status")
        self.assertEqual(set(upd["input_schema"]["required"]), {"customer", "new_status"})
        self.assertEqual(upd["input_schema"]["properties"]["new_status"]["enum"], tm.ORDER_STATUSES)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd worker && .venv/bin/python -m unittest test_trade_memory -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'trade_memory'`

- [ ] **Step 3: 写实现(纯逻辑部分)**

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd worker && .venv/bin/python -m unittest test_trade_memory -v`
Expected: PASS(全部用例)

- [ ] **Step 5: Commit**

```bash
git add worker/trade_memory.py worker/test_trade_memory.py
git commit -m "feat(tradego-memory): P0 纯逻辑 — 状态迁移/双时序/prompt 格式化 + 订单工具 schema + 单测"
```

---

## Task 3: `trade_memory.py` DB 薄封装 + dispatch

**Files:**
- Modify: `worker/trade_memory.py`(追加到文件末尾)

- [ ] **Step 1: 追加 DB 封装与 dispatch**

```python
# ── DB 薄封装(worker 传 service-role sb;本地不单测,Task 6 真实验)──────────────
from datetime import datetime, timezone

MEMORY_BUCKET_RULES_LIMIT = 40


def _now_iso() -> str:
    """关闭旧订单行用的 UTC ISO 时间戳(supabase-py 不能传 SQL now(),需 Python 算)。"""
    return datetime.now(timezone.utc).isoformat()


def load_frozen_rules(sb, expert_id: str, product: str = "tradego") -> list[dict]:
    """读该大咖该产品的冻结规则,版本新→旧。"""
    if not expert_id:
        return []
    return sb.table("tradego_memory_rules") \
        .select("content, version") \
        .eq("expert_id", expert_id).eq("product", product).eq("status", "frozen") \
        .order("version", desc=True).limit(MEMORY_BUCKET_RULES_LIMIT) \
        .execute().data or []


def load_active_orders(sb, room_id: str) -> list[dict]:
    """读本房订单全部行,Python 侧过滤当前态(避开 postgrest null 过滤歧义)。"""
    rows = sb.table("tradego_orders") \
        .select("customer, product_desc, amount, currency, status, valid_to") \
        .eq("room_id", room_id).execute().data or []
    return current_orders_from_rows(rows)


def dispatch_order_tool(sb, room_id: str, expert_id: str,
                        name: str, tool_input: dict, source_message_id: str | None = None) -> dict:
    """执行订单工具,返回给 LLM 的 tool_result dict。"""
    ti = tool_input or {}
    if name == "query_orders":
        orders = load_active_orders(sb, room_id)
        cust = (ti.get("customer") or "").strip()
        if cust:
            orders = [o for o in orders if (o.get("customer") or "") == cust]
        return {"ok": True, "orders": orders, "count": len(orders)}

    if name == "update_order_status":
        customer = (ti.get("customer") or "").strip()
        new_status = (ti.get("new_status") or "").strip()
        if not customer or not new_status:
            return {"ok": False, "error": "缺 customer 或 new_status"}
        # 取该客户当前活跃订单
        active = [o for o in load_active_orders(sb, room_id)
                  if (o.get("customer") or "") == customer]
        old_status = active[0]["status"] if active else None
        if not is_valid_transition(old_status, new_status):
            return {"ok": False,
                    "error": f"非法状态变更:{old_status or '(新建)'} → {new_status}。"
                             f"只能前进,合法状态:{ORDER_STATUSES}"}
        # 关闭旧行(若有)
        if active:
            sb.table("tradego_orders").update({"valid_to": _now_iso()}) \
                .eq("room_id", room_id).eq("customer", customer).is_("valid_to", "null").execute()
        # 插新行(继承可选字段,新值覆盖)
        prev = active[0] if active else {}
        row = {
            "room_id": room_id, "expert_id": expert_id, "customer": customer,
            "status": new_status,
            "product_desc": ti.get("product_desc") or prev.get("product_desc"),
            "amount": ti.get("amount") if ti.get("amount") is not None else prev.get("amount"),
            "currency": ti.get("currency") or prev.get("currency"),
            "source_message_id": source_message_id,
        }
        sb.table("tradego_orders").insert(row).execute()
        return {"ok": True, "customer": customer,
                "from": old_status or "(新建)", "to": new_status}

    return {"ok": False, "error": f"未知订单工具 {name}"}
```

- [ ] **Step 2: import 自检(确认无语法错)**

Run: `cd worker && .venv/bin/python -c "import trade_memory; print('ok', len(trade_memory.ORDER_TOOL_SCHEMAS))"`
Expected: `ok 2`

- [ ] **Step 3: 跑既有单测确认没碰坏纯逻辑**

Run: `cd worker && .venv/bin/python -m unittest test_trade_memory -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add worker/trade_memory.py
git commit -m "feat(tradego-memory): P0 DB 封装 + 订单工具 dispatch(双时序更新/状态校验)"
```

---

## Task 4: worker 路由 —— 直连开关 + 直连模型名 + 房间元数据

**Files:**
- Modify: `worker/chat2go_worker.py`(`_anthropic_client` 第 210-217 行;`DIRECT_MODEL` 加在 `DEFAULT_MODEL` 附近;`_room_meta` 加在 `_sb_client` 之后)

- [ ] **Step 1: 改 `_anthropic_client` 支持强制直连**

把现有(210-217):
```python
def _anthropic_client():
    from anthropic import Anthropic
    or_key = os.environ.get("OPENROUTER_API_KEY")
    if or_key:
        return Anthropic(api_key=or_key, base_url="https://openrouter.ai/api")
    return Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
```
改成:
```python
def _anthropic_client(force_direct: bool = False):
    from anthropic import Anthropic
    # force_direct: tradego 记忆需直连官方 Anthropic(为 memory tool 等 beta 铺路,
    # OpenRouter 不透传 context-management beta)。其它产品仍可走 OpenRouter。
    or_key = os.environ.get("OPENROUTER_API_KEY")
    if or_key and not force_direct:
        return Anthropic(api_key=or_key, base_url="https://openrouter.ai/api")
    return Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
```

- [ ] **Step 2: 加直连模型名常量(在 `DEFAULT_MODEL` 定义之后,约 226 行)**

```python
# tradego 强制直连时用横杠名(忽略 OpenRouter 点号名)
DIRECT_MODEL = "claude-sonnet-4-6"
```

- [ ] **Step 3: 加 `_room_meta`(在 `_sb_client` 函数之后)**

```python
def _room_meta(sb, room_id: str) -> dict:
    """取房间 expert_id + product(记忆按大咖+产品隔离;payload 里没带)。"""
    try:
        row = sb.table("rooms").select("expert_id, product").eq("id", room_id) \
            .maybe_single().execute()
        return (row.data or {}) if row else {}
    except Exception:
        return {}
```

- [ ] **Step 4: import 自检**

Run: `cd worker && .venv/bin/python -c "import chat2go_worker as w; print(w.DIRECT_MODEL); print(callable(w._room_meta))"`
Expected: `claude-sonnet-4-6` 然后 `True`(注:需 fake modal;若报 modal 缺失,用 `test_worker_toolloop` 的 `_install_fake_modal` 已注入路径——改跑下一步整体测试代替)

- [ ] **Step 5: 跑既有 worker 单测确认没碰坏**

Run: `cd worker && .venv/bin/python -m unittest test_worker_toolloop -v 2>&1 | tail -5`
Expected: 仅既有 2 个 make_excel/make_pdf 因本地缺库 FAIL,其余 PASS(无新增失败)

- [ ] **Step 6: Commit**

```bash
git add worker/chat2go_worker.py
git commit -m "feat(tradego-memory): worker 路由 — _anthropic_client(force_direct) + DIRECT_MODEL + _room_meta"
```

---

## Task 5: worker ingest 接线 —— 注入规则/订单 + 强制直连 + 挂订单工具

**Files:**
- Modify: `worker/chat2go_worker.py`(顶部 import 区加 `import trade_memory as tm`;`ingest` 的 system/client/model 组装段;`_run_completion` 签名与 trade 工具+dispatch)

- [ ] **Step 1: 顶部加 import(在 `import doc_gen as dg` 之后)**

```python
import trade_memory as tm   # 订单状态机 + 冻结规则(记忆 P0)
```
并在 image 的 `.add_local_python_source("doc_gen")` 之后加一行:
```python
    .add_local_python_source("trade_memory")
```

- [ ] **Step 2: 改 ingest 的 system/client/model 组装**

定位 ingest 里这段(现状):
```python
        base_system = _resolve_system_prompt(industry, room_system_prompt)
        mem_rows = _load_memories(sb, room_id)
        system = base_system + _format_memories(mem_rows)

        is_trade = _is_trade_room(industry)
        if is_trade:
            system = system + TRADE_ACCOUNTING_GUIDE

        cli = _anthropic_client()
        out_text, doc_attachments = _run_completion(cli, sb, model, system, messages, is_trade)
```
改成:
```python
        base_system = _resolve_system_prompt(industry, room_system_prompt)
        mem_rows = _load_memories(sb, room_id)
        system = base_system + _format_memories(mem_rows)

        is_trade = _is_trade_room(industry)
        meta = _room_meta(sb, room_id) if is_trade else {}
        expert_id = meta.get("expert_id") or ""
        product = meta.get("product") or "tradego"
        if is_trade:
            system = system + TRADE_ACCOUNTING_GUIDE
            # 记忆 P0:注入冻结规则(权威)+ 当前活跃订单
            rules = tm.load_frozen_rules(sb, expert_id, product)
            orders = tm.load_active_orders(sb, room_id)
            system = system + tm.format_rules_for_prompt(rules) + tm.format_orders_for_prompt(orders)
            cli = _anthropic_client(force_direct=True)   # 直连 Anthropic
            model = DIRECT_MODEL
        else:
            cli = _anthropic_client()

        out_text, doc_attachments = _run_completion(
            cli, sb, model, system, messages, is_trade,
            room_id=room_id, expert_id=expert_id,
            trigger_message_id=trigger_message_id)
```

- [ ] **Step 3: 改 `_run_completion` 签名 + trade 工具列表 + dispatch**

定位 `_run_completion` 定义与 trade 分支。把签名:
```python
def _run_completion(cli, sb, model, system, messages, is_trade):
```
改成:
```python
def _run_completion(cli, sb, model, system, messages, is_trade,
                    room_id=None, expert_id=None, trigger_message_id=None):
```
把 trade 工具组装(现状 `tools = ta.TOOL_SCHEMAS + dg.DOC_TOOL_SCHEMAS`)改成:
```python
    tools = ta.TOOL_SCHEMAS + dg.DOC_TOOL_SCHEMAS + tm.ORDER_TOOL_SCHEMAS
```
在工具循环的 dispatch 分支里(现状:`if tu.name in dg.DOC_BUILDERS: ... else: out = ta.dispatch(...)`),改成三分支:
```python
                if tu.name in dg.DOC_BUILDERS:
                    try:
                        att, out = _make_doc_and_upload(sb, tu.name, tu.input or {})
                        attachments.append(att)
                    except Exception as e:  # noqa: BLE001
                        out = {"error": f"文件生成/上传失败: {type(e).__name__}: {e}"}
                elif tu.name in tm.ORDER_TOOLS:
                    out = tm.dispatch_order_tool(sb, room_id, expert_id, tu.name,
                                                 tu.input or {}, source_message_id=trigger_message_id)
                else:
                    out = ta.dispatch(tu.name, tu.input or {})
```

- [ ] **Step 4: import 自检(用 fake modal)**

Run: `cd worker && .venv/bin/python -c "import test_worker_toolloop"` (该测试文件顶部注入 fake modal 并 import worker)
Expected: 无报错(import 成功)

- [ ] **Step 5: 跑全部 worker 单测确认没碰坏**

Run: `cd worker && .venv/bin/python -m unittest test_worker_toolloop test_trade_accounting test_trade_memory 2>&1 | tail -6`
Expected: 仅既有 2 个 make_excel/make_pdf 本地缺库 FAIL,无新增失败

- [ ] **Step 6: Commit**

```bash
git add worker/chat2go_worker.py
git commit -m "feat(tradego-memory): ingest 接线 — 注入冻结规则/活跃订单 + 强制直连 + 挂订单工具"
```

---

## Task 6: 部署 + 真实 Chrome 端到端验证

**Files:** 无(部署 + 验证)

- [ ] **Step 1: 部署 worker**

Run: `cd worker && ~/.venv-c2g/bin/modal deploy chat2go_worker.py 2>&1 | tail -5`
Expected: `✓ App deployed`

- [ ] **Step 2: 验证「规则注入被遵守」(真实 Chrome,按 feedback_visual_test_real_chrome)**

在 `http://chat2go.xyz/chat.html`(硬刷)tradego 房发:`给客户报个价,LED灯 成本5元 1000个,没说币种和条款`
预期 AI 回复体现种子规则:**USD 计价 + FOB 深圳 + 加 12% 利润**(即单价≈$5.6×汇率口径或按其口径,关键是体现"USD/FOB/12%"而非自由发挥)。

- [ ] **Step 3: 验证「订单状态机」**

续发:`这个客户叫孟买之星,先记一下报价了`
→ 预期 AI 调 `update_order_status(customer=孟买之星, new_status=报价)`。
用 MCP `execute_sql`:`select customer,status,valid_to from tradego_orders where room_id='0ac15b5b-e9ab-4737-873e-9ab9651f0f25' order by created_at;`
预期:1 行(孟买之星 / 报价 / valid_to=null)。

- [ ] **Step 4: 验证「状态推进 + 双时序」**

续发:`孟买之星付定金了`
→ 预期调 `update_order_status(孟买之星, 已付定金)`。
再查同 SQL:预期 2 行 —— 旧「报价」行 valid_to 非空,新「已付定金」行 valid_to=null。
再发 `孟买之星现在啥进度`→ 预期 AI 调 query_orders 答「已付定金」。

- [ ] **Step 5: 验证「直连 Anthropic 生效」**

Run: `cd /tmp && ( ~/.venv-c2g/bin/modal app logs chat2go-worker > /tmp/c2glog.txt 2>&1 ) & sleep 12; kill %1 2>/dev/null; grep -i "provider=" /tmp/c2glog.txt | tail -3`
预期:tradego 请求日志 `provider=direct`(或无 openrouter 字样);若 worker 有打 provider 日志则确认非 openrouter。(若未打该日志,跳过此步,以 Step 2-4 行为正确为准。)

- [ ] **Step 6: 清理测试数据 + 收尾**

用 MCP `execute_sql` 删测试订单:`delete from tradego_orders where customer='孟买之星';`
确认 tradego 房测试消息按需清理(参既有 SOP)。

- [ ] **Step 7: 最终 commit(若验证中有微调)**

```bash
git add -A worker/
git commit -m "test(tradego-memory): P0 端到端验证通过(规则注入+订单状态机+双时序+直连)"
git push origin main
```

---

## 完成定义(P0)
- tradego 房:冻结规则被注入且被 AI 遵守;订单可新建/前进/查询,双时序留痕;tradego 走直连 Anthropic;其它 3 产品行为不变;worker 单测除既有本地缺库 2 项外全绿。
- 下一步(独立计划):P1(memory tool 后端 + 候选写入 + 大咖确认冻结)。
