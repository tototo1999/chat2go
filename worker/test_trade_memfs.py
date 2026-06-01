"""测试 trade_memfs (memory_20250818 后端: 六命令 + 路径防护)。
用 FakeStore (内存 dict) 测 dispatch 返回的 STRING 契约。
run: ~/.venv-c2g/bin/python -m unittest test_trade_memfs -v
"""
import unittest

import trade_memfs as tmf


class FakeStore:
    """内存版 store: path -> content。read/write/delete/list 与 SupabaseStore 同接口。"""
    def __init__(self):
        self.files = {}

    def read(self, path):
        return self.files.get(path)

    def write(self, path, content):
        self.files[path] = content

    def delete(self, path):
        self.files.pop(path, None)

    def list(self, prefix):
        return sorted(p for p in self.files if p.startswith(prefix))


class TestDispatch(unittest.TestCase):
    def setUp(self):
        self.s = FakeStore()

    def test_create_then_view_file(self):
        out = tmf.dispatch(self.s, {"command": "create", "path": "/memories/a.md",
                                    "file_text": "hello\nworld"})
        self.assertIn("File created successfully at: /memories/a.md", out)
        out = tmf.dispatch(self.s, {"command": "view", "path": "/memories/a.md"})
        self.assertIn("content of /memories/a.md with line numbers", out)
        self.assertIn("hello", out)
        self.assertIn("world", out)
        # 行号: 第一行前缀含 "1" + tab
        self.assertIn("\thello", out)

    def test_view_range(self):
        tmf.dispatch(self.s, {"command": "create", "path": "/memories/a.md",
                              "file_text": "l1\nl2\nl3\nl4"})
        out = tmf.dispatch(self.s, {"command": "view", "path": "/memories/a.md",
                                    "view_range": [2, 3]})
        self.assertIn("l2", out)
        self.assertIn("l3", out)
        self.assertNotIn("l1", out)
        self.assertNotIn("l4", out)

    def test_create_existing(self):
        tmf.dispatch(self.s, {"command": "create", "path": "/memories/a.md",
                              "file_text": "x"})
        out = tmf.dispatch(self.s, {"command": "create", "path": "/memories/a.md",
                                    "file_text": "y"})
        self.assertIn("already exists", out)

    def test_str_replace_success(self):
        tmf.dispatch(self.s, {"command": "create", "path": "/memories/a.md",
                              "file_text": "foo bar baz"})
        out = tmf.dispatch(self.s, {"command": "str_replace", "path": "/memories/a.md",
                                    "old_str": "bar", "new_str": "QUX"})
        self.assertIn("has been edited", out)
        self.assertEqual(self.s.read("/memories/a.md"), "foo QUX baz")

    def test_str_replace_not_found(self):
        out = tmf.dispatch(self.s, {"command": "str_replace", "path": "/memories/nope.md",
                                    "old_str": "x", "new_str": "y"})
        self.assertIn("does not exist", out)

    def test_str_replace_no_match(self):
        tmf.dispatch(self.s, {"command": "create", "path": "/memories/a.md",
                              "file_text": "abc"})
        out = tmf.dispatch(self.s, {"command": "str_replace", "path": "/memories/a.md",
                                    "old_str": "zzz", "new_str": "y"})
        self.assertIn("No replacement was performed", out)
        self.assertIn("did not appear verbatim", out)

    def test_str_replace_duplicate(self):
        tmf.dispatch(self.s, {"command": "create", "path": "/memories/a.md",
                              "file_text": "x x x"})
        out = tmf.dispatch(self.s, {"command": "str_replace", "path": "/memories/a.md",
                                    "old_str": "x", "new_str": "y"})
        self.assertIn("Multiple occurrences", out)

    def test_insert_at_line(self):
        tmf.dispatch(self.s, {"command": "create", "path": "/memories/a.md",
                              "file_text": "l1\nl2\nl3"})
        out = tmf.dispatch(self.s, {"command": "insert", "path": "/memories/a.md",
                                    "insert_line": 1, "insert_text": "INSERTED"})
        self.assertIn("has been edited", out)
        self.assertEqual(self.s.read("/memories/a.md"),
                         "l1\nINSERTED\nl2\nl3\n")

    def test_insert_out_of_range(self):
        tmf.dispatch(self.s, {"command": "create", "path": "/memories/a.md",
                              "file_text": "l1\nl2"})
        out = tmf.dispatch(self.s, {"command": "insert", "path": "/memories/a.md",
                                    "insert_line": 99, "insert_text": "x"})
        self.assertIn("Invalid insert_line", out)

    def test_delete(self):
        tmf.dispatch(self.s, {"command": "create", "path": "/memories/a.md",
                              "file_text": "x"})
        out = tmf.dispatch(self.s, {"command": "delete", "path": "/memories/a.md"})
        self.assertIn("Successfully deleted /memories/a.md", out)
        self.assertIsNone(self.s.read("/memories/a.md"))

    def test_delete_missing(self):
        out = tmf.dispatch(self.s, {"command": "delete", "path": "/memories/nope.md"})
        self.assertIn("does not exist", out)

    def test_rename_success(self):
        tmf.dispatch(self.s, {"command": "create", "path": "/memories/a.md",
                              "file_text": "x"})
        out = tmf.dispatch(self.s, {"command": "rename", "old_path": "/memories/a.md",
                                    "new_path": "/memories/b.md"})
        self.assertIn("Successfully renamed /memories/a.md to /memories/b.md", out)
        self.assertIsNone(self.s.read("/memories/a.md"))
        self.assertEqual(self.s.read("/memories/b.md"), "x")

    def test_rename_dest_exists(self):
        tmf.dispatch(self.s, {"command": "create", "path": "/memories/a.md", "file_text": "x"})
        tmf.dispatch(self.s, {"command": "create", "path": "/memories/b.md", "file_text": "y"})
        out = tmf.dispatch(self.s, {"command": "rename", "old_path": "/memories/a.md",
                                    "new_path": "/memories/b.md"})
        self.assertIn("already exists", out)

    def test_rename_source_missing(self):
        out = tmf.dispatch(self.s, {"command": "rename", "old_path": "/memories/nope.md",
                                    "new_path": "/memories/b.md"})
        self.assertIn("does not exist", out)

    def test_path_traversal_absolute(self):
        out = tmf.dispatch(self.s, {"command": "view", "path": "/etc/passwd"})
        self.assertIn("invalid path", out)

    def test_path_traversal_dotdot(self):
        out = tmf.dispatch(self.s, {"command": "create", "path": "/memories/../x",
                                    "file_text": "x"})
        self.assertIn("invalid path", out)

    def test_rename_traversal(self):
        out = tmf.dispatch(self.s, {"command": "rename", "old_path": "/memories/a.md",
                                    "new_path": "/etc/evil"})
        self.assertIn("invalid path", out)

    def test_view_empty_memories_root(self):
        # /memories 空目录 view 不报错, 返回 header
        out = tmf.dispatch(self.s, {"command": "view", "path": "/memories"})
        self.assertIn("files and directories in /memories", out)
        self.assertNotIn("does not exist", out)

    def test_view_dir_with_files(self):
        tmf.dispatch(self.s, {"command": "create", "path": "/memories/a.md", "file_text": "hi"})
        tmf.dispatch(self.s, {"command": "create", "path": "/memories/b.md", "file_text": "yo"})
        out = tmf.dispatch(self.s, {"command": "view", "path": "/memories"})
        self.assertIn("/memories/a.md", out)
        self.assertIn("/memories/b.md", out)
        self.assertIn("2B", out)  # len("hi")

    def test_view_nonexistent_path(self):
        out = tmf.dispatch(self.s, {"command": "view", "path": "/memories/ghost.md"})
        self.assertIn("does not exist", out)

    def test_unknown_command(self):
        out = tmf.dispatch(self.s, {"command": "frobnicate", "path": "/memories/a.md"})
        self.assertIn("unknown memory command", out)


