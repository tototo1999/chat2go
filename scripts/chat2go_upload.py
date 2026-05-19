#!/usr/bin/env python3
"""
chat2go.cn 附件上传 helper (给 tradego-contract skill 用)

为什么需要这个:
- chat-uploads bucket 的 INSERT RLS 要求 authenticated session
- anon key 直接上传会 403 (row-level security policy)
- 复刻 chat2go.py 适配器的 connection_key → exchange → verify_otp 登录流程

使用:
    from chat2go_upload import upload_pdf_to_chat
    public_url = upload_pdf_to_chat("/tmp/contract.pdf", room_id="uuid-of-room")
"""
import os
import time
import threading
from pathlib import Path
import httpx
from supabase import create_client

# ── 模块级 session 缓存 ──
# _exchange_session 在整个进程生命周期只跑一次（Supabase session 默认 1 小时有效）
# 避免每次上传都重新走 Edge Function 认证导致超时
_cached_sb = None
_cached_expert_id = None
_cached_email = None
_cached_at = 0.0
_SESSION_TTL = 3000  # 50 分钟，保留 10 分钟余量
_cache_lock = threading.Lock()


def _load_creds():
    """从 ~/.hermes/.env 读 CHAT2GO_TOKEN / SUPABASE URL / ANON KEY(跟 Hermes 主进程同源)"""
    env = {}
    for line in Path("~/.hermes/.env").expanduser().read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    def get(name):
        return os.environ.get(name) or env.get(name)
    connection_key = get("CHAT2GO_TOKEN")
    supabase_url = get("CHAT2GO_SUPABASE_URL")
    supabase_anon_key = get("CHAT2GO_SUPABASE_ANON_KEY")
    if not connection_key:
        raise RuntimeError("CHAT2GO_TOKEN 没在 ~/.hermes/.env 里")
    if not (supabase_url and supabase_anon_key):
        raise RuntimeError("CHAT2GO_SUPABASE_URL/ANON_KEY 没在 ~/.hermes/.env 里")
    return connection_key, supabase_url, supabase_anon_key


def _exchange_session(connection_key, supabase_url, anon_key):
    """复刻 chat2go.py: connection_key → magiclink token_hash"""
    resp = httpx.post(
        f"{supabase_url}/functions/v1/agent-auth/exchange",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {anon_key}",
            "apikey": anon_key,
        },
        json={"key": connection_key},
        timeout=60,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"exchange failed {resp.status_code}: {resp.text[:200]}")
    return resp.json()


def authenticated_sb():
    """返回已登录的 Supabase sync client，session 在 TTL 内复用，不重复走 _exchange_session。"""
    global _cached_sb, _cached_expert_id, _cached_email, _cached_at
    with _cache_lock:
        if _cached_sb is not None and (time.time() - _cached_at) < _SESSION_TTL:
            return _cached_sb, _cached_expert_id, _cached_email
        connection_key, supabase_url, anon_key = _load_creds()
        sb = create_client(supabase_url, anon_key)
        otp = _exchange_session(connection_key, supabase_url, anon_key)
        sb.auth.verify_otp({
            "token_hash": otp["token_hash"],
            "type": "magiclink",
        })
        _cached_sb = sb
        _cached_expert_id = otp.get("expert_id")
        _cached_email = otp.get("email")
        _cached_at = time.time()
        return _cached_sb, _cached_expert_id, _cached_email


def _get_url(sb, storage_key: str, expires_in: int = 604800) -> str:
    """
    chat-uploads bucket 非 public，必须用 signed URL。
    expires_in 默认 7 天（604800s）。
    """
    result = sb.storage.from_("chat-uploads").create_signed_url(storage_key, expires_in)
    # SDK 返回 dict 或对象，兼容两种
    if isinstance(result, dict):
        path = result.get("signedURL") or result.get("signedUrl") or ""
    else:
        path = getattr(result, "signed_url", "") or getattr(result, "signedURL", "") or str(result)
    if path.startswith("/"):
        _, supabase_url, _ = _load_creds()
        return f"{supabase_url}/storage/v1{path}"
    return path


