"""Anthropic native memory tool (memory_20250818) 客户端后端。

模型发 tool_use(name="memory", input={command,...}); 本模块执行并返回
Claude 专门调过的 plain-string 格式(NOT json)。文件持久化到 Supabase
表 tradego_memory_files(expert_id, product, path, content)。

安全: 所有路径必须以 /memories 开头且不含 '..'(防遍历)。
"""
from __future__ import annotations


class SupabaseStore:
    """tradego_memory_files 表的 path->content 视图(按 expert_id+product 隔离)。"""

    def __init__(self, sb, expert_id, product="tradego"):
        self.sb = sb
        self.expert_id = expert_id
        self.product = product

    def read(self, path):
        res = (self.sb.table("tradego_memory_files")
               .select("content")
               .eq("expert_id", self.expert_id)
               .eq("product", self.product)
               .eq("path", path)
               .maybe_single()
               .execute())
        data = getattr(res, "data", None)
        if not data:
            return None
        return data.get("content")

    def write(self, path, content):
        self.sb.table("tradego_memory_files").upsert(
            {"expert_id": self.expert_id, "product": self.product,
             "path": path, "content": content, "updated_at": "now()"},
            on_conflict="expert_id,product,path",
        ).execute()

    def delete(self, path):
        (self.sb.table("tradego_memory_files")
         .delete()
         .eq("expert_id", self.expert_id)
         .eq("product", self.product)
         .eq("path", path)
         .execute())

    def list(self, prefix):
        res = (self.sb.table("tradego_memory_files")
               .select("path")
               .eq("expert_id", self.expert_id)
               .eq("product", self.product)
               .like("path", prefix + "%")
               .execute())
        rows = getattr(res, "data", None) or []
        return sorted(r["path"] for r in rows)


def _safe(path) -> bool:
    if path is None:
        return False
    if not path.startswith("/memories"):
        return False
    if ".." in path:
        return False
    return True


def _with_line_numbers(content: str, view_range=None) -> str:
    lines = content.split("\n")
    start, end = 1, len(lines)
    if view_range and len(view_range) == 2:
        start = int(view_range[0])
        end = int(view_range[1])
    out = []
    for i, line in enumerate(lines, start=1):
        if i < start or i > end:
            continue
        out.append(f"{i:>6}\t{line}")
    return "\n".join(out)


def dispatch(store, tin: dict) -> str:
    cmd = tin.get("command")

    if cmd == "rename":
        op = tin.get("old_path")
        np = tin.get("new_path")
        if not _safe(op):
            return f"Error: invalid path {op} (must be under /memories)"
        if not _safe(np):
            return f"Error: invalid path {np} (must be under /memories)"
        cur = store.read(op)
        if cur is None:
            return f"Error: The path {op} does not exist"
        if store.read(np) is not None:
            return f"Error: The destination {np} already exists"
        store.write(np, cur)
        store.delete(op)
        return f"Successfully renamed {op} to {np}"

    path = tin.get("path")
    if not _safe(path):
        return f"Error: invalid path {path} (must be under /memories)"

    if cmd == "view":
        cur = store.read(path)
        if cur is not None:
            body = _with_line_numbers(cur, tin.get("view_range"))
            return f"Here's the content of {path} with line numbers:\n" + body
        listed = store.list(path.rstrip("/") + "/")
        if listed or path == "/memories":
            header = f"Here're the files and directories in {path}:"
            if not listed:
                return header
            return header + "\n" + "\n".join(
                f"{len(store.read(p))}B\t{p}" for p in listed)
        return f"The path {path} does not exist. Please provide a valid path."

    if cmd == "create":
        if store.read(path) is not None:
            return f"Error: File {path} already exists"
        store.write(path, tin.get("file_text", ""))
        return f"File created successfully at: {path}"

    if cmd == "str_replace":
        cur = store.read(path)
        if cur is None:
            return f"Error: The path {path} does not exist. Please provide a valid path."
        old_str = tin.get("old_str", "")
        count = cur.count(old_str)
        if count == 0:
            return f"No replacement was performed, old_str `{old_str}` did not appear verbatim in {path}."
        if count > 1:
            return f"No replacement was performed. Multiple occurrences of old_str `{old_str}`. Please ensure it is unique"
        store.write(path, cur.replace(old_str, tin.get("new_str", ""), 1))
        return "The memory file has been edited."

    if cmd == "insert":
        cur = store.read(path)
        if cur is None:
            return f"Error: The path {path} does not exist"
        lines = cur.splitlines()
        n = len(lines)
        il = int(tin["insert_line"])
        if il < 0 or il > n:
            return f"Error: Invalid insert_line parameter: {il}. It should be within the range [0, {n}]"
        lines.insert(il, tin.get("insert_text", "").rstrip("\n"))
        store.write(path, "\n".join(lines) + "\n")
        return f"The file {path} has been edited."

    if cmd == "delete":
        if store.read(path) is None and not store.list(path.rstrip("/") + "/"):
            return f"Error: The path {path} does not exist"
        store.delete(path)
        return f"Successfully deleted {path}"

    return f"Error: unknown memory command: {tin.get('command')}"
