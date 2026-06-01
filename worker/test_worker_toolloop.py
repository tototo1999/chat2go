"""测试 worker tool-use 循环真实代码 (_run_completion / _is_trade_room)。
本机没装 modal → 注入 fake modal 到 sys.modules 后再 import chat2go_worker,
这样测的是 worker 里的真实循环逻辑, 不是副本。
run: python3 -m unittest test_worker_toolloop -v
"""
import os
import sys
import types
import unittest

# vision SSRF 校验需要 SUPABASE_URL; 测试统一用本项目 Storage 域名
os.environ.setdefault("SUPABASE_URL", "https://qjnagbzqhoansixqharb.supabase.co")
_SB = "https://qjnagbzqhoansixqharb.supabase.co/storage/v1/object/public/chat-uploads"


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


class _FakeStorageBucket:
    def __init__(self, log):
        self._log = log

    def upload(self, path, data, opts):
        self._log.append({"path": path, "size": len(data), "opts": opts})

    def get_public_url(self, path):
        return f"https://fake.supabase/storage/{path}"


class _FakeStorage:
    def __init__(self):
        self.uploads = []

    def from_(self, bucket):
        return _FakeStorageBucket(self.uploads)


class _FakeSb:
    """fake supabase client, 只实现 storage(文档上传用)。"""
    def __init__(self):
        self.storage = _FakeStorage()


class TestIsTradeRoom(unittest.TestCase):
    def test_aliases(self):
        self.assertTrue(w._is_trade_room("外贸"))
        self.assertTrue(w._is_trade_room("外贸跟单"))
        self.assertFalse(w._is_trade_room("英语口语"))
        self.assertFalse(w._is_trade_room("算命"))


class TestVisionUrlSSRF(unittest.TestCase):
    def setUp(self):
        os.environ["SUPABASE_URL"] = "https://qjnagbzqhoansixqharb.supabase.co"

    def test_allows_own_storage_url(self):
        ok = "https://qjnagbzqhoansixqharb.supabase.co/storage/v1/object/public/chat-uploads/gen/a.png"
        self.assertTrue(w._is_safe_image_url(ok))

    def test_rejects_external_host(self):
        # 审计#5: 不能让 Claude fetch 任意外部地址(SSRF)
        self.assertFalse(w._is_safe_image_url("https://evil.example.com/x.png"))
        self.assertFalse(w._is_safe_image_url("http://169.254.169.254/latest/meta-data/"))
        self.assertFalse(w._is_safe_image_url("https://qjnagbzqhoansixqharb.supabase.co/evil"))

    def test_rejects_non_https(self):
        self.assertFalse(w._is_safe_image_url("http://qjnagbzqhoansixqharb.supabase.co/storage/v1/object/x.png"))

    def test_image_atts_filters_unsafe_url(self):
        row = {"role": "user", "attachments": [
            {"name": "a.png", "url": "https://evil.com/a.png", "mime_type": "image/png"},
            {"name": "b.png", "url": "https://qjnagbzqhoansixqharb.supabase.co/storage/v1/object/public/chat-uploads/b.png", "mime_type": "image/png"},
        ]}
        imgs = w._image_atts(row)
        urls = [a["url"] for a in imgs]
        self.assertEqual(len(imgs), 1)
        self.assertIn("supabase.co/storage", urls[0])


