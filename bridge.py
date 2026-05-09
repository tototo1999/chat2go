#!/usr/bin/env python3
"""
Chat2GO · Hermes Bridge (async)
================================
专家在本地运行此脚本，把本地 Hermes Agent 接入 Chat2GO 调试室。

架构：
  小白发消息 → Supabase messages 表 → Realtime 推送
    → bridge.py 收到 → subprocess 调 `hermes chat -q ... -Q --resume <session>`
      → Hermes 完整 agent loop (soul.md / skills / tools / memory / 模型)
        → AI 回复 → bridge.py 写回 Supabase
          → Realtime 推送给所有参与者

关键设计：
  • bridge.py 不直接调 LLM API。一切走 Hermes，让专家通过 ~/.hermes 的
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

# Demo 默认专家账号
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


async def call_claude(query: str, system: str = "", model: str = "claude-sonnet-4-5", timeout: int = 120) -> str:
    """直接调 Anthropic API（demo 临时方案，跳过 Hermes）。"""
    import httpx
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("环境变量 ANTHROPIC_API_KEY 未设置")

    payload = {
        "model": model or "claude-sonnet-4-5",
        "max_tokens": 2048,
        "messages": [{"role": "user", "content": query}],
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
    r = await sb.table("messages").select("role,content,created_at").eq("room_id", room_id).order("created_at", desc=True).limit(limit).execute()
    return list(reversed(r.data or []))


def format_conversation(history: list, current_user_msg: str, expert_prompt: str = "") -> str:
    """把对话历史格式化成一段给 LLM 的 query 文本。"""
    parts = []
    if history:
        parts.append("【对话历史】")
        for m in history:
            role = m["role"]
            label = {"user": "小白", "expert": "专家", "ai": "你（AI）"}.get(role, role)
            parts.append(f"{label}: {m['content']}")
        parts.append("")
    parts.append(f"【小白用户最新消息】\n{current_user_msg}")
    return "\n".join(parts)


def build_system_prompt(room: dict) -> str:
    """构造 system prompt。行业基础 + 专家补充。"""
    industry = (room.get("industry") or "").strip()
    base = (
        f"你是 Chat2GO 平台的 AI 助手，工作在【{industry or '通用'}】行业的调试室里。"
        "三方在线：小白（你的服务对象）、专家（行业老师，会偶尔指点你）、你（AI 助手）。\n\n"
        "【输出风格】\n"
        "- 默认简短：日常对话 1-3 句话，不要列长清单。\n"
        "- 列表项之间不要空行，紧凑排列。\n"
        "- 不要加多余的 emoji 和客套话（「很高兴为您服务」之类的）。\n"
        "- 只在小白明确要求合同/报告/方案/规格表时才输出长篇 Markdown 文档。\n"
        "- 长文档用 Markdown 标题、表格、列表，前端会自动渲染并提供 PDF 下载。\n"
    )
    extra = (room.get("system_prompt") or "").strip()
    if extra:
        return f"{base}\n【本调试室的专家补充指令】\n{extra}"
    return base


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

        if msg_id in self.processing:
            return
        self.processing.add(msg_id)

        room = self.rooms.get(room_id)
        if not room:
            self.processing.discard(msg_id); return

        model = self.resolve_model(room)
        expert_prompt = (room.get("system_prompt") or "").strip()

        print(f"[bridge] [{room['name']}] 用户: {content[:60]}{'…' if len(content) > 60 else ''}")
        print(f"[bridge] → {self.ai_mode} (model={model or 'default'})")

        try:
            history = await fetch_history(self.sb, room_id, limit=12)
            # 排除掉当前这条最新的 user 消息（避免重复）
            history = [m for m in history if m.get("content") != content or m.get("role") != "user"]
            query = format_conversation(history, content, expert_prompt)
            system = build_system_prompt(room)

            if self.ai_mode == "hermes":
                # 把 system prompt 拼进 query（Hermes -Q 不接 --system 参数）
                full_query = f"{system}\n\n{query}\n\n请直接回复小白的最新消息。"
                ai_text = await call_hermes(full_query, model=model, skills=self.skills)
            else:
                ai_text = await call_claude(query, system=system, model=model or "claude-sonnet-4-5")
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
        """Realtime 回调（同步）。把 user 消息派发到 async 任务里处理。"""
        # ── 调试：打印原始 payload，方便排查结构 ──
        try:
            print(f"[bridge][debug] realtime payload keys: {list(payload.keys()) if isinstance(payload, dict) else type(payload)}")
        except Exception:
            pass

        # 兼容多种 payload 结构（不同版本 supabase-py / realtime-py 字段不同）
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
            print(f"[bridge][debug] 找不到 record 字段，原始 payload: {payload}")
            return

        role    = msg.get("role")
        room_id = msg.get("room_id")
        print(f"[bridge][debug] 收到 INSERT: role={role} room={str(room_id)[:8]}… in_rooms={room_id in self.rooms}")

        if role != "user" or room_id not in self.rooms:
            return

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
