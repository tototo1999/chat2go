"""chat2go.ai Modal worker — 文本对话 serverless 替代 Hermes daemon。

调用链:
    chat.html 用户发消息
        → INSERT messages (role=user/expert)
        → fetch Edge Function chat2go-ingest
            → INSERT placeholder AI 消息 (content='...')
            → POST 本 worker (fire-and-forget)
                → 本 worker 拉历史 → 调 Claude → UPDATE placeholder
                    → Supabase Realtime → chat.html 自动重渲

部署(2026-05-25):
    # 复用 speak2go-secrets(已有 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY)
    modal secret create chat2go-extras ANTHROPIC_API_KEY=sk-ant-...
    modal deploy chat2go_worker.py
    # 拿到 endpoint,塞到 Supabase Edge Function chat2go-ingest 的 CHAT2GO_MODAL_WORKER_URL
    # Worker 端目前不做 token 校验,Edge Function 端 CHAT2GO_MODAL_WORKER_TOKEN
    # 仅作 header 透传(规避 Modal endpoint 公开 URL 被滥用是后续 TODO)。

成本预估:
    Claude Sonnet 4.6 单轮 ~2-4k input + 1-2k output ≈ $0.015-0.03/轮
    单房日均 50 轮 × 30 房 ≈ $20-45/日,低于 Hermes mini 电费 + 维护成本
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

import modal

# ── Modal app + image ────────────────────────────────────────────────────────
app = modal.App("chat2go-worker")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "supabase>=2.10.0",
        "anthropic>=0.39.0",
        "httpx>=0.27",
        "fastapi[standard]>=0.115",
    )
)

# 复用 speak2go-secrets(已有 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY) + chat2go-extras
# (只装 ANTHROPIC_API_KEY)。这样不用把 service_role 复制成两份,也不用从
# Supabase dashboard 重新取。
secrets = [
    modal.Secret.from_name("speak2go-secrets"),
    modal.Secret.from_name("chat2go-extras"),
]

# ── 行业 system prompt(从 supabase/functions/chat-ai/index.ts 同步过来,加 命理) ────

INDUSTRY_PROMPTS: dict[str, str] = {
    "外贸": """你是一位外贸行业的 AI 助手,专注于帮助跟单员处理外贸业务。
你熟悉:合同生成(FOB/CIF/CFR 条款)、信用证、提单、装箱单、报关、物流跟踪、汇率结算。
用简洁、专业的中文回复。对于合同条款,直接给出可复用的模板片段。""",

    "健身": """你是一位健身行业的 AI 助手,帮助健身教练管理学员和课程。
你熟悉:学员 CRM 记录、训练计划制定、体测数据分析、课程排期、营养建议。
用鼓励、专业的语气回复,给出具体可操作的建议。""",

    "地产": """你是一位房地产行业的 AI 助手,帮助中介提升带客效率。
你熟悉:房源分析、周边配套研报、客户意向判断、谈判策略、合同要点。
回复简洁有力,优先给出数据支撑的分析。""",

    "教育": """你是一位教育行业的 AI 助手,帮助学生和教师提升学习效果。
你熟悉:课件整理、知识点讲解、习题解析、学习计划制定、考点总结。
用清晰、有条理的方式解释,适合中学生和大学生理解。""",

    "量化": """你是一位量化交易领域的 AI 助手,帮助用户理解量化策略。
你熟悉:回测逻辑、因子分析、风险控制、仓位管理、Python/pandas 数据处理。
面向非专业用户时,用类比和简单语言解释复杂概念。""",

    "医疗": """你是一位医疗辅助 AI 助手,帮助医生处理患者咨询和诊疗记录整理。
重要:你只提供信息参考,不做最终诊断,每次回复都提醒用户以医生判断为准。
你熟悉:常见症状描述规范、病历整理格式、患者沟通话术。""",

    "算命": """你是一位命理研习 AI 助手,辅助命理师与求测者沟通。
