# Trade2GO Trace 采集 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development(推荐)或 superpowers:executing-plans 逐任务实现。步骤用 `- [ ]` 勾选。

**Goal:** 把每条真实外贸房请求结构化落库成可回放的 trace,作为将来换模型 A/B 的语料。

**Architecture:** 新建 Supabase 表 `trade_eval_traces`;worker 在 `_run_completion` 里收集每次模型调用的 usage + tool-use 步骤,在 `ingest` 末尾组装成一行 trace 落库。**best-effort:落库失败绝不影响给用户的回复。** 仅外贸房(`is_trade`)采集。

**Tech Stack:** Modal worker(`worker/chat2go_worker.py`)、新模块 `worker/trade_trace.py`、Supabase(`apply_migration`)、unittest(fake modal + fake anthropic,跑 `~/.venv-c2g/bin/python -m unittest`)。

**关联 spec:** `docs/superpowers/specs/2026-06-01-trade2go-记忆天花板-design.md` §7.1。

---

## 文件结构
- 新建 `worker/trade_trace.py` — 纯函数 `build_trace_row(...)`(组装 dict)+ `persist_trace(sb, row)`(落库,best-effort)。
- 改 `worker/chat2go_worker.py` — `_run_completion` 收集 `trace_steps`;`ingest` 组装 + 落库。
- 新建 `worker/test_trade_trace.py` — 纯逻辑单测。
- Supabase 迁移:`trade_eval_traces` 表 + RLS(仅 service-role)。

---

## Task 1: 建 `trade_eval_traces` 表

**Files:** Supabase 迁移(经 Supabase MCP `apply_migration`,name=`create_trade_eval_traces`)。

- [ ] **Step 1: preview-then-go,执行迁移 SQL**

```sql
create table if not exists public.trade_eval_traces (
  id uuid primary key default gen_random_uuid(),
  room_id uuid not null,
  trigger_message_id uuid,
  expert_id text,
  product text default 'tradego',
  model text,
  system_prompt text,          -- 输入快照:当时注入的 system
  input_messages jsonb,        -- 发给模型的 history
  tool_steps jsonb,            -- 每次调用的 tool-use 序列 + 结果 + usage
  output_text text,
  usage jsonb,                 -- 汇总 in/out/cache
  created_at timestamptz not null default now()
);
create index if not exists idx_trade_eval_traces_room on public.trade_eval_traces(room_id, created_at desc);
alter table public.trade_eval_traces enable row level security;
-- 不建任何 policy = 默认拒绝;worker 用 service_role 绕 RLS 写入,其他角色读不到(内部评测语料,含真实业务数据)
```

- [ ] **Step 2: 核验表存在**

Run(Supabase MCP execute_sql):`select count(*) from public.trade_eval_traces;`
Expected:返回 `0`,无错误。

---

## Task 2: `build_trace_row` 纯函数 + 测试

**Files:**
- Create: `worker/trade_trace.py`
- Test: `worker/test_trade_trace.py`

- [ ] **Step 1: 写失败测试**

```python
# worker/test_trade_trace.py
import unittest
import trade_trace as tt


class TestBuildTraceRow(unittest.TestCase):
    def test_assembles_full_row(self):
        steps = [
            {"call": 0, "text": "", "tool_uses": [{"name": "query_orders", "input": {"room": "r1"}}],
             "tool_results": [{"name": "query_orders", "output": {"orders": []}}],
             "usage": {"input_tokens": 100, "output_tokens": 10,
                       "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}},
            {"call": 1, "text": "已查到", "tool_uses": [],
             "tool_results": [], "usage": {"input_tokens": 120, "output_tokens": 8,
                                           "cache_creation_input_tokens": 0, "cache_read_input_tokens": 100}},
        ]
        row = tt.build_trace_row(
            room_id="r1", trigger_message_id="m1", expert_id="e1", product="tradego",
            model="claude-sonnet-4-6", system="SYS", input_messages=[{"role": "user", "content": "hi"}],
            steps=steps, output_text="已查到",
        )
        self.assertEqual(row["room_id"], "r1")
        self.assertEqual(row["model"], "claude-sonnet-4-6")
        self.assertEqual(row["output_text"], "已查到")
        self.assertEqual(len(row["tool_steps"]), 2)
        # usage 汇总两次调用
        self.assertEqual(row["usage"]["input_tokens"], 220)
        self.assertEqual(row["usage"]["output_tokens"], 18)
        self.assertEqual(row["usage"]["cache_read_input_tokens"], 100)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run:`cd worker && ~/.venv-c2g/bin/python -m unittest test_trade_trace -v`
Expected:FAIL（`ModuleNotFoundError: No module named 'trade_trace'`）。

- [ ] **Step 3: 写实现**

```python
# worker/trade_trace.py
"""Trace 采集:把一次真实请求组装成可回放的 trace 行,落 Supabase。
纯函数 build_trace_row 可单测;persist_trace best-effort 落库,失败不抛。"""
from __future__ import annotations