class TestBuildMessagesVision(unittest.TestCase):
    def test_plain_text_stays_string(self):
        # 无附件 → content 仍是字符串(向后兼容)
        hist = [{"role": "user", "content": "你好", "attachments": []}]
        out = w._build_messages(hist)
        self.assertEqual(len(out), 1)
        self.assertIsInstance(out[0]["content"], str)
        self.assertIn("你好", out[0]["content"])

    def test_image_becomes_vision_block(self):
        # 图片附件 → content 变 block list, 含 image(url source) + text
        hist = [{"role": "user", "content": "这单子写了啥",
                 "attachments": [{"name": "a.png", "url": "https://qjnagbzqhoansixqharb.supabase.co/storage/v1/object/public/chat-uploads/a.png",
                                  "mime_type": "image/png"}]}]
        out = w._build_messages(hist)
        self.assertEqual(len(out), 1)
        content = out[0]["content"]
        self.assertIsInstance(content, list)
        kinds = [b["type"] for b in content]
        self.assertIn("image", kinds)
        self.assertIn("text", kinds)
        img = next(b for b in content if b["type"] == "image")
        self.assertEqual(img["source"]["type"], "url")
        self.assertEqual(img["source"]["url"], "https://qjnagbzqhoansixqharb.supabase.co/storage/v1/object/public/chat-uploads/a.png")

    def test_nonimage_attachment_no_vision(self):
        # pdf/xlsx 附件不进 vision(避免 API 报错), content 保持字符串
        hist = [{"role": "user", "content": "看这个",
                 "attachments": [{"name": "b.pdf", "url": "https://x/b.pdf",
                                  "mime_type": "application/pdf"}]}]
        out = w._build_messages(hist)
        self.assertIsInstance(out[0]["content"], str)

    def test_image_by_extension(self):
        # mime 缺失时按扩展名判断
        hist = [{"role": "user", "content": "图",
                 "attachments": [{"name": "photo.JPG", "url": "https://qjnagbzqhoansixqharb.supabase.co/storage/v1/object/public/chat-uploads/p.jpg"}]}]
        out = w._build_messages(hist)
        self.assertIsInstance(out[0]["content"], list)

    def test_image_only_no_text(self):
        # 只发图无文字 → 仍出 image block(text 可空或省略)
        hist = [{"role": "user", "content": "",
                 "attachments": [{"name": "a.png", "url": "https://qjnagbzqhoansixqharb.supabase.co/storage/v1/object/public/chat-uploads/a.png",
                                  "mime_type": "image/png"}]}]
        out = w._build_messages(hist)
        self.assertEqual(len(out), 1)
        kinds = [b["type"] for b in out[0]["content"]]
        self.assertIn("image", kinds)


