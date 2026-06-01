"""测试 trade_trace: 纯函数 build_trace_row(usage 汇总 + 字段映射)
+ _run_completion 收集 trace_steps(Task 3)。
run: ~/.venv-c2g/bin/python -m unittest test_trade_trace -v
"""
import unittest

import trade_trace as ttrace

# 复用 test_worker_toolloop 的 fake modal + fake client(它已注入 sys.modules['modal'])
import test_worker_toolloop as tw  # noqa: E402

w = tw.w


class TestBuildTraceRow(unittest.TestCase):
    def _steps(self):
        return [
            {
                "call": 0,
                "text": "",
                "tool_uses": [{"name": "query_orders", "input": {"room_id": "r1"}}],
                "usage": {"input_tokens": 100, "output_tokens": 10},
            },
            {
                "call": 1,
                "text": "查到 1 单",
                "tool_uses": [],
                "usage": {"input_tokens": 120, "output_tokens": 8,
                          "cache_read_input_tokens": 100},
            },
        ]

    def test_usage_summed(self):
        row = ttrace.build_trace_row(
            room_id="r1", trigger_message_id="m1", expert_id="e1",
            product="tradego", model="claude-x", system="你是外贸助手",
            input_messages=[{"role": "user", "content": "查订单"}],
            steps=self._steps(), output_text="查到 1 单")
        usage = row["usage"]
        self.assertEqual(usage["input_tokens"], 220)
        self.assertEqual(usage["output_tokens"], 18)
        self.assertEqual(usage["cache_read_input_tokens"], 100)
        self.assertEqual(usage["cache_creation_input_tokens"], 0)

    def test_field_mapping(self):
        steps = self._steps()
        msgs = [{"role": "user", "content": "查订单"}]
        row = ttrace.build_trace_row(
            room_id="r1", trigger_message_id="m1", expert_id="e1",
            product="tradego", model="claude-x", system="你是外贸助手",
            input_messages=msgs, steps=steps, output_text="查到 1 单")
        self.assertEqual(row["room_id"], "r1")
        self.assertEqual(row["trigger_message_id"], "m1")
        self.assertEqual(row["expert_id"], "e1")
        self.assertEqual(row["product"], "tradego")
        self.assertEqual(row["model"], "claude-x")
        self.assertEqual(row["system_prompt"], "你是外贸助手")
        self.assertEqual(row["input_messages"], msgs)
        self.assertEqual(row["tool_steps"], steps)
        self.assertEqual(row["output_text"], "查到 1 单")

    def test_empty_expert_and_product_defaults(self):
        row = ttrace.build_trace_row(
            room_id="r1", trigger_message_id="m1", expert_id="",
            product="", model="m", system="s",
            input_messages=[], steps=[], output_text="x")
        self.assertIsNone(row["expert_id"])
        self.assertEqual(row["product"], "tradego")
        self.assertEqual(row["usage"]["input_tokens"], 0)


class _Usage:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class _RespU(tw._Resp):
    """带 usage 的响应(复用 tw._Resp 的 content)。"""
    def __init__(self, content, usage=None):
        super().__init__(content)
        self.usage = usage


class _TableQ:
    """空表查询链:任何 select/eq/...→自身,execute→data=[]。"""
    def __getattr__(self, _):
        return lambda *a, **k: self

    def execute(self):
        import types as _t
        return _t.SimpleNamespace(data=[])


class _SbWithTable(tw._FakeSb):
    def table(self, _name):
        return _TableQ()


class TestRunCompletionTrace(unittest.TestCase):
    def test_collects_trace_steps_with_usage_and_tool_use(self):
        # 第1次:AI 申请 query_orders(带 usage); 第2次:AI 给最终文字(带 usage)
        tool_block = tw._Block("tool_use", name="query_orders",
                               input={"room_id": "r1"}, id="t1")
        cli = tw._FakeCli([
            _RespU([tool_block],
                   usage=_Usage(input_tokens=100, output_tokens=10,
                                cache_creation_input_tokens=0,
                                cache_read_input_tokens=0)),
            _RespU([tw._Block("text", text="查到 0 单")],
                   usage=_Usage(input_tokens=120, output_tokens=8,
                                cache_creation_input_tokens=0,
                                cache_read_input_tokens=100)),
        ])
        steps: list = []
        out, atts = w._run_completion(
            cli, _SbWithTable(), "m", "sys",
            [{"role": "user", "content": "查订单"}], is_trade=True,
            room_id="r1", expert_id="e1", product="tradego",
            trigger_message_id="m1", trace_steps=steps)
        self.assertEqual(out, "查到 0 单")
        # 两次 create 都被收集
        self.assertEqual(len(steps), 2)
        # 第一步捕获 tool_use
        self.assertEqual(steps[0]["call"], 0)
        self.assertEqual(steps[0]["tool_uses"], [{"name": "query_orders",
                                                  "input": {"room_id": "r1"}}])
        self.assertEqual(steps[0]["usage"]["input_tokens"], 100)
        self.assertEqual(steps[0]["usage"]["output_tokens"], 10)
        # 第二步是纯文本收尾
        self.assertEqual(steps[1]["call"], 1)
        self.assertEqual(steps[1]["tool_uses"], [])
        self.assertEqual(steps[1]["text"], "查到 0 单")
        self.assertEqual(steps[1]["usage"]["cache_read_input_tokens"], 100)
        # 汇总正确
        usage = ttrace.build_trace_row(
            room_id="r1", trigger_message_id="m1", expert_id="e1",
            product="tradego", model="m", system="sys",
            input_messages=[], steps=steps, output_text=out)["usage"]
        self.assertEqual(usage["input_tokens"], 220)
        self.assertEqual(usage["output_tokens"], 18)
        self.assertEqual(usage["cache_read_input_tokens"], 100)

    def test_trace_steps_none_is_noop(self):
        # trace_steps=None(默认) → 不收集, 不崩
        cli = tw._FakeCli([tw._Resp([tw._Block("text", text="ok")])])
        out, atts = w._run_completion(
            cli, _SbWithTable(), "m", "sys",
            [{"role": "user", "content": "hi"}], is_trade=True,
            room_id="r1", expert_id="e1", product="tradego",
            trigger_message_id="m1")
        self.assertEqual(out, "ok")


if __name__ == "__main__":
    unittest.main()