# ── worker 集成: memory tool 经 _run_completion 不崩, content 是 plain string ──
import test_worker_toolloop as tw  # noqa: E402  复用 fake-modal 后的真实 worker

w = tw.w
_Block = tw._Block
_Resp = tw._Resp
_FakeCli = tw._FakeCli


class _MemSbQuery:
    """支持 memory 分支用到的链: select/eq/maybe_single/upsert/delete/like/execute。"""
    def __init__(self, files):
        self._files = files
        self._mode = None      # 'read' | 'list' | 'delete'
        self._path = None
        self._prefix = None
        self._upsert = None

    def select(self, *a, **k):
        self._mode = "read"
        return self

    def upsert(self, row, *a, **k):
        self._upsert = row
        return self

    def delete(self, *a, **k):
        self._mode = "delete"
        return self

    def eq(self, col, val):
        if col == "path":
            self._path = val
        return self

    def like(self, col, pattern):
        self._mode = "list"
        self._prefix = pattern.rstrip("%")
        return self

    def maybe_single(self):
        return self

    def execute(self):
        import types as _t
        if self._upsert is not None:
            self._files[self._upsert["path"]] = self._upsert["content"]
            return _t.SimpleNamespace(data=self._upsert)
        if self._mode == "delete":
            self._files.pop(self._path, None)
            return _t.SimpleNamespace(data=None)
        if self._mode == "list":
            rows = [{"path": p} for p in self._files if p.startswith(self._prefix)]
            return _t.SimpleNamespace(data=rows)
        # read
        if self._path in self._files:
            return _t.SimpleNamespace(data={"content": self._files[self._path]})
        return _t.SimpleNamespace(data=None)


