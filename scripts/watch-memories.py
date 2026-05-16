#!/usr/bin/env python3
"""
实时观察 memories 表新写入。

用法:
  ./scripts/watch-memories.py                # 看所有 scope
  ./scripts/watch-memories.py --scope expert # 只看大咖跨房间记忆
  ./scripts/watch-memories.py --scope room   # 只看本房间记忆
  ./scripts/watch-memories.py --interval 2   # 每 2 秒查一次(默认 5s)
  ./scripts/watch-memories.py --since 0      # 从 0 秒前(显示历史全部),否则从启动时算起

按 Ctrl+C 退出。

依赖:走 Hermes venv,无需额外装包。
推荐用法:
  /Users/dami2026/.hermes/hermes-agent/venv/bin/python /Users/dami2026/chat2go/scripts/watch-memories.py

或者加 alias:
  alias watch-mem='/Users/dami2026/.hermes/hermes-agent/venv/bin/python /Users/dami2026/chat2go/scripts/watch-memories.py'
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone

try:
    from supabase import acreate_client
except ImportError:
    print("ERROR: 没装 supabase-py。请用 Hermes venv 跑:")
    print("  /Users/dami2026/.hermes/hermes-agent/venv/bin/python <本脚本>")
    sys.exit(1)

# 跟 chat2go.py 一致
SUPABASE_URL = "https://qjnagbzqhoansixqharb.supabase.co"
SUPABASE_ANON_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    ".eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InFqbmFnYnpxaG9hbnNpeHFoYXJiIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzgzNDIxODIsImV4cCI6MjA5MzkxODE4Mn0"
    ".GpMUVTk6JvqeciXagXQiJunc8TLFMHg3_b9reIjJ2Y8"
)
EXPERT_EMAIL = "lirui88888862@gmail.com"
EXPERT_PASSWORD = "123456"

# ANSI 色
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"

SCOPE_COLOR = {
    "expert": MAGENTA,   # 大咖跨房间 = 紫
    "room":   GREEN,     # 本房间 = 绿
    "user":   YELLOW,    # 小白个人 = 黄
}


def fmt_local(iso_utc: str) -> str:
    """UTC ISO → 本地 HH:MM:SS"""
    try:
        dt = datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
        local = dt.astimezone()
        return local.strftime("%H:%M:%S")
    except Exception:
        return iso_utc[11:19]


def print_row(row: dict):
    scope = row.get("scope", "?")
    color = SCOPE_COLOR.get(scope, "")
    ts = fmt_local(row.get("created_at", ""))
    content = (row.get("content") or "").replace("\n", " ")[:200]
    tags = row.get("tags") or []
    tag_str = f" {DIM}[{', '.join(tags)}]{RESET}" if tags else ""
    src = (row.get("source_message_id") or "")[:8]
    print(f"{DIM}{ts}{RESET}  {color}{BOLD}[{scope:>6}]{RESET}  {content}{tag_str}  {DIM}src={src}…{RESET}")


async def main(args):
    sb = await acreate_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    await sb.auth.sign_in_with_password({"email": EXPERT_EMAIL, "password": EXPERT_PASSWORD})

    if args.since == 0:
        # 看全部历史
        cursor = "2026-01-01T00:00:00+00:00"
        print(f"{CYAN}=== 从历史开始,显示全部 memories ==={RESET}")
    else:
        # 从 N 秒前算
        from datetime import timedelta
        cursor_dt = datetime.now(timezone.utc) - timedelta(seconds=args.since)
        cursor = cursor_dt.isoformat()
        print(f"{CYAN}=== 从 {args.since}s 前开始监听 memories(scope={args.scope or 'all'},interval={args.interval}s){RESET}")
        print(f"{DIM}按 Ctrl+C 退出{RESET}\n")

    seen_ids: set[str] = set()
    while True:
        try:
            q = sb.table("memories").select("id,scope,content,tags,source_message_id,created_at").gt("created_at", cursor).order("created_at", desc=False).limit(100)
            if args.scope:
                q = q.eq("scope", args.scope)
            r = await q.execute()
            for row in r.data or []:
                rid = row.get("id")
                if rid in seen_ids:
                    continue
                seen_ids.add(rid)
                print_row(row)
                ts = row.get("created_at")
                if ts and ts > cursor:
                    cursor = ts
        except Exception as e:
            print(f"{RED}[err]{RESET} 查询失败:{e}",file=sys.stderr)
        await asyncio.sleep(args.interval)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="实时观察 chat2go memories 表新写入")
    p.add_argument("--scope", choices=["expert", "room", "user"], help="只看特定 scope")
    p.add_argument("--interval", type=int, default=5, help="轮询间隔秒(默认 5)")
    p.add_argument("--since", type=int, default=10, help="从 N 秒前开始(默认 10);0=显示全部历史")
    args = p.parse_args()
    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        print(f"\n{DIM}stopped.{RESET}")
