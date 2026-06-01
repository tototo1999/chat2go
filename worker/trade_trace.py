# worker/trade_trace.py
"""Trace 采集:把一次真实请求组装成可回放的 trace 行,落 Supabase。
纯函数 build_trace_row 可单测;persist_trace best-effort 落库,失败不抛。"""
from __future__ import annotations


def _sum_usage(steps: list[dict]) -> dict:
    keys = ("input_tokens", "output_tokens",
            "cache_creation_input_tokens", "cache_read_input_tokens")
    total = {k: 0 for k in keys}
    for s in steps:
        u = s.get("usage") or {}
        for k in keys:
            total[k] += int(u.get(k) or 0)
    return total


def build_trace_row(*, room_id, trigger_message_id, expert_id, product,
                    model, system, input_messages, steps, output_text) -> dict:
    return {
        "room_id": room_id,
        "trigger_message_id": trigger_message_id,
        "expert_id": expert_id or None,
        "product": product or "tradego",
        "model": model,
        "system_prompt": system,
        "input_messages": input_messages,
        "tool_steps": steps,
        "output_text": output_text,
        "usage": _sum_usage(steps),
    }


def persist_trace(sb, row: dict) -> None:
    """best-effort 落库;任何异常吞掉,绝不影响主回复。"""
    try:
        sb.table("trade_eval_traces").insert(row).execute()
    except Exception as e:  # noqa: BLE001
        print(f"[trace] persist failed (ignored): {type(e).__name__}: {e}")
