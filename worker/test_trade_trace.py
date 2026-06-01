"""测试 trade_trace: 纯函数 build_trace_row(usage 汇总 + 字段映射)
+ _run_completion 收集 trace_steps(Task 3)。
run: ~/.venv-c2g/bin/python -m unittest test_trade_trace -v
"""
import unittest

import trade_trace as ttrace


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


if __name__ == "__main__":
    unittest.main()