def _sum_usage(steps: list[dict]) -> dict:
    keys = ("input_tokens", "output_tokens",
            "cache_creation_input_tokens", "cache_read_input_tokens")
    total = {k: 0 for k in keys}
    for s in steps:
        u = s.get("usage") or {}
        for k in keys:
            total[k] += int(u.get(k) or 0)
    return total


def build_trace_row(*, room_id, trigger_message_id, expert_id, product,
                    model, system, input_messages, steps, output_text) -> dict:
    return {
        "room_id": room_id,
        "trigger_message_id": trigger_message_id,
        "expert_id": expert_id or None,
        "product": product or "tradego",
        "model": model,
        "system_prompt": system,
        "input_messages": input_messages,
        "tool_steps": steps,
        "output_text": output_text,
        "usage": _sum_usage(steps),
    }


def persist_trace(sb, row: dict) -> None:
    """best-effort 落库;任何异常吞掉,绝不影响主回复。"""
    try:
        sb.table("trade_eval_traces").insert(row).execute()
    except Exception as e:  # noqa: BLE001
        print(f"[trace] persist failed (ignored): {type(e).__name__}: {e}")
```

- [ ] **Step 4: 跑测试确认通过**

Run:`cd worker && ~/.venv-c2g/bin/python -m unittest test_trade_trace -v`
Expected:PASS。

- [ ] **Step 5: 提交**

```bash
git add worker/trade_trace.py worker/test_trade_trace.py
git commit -m "feat(trace): build_trace_row + persist_trace(best-effort) + 单测"
```

---

## Task 3: `_run_completion` 收集 trace_steps

**Files:** Modify `worker/chat2go_worker.py`（`_run_completion`,约 680-751 行）

- [ ] **Step 1: 加失败测试(扩 test_worker_toolloop 模式)**

```python
# worker/test_trade_trace.py — 追加
import sys, types, os
os.environ.setdefault("SUPABASE_URL", "https://qjnagbzqhoansixqharb.supabase.co")
# 复用 test_worker_toolloop 的 fake modal 安装
import test_worker_toolloop as tw  # noqa: E402  (其顶部已 _install_fake_modal)
w = tw.w


class TestRunCompletionCollectsSteps(unittest.TestCase):
    def test_steps_capture_usage_and_tooluse(self):
        # 假 client:第1次返回 query_orders tool_use,第2次返回纯文本
        Block = tw._Block
        class _Usage:
            def __init__(s, i, o, cw=0, cr=0):
                s.input_tokens, s.output_tokens = i, o
                s.cache_creation_input_tokens, s.cache_read_input_tokens = cw, cr
        class _Resp:
            def __init__(s, content, usage): s.content, s.usage = content, usage
        class _Cli:
            def __init__(s): s.n = 0
            class messages:  # placeholder, replaced below
                pass
        cli = _Cli()
        responses = [
            _Resp([Block("tool_use", name="query_orders", input={"room": "r1"}, id="t1")], _Usage(100, 10)),
            _Resp([Block("text", text="已查到")], _Usage(120, 8, cr=100)),
        ]
        def _create(**kw):
            r = responses[cli.n]; cli.n += 1; return r
        cli.messages = types.SimpleNamespace(create=_create)

        steps = []
        out, atts = w._run_completion(
            cli, sb=_FakeSB(), model="claude-sonnet-4-6", system="SYS",
            messages=[{"role": "user", "content": "查订单"}], is_trade=True,
            room_id="r1", expert_id="e1", product="tradego", trace_steps=steps)
        self.assertEqual(out, "已查到")
        self.assertEqual(len(steps), 2)
        self.assertEqual(steps[0]["tool_uses"][0]["name"], "query_orders")
        self.assertEqual(steps[1]["usage"]["cache_read_input_tokens"], 100)


class _FakeSB:
    def table(self, *_): return self
    def insert(self, *_): return self
    def select(self, *_): return self
    def eq(self, *_): return self
    def execute(self): return types.SimpleNamespace(data=[])
```

> 注:`query_orders` 在 `_run_completion` 里会走 `tm.dispatch_order_tool`;测试的 `_FakeSB` 让它返回空,不报错即可。若该路径需要更多 sb 方法,按报错补 `_FakeSB` 的桩方法。

- [ ] **Step 2: 跑测试确认失败**

Run:`cd worker && ~/.venv-c2g/bin/python -m unittest test_trade_trace -v`
Expected:FAIL(`_run_completion() got an unexpected keyword argument 'trace_steps'`)。

- [ ] **Step 3: 改 `_run_completion` 收集 steps**

在签名加 `trace_steps: list | None = None`。在 trade 的 tool-use 循环里,每次 `cli.messages.create` 后:

```python
        resp = cli.messages.create(
            model=model, max_tokens=MAX_TOKENS, system=system_blocks,
            messages=convo, tools=tools,
        )
        u = getattr(resp, "usage", None)
        if u:
            print(f"[chat2go] usage in={u.input_tokens} ...")   # 已有
        # ★ 收集 trace 步骤
        if trace_steps is not None:
            trace_steps.append({
                "call": len(trace_steps),
                "text": _extract_text(resp),
                "tool_uses": [{"name": b.name, "input": b.input}
                              for b in resp.content if getattr(b, "type", None) == "tool_use"],
                "usage": {k: getattr(u, k, 0) for k in
                          ("input_tokens", "output_tokens",
                           "cache_creation_input_tokens", "cache_read_input_tokens")} if u else {},
            })