你熟悉:八字四柱、紫微斗数、奇门遁甲、易经卦象、风水基础。
**重要边界**:命理输出只作传统文化研习与心理引导参考,不替代医疗、法律、金融的专业建议;
不预测寿数、不下生死断语、不鼓动改命消业的高额服务。
回复风格:中文,先列出基本盘面/卦象/格局,再给读法,最后给一两句生活化的建议;
用户给生辰八字时按公历转干支后排盘,看不全的字段直接问追问。""",
}

# 同义词映射(数据库里有 '算命' 和 '命理' 两种写法时统一)
INDUSTRY_ALIASES = {"命理": "算命"}

DEFAULT_SYSTEM = """你是 Chat2GO.ai 平台的专属 AI 助手,工作在"Chat 调试室"中。
你的目标是帮助小白和大咖共同理清需求,展示 AI 能做什么,最终为小白交付一个可以独立使用的专属 AI 助手。
请用简洁、专业的中文回复。如果需要更多信息才能准确回答,请直接追问关键细节。"""

# ── Helpers ───────────────────────────────────────────────────────────────────


def _sb_client():
    """Supabase service-role client(绕过 RLS,读全房消息)。"""
    from supabase import create_client
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    )


def _anthropic_client():
    from anthropic import Anthropic
    return Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


# 房间内最近 N 轮上下文 (足够保留 token 上下文,又不爆 200k)
HISTORY_LIMIT = 40
# Claude 模型默认(rooms.model 为空时用)
DEFAULT_MODEL = "claude-sonnet-4-6"
# 单次回复 max_tokens
MAX_TOKENS = 4096


def _load_history(sb, room_id: str, channel: str, before_message_id: str) -> list[dict]:
    """拉本房本频道 N 条历史消息,按时间升序返回。
    placeholder 自身(role=ai content='...') 也会被拉到,要在这一步过滤掉。
    """
    # 拿 trigger 消息的 created_at,确保上下文截止到它(不含 placeholder)
    trig = sb.table("messages").select("created_at").eq("id", before_message_id).single().execute()
    cutoff = trig.data["created_at"] if trig.data else None

    q = sb.table("messages") \
        .select("id, role, content, type, attachments, created_at, channel") \
        .eq("room_id", room_id) \
        .eq("channel", channel) \
        .order("created_at", desc=True) \
        .limit(HISTORY_LIMIT)
    if cutoff:
        q = q.lte("created_at", cutoff)
    rows = q.execute().data or []
    rows.reverse()  # 升序
    # 防御性过滤:placeholder 占位 AI 消息("..." / 以 ⚠️ 开头) 不该进上下文
    cleaned = [r for r in rows if not _is_placeholder(r)]
    return cleaned


def _is_placeholder(row: dict) -> bool:
    if row.get("role") != "ai":
        return False
    c = (row.get("content") or "").strip()
    return c == "..." or c.startswith("⚠️")


def _build_messages(history: list[dict]) -> list[dict]:
    """history → Anthropic messages array。
    role 映射:user / expert → 'user';ai → 'assistant'。
    连续 same role 用换行拼接,Anthropic 要求 user/assistant 交替。
    """
    out: list[dict] = []
    for r in history:
        role = "assistant" if r.get("role") == "ai" else "user"
        content = (r.get("content") or "").strip()
        if not content:
            continue
        # 把 user/expert 区分塞进 content 前缀,让 LLM 看到角色差异
        if r.get("role") == "expert":
            content = f"[大咖] {content}"
        elif r.get("role") == "user":
            content = f"[小白] {content}"
        if out and out[-1]["role"] == role:
            out[-1]["content"] += "\n\n" + content
        else:
            out.append({"role": role, "content": content})
    # 必须以 user 起头
    while out and out[0]["role"] != "user":
        out.pop(0)
    return out


def _resolve_system_prompt(industry: str, room_system_prompt: str) -> str:
    """room.system_prompt 非空时优先(大咖可自定义),否则查 INDUSTRY_PROMPTS,再否则 default。"""
    if room_system_prompt and room_system_prompt.strip():
        return room_system_prompt.strip()
    key = INDUSTRY_ALIASES.get(industry, industry)
    return INDUSTRY_PROMPTS.get(key, DEFAULT_SYSTEM)


def _looks_markdown(text: str) -> bool:
    """简单启发:含 ## / **/ - 列表 / ```代码块 等 → markdown 类型。"""
    triggers = ("##", "**", "```", "\n- ", "\n* ", "\n1. ")
    return any(t in text for t in triggers)


def _update_placeholder(sb, placeholder_id: str, content: str, msg_type: str | None = None) -> None:
    payload: dict[str, Any] = {"content": content}
    if msg_type:
        payload["type"] = msg_type
    sb.table("messages").update(payload).eq("id", placeholder_id).execute()


# ── Modal entry point ─────────────────────────────────────────────────────────

@app.function(
    image=image,
    secrets=secrets,
    timeout=600,   # 10min — 单轮 Claude 极少超 2 min,留余量
    cpu=1,
    memory=1024,
)
@modal.fastapi_endpoint(method="POST")
def ingest(payload: dict) -> dict:
    """Modal web endpoint,被 supabase/functions/chat2go-ingest 调用。"""
    placeholder_id = payload.get("placeholder_id")
    room_id = payload.get("room_id")
    trigger_message_id = payload.get("trigger_message_id")
    channel = payload.get("channel", "main")
    industry = payload.get("industry", "")
    room_system_prompt = payload.get("system_prompt", "") or ""
    model = (payload.get("model") or "").strip() or DEFAULT_MODEL

    if not (placeholder_id and room_id and trigger_message_id):
        return {"ok": False, "error": "missing_required_fields"}

    sb = _sb_client()
    t0 = time.time()

    try:
        history = _load_history(sb, room_id, channel, trigger_message_id)
        messages = _build_messages(history)
        if not messages:
            _update_placeholder(sb, placeholder_id,
                                "⚠️ 没拉到上下文消息,无法回复。请重新发一条试试。")
            return {"ok": False, "error": "empty_history"}

        system = _resolve_system_prompt(industry, room_system_prompt)

        cli = _anthropic_client()
        resp = cli.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=messages,
        )
        # 取 text
        out_text = ""
        for blk in resp.content:
            if getattr(blk, "type", None) == "text":
                out_text += getattr(blk, "text", "")
        out_text = out_text.strip() or "(AI 没有返回内容)"

        msg_type = "markdown" if _looks_markdown(out_text) else "text"
        _update_placeholder(sb, placeholder_id, out_text, msg_type=msg_type)

        dt = time.time() - t0
        return {
            "ok": True,
            "placeholder_id": placeholder_id,
            "elapsed_s": round(dt, 1),
            "model": model,
            "input_msgs": len(messages),
            "output_chars": len(out_text),
        }
    except Exception as e:
        print(f"[error] chat2go ingest failed: {e!r}")
        try:
            _update_placeholder(sb, placeholder_id,
                                f"⚠️ AI 调用失败:{type(e).__name__} {str(e)[:160]}")
        except Exception:
            pass
        return {"ok": False, "error": str(e), "placeholder_id": placeholder_id}


if __name__ == "__main__":
    print("chat2go_worker.py — Modal app skeleton OK")
    print("Deploy: modal deploy chat2go_worker.py")
    print("Endpoint will be: https://<workspace>--chat2go-worker-ingest.modal.run")