def upload_pdf_to_chat(
    pdf_path: str,
    room_id: str | None = None,
    name_hint: str = "contract",
    sb=None,  # 传入已认证的 client 可跳过 _exchange_session
) -> str:
    """
    上传 PDF 到 chat-uploads bucket，返回 signed URL（7天有效）。
    路径: tradego/{room_id or 'misc'}/{timestamp}_{name_hint}.pdf

    sb: 可选，传入 gateway adapter 的 self._sb（异步 client 会自动 fallback 到同步认证）
    """
    if sb is None:
        sb, _, _ = authenticated_sb()
    base = room_id or "misc"
    storage_key = f"tradego/{base}/{int(time.time())}_{name_hint}.pdf"
    with open(pdf_path, "rb") as f:
        sb.storage.from_("chat-uploads").upload(
            storage_key,
            f,
            {"content-type": "application/pdf"},
        )
    return _get_url(sb, storage_key)


def upload_file_to_chat(
    file_path: str,
    room_id: str | None = None,
    name_hint: str = "file",
    mime_type: str | None = None,
    expires_in: int = 604800,
) -> str:
    """
    通用文件上传：PDF / Excel / DOCX 等。
    mime_type 不传时按扩展名自动推断。
    返回 signed URL（默认 7 天有效）。
    chat-uploads bucket 非 public，不能用 get_public_url()。
    """
    import mimetypes
    sb, _, _ = authenticated_sb()
    ext = Path(file_path).suffix.lower()
    if mime_type is None:
        mime_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
    base = room_id or "misc"
    storage_key = f"tradego/{base}/{int(time.time())}_{name_hint}{ext}"
    with open(file_path, "rb") as f:
        sb.storage.from_("chat-uploads").upload(
            storage_key,
            f,
            {"content-type": mime_type},
        )
    return _get_url(sb, storage_key, expires_in)


def send_file_to_room(
    file_path: str,
    room_id: str,
    caption: str = "",
    name_hint: str | None = None,
    mime_type: str | None = None,
    expires_in: int = 604800,
) -> str:
    """
    上传文件并以附件形式发到 chat2go 房间（前端显示文件图标/预览，而非纯链接）。
    返回 message_id。

    用法：
        send_file_to_room("/tmp/PI_001.pdf", room_id="uuid", caption="PI 报价单")
        send_file_to_room("/tmp/order.xlsx", room_id="uuid", caption="装箱单")
    """
    import os, mimetypes
    from pathlib import Path

    sb, expert_id, _ = authenticated_sb()

    ext = Path(file_path).suffix.lower()
    if mime_type is None:
        mime_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"

    display_name = (name_hint or Path(file_path).name)
    if not display_name.endswith(ext):
        display_name = display_name + ext

    # storage key 只允许 ASCII，去掉中文字符
    import re as _re
    safe_name = _re.sub(r'[^\x00-\x7F]', '', display_name).strip("_- ") or f"file{ext}"

    base = room_id or "misc"
    import time as _time
    storage_key = f"tradego/{base}/{int(_time.time())}_{safe_name}"

    with open(file_path, "rb") as f:
        sb.storage.from_("chat-uploads").upload(
            storage_key, f, {"content-type": mime_type}
        )

    signed_url = _get_url(sb, storage_key, expires_in)
    file_size = os.path.getsize(file_path)

    resp = sb.table("messages").insert({
        "room_id": room_id,
        "user_id": expert_id,
        "role": "ai",
        "type": "text",
        "content": caption or display_name,
        "attachments": [{
            "url": signed_url,
            "name": display_name,
            "mime_type": mime_type,
            "size": file_size,
        }],
    }).execute()
    return (resp.data or [{}])[0].get("id", "unknown")


def send_message_to_room(
    content: str,
    room_id: str,
    expert_id: str,
    msg_type: str = "text",
) -> str:
    """
    以大咖身份向指定 room 发纯文本消息，返回 message_id。
    发文件请用 send_file_to_room()。
    """
    sb, _, _ = authenticated_sb()
    resp = sb.table("messages").insert({
        "room_id": room_id,
        "user_id": expert_id,
        "role": "ai",
        "type": msg_type,
        "content": content,
    }).execute()
    return (resp.data or [{}])[0].get("id", "unknown")


if __name__ == "__main__":
    import sys
    pdf = sys.argv[1] if len(sys.argv) > 1 else "/tmp/contract_sanity_check.pdf"
    ROOM = "0ac15b5b-e9ab-4737-873e-9ab9651f0f25"
    print(f"上传并发送附件: {pdf}")
    msg_id = send_file_to_room(pdf, room_id=ROOM, caption="测试合同")
    print(f"✅ message_id: {msg_id}")

