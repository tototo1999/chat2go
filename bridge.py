#!/usr/bin/env python3
"""
Chat2GO · Hermes Bridge (async)
================================
大咖在本地运行此脚本，把本地 Hermes Agent 接入 Chat2GO 调试室。

架构：
  小白发消息 → Supabase messages 表 → Realtime 推送
    → bridge.py 收到 → subprocess 调 `hermes chat -q ... -Q --resume <session>`
      → Hermes 完整 agent loop (soul.md / skills / tools / memory / 模型)
        → AI 回复 → bridge.py 写回 Supabase
          → Realtime 推送给所有参与者

关键设计：
  • bridge.py 不直接调 LLM API。一切走 Hermes，让大咖通过 ~/.hermes 的
    soul.md、skills、tools、memory 来定制 AI 行为。
  • 每个调试室对应一个 Hermes session（chat2go-<room_id_short>），
    长期记忆自动累积。
  • supabase-py v2 起 realtime 只支持 AsyncClient，故全程 asyncio。

用法：
  python bridge.py                                        # 用默认 demo 账号
  python bridge.py --email x@x.com --password xxx
  python bridge.py set-prompt <room_id> "..."             # 设置房间 system prompt
  python bridge.py set-model <room_id> qwen2.5:14b        # 设置房间模型
"""

import os
from pathlib import Path as _Path

# ── 自动加载 ~/chat2go/.env（API key 等私密配置）──
def _load_dotenv():
    env_file = _Path(__file__).parent / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        # 已有同名环境变量优先使用现有的
        os.environ.setdefault(k, v)
_load_dotenv()

# ── 修复 Homebrew Python 的 SSL 证书路径问题 ──
# 必须在 import websockets / supabase 之前设置
try:
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    os.environ.setdefault("SSL_CERT_DIR", os.path.dirname(certifi.where()))
    os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
except ImportError:
    pass

import argparse
import asyncio
import re
import shutil
import ssl
import sys
from pathlib import Path
from typing import Optional

# 兜底：把默认 SSL context 也指到 certifi
try:
    import certifi as _certifi
    _orig_create_default_context = ssl.create_default_context
    def _patched_create_default_context(*args, **kwargs):
        if "cafile" not in kwargs and "capath" not in kwargs:
            kwargs["cafile"] = _certifi.where()
        return _orig_create_default_context(*args, **kwargs)
    ssl.create_default_context = _patched_create_default_context
except ImportError:
    pass

# ── 依赖检查 ──
try:
    from supabase import acreate_client, AsyncClient
except ImportError:
    print("[bridge] 缺少依赖：pip install supabase")
    sys.exit(1)

# ── Supabase 配置（与 chat.html / login.html 保持一致）──
SUPABASE_URL = "https://qjnagbzqhoansixqharb.supabase.co"
SUPABASE_ANON_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    ".eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InFqbmFnYnpxaG9hbnNpeHFoYXJiIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzgzNDIxODIsImV4cCI6MjA5MzkxODE4Mn0"
    ".GpMUVTk6JvqeciXagXQiJunc8TLFMHg3_b9reIjJ2Y8"
)

# Demo 默认大咖账号
DEFAULT_EXPERT_EMAIL    = "lirui88888862@gmail.com"
DEFAULT_EXPERT_PASSWORD = "123456"

HERMES_BIN = shutil.which("hermes") or str(Path.home() / ".local" / "bin" / "hermes")


def hermes_session_id(room_id: str) -> str:
    return f"chat2go-{room_id[:8]}"


def lookslike_markdown(text: str) -> bool:
    return bool(
        re.search(r"^#{1,3} ", text, re.M)
        or re.search(r"\|.+\|.+\|", text)
        or re.search(r"^[-*] ", text, re.M)
    )


