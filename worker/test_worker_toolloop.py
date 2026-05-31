"""测试 worker tool-use 循环真实代码 (_run_completion / _is_trade_room)。
本机没装 modal → 注入 fake modal 到 sys.modules 后再 import chat2go_worker,
这样测的是 worker 里的真实循环逻辑, 不是副本。
run: python3 -m unittest test_worker_toolloop -v
"""
import sys
import types
import unittest


# ── fake modal: 让 chat2go_worker 顶层 import + 装饰器调用都能过 ───────────────
def _install_fake_modal():
    m = types.ModuleType("modal")

    class _Chain:
        def __getattr__(self, _):  # .pip_install().add_local_python_source() 链式返回自身
            return lambda *a, **k: self

    class _Image:
        @staticmethod
        def debian_slim(*a, **k):
            return _Chain()

    class _App:
        def __init__(self, *a, **k):
            pass

        def function(self, *a, **k):
            return lambda fn: fn  # 装饰器透传

    class _Secret:
        @staticmethod
        def from_name(*a, **k):
            return object()

    m.App = _App
    m.Image = _Image
    m.Secret = _Secret
    m.fastapi_endpoint = lambda *a, **k: (lambda fn: fn)
    sys.modules["modal"] = m


_install_fake_modal()
import chat2go_worker as w  # noqa: E402


# ── fake anthropic client + 响应块 ───────────────────────────────────────────
class _Block:
    def __init__(self, type, text=None, name=None, input=None, id=None):
        self.type = type
        self.text = text
        self.name = name
        self.input = input
        self.id = id


class _Resp:
    def __init__(self, content):
        self.content = content


class _FakeCli:
    """按脚本依次返回 responses; 记录每次 create 是否带 tools。"""
    def __init__(self, scripted):
        self._scripted = list(scripted)
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._scripted.pop(0)


class TestIsTradeRoom(unittest.TestCase):
    def test_aliases(self):
        self.assertTrue(w._is_trade_room("外贸"))
        self.assertTrue(w._is_trade_room("外贸跟单"))
        self.assertFalse(w._is_trade_room("英语口语"))
        self.assertFalse(w._is_trade_room("算命"))


class TestRunCompletion(unittest.TestCase):
    def test_non_trade_single_call_no_tools(self):
        cli = _FakeCli([_Resp([_Block("text", text="你好")])])
        out = w._run_completion(cli, "m", "sys", [{"role": "user", "content": "hi"}], is_trade=False)
        self.assertEqual(out, "你好")
        self.assertEqual(len(cli.calls), 1)
        self.assertNotIn("tools", cli.calls[0])  # 非外贸不挂工具

    def test_trade_calls_tool_then_answers(self):
        # 第1次:AI 申请调 calc_unit_cost; 第2次:AI 给最终文字
        tool_block = _Block("tool_use", name="calc_unit_cost",
                            input={"purchase_total": 100, "freight": 20, "duty": 15,
                                   "misc_fees": 0, "quantity": 10}, id="t1")
        cli = _FakeCli([
            _Resp([tool_block]),
            _Resp([_Block("text", text="单位成本 13.50")]),
        ])
        out = w._run_completion(cli, "m", "sys",
                                [{"role": "user", "content": "算成本"}], is_trade=True)
        self.assertEqual(out, "单位成本 13.50")
        # 第一次带 tools
        self.assertIn("tools", cli.calls[0])
        # 第二次 convo 里应含 assistant(tool_use) + user(tool_result)
        msgs2 = cli.calls[1]["messages"]
        roles = [m["role"] for m in msgs2]
        self.assertIn("assistant", roles)
        # tool_result 里应含正确算出的 135.00
        tr = msgs2[-1]["content"][0]
        self.assertEqual(tr["type"], "tool_result")
        self.assertIn("135.00", tr["content"])

    def test_trade_no_tool_use_returns_text(self):
        # 外贸房但 AI 直接回答(不调工具, 比如纯咨询)
        cli = _FakeCli([_Resp([_Block("text", text="FOB 是离岸价")])])
        out = w._run_completion(cli, "m", "sys",
                                [{"role": "user", "content": "FOB啥意思"}], is_trade=True)
        self.assertEqual(out, "FOB 是离岸价")
        self.assertEqual(len(cli.calls), 1)

    def test_trade_iter_cap(self):
        # AI 一直要调工具 → 撞上限 MAX_TOOL_ITERS, 最后无 tools 收尾
        tb = _Block("tool_use", name="calc_unit_cost",
                    input={"purchase_total": 1, "quantity": 1}, id="t")
        scripted = [_Resp([tb]) for _ in range(w.MAX_TOOL_ITERS)]
        scripted.append(_Resp([_Block("text", text="收尾总结")]))
        cli = _FakeCli(scripted)
        out = w._run_completion(cli, "m", "sys",
                                [{"role": "user", "content": "x"}], is_trade=True)
        self.assertEqual(out, "收尾总结")
        # 最后一次收尾调用不带 tools
        self.assertNotIn("tools", cli.calls[-1])


if __name__ == "__main__":
    unittest.main()
