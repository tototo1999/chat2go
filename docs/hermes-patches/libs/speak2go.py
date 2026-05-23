"""
speak2go 上传录音转写 handler.

老师上传 .mp3/.m4a/.wav → chat2go.py adapter 检 audio attachment → spawn
handle_audio_upload_lesson(此模块) → mlx-whisper 转写 + pyannote diarize +
T/S 启发式标注 → 主聊 todo_proposal 卡片 + 私聊 transcript_full markdown。

附属 handler:
- handle_extract_todos_from_recording — 🎙 按钮重抽 todo
- handle_translate_message — 🌐 按钮单条翻译
- handle_confirm_todo_apply / handle_discard_todo_proposal — todo 提议 ✓/✕

(实时课堂流相关 handler 2026-05-22 已 ripped:
 handle_knowledge_unit_end / handle_lesson_ended / handle_lesson_end_streamed /
 handle_timed_review / fetch_lesson_transcript / format_transcript_for_llm)
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

logger = logging.getLogger("chat2go.speak2go")

SPEAK2GO_LLM = os.environ.get("CLASSROOM_LLM", "claude-sonnet-4-5-20250929")


# ── 工具 ─────────────────────────────────────────────────────────────────────

async def call_claude(
    *, system: str, user_prompt: str, max_tokens: int = 2048,
    timeout: float = 30.0, model: Optional[str] = None,
) -> Optional[str]:
    """走 Anthropic HTTP API。失败返回 None。"""
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not anthropic_key:
        logger.warning("speak2go: 无 ANTHROPIC_API_KEY,跳过")
        return None

    async def _call():
        async with httpx.AsyncClient(timeout=timeout) as c:
            resp = await c.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": anthropic_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": model or SPEAK2GO_LLM,
                    "max_tokens": max_tokens,
                    "system": system,
                    "messages": [{"role": "user", "content": user_prompt}],
                },
            )
            resp.raise_for_status()
            return resp.json()
    try:
        result = await asyncio.wait_for(_call(), timeout=timeout + 5)
    except (asyncio.TimeoutError, httpx.HTTPError) as e:
        logger.warning("Claude 调用失败: %s", e)
        return None

    text = ""
    for block in result.get("content", []) or []:
        if block.get("type") == "text":
            text = block.get("text", "")
            break
    return text.strip() or None


async def handle_extract_todos_from_recording(
    sb, expert_id: str, room_id: str,
) -> None:
    """老师点 todo 面板 "🎙 录音提 todo" 按钮 → 拉最近 1 条上传录音的 transcript_full
    (message_type='transcript_full',handle_audio_upload_lesson 写入私聊)→ Claude Haiku
    抽 action items → append 新 group 到 active 模板 → 写 AI 回复。

    2026-05-22 改造:实时课堂流暂停后,数据源从 source='asr' 改为最近上传录音的
    transcript_full message。功能定位 = "重抽" — 上传时已经自动抽过一次 todo_proposal,
    用户嫌不全或想换角度可再点这个按钮重抽。
    """
    import json as _json
    import re as _re

    # 1. 拉最近一条上传录音生成的 transcript_full(跨天也找最新一条,不限时间窗)
    try:
        r = await (
            sb.table("messages")
            .select("id,content,created_at")
            .eq("room_id", room_id).eq("message_type", "transcript_full")
            .order("created_at", desc=True).limit(1)
            .execute()
        )
        rows = list(r.data or [])
    except Exception as e:
        logger.exception("extract_todos: 拉 transcript_full 失败: %s", e)
        rows = []

    if not rows:
        await _post_ai_reply(sb, room_id, expert_id,
            "No uploaded recording yet — upload a class audio (.mp3/.m4a/.wav) and retry.")
        return

    raw_md = (rows[0].get("content") or "").strip()
    # transcript_full markdown 格式:
    #   # 📝 Transcript — `<name>` (timestamp)
    #
    #   <body>
    #
    #   ---
    #
    #   _Speaker labels ..._
    # 提取 body — 去掉 H1 标题 + 末尾 footer
    body = raw_md
    body = _re.sub(r"^#\s+📝[^\n]*\n", "", body)  # H1 header
    body = _re.sub(r"\n+---\n+_Speaker labels[^_]*_\s*$", "", body)
    body = _re.sub(r"\n+---\n+_Speaker labeling unavailable[^_]*_\s*$", "", body)
    transcript = body.strip()
    if not transcript:
        await _post_ai_reply(sb, room_id, expert_id,
            "Latest recording transcript is empty.")
        return
    logger.info("extract_todos: using transcript_full id=%s (%d chars)",
                rows[0].get("id"), len(transcript))

    # 2. Claude Haiku 抽 JSON
    system = "你是英语老师的助教,只输出 JSON 数组,不要任何解释。"
    user_prompt = (
        "从下面老师的课堂录音转写里提取『老师课后应该做的事』。\n\n"
        "只提取以下类型(其它忽略):\n"
        "- 下节课要讲的内容\n- 学生表现出的薄弱点要补强\n"
        "- 老师答应给学生的资料/作业\n- 老师自己提到要准备/查的东西\n\n"
        "输出 JSON 数组,每项 {\"label\":\"动作\"}。label 控制 25 字内,动词开头,"
        "不要客套。没找到就输出 []。只输出 JSON。\n\n"
        f"---录音转写---\n{transcript}\n"
    )
    raw = await call_claude(
        system=system, user_prompt=user_prompt,
        max_tokens=800, timeout=30.0,
        model="claude-haiku-4-5-20251001",
    )
    items: list[dict] = []
    if raw:
        try:
            # 兼容 LLM 偶尔包 ```json ... ``` 围栏
            txt = raw.strip()
            if txt.startswith("```"):
                txt = txt.split("```", 2)[1].lstrip("json").strip()
                if txt.endswith("```"):
                    txt = txt[:-3].strip()
            parsed = _json.loads(txt)
            if isinstance(parsed, list):
                items = [
                    {"label": str(p.get("label", "")).strip()[:50]}
                    for p in parsed if isinstance(p, dict) and p.get("label")
                ]
        except Exception as e:
            logger.warning("extract_todos: parse JSON 失败 raw=%r err=%s", raw[:200], e)

    if not items:
        await _post_ai_reply(sb, room_id, expert_id,
            "这段录音里没找到明确的待办项。")
        return

    # 3. 找 active 模板,append 新 group
    try:
        room_r = await (
            sb.table("rooms").select("active_todo_template_id")
            .eq("id", room_id).maybe_single().execute()
        )
        tmpl_id = (room_r.data or {}).get("active_todo_template_id") if room_r else None
        if not tmpl_id:
            await _post_ai_reply(sb, room_id, expert_id,
                "当前房间没绑定 todo 模板,先在左侧栏初始化一下。")
            return

        tmpl_r = await (
            sb.table("expert_todo_templates").select("id,payload")
            .eq("id", tmpl_id).maybe_single().execute()
        )
        if not tmpl_r or not tmpl_r.data:
            await _post_ai_reply(sb, room_id, expert_id,
                "todo 模板不存在,可能已被删除。")
            return

        payload = list(tmpl_r.data.get("payload") or [])
        new_group = {
            "label": f"🎙 录音跟踪 — {datetime.now().strftime('%m-%d %H:%M')}",
            "items": items,
        }
        payload.append(new_group)
        await (
            sb.table("expert_todo_templates")
            .update({"payload": payload})
            .eq("id", tmpl_id).execute()
        )
    except Exception as e:
        logger.exception("extract_todos: 更新模板失败: %s", e)
        await _post_ai_reply(sb, room_id, expert_id,
            f"待办抽取成功但写入模板失败:{e}")
        return

    # 4. 写 AI 回复 — attachments 里塞 _event 触发前端 reload
    await _post_ai_reply(
        sb, room_id, expert_id,
        f"✓ 从这段录音提取了 {len(items)} 个待办,已加进左侧栏「🎙 录音跟踪」分组",
        attachments=[{"_event": "todos_updated"}],
    )
    logger.info("speak2go: extract_todos 完成 room=%s items=%d", str(room_id)[:8], len(items))


def _ffmpeg_to_wav16k_mono(src_path: str) -> str | None:
    """用 ffmpeg 把任意容器(m4a/mp3/aac/...)转成 16kHz mono PCM wav。
    返回 临时 wav 路径,失败 None。绕过 pyannote 对 m4a 容器 sample 数不齐的 quirk
    (`477888 samples instead of expected 480000`)。
    调用方负责 unlink 返回的临时文件。"""
    import subprocess as _sp
    import tempfile as _tempfile
    import os as _os
    try:
        _wf = _tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        _wf.close()
        _cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", src_path,
            "-ac", "1",          # mono
            "-ar", "16000",      # 16kHz (pyannote internal sample rate)
            "-acodec", "pcm_s16le",
            _wf.name,
        ]
        _r = _sp.run(_cmd, capture_output=True, timeout=120)
        if _r.returncode != 0:
            logger.warning("ffmpeg wav 转换失败 rc=%s stderr=%s", _r.returncode, _r.stderr[:300])
            try: _os.unlink(_wf.name)
            except: pass
            return None
        return _wf.name
    except Exception as _e:
        logger.warning("ffmpeg wav 转换异常: %s", _e)
        return None


def _diarize_and_label_from_path(local_path: str) -> dict | None:
    """对本地 wav/m4a 跑 mlx-whisper(拿 segments) + pyannote diarize + merge。

    返回 dict:{
        "labeled_md": "**T:** ...\\n\\n**S:** ...",   # 给 transcript_full 用
        "turns": [{start, end, text, speaker_label, ...}],  # 给 timeline 抽取用
    }
    任何步骤失败 → None。调用方应 fallback 到原裸 transcript。

    2026-05-22:diarize 前先 ffmpeg 转 16kHz mono wav,绕过 m4a 容器 sample 数对不齐的
    pyannote quirk。mlx-whisper 仍用原文件(它对 m4a 没问题)。
    """
    import os as _os
    try:
        from libs.asr import mlx_whisper_provider as _mlxw
        _whisper_r = _mlxw.transcribe(local_path)
    except Exception as _e:
        logger.warning("diarize: mlx-whisper 重转失败: %s", _e)
        return None
    if not _whisper_r.segments:
        logger.info("diarize: mlx-whisper 无 segments,跳过")
        return None

    # 短片跳 diarize:< 30s 一般是单人或简短交流,强制 num_speakers=2 反而引入误标
    _duration = max((s.get("end") or 0.0 for s in _whisper_r.segments), default=0.0)
    if _duration < 30.0:
        logger.info("diarize: 音频 %.1fs < 30s,跳过 diarize(短片不强行切 T/S)", _duration)
        return None

    _wav_path = _ffmpeg_to_wav16k_mono(local_path)
    if not _wav_path:
        logger.warning("diarize: ffmpeg 预转 wav 失败,跳过 diarize")
        return None

    try:
        try:
            from libs.asr import pyannote_diarizer as _pyd
            _diar_r = _pyd.diarize(_wav_path, num_speakers=2)
        except RuntimeError as _e:
            logger.warning("diarize: pyannote 不可用: %s", _e)
            return None
        except Exception as _e:
            logger.exception("diarize: pyannote 失败: %s", _e)
            return None

        try:
            from libs.asr import transcript_merger as _tm
            _turns = _tm.merge(_whisper_r.segments, _diar_r.segments)
            if not _turns:
                return None
            return {
                "labeled_md": _tm.turns_to_markdown(_turns),
                "turns": _turns,
            }
        except Exception as _e:
            logger.exception("diarize: merge 失败: %s", _e)
            return None
    finally:
        try: _os.unlink(_wav_path)
        except: pass


async def _diarize_and_label(audio_url: str, plain_transcript: str) -> dict | None:
    """URL 版:下载到 temp 文件 → 调 _diarize_and_label_from_path,返回 dict。"""
    if not audio_url:
        return None
    try:
        import tempfile as _tempfile
        import os as _os
        import httpx as _httpx
    except Exception as _e:
        logger.warning("diarize: 缺基础依赖: %s", _e)
        return None

    try:
        async with _httpx.AsyncClient(timeout=60) as _c:
            _r = await _c.get(audio_url)
            _r.raise_for_status()
            _data = _r.content
    except Exception as _e:
        logger.warning("diarize: 下载音频失败 %s: %s", audio_url[:60], _e)
        return None

    _ext = ".m4a"
    for _e in (".wav", ".mp3", ".m4a", ".aac", ".ogg", ".webm", ".flac", ".mp4"):
        if audio_url.lower().rsplit("?", 1)[0].endswith(_e):
            _ext = _e
            break

    with _tempfile.NamedTemporaryFile(suffix=_ext, delete=False) as _f:
        _f.write(_data)
        _tmp_path = _f.name
    try:
        # 同步函数放 executor,不阻塞 event loop
        _loop = asyncio.get_event_loop()
        return await _loop.run_in_executor(None, lambda: _diarize_and_label_from_path(_tmp_path))
    finally:
        try: _os.unlink(_tmp_path)
        except: pass


async def handle_audio_upload_lesson(
    sb, expert_id: str, room_id: str, transcript: str,
    audio_name: str = "uploaded audio",
    audio_url: str | None = None,
) -> None:
    """老师上传音频 → diarize 拿 timestamped turns → Haiku 抽 timeline-knowledge 树 →
    直接 append 到 active todo template(每个 timeline 段 = 1 group,知识点 = items),
    同时写 transcript_full 到私聊。

    2026-05-22 改造:替换了原"5-8 个老师课后 todo"的逻辑,改为"上课的时间轴 × 知识点
    树状轴" — 整堂课分时间段,每段下挂当时讲的知识点。
    """
    if not transcript or len(transcript.strip()) < 80:
        logger.info("audio_upload: transcript 太短(%d chars),跳过", len(transcript or ""))
        return

    # 1. 跑 diarize 拿到带时间戳的 turns(也产出 labeled markdown 给私聊用)
    try:
        _diar = await _diarize_and_label(audio_url or "", transcript)
    except Exception as _de:
        logger.warning("audio_upload: diarize 失败 fallback plain: %s", _de)
        _diar = None

    _turns = (_diar or {}).get("turns") or []
    _labeled_md = (_diar or {}).get("labeled_md")

    # 2. 写 transcript_full 到私聊 — 先做这步,不被 Haiku 失败阻塞
    if _labeled_md:
        _body = _labeled_md
        _footer = "_Speaker labels (T = teacher, S = student) inferred from voice activity._"
    else:
        _body = transcript
        _footer = "_Speaker labeling unavailable — showing plain transcript._"
    transcript_md = (
        f"# 📝 Transcript — `{audio_name}` ({datetime.now().strftime('%Y-%m-%d %H:%M')})\n\n"
        f"{_body}\n\n---\n\n{_footer}"
    )
    try:
        await sb.table("messages").insert({
            "room_id": room_id, "user_id": expert_id, "role": "ai",
            "type": "markdown", "content": transcript_md,
            "source": "ai-generated", "message_type": "transcript_full",
            "channel": "expert_user",
        }).execute()
        logger.info("speak2go: audio_upload transcript posted to private channel (labeled=%s, %d chars)",
                    bool(_labeled_md), len(_body))
    except Exception as _e:
        logger.exception("audio_upload: 私聊 transcript 写入失败: %s", _e)

    # 3. 抽 timeline-knowledge 树喂 Haiku
    #    没 turns 时(diarize 失败)就用 plain transcript,只是没时间戳,topic+points 仍能出
    import json as _json
    _has_timed = bool(_turns)
    if _has_timed:
        _max_t = max((t.get("end") or 0.0) for t in _turns)
        # 把 turns 渲染成 "[mm:ss] T/S: text" 一行一段
        _timed_lines = []
        for t in _turns:
            _s = int((t.get("start") or 0.0))
            _mmss = f"{_s//60}:{_s%60:02d}"
            _spk = t.get("speaker_label") or "?"
            _txt = (t.get("text") or "").strip()
            if _txt:
                _timed_lines.append(f"[{_mmss}] {_spk}: {_txt}")
        _timed_transcript = "\n".join(_timed_lines)
        _dur_hint = f"Total duration ~{int(_max_t//60)}:{int(_max_t%60):02d}."
    else:
        _timed_transcript = transcript
        _dur_hint = "(No timestamps available — group by topic only and put time as empty string.)"

    tree_system = (
        "You are summarizing an English class recording into a TIMELINE × KNOWLEDGE-POINTS "
        "tree. Output strict JSON only — no explanations, no markdown fences."
    )
    tree_prompt = (
        "Build a 2-level outline of the class:\n"
        "- 3-7 top-level **timeline segments**, each covering a contiguous time range and a single TOPIC.\n"
        "- Under each segment, list 1-6 **knowledge points** actually covered "
        "(vocab, grammar, pronunciation, reading skill, idiom, etc.).\n\n"
        "JSON schema (strict, no extra keys):\n"
        '[{"time": "0:00-2:30", "topic": "Reading Toh & Frog", '
        '"points": ["past tense verbs: knocked, walked", "onomatopoeia: blah blah"]}, ...]\n\n'
        "Rules:\n"
        "- `time`: 'M:SS-M:SS' or 'MM:SS-MM:SS'. If transcript has no timestamps, use empty string.\n"
        "- `topic`: ≤40 chars, in primary language of the class.\n"
        "- `points`: each ≤80 chars, concrete (concept + examples), in primary language.\n"
        "- 跳过寒暄 / 关机操作 / 无关闲聊。\n"
        f"- {_dur_hint}\n\n"
        f"---TRANSCRIPT---\n{_timed_transcript}\n"
    )
    tree_raw = await call_claude(
        system=tree_system, user_prompt=tree_prompt,
        max_tokens=1500, timeout=40.0,
        model="claude-haiku-4-5-20251001",
    )
    tree_items: list[dict] = []
    if tree_raw:
        try:
            _txt = tree_raw.strip()
            if _txt.startswith("```"):
                _txt = _txt.split("```", 2)[1].lstrip("json").strip()
                if _txt.endswith("```"):
                    _txt = _txt[:-3].strip()
            _parsed = _json.loads(_txt)
            if isinstance(_parsed, list):
                for seg in _parsed:
                    if not isinstance(seg, dict): continue
                    _topic = str(seg.get("topic", "")).strip()[:40]
                    _time = str(seg.get("time", "")).strip()[:20]
                    _pts = seg.get("points") or []
                    if not _topic or not isinstance(_pts, list): continue
                    _label = f"📅 {_time} {_topic}" if _time else f"📅 {_topic}"
                    _items = [
                        {"label": str(p).strip()[:80]}
                        for p in _pts if isinstance(p, str) and p.strip()
                    ]
                    if _items:
                        tree_items.append({"label": _label[:60], "items": _items})
        except Exception as _e:
            logger.warning("audio_upload: tree JSON parse 失败 raw=%r err=%s", tree_raw[:200], _e)

    if not tree_items:
        logger.warning("audio_upload: Haiku 没输出有效 timeline-tree,跳过 sidebar 更新")
        await _post_ai_reply(
            sb, room_id, expert_id,
            f"✓ Transcript for `{audio_name}` posted to private channel. "
            "(Couldn't auto-build a timeline outline — try uploading a clearer recording.)",
        )
        return

    # 4. Append 到 active todo template payload
    try:
        room_r = await (
            sb.table("rooms").select("active_todo_template_id")
            .eq("id", room_id).maybe_single().execute()
        )
        tmpl_id = (room_r.data or {}).get("active_todo_template_id") if room_r else None
        if not tmpl_id:
            await _post_ai_reply(sb, room_id, expert_id,
                "Outline ready but no active todo template — initialize one in the sidebar first.")
            return

        tmpl_r = await (
            sb.table("expert_todo_templates").select("id,payload")
            .eq("id", tmpl_id).maybe_single().execute()
        )
        if not tmpl_r or not tmpl_r.data:
            await _post_ai_reply(sb, room_id, expert_id,
                "Outline ready but todo template not found (may be deleted).")
            return

        payload = list(tmpl_r.data.get("payload") or [])
        payload.extend(tree_items)
        await (
            sb.table("expert_todo_templates")
            .update({"payload": payload})
            .eq("id", tmpl_id).execute()
        )
        logger.info(
            "speak2go: audio_upload timeline-tree appended (%d segments / %d total points)",
            len(tree_items), sum(len(g["items"]) for g in tree_items),
        )
    except Exception as _e:
        logger.exception("audio_upload: 更新 todo template 失败: %s", _e)
        await _post_ai_reply(sb, room_id, expert_id,
            f"Outline extracted but writing to sidebar failed: {_e}")
        return

    # 5. 写 AI 回复 — attachments._event='todos_updated' 触发前端 reload
    _summary = "\n".join(
        f"- {g['label']}: {len(g['items'])} point(s)" for g in tree_items
    )
    await _post_ai_reply(
        sb, room_id, expert_id,
        (f"✓ Outline built from `{audio_name}` — {len(tree_items)} segment(s) added to "
         f"your sidebar plan:\n\n{_summary}"),
        attachments=[{"_event": "todos_updated"}],
    )


async def handle_confirm_todo_apply(
    sb, expert_id: str, room_id: str, items: list,
) -> None:
    """老师点 ✓ Apply → append items 到 active expert_todo_templates,
    AI 消息 attachments 带 _event='todos_updated' 让前端 reload sidebar。"""
    if not items:
        return
    try:
        room_r = await sb.table("rooms").select("active_todo_template_id").eq("id", room_id).maybe_single().execute()
        tmpl_id = (room_r.data or {}).get("active_todo_template_id") if room_r else None
        if not tmpl_id:
            await _post_ai_reply(sb, room_id, expert_id, "No active todo template — initialize one first.")
            return
        tmpl_r = await sb.table("expert_todo_templates").select("id,payload").eq("id", tmpl_id).maybe_single().execute()
        if not tmpl_r or not tmpl_r.data:
            return
        payload = list(tmpl_r.data.get("payload") or [])
        payload.append({
            "label": f"📅 {datetime.now().strftime('%m-%d %H:%M')} review",
            "items": [{"label": str(it.get("label", "")).strip()[:80]} for it in items if it.get("label")],
        })
        await sb.table("expert_todo_templates").update({"payload": payload}).eq("id", tmpl_id).execute()
        await _post_ai_reply(
            sb, room_id, expert_id,
            f"✓ Applied {len(items)} items to the sidebar.",
            attachments=[{"_event": "todos_updated"}],
        )
    except Exception as e:
        logger.exception("confirm_todo_apply 失败: %s", e)


async def handle_discard_todo_proposal(
    sb, expert_id: str, room_id: str,
) -> None:
    """老师点 ✕ Discard → 写一句确认消息,proposal 卡片前端自己置灰。"""
    await _post_ai_reply(sb, room_id, expert_id, "✕ Proposal dismissed.")


async def handle_translate_message(
    sb, expert_id: str, room_id: str, source_message_id: str,
) -> None:
    """老师/学生点消息下方 🌐 翻译按钮 → 拉源消息 content → Haiku 双向翻译
    (含中文字符 → 英; 否则 → 中)→ 写 AI 消息携带 _event='translation_result'
    + source_message_id + translation,前端 Realtime 捕获后把灰字插源消息下方。"""
    import re as _re
    # 1. 拉源消息内容
    try:
        r = await (
            sb.table("messages").select("content")
            .eq("id", source_message_id).maybe_single().execute()
        )
        src_text = ((r.data or {}).get("content") or "").strip() if r else ""
    except Exception as e:
        logger.exception("translate: 拉源消息失败: %s", e)
        return
    if not src_text:
        return

    # 2. 语言检测 — 简单包含 CJK 字符就当中文(主要场景)
    has_cjk = bool(_re.search(r"[一-鿿]", src_text))
    target_lang = "American English (NYC-casual vibe)" if has_cjk else "中文(简体)"

    # 3. Haiku 翻译
    system = "You are a translation engine. Output ONLY the translation, no commentary, no quotes."
    user_prompt = (
        f"Translate the following text to {target_lang}. "
        f"Preserve names, numbers, code, emoji as-is. "
        f"Match the casual tone of the original.\n\n"
        f"---\n{src_text}\n---"
    )
    translation = await call_claude(
        system=system, user_prompt=user_prompt,
        max_tokens=2000, timeout=25.0,
        model="claude-haiku-4-5-20251001",
    )
    if not translation:
        translation = "[translation unavailable]"

    # 4. 写 AI 消息携带翻译结果(前端用 _event 标记捕获,不渲染为独立 bubble)
    try:
        await sb.table("messages").insert({
            "room_id": room_id, "user_id": expert_id, "role": "ai",
            "type": "text",
            "content": f"[translation of {source_message_id[:8]}]",
            "source": "ai-generated",
            "attachments": [{
                "_event": "translation_result",
                "source_message_id": source_message_id,
                "translation": translation,
            }],
        }).execute()
        logger.info("speak2go: translate done src=%s len=%d", source_message_id[:8], len(translation))
    except Exception as e:
        logger.exception("translate: 写 AI 回复失败: %s", e)


async def _post_ai_reply(
    sb, room_id: str, expert_id: str, text: str,
    attachments: Optional[list] = None,
) -> None:
    """写一条 AI 消息回到房,前端通过 Realtime INSERT 收到。"""
    row = {
        "room_id": room_id, "user_id": expert_id, "role": "ai",
        "type": "text", "content": text, "source": "ai-generated",
    }
    if attachments:
        row["attachments"] = attachments
    try:
        await sb.table("messages").insert(row).execute()
    except Exception as e:
        logger.exception("_post_ai_reply 失败: %s", e)
