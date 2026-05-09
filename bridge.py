#!/usr/bin/env python3
"""
Chat2GO · Hermes Bridge
=======================
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
    长期记忆自动累积。专家在 Telegram 和 Chat2GO 网页用同一个 Hermes，
    记忆和能力完全互通。
  • 房间级覆盖：rooms.model / rooms.system_prompt 通过 -m / 前缀注入。

用法：
  python bridge.py                                        # 交互式登录
  python bridge.py --email x@x.com --password xxx
  python bridge.py set-prompt <room_id> "..."             # 设置房间 system prompt
  python bridge.py set-model <room_id> qwen2.5:14b        # 设置房间模型
"""

import argparse
import asyncio
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

# ── 依赖检查 ──────────────────────────────────────────────────────────────────
MISSING = []
try:
    from supabase import create_client, Client
except ImportError:
    MISSING.append("supabase")
try:
    import realtime  # noqa: F401  (transitive via supabase, double-check)
except ImportError:
    pass  # supabase 一般会自带，不强求

if MISSING:
    print(f"[bridge] 缺少依赖：pip install {' '.join(MISSING)}")
    sys.exit(1)

# ── Supabase 配置（与 chat.html / login.html 保持一致）────────────────────────
SUPABASE_URL = "https://qjnagbzqhoansixqharb.supabase.co"
SUPABASE_ANON_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    ".eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InFqbmFnYnpxaG9hbnNpeHFoYXJiIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzgzNDIxODIsImV4cCI6MjA5MzkxODE4Mn0"
    ".GpMUVTk6JvqeciXagXQiJunc8TLFMHg3_b9reIjJ2Y8"
)

# ── Hermes CLI ──
HERMES_BIN = shutil.which("hermes") or str(Path.home() / ".local" / "bin" / "hermes")


def hermes_session_id(room_id: str) -> str:
    """每个房间一个 Hermes session，记忆隔离持久化。"""
    return f"chat2go-{room_id[:8]}"


def call_hermes(query: str, session: str, model: str = "", skills: str = "", timeout: int = 180) -> str:
    """
    通过 subprocess 调用 `hermes chat -q ... -Q --resume <session>`。
    -Q quiet mode 只输出最终回复，没有 banner/spinner/工具预览。
    Hermes 自动加载该专家的 soul.md / skills / tools / memory。
    """
    cmd = [HERMES_BIN, "chat", "-q", query, "-Q", "--resume", session]
    if model:
        cmd += ["-m", model]
    if skills:
        cmd += ["-s", skills]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        raise RuntimeError(f"找不到 hermes 命令：{HERMES_BIN}。请确认 Hermes Agent 已安装。")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Hermes 响应超时（>{timeout}s）。")

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise RuntimeError(f"Hermes 调用失败 (exit {result.returncode}): {stderr[:300]}")

    output = (result.stdout or "").strip()
    # Hermes -Q 模式末尾可能附带 session info 行（如 `Session: xxx`），裁掉
    output = re.sub(r"\n*Session:.*$", "", output, flags=re.M).strip()
    return output


def lookslike_markdown(text: str) -> bool:
    """判断 AI 输出是否结构化文档（合同/报告/方案），用于前端 Markdown 渲染 + PDF。"""
    return bool(
        re.search(r"^#{1,3} ", text, re.M)
        or re.search(r"\|.+\|.+\|", text)
        or re.search(r"^[-*] ", text, re.M)
    )