class _MemSb:
    def __init__(self):
        self.files = {}

    def table(self, _name):
        return _MemSbQuery(self.files)


class TestWorkerMemoryIntegration(unittest.TestCase):
    def test_memory_tool_does_not_crash_and_returns_text(self):
        # 第1次: AI 调 memory view /memories; 第2次: AI 给最终文字
        mem_tu = _Block("tool_use", name="memory",
                        input={"command": "view", "path": "/memories"}, id="m1")
        cli = _FakeCli([
            _Resp([mem_tu]),
            _Resp([_Block("text", text="记忆已读取")]),
        ])
        sb = _MemSb()
        out, atts = w._run_completion(
            cli, sb, "claude-opus-4-8", "sys",
            [{"role": "user", "content": "看下记忆"}],
            is_trade=True, expert_id="exp1", product="tradego")
        self.assertEqual(out, "记忆已读取")
        # memory tool_result content 必须是 plain string(非 json), 含目录 header
        tr = cli.calls[1]["messages"][-1]["content"][0]
        self.assertEqual(tr["type"], "tool_result")
        self.assertIsInstance(tr["content"], str)
        self.assertIn("files and directories in /memories", tr["content"])
        # 第一次调用带了 memory tool + adaptive thinking + high effort
        names = [t.get("name") for t in cli.calls[0]["tools"]]
        self.assertIn("memory", names)
        self.assertEqual(cli.calls[0]["thinking"], {"type": "adaptive"})
        self.assertEqual(cli.calls[0]["output_config"], {"effort": "high"})

    def test_memory_create_persists_string_result(self):
        create_tu = _Block("tool_use", name="memory",
                           input={"command": "create", "path": "/memories/lessons.md",
                                  "file_text": "客户 ACME 只接受 FOB"}, id="m2")
        cli = _FakeCli([
            _Resp([create_tu]),
            _Resp([_Block("text", text="已记住")]),
        ])
        sb = _MemSb()
        out, _ = w._run_completion(
            cli, sb, "claude-opus-4-8", "sys",
            [{"role": "user", "content": "记住 ACME 只接受 FOB"}],
            is_trade=True, expert_id="exp1", product="tradego")
        self.assertEqual(out, "已记住")
        self.assertEqual(sb.files["/memories/lessons.md"], "客户 ACME 只接受 FOB")
        tr = cli.calls[1]["messages"][-1]["content"][0]
        self.assertIsInstance(tr["content"], str)
        self.assertIn("created successfully", tr["content"])


if __name__ == "__main__":
    unittest.main()