async def call_claude(query: str, system: str = "", model: str = "claude-sonnet-4-5",
                      image_urls: list | None = None, timeout: int = 120) -> str:
    """直接调 Anthropic API。支持 image_urls=[(url, mime_type), ...]。"""
    import httpx
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("环境变量 ANTHROPIC_API_KEY 未设置")

    # 构造 user message content：图片在前，文本在后
    content_blocks = []
    for url, mime in (image_urls or []):
        content_blocks.append({
            "type": "image",
            "source": {"type": "url", "url": url},
        })
    content_blocks.append({"type": "text", "text": query})

    payload = {
        "model": model or "claude-sonnet-4-5",
        "max_tokens": 2048,
        "messages": [{"role": "user", "content": content_blocks}],
    }
    if system:
        payload["system"] = system

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
        )
    if resp.status_code != 200:
        raise RuntimeError(f"Claude API 错误 {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    return data["content"][0]["text"].strip()


async def call_hermes(query: str, model: str = "", skills: str = "", timeout: int = 180) -> str:
    """
    异步调用 `hermes chat -q ... -Q`。
    不使用 Hermes 的 session 机制（Hermes session ID 是自动生成的时间戳格式，
    无法用稳定的房间 ID 映射）。对话历史由 bridge 拼进 query 自己管理。
    """
    cmd = [HERMES_BIN, "chat", "-q", query, "-Q"]
    if model:
        cmd += ["-m", model]
    if skills:
        cmd += ["-s", skills]

    print(f"[bridge][debug] 执行: hermes chat -q <…{len(query)} 字…> -Q" + (f" -m {model}" if model else "") + (f" -s {skills}" if skills else ""))

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError(f"Hermes 响应超时（>{timeout}s）。")
    except FileNotFoundError:
        raise RuntimeError(f"找不到 hermes 命令：{HERMES_BIN}。请确认 Hermes Agent 已安装。")

    out_text = (stdout or b"").decode(errors="replace").strip()
    err_text = (stderr or b"").decode(errors="replace").strip()

    if proc.returncode != 0:
        print(f"[bridge][debug] hermes stdout:\n{out_text or '(空)'}")
        print(f"[bridge][debug] hermes stderr:\n{err_text or '(空)'}")
        raise RuntimeError(f"Hermes 调用失败 (exit {proc.returncode}). stderr={err_text[:300] or '空'}")

    out_text = re.sub(r"\n*Session:.*$", "", out_text, flags=re.M).strip()
    return out_text


async def fetch_history(sb, room_id: str, limit: int = 12) -> list:
    """取最近 N 条消息，按时间正序返回。"""
    r = await sb.table("messages").select("role,content,attachments,created_at").eq("room_id", room_id).order("created_at", desc=True).limit(limit).execute()
    return list(reversed(r.data or []))


# ── 附件文本提取 ──
async def extract_attachment_text(att: dict, max_chars: int = 30000) -> str:
    """下载附件并提取文本。失败返回空字符串。"""
    import httpx
    name = att.get("name", "unknown")
    url = att.get("url", "")
    mime = (att.get("mime_type") or "").lower()
    if not url:
        return ""

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.content
    except Exception as e:
        return f"[下载失败: {name} - {e}]"

    text = ""
    lower_name = name.lower()

    # 文本类
    if (
        lower_name.endswith((".txt", ".md", ".markdown", ".csv", ".json", ".html", ".htm", ".xml", ".log"))
        or mime.startswith("text/")
        or "json" in mime
    ):
        try:
            text = data.decode("utf-8", errors="replace")
        except Exception:
            text = data.decode("latin-1", errors="replace")

    # PDF
    elif lower_name.endswith(".pdf") or "pdf" in mime:
        try:
            import pypdf
            from io import BytesIO
            reader = pypdf.PdfReader(BytesIO(data))
            text = "\n".join(p.extract_text() or "" for p in reader.pages)
        except ImportError:
            return f"[PDF 文本提取需要安装 pypdf：pip install pypdf]"
        except Exception as e:
            return f"[PDF 解析失败: {name} - {e}]"

    # DOCX
    elif lower_name.endswith(".docx") or "wordprocessing" in mime:
        try:
            import docx
            from io import BytesIO
            doc = docx.Document(BytesIO(data))
            text = "\n".join(p.text for p in doc.paragraphs)
        except ImportError:
            return f"[DOCX 文本提取需要安装 python-docx：pip install python-docx]"
        except Exception as e:
            return f"[DOCX 解析失败: {name} - {e}]"

    else:
        return f"[不支持的文件类型: {name} ({mime})]"

    text = text.strip()
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n\n[... 文件过长，已截断到 {max_chars} 字符 ...]"
    return text


def format_conversation(history: list, current_user_msg: str, expert_prompt: str = "", attachment_texts: list | None = None) -> str:
    """把对话历史和当前消息（含附件文本）格式化成给 LLM 的 query。"""
    parts = []
    if history:
        parts.append("【对话历史】")
        for m in history:
            role = m["role"]
            label = {"user": "小白", "expert": "大咖", "ai": "你（AI）"}.get(role, role)
            content = m.get("content") or ""
            atts = m.get("attachments") or []
            if atts:
                names = ", ".join(a.get("name", "?") for a in atts)
                content = f"{content} [附件: {names}]"
            parts.append(f"{label}: {content}")
        parts.append("")

    parts.append(f"【小白用户最新消息】\n{current_user_msg}")

    if attachment_texts:
        parts.append("\n【小白上传的文件内容（请仔细阅读，作为生成内容的参考模板/资料）】")
        for fname, ftext in attachment_texts:
            parts.append(f"\n--- 文件：{fname} ---\n{ftext}\n--- 文件结束 ---")

    return "\n".join(parts)


def build_system_prompt(room: dict) -> str:
    """构造 system prompt。行业基础 + 大咖补充。"""
    industry = (room.get("industry") or "").strip()
    base = (
        f"你是 Chat2GO 平台的 AI 助手，工作在【{industry or '通用'}】行业的调试室里。"
        "三方在线：小白（你的服务对象）、大咖（行业老师，会偶尔指点你）、你（AI 助手）。\n\n"
        "【输出风格 - 严格遵守】\n"
        "1. 默认简短：日常对话 1-3 句话，绝不列长清单或多个标题。\n"
        "2. **绝对不要**在列表项之间加空行，bullet/编号列表必须紧贴排列：\n"
        "   ✅ 正确格式：\n"
        "   - 项目一\n"
        "   - 项目二\n"
        "   - 项目三\n"
        "   ❌ 错误格式（不要这样写）：\n"
        "   - 项目一\n"
        "   \n"
        "   - 项目二\n"
        "3. 段落之间最多一个空行，不要连续多个空行。\n"
        "4. 不要每段开头加 emoji，不要写「很高兴为您服务」这类客套话。\n"
        "5. 只在小白明确要求合同/报告/方案/规格表时才输出长篇 Markdown 文档。\n"
        "6. 长文档用紧凑的 Markdown：标题下直接接内容，表格代替长列表。\n"
    )
    extra = (room.get("system_prompt") or "").strip()
    if extra:
        return f"{base}\n【本调试室的大咖补充指令】\n{extra}"
    return base


def normalize_markdown(text: str) -> str:
    """压缩 AI 输出里多余的空行、列表项之间的空行。"""
    if not text:
        return text
    # 1. 三个及以上连续换行 → 两个
    text = re.sub(r'\n{3,}', '\n\n', text)
    # 2. 列表项之间的空行（- xxx \n\n - yyy → - xxx \n - yyy）
    text = re.sub(r'(\n[-*+] [^\n]+)\n\n(?=[-*+] )', r'\1\n', text)
    text = re.sub(r'(\n\d+\. [^\n]+)\n\n(?=\d+\. )', r'\1\n', text)
    # 3. 标题后的空行收紧（标题后 \n\n 内容 → 标题后 \n 内容）
    text = re.sub(r'(\n#{1,4} [^\n]+)\n\n', r'\1\n', text)
    return text.strip()


# ── 主桥接类 ──
class Chat2GOBridge:
    def __init__(self, email: str, password: str, model: str = "", skills: str = "", ai_mode: str = "claude"):
        self.email = email
        self.password = password
        self.model = model
        self.skills = skills
        self.ai_mode = ai_mode  # "claude" | "hermes"
        self.sb: Optional[AsyncClient] = None
        self.expert_id: Optional[str] = None
        self.rooms: dict = {}
        self.processing: set = set()

    async def login(self):
        self.sb = await acreate_client(SUPABASE_URL, SUPABASE_ANON_KEY)
        resp = await self.sb.auth.sign_in_with_password({"email": self.email, "password": self.password})
        self.expert_id = resp.user.id
        print(f"[bridge] 已登录：{self.email}  (id={self.expert_id[:8]}…)")

    async def load_rooms(self):
        result = await self.sb.table("rooms").select("*").eq("expert_id", self.expert_id).execute()
        new_rooms = {r["id"]: r for r in (result.data or [])}
        if set(new_rooms) != set(self.rooms):
            print(f"[bridge] 调试室列表：{[r['name'] for r in new_rooms.values()] or '(空)'}")
        self.rooms = new_rooms

    def resolve_model(self, room: dict) -> str:
        return (room.get("model") or "").strip() or self.model

    async def handle_user_message(self, msg: dict):
        msg_id = msg.get("id")
        room_id = msg.get("room_id")
        content = msg.get("content", "")
        attachments = msg.get("attachments") or []
        sender_role = msg.get("role", "user")  # 'user' | 'expert'

        if msg_id in self.processing:
            return
        self.processing.add(msg_id)

        room = self.rooms.get(room_id)
        if not room:
            self.processing.discard(msg_id); return

        model = self.resolve_model(room)
        expert_prompt = (room.get("system_prompt") or "").strip()

        att_summary = f" [附件 {len(attachments)} 个]" if attachments else ""
        sender_label = "大咖" if sender_role == "expert" else "小白"
        print(f"[bridge] [{room['name']}] {sender_label}: {content[:60]}{'…' if len(content) > 60 else ''}{att_summary}")
        print(f"[bridge] → {self.ai_mode} (model={model or 'default'})")

        try:
            # 分类附件：图片 vs 文本类
            attachment_texts = []
            image_urls = []
            for att in attachments:
                mime = (att.get("mime_type") or "").lower()
                name = att.get("name", "file")
                url  = att.get("url", "")
                if mime.startswith("image/") or any(name.lower().endswith(e) for e in (".png", ".jpg", ".jpeg", ".gif", ".webp")):
                    image_urls.append((url, mime or "image/png"))
                    print(f"[bridge] 图片附件: {name}")
                else:
                    print(f"[bridge] 读取附件: {name}")
                    text = await extract_attachment_text(att)
                    attachment_texts.append((name, text))
                    print(f"[bridge] 附件 {name} 提取了 {len(text)} 字符")

            history = await fetch_history(self.sb, room_id, limit=12)
            # 排除掉当前这条最新的 user 消息（避免重复）
            history = [m for m in history if m.get("content") != content or m.get("role") != "user"]
            query = format_conversation(history, content, expert_prompt, attachment_texts)
            system = build_system_prompt(room)

            if self.ai_mode == "hermes":
                # 把 system prompt 拼进 query（Hermes -Q 不接 --system 参数）
                full_query = f"{system}\n\n{query}\n\n请直接回复小白的最新消息。"
                ai_text = await call_hermes(full_query, model=model, skills=self.skills)
            else:
                ai_text = await call_claude(query, system=system, model=model or "claude-sonnet-4-5",
                                            image_urls=image_urls)

            # 压缩 AI 输出里多余的空行
            ai_text = normalize_markdown(ai_text)
            if not ai_text:
                ai_text = "（Hermes 返回空回复，请检查 hermes chat 是否能正常工作）"
            print(f"[bridge] [{room['name']}] AI: {ai_text[:80]}{'…' if len(ai_text) > 80 else ''}")

            await self.sb.table("messages").insert({
                "room_id": room_id,
                "user_id": self.expert_id,
                "role": "ai",
                "type": "markdown" if lookslike_markdown(ai_text) else "text",
                "content": ai_text,
            }).execute()

        except Exception as e:
            err_str = str(e)
            print(f"[bridge] AI 调用失败 (mode={self.ai_mode})：{err_str}")
            try:
                await self.sb.table("messages").insert({
                    "room_id": room_id,
                    "user_id": self.expert_id,
                    "role": "ai",
                    "content": f"⚠️ AI 调用失败 (mode={self.ai_mode}): {err_str[:300]}",
                }).execute()
            except Exception:
                pass
        finally:
            self.processing.discard(msg_id)

    def on_realtime_message(self, payload):
        """Realtime 回调（同步）。把 user/expert 消息派发到 async 任务里处理。"""
        msg = {}
        if isinstance(payload, dict):
            msg = (
                payload.get("record")
                or payload.get("new")
                or (payload.get("data") or {}).get("record")
                or (payload.get("payload") or {}).get("record")
                or {}
            )

        if not msg:
            return

        role    = msg.get("role")
        room_id = msg.get("room_id")

        # AI 自己的消息跳过（防死循环）；其他角色（user / expert）都响应
        if role == "ai" or room_id not in self.rooms:
            return

        print(f"[bridge][debug] 收到 INSERT: role={role} room={str(room_id)[:8]}…")

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.handle_user_message(msg))
        except RuntimeError:
            asyncio.run_coroutine_threadsafe(self.handle_user_message(msg), self._loop)

    async def run(self):
        self._loop = asyncio.get_running_loop()
        await self.login()
        await self.load_rooms()

        if not self.rooms:
            print("[bridge] 没有属于你的调试室。请先在网页上新建一个调试室。")
            return

        print(f"[bridge] Hermes 二进制：{HERMES_BIN}")
        if self.model:
            print(f"[bridge] 启动默认模型：{self.model}")
        if self.skills:
            print(f"[bridge] 启动加载技能：{self.skills}")
        print(f"[bridge] 监听中… 按 Ctrl+C 退出\n")

        # supabase-py 异步 realtime
        channel = self.sb.realtime.channel("chat2go-bridge")
        channel.on_postgres_changes(
            event="INSERT",
            schema="public",
            table="messages",
            callback=self.on_realtime_message,
        )

        def on_subscribed(status, *args, **kwargs):
            print(f"[bridge][debug] realtime channel status: {status}  args={args}")

        try:
            await channel.subscribe(on_subscribed)
        except TypeError:
            # 旧版本 subscribe 不接 callback
            await channel.subscribe()
            print("[bridge][debug] realtime channel subscribed (no callback)")

        # 兜底：每 5 秒轮询一次 messages 表，捕捉漏掉的新 user 消息
        last_seen_ts = {}  # room_id → latest created_at processed
        try:
            while True:
                await asyncio.sleep(5)
                await self.load_rooms()
                # 轮询兜底
                for room_id in list(self.rooms.keys()):
                    try:
                        q = self.sb.table("messages").select("*").eq("room_id", room_id).eq("role", "user").order("created_at", desc=True).limit(3)
                        r = await q.execute()
                        for m in (r.data or []):
                            if m["id"] in self.processing:
                                continue
                            ts = m["created_at"]
                            if last_seen_ts.get(room_id) and ts <= last_seen_ts[room_id]:
                                continue
                            # 检查是否已经有 AI 回复在它之后
                            ai_q = await self.sb.table("messages").select("id").eq("room_id", room_id).eq("role", "ai").gt("created_at", ts).limit(1).execute()
                            if ai_q.data:
                                last_seen_ts[room_id] = ts
                                continue
                            print(f"[bridge][poll] 发现未处理的 user 消息 {m['id'][:8]}…")
                            asyncio.create_task(self.handle_user_message(m))
                            last_seen_ts[room_id] = ts
                    except Exception as e:
                        print(f"[bridge][poll] 轮询出错: {e}")
        except asyncio.CancelledError:
            pass