```

在收尾(用尽迭代)那次 create 之后也 append 一条同结构(`tool_uses` 为空)。非 trade 分支不动(trace 只采外贸房)。

- [ ] **Step 4: 跑测试确认通过**

Run:`cd worker && ~/.venv-c2g/bin/python -m unittest test_trade_trace test_worker_toolloop -v`
Expected:PASS(新测试通过,且不破坏原有 toolloop 测试)。

- [ ] **Step 5: 提交**

```bash
git add worker/chat2go_worker.py worker/test_trade_trace.py
git commit -m "feat(trace): _run_completion 收集 trace_steps(usage+tool_use)"
```

---

## Task 4: `ingest` 组装 + 落库

**Files:** Modify `worker/chat2go_worker.py`（`ingest`,约 808-887 行)

- [ ] **Step 1: 顶部 import**

```python
import trade_trace as ttrace
```
(与 `import trade_accounting as ta` 等并列;并确认 image 的 `add_local_python_source` 已含 `trade_trace`——见 Task 5。)

- [ ] **Step 2: ingest 里传 trace_steps + 落库**

`is_trade` 时建 `trace_steps=[]` 传入 `_run_completion`;拿到 `out_text` 后(在 `_update_placeholder` 之后),best-effort 落库:

```python
        trace_steps = [] if is_trade else None
        out_text, doc_attachments = _run_completion(
            cli, sb, model, system, messages, is_trade,
            room_id=room_id, expert_id=expert_id, product=product,
            trigger_message_id=trigger_message_id,
            image_map=image_map, img_choices=(img_choices if is_trade else None),
            trace_steps=trace_steps)

        msg_type = "markdown" if _looks_markdown(out_text) else "text"
        _update_placeholder(sb, placeholder_id, out_text, msg_type=msg_type,
                            attachments=doc_attachments or None)

        # ★ trace 落库(仅外贸房;best-effort,失败不影响已发出的回复)
        if is_trade:
            ttrace.persist_trace(sb, ttrace.build_trace_row(
                room_id=room_id, trigger_message_id=trigger_message_id,
                expert_id=expert_id, product=product, model=model,
                system=system, input_messages=messages,
                steps=trace_steps, output_text=out_text))
```

- [ ] **Step 3: 本地语法自检**

Run:`cd worker && OPENROUTER_API_KEY=x ~/.venv-c2g/bin/python -c "import ast; ast.parse(open('chat2go_worker.py').read()); print('OK')"`
Expected:`OK`。

- [ ] **Step 4: 提交**

```bash
git add worker/chat2go_worker.py
git commit -m "feat(trace): ingest 末尾 best-effort 落库 trade_eval_traces"
```

---

## Task 5: 部署 + 真机验证一条 trace 落库

**Files:** `worker/chat2go_worker.py`（image 的 `add_local_python_source`)

- [ ] **Step 1: 确认 image 打包了 trade_trace**

在 `image = modal.Image...add_local_python_source(...)` 列表里加 `"trade_trace"`(与 `trade_accounting`/`doc_gen`/`trade_memory` 并列)。Run `grep -n add_local_python_source worker/chat2go_worker.py` 确认。

- [ ] **Step 2: 部署**

Run:`cd worker && ~/.venv-c2g/bin/modal deploy chat2go_worker.py`
Expected:`✓ App deployed`。

- [ ] **Step 3: 真机触发一条(用测试房 iamarobot `38ebcd0e`,别碰小白实时房 `0ac15b5b`)**

在 iamarobot 外贸房发一条会动工具的消息(如"查一下当前订单"或一句报价)。等 ≥55s(worker 跑完)。

- [ ] **Step 4: 核验 trace 落库**

Run(Supabase MCP execute_sql):
```sql
select id, model, jsonb_array_length(tool_steps) as steps,
       usage->>'cache_read_input_tokens' as cache_r, length(output_text) as out_len, created_at
from trade_eval_traces where room_id='38ebcd0e-ec6c-43f8-9fca-ced8f0655892'
order by created_at desc limit 3;
```
Expected:至少 1 行,`steps>=1`、`out_len>0`、`created_at` 是刚才。

- [ ] **Step 5: 提交(若改了 image)**

```bash
git add worker/chat2go_worker.py
git commit -m "chore(trace): image 打包 trade_trace 模块"
```

---

## Self-Review 已过
- 覆盖 spec §7.1(表 + 输入快照 + tool-use 序列 + usage + best-effort + 仅外贸 + 隐私 RLS)✅
- 无占位:每步有真实 SQL/代码/命令/期望输出 ✅
- 类型一致:`build_trace_row` 字段 = 表列 = `_run_completion` 收集的 step 结构 ✅
- 边界:trace 只采外贸房;落库失败吞异常不影响回复 ✅