# ── 主桥接类 ──────────────────────────────────────────────────────────────────
class Chat2GOBridge:
    def __init__(self, email: str, password: str, model: str = "", skills: str = ""):
        self.email = email
        self.password = password
        self.model = model      # 启动级默认模型（可被 room.model 覆盖）
        self.skills = skills    # 启动级技能（可被 room 配置覆盖，未来扩展）
        self.sb: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
        self.expert_id: Optional[str] = None
        self.rooms: dict = {}
        self.processing: set = set()

    def login(self):
        resp = self.sb.auth.sign_in_with_password({"email": self.email, "password": self.password})
        self.expert_id = resp.user.id
        print(f"[bridge] 已登录：{self.email}  (id={self.expert_id[:8]}…)")

    def load_rooms(self):
        result = self.sb.table("rooms").select("*").eq("expert_id", self.expert_id).execute()
        new_rooms = {r["id"]: r for r in (result.data or [])}
        if set(new_rooms) != set(self.rooms):
            print(f"[bridge] 调试室列表：{[r['name'] for r in new_rooms.values()] or '(空)'}")
        self.rooms = new_rooms

    def build_query(self, room: dict, user_msg: str) -> str:
        """
        把房间级 system_prompt 作为前缀注入到查询里。
        Hermes session 会自动累积上下文，重复的前缀不会污染（Hermes 会去重/折叠）。
        """
        extra = (room.get("system_prompt") or "").strip()
        if extra:
            return f"【本调试室专家指令】\n{extra}\n\n【小白用户消息】\n{user_msg}"
        return user_msg

    def resolve_model(self, room: dict) -> str:
        """模型优先级：room.model > 启动参数 > Hermes 全局 config（让 Hermes 自己解析）。"""
        return (room.get("model") or "").strip() or self.model

    def handle_new_message(self, payload: dict):
        msg = payload.get("new", {})
        msg_id = msg.get("id")
        room_id = msg.get("room_id")
        role = msg.get("role")
        content = msg.get("content", "")

        # 只响应小白用户消息；专家消息和 AI 自己的消息都跳过
        if role != "user" or room_id not in self.rooms:
            return
        if msg_id in self.processing:
            return
        self.processing.add(msg_id)

        room = self.rooms[room_id]
        model = self.resolve_model(room)
        session = hermes_session_id(room_id)
        query = self.build_query(room, content)

        print(f"[bridge] [{room['name']}] 用户: {content[:60]}{'…' if len(content) > 60 else ''}")
        print(f"[bridge] → hermes chat (session={session}, model={model or 'default'})")

        try:
            ai_text = call_hermes(query, session=session, model=model, skills=self.skills)
            if not ai_text:
                ai_text = "（Hermes 返回空回复，请检查 hermes chat 是否能正常工作）"
            print(f"[bridge] [{room['name']}] AI: {ai_text[:80]}{'…' if len(ai_text) > 80 else ''}")

            self.sb.table("messages").insert({
                "room_id": room_id,
                "user_id": self.expert_id,
                "role": "ai",
                "type": "markdown" if lookslike_markdown(ai_text) else "text",
                "content": ai_text,
            }).execute()

        except Exception as e:
            print(f"[bridge] Hermes 调用失败：{e}")
            try:
                self.sb.table("messages").insert({
                    "room_id": room_id,
                    "user_id": self.expert_id,
                    "role": "ai",
                    "content": f"⚠️ 本地 Hermes 调用失败：{e}",
                }).execute()
            except Exception:
                pass
        finally:
            self.processing.discard(msg_id)

    async def run(self):
        self.login()
        self.load_rooms()

        if not self.rooms:
            print("[bridge] 没有属于你的调试室。请先在网页上新建一个（你会自动成为 expert_id）。")
            return

        print(f"[bridge] Hermes 二进制：{HERMES_BIN}")
        if self.model:
            print(f"[bridge] 启动默认模型：{self.model}")
        if self.skills:
            print(f"[bridge] 启动加载技能：{self.skills}")
        print(f"[bridge] 监听中… 按 Ctrl+C 退出\n")

        channel = (
            self.sb.realtime.channel("chat2go-bridge")
            .on_postgres_changes(
                event="INSERT",
                schema="public",
                table="messages",
                callback=lambda payload: self.handle_new_message(payload),
            )
        )
        await channel.subscribe()

        try:
            while True:
                await asyncio.sleep(15)
                # 周期性刷新房间列表（专家可能新建房间或改 model/system_prompt）
                self.load_rooms()
        except asyncio.CancelledError:
            pass


# ── 子命令：set-prompt / set-model ────────────────────────────────────────────
def _login_for_admin(args) -> Client:
    sb = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    email    = args.email    or input("Chat2GO 专家邮箱: ").strip()
    password = args.password or input("Chat2GO 密码: ").strip()
    sb.auth.sign_in_with_password({"email": email, "password": password})
    return sb


def cmd_set_prompt(args):
    sb = _login_for_admin(args)
    sb.table("rooms").update({"system_prompt": args.prompt}).eq("id", args.room_id).execute()
    print(f"[bridge] room {args.room_id[:8]}… system_prompt 已更新。")


def cmd_set_model(args):
    sb = _login_for_admin(args)
    sb.table("rooms").update({"model": args.model}).eq("id", args.room_id).execute()
    print(f"[bridge] room {args.room_id[:8]}… model 已更新为 {args.model}。")


# ── 入口 ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Chat2GO · Hermes Bridge — 把本地 Hermes Agent 接入 Chat2GO 调试室"
    )
    parser.add_argument("--email",    help="Chat2GO 专家邮箱")
    parser.add_argument("--password", help="Chat2GO 密码")
    parser.add_argument("--model",    default="", help="默认模型（可被 room.model 覆盖）")
    parser.add_argument("--skills",   default="", help="启动加载的 Hermes 技能（逗号分隔）")

    sub = parser.add_subparsers(dest="cmd")

    p_prompt = sub.add_parser("set-prompt", help="设置房间 system prompt")
    p_prompt.add_argument("room_id")
    p_prompt.add_argument("prompt")
    p_prompt.add_argument("--email")
    p_prompt.add_argument("--password")

    p_model = sub.add_parser("set-model", help="设置房间模型")
    p_model.add_argument("room_id")
    p_model.add_argument("model")
    p_model.add_argument("--email")
    p_model.add_argument("--password")

    args = parser.parse_args()

    if args.cmd == "set-prompt":
        cmd_set_prompt(args); return
    if args.cmd == "set-model":
        cmd_set_model(args); return

    # 检查 Hermes 是否可用
    if not HERMES_BIN or not Path(HERMES_BIN).exists():
        print(f"[bridge] ⚠️  找不到 hermes 命令。请先安装 Hermes Agent。")
        print(f"[bridge]    pip install hermes-agent && hermes setup")
        sys.exit(1)

    email    = args.email    or input("Chat2GO 专家邮箱: ").strip()
    password = args.password or input("Chat2GO 密码: ").strip()

    bridge = Chat2GOBridge(email=email, password=password, model=args.model, skills=args.skills)

    try:
        asyncio.run(bridge.run())
    except KeyboardInterrupt:
        print("\n[bridge] 已退出。")


if __name__ == "__main__":
    main()