# ── 子命令 ──
async def _login_for_admin(args) -> AsyncClient:
    sb = await acreate_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    email    = args.email    or DEFAULT_EXPERT_EMAIL
    password = args.password or DEFAULT_EXPERT_PASSWORD
    await sb.auth.sign_in_with_password({"email": email, "password": password})
    return sb


async def cmd_set_prompt(args):
    sb = await _login_for_admin(args)
    await sb.table("rooms").update({"system_prompt": args.prompt}).eq("id", args.room_id).execute()
    print(f"[bridge] room {args.room_id[:8]}… system_prompt 已更新。")


async def cmd_set_model(args):
    sb = await _login_for_admin(args)
    await sb.table("rooms").update({"model": args.model}).eq("id", args.room_id).execute()
    print(f"[bridge] room {args.room_id[:8]}… model 已更新为 {args.model}。")


# ── 入口 ──
def main():
    parser = argparse.ArgumentParser(description="Chat2GO · AI Bridge")
    parser.add_argument("--email")
    parser.add_argument("--password")
    parser.add_argument("--model",  default="")
    parser.add_argument("--skills", default="")
    parser.add_argument("--ai-mode", choices=["claude", "hermes"], default="claude",
                        help="AI 后端：claude=直连 Anthropic API（demo 默认）；hermes=本地 Hermes Agent")

    sub = parser.add_subparsers(dest="cmd")

    p_prompt = sub.add_parser("set-prompt")
    p_prompt.add_argument("room_id"); p_prompt.add_argument("prompt")
    p_prompt.add_argument("--email"); p_prompt.add_argument("--password")

    p_model = sub.add_parser("set-model")
    p_model.add_argument("room_id"); p_model.add_argument("model")
    p_model.add_argument("--email"); p_model.add_argument("--password")

    args = parser.parse_args()

    if args.cmd == "set-prompt":
        asyncio.run(cmd_set_prompt(args)); return
    if args.cmd == "set-model":
        asyncio.run(cmd_set_model(args)); return

    if args.ai_mode == "hermes":
        if not HERMES_BIN or not Path(HERMES_BIN).exists():
            print(f"[bridge] ⚠️  --ai-mode hermes 但找不到 hermes 命令。")
            sys.exit(1)
    else:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print(f"[bridge] ⚠️  --ai-mode claude 但环境变量 ANTHROPIC_API_KEY 未设置。")
            print(f"[bridge]    临时设置：export ANTHROPIC_API_KEY=sk-ant-xxx")
            sys.exit(1)

    email    = args.email    or DEFAULT_EXPERT_EMAIL
    password = args.password or DEFAULT_EXPERT_PASSWORD

    print(f"[bridge] AI 后端：{args.ai_mode}")
    bridge = Chat2GOBridge(email=email, password=password, model=args.model, skills=args.skills, ai_mode=args.ai_mode)

    try:
        asyncio.run(bridge.run())
    except KeyboardInterrupt:
        print("\n[bridge] 已退出。")


if __name__ == "__main__":
    main()