class TestRunCompletion(unittest.TestCase):
    def test_non_trade_single_call_no_tools(self):
        cli = _FakeCli([_Resp([_Block("text", text="你好")])])
        out, atts = w._run_completion(cli, _FakeSb(), "m", "sys",
                                      [{"role": "user", "content": "hi"}], is_trade=False)
        self.assertEqual(out, "你好")
        self.assertEqual(atts, [])
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
        out, atts = w._run_completion(cli, _FakeSb(), "m", "sys",
                                      [{"role": "user", "content": "算成本"}], is_trade=True)
        self.assertEqual(out, "单位成本 13.50")
        self.assertEqual(atts, [])  # 纯核算无文件
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
        out, atts = w._run_completion(cli, _FakeSb(), "m", "sys",
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
        out, atts = w._run_completion(cli, _FakeSb(), "m", "sys",
                                      [{"role": "user", "content": "x"}], is_trade=True)
        self.assertEqual(out, "收尾总结")
        # 最后一次收尾调用不带 tools
        self.assertNotIn("tools", cli.calls[-1])

    def test_make_excel_uploads_and_attaches(self):
        # AI 调 make_excel → worker 生成+上传 → attachment 累积 + tool_result 带 url
        tb = _Block("tool_use", name="make_excel",
                    input={"filename": "订单核算表", "headers": ["项目", "金额"],
                           "rows": [["采购", 100]]}, id="x1")
        cli = _FakeCli([
            _Resp([tb]),
            _Resp([_Block("text", text="已生成 Excel,见下方下载")]),
        ])
        sb = _FakeSb()
        out, atts = w._run_completion(cli, sb, "m", "sys",
                                      [{"role": "user", "content": "做成excel"}], is_trade=True)
        self.assertEqual(out, "已生成 Excel,见下方下载")
        # attachment 累积了 1 个 .xlsx
        self.assertEqual(len(atts), 1)
        self.assertEqual(atts[0]["name"], "订单核算表.xlsx")
        self.assertTrue(atts[0]["url"].startswith("https://fake.supabase/"))
        self.assertIn("spreadsheet", atts[0]["mime_type"])
        # storage 路径 ASCII
        self.assertTrue(atts[0]["storage_path"].isascii())
        # 真有上传发生
        self.assertEqual(len(sb.storage.uploads), 1)
        # tool_result 回灌给 AI 含 url
        tr = cli.calls[1]["messages"][-1]["content"][0]
        self.assertIn("fake.supabase", tr["content"])

    def test_make_pdf_attaches(self):
        tb = _Block("tool_use", name="make_pdf",
                    input={"filename": "报价单", "blocks": [
                        {"type": "paragraph", "text": "你好客户"}]}, id="p1")
        cli = _FakeCli([_Resp([tb]), _Resp([_Block("text", text="PDF 已生成")])])
        out, atts = w._run_completion(cli, _FakeSb(), "m", "sys",
                                      [{"role": "user", "content": "出pdf"}], is_trade=True)
        self.assertEqual(len(atts), 1)
        self.assertEqual(atts[0]["name"], "报价单.pdf")
        self.assertEqual(atts[0]["mime_type"], "application/pdf")


# ── _load_history: 触发消息查不到时不该崩 (PGRST116 回归) ─────────────────────
class _FakeQuery:
    """模拟 supabase-py 查询链; maybe_single 标记下次 execute 返回触发消息结果。"""
    def __init__(self, trig_data, history_rows):
        self._trig_data = trig_data
        self._history = history_rows
        self._is_trig = False

    # 链式方法一律返回自身
    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def order(self, *a, **k): return self
    def limit(self, *a, **k): return self
    def lte(self, *a, **k): return self

    def maybe_single(self):
        self._is_trig = True
        return self

    def single(self):  # 若代码回退用 single, 0 行抛 PGRST116 — 测试要保证不会走这
        self._is_trig = True
        self._raise_single = True
        return self

    def execute(self):
        if self._is_trig:
            if getattr(self, "_raise_single", False) and self._trig_data is None:
                raise Exception("PGRST116: Cannot coerce the result to a single JSON object")
            return types.SimpleNamespace(data=self._trig_data)
        return types.SimpleNamespace(data=self._history)


class _FakeSbHistory:
    def __init__(self, trig_data, history_rows):
        self._trig_data = trig_data
        self._history = history_rows

    def table(self, _name):
        return _FakeQuery(self._trig_data, self._history)


class TestLoadHistory(unittest.TestCase):
    def _rows(self):
        return [
            {"id": "u1", "role": "user", "content": "你好", "type": "text",
             "attachments": None, "created_at": "2026-05-31T00:00:00+00", "channel": "main"},
            {"id": "ph", "role": "ai", "content": "...", "type": "text",
             "attachments": None, "created_at": "2026-05-31T00:00:01+00", "channel": "main"},
        ]

    def test_trigger_missing_does_not_crash(self):
        # 触发消息查到 0 行 (data=None) → 不抛, 退化成照常拉历史
        sb = _FakeSbHistory(trig_data=None, history_rows=self._rows())
        out = w._load_history(sb, "room1", "main", "missing-id")
        self.assertEqual([r["id"] for r in out], ["u1"])  # placeholder '...' 被过滤

    def test_trigger_found_normal(self):
        sb = _FakeSbHistory(trig_data={"created_at": "2026-05-31T00:00:05+00"},
                            history_rows=self._rows())
        out = w._load_history(sb, "room1", "main", "u1")
        self.assertEqual([r["id"] for r in out], ["u1"])


if __name__ == "__main__":
    unittest.main()
