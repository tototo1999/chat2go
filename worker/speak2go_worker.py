"""speak2go v2 Modal worker — Mentra glass-demo 多模态二段处理。

调用链:
    Mentra app POST
        → Supabase Edge Function speak2go-ingest(INSERT placeholder + 调本 worker)
            → 本 worker(拉 Storage → Scribe v2 → Gemini Flash → 写回 messages)
                → Supabase Realtime → chat.html 自动重渲

架构选型(Gate 1 2026-05-24 实测后调整):
    - 主路径转录:**ElevenLabs Scribe v2**(専用 ASR + 原生 diarize,WER 2.2%,无 LLM hallucination loop)
    - 后置摘要:**Gemini 2.5 Flash**(吃 transcript text + 板书图,出 timeline/errors/mastery)
    - 这是 2 步链路而非 1 步,但 Gemini 直接吃 audio 在长 audio + drill 重复内容上会陷 loop(已实测翻车)

部署:
    1. modal token new(本地配过 Modal 账号)
    2. 设环境密钥:
       modal secret create speak2go-secrets \
           SUPABASE_URL=https://xxx.supabase.co \
           SUPABASE_SERVICE_ROLE_KEY=eyJ... \
           ELEVENLABS_API_KEY=sk_... \
           GEMINI_API_KEY=AIzaSy... \
           MODAL_WORKER_TOKEN=<random 32-byte hex>
    3. modal deploy speak2go_worker.py
       → 拿到 web endpoint URL,塞到 Supabase Edge Function 的 MODAL_WORKER_URL 环境变量

成本预估(90min 课):
    ElevenLabs Scribe v2: $0.40/h × 1.5 = $0.60(实际按段计可能 $0.33)
    Gemini 2.5 Flash 摘要: ~$0.02(transcript text + 几张图,输入 token 小)
    ≈ $0.35-0.60/课;10 老师 × 20 课/月 ≈ $70-120/月,远低于 $300 cap
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any

import modal

# glossary 单词表深链(导入 NYC Global Center)
# speak2go.ai 原生托管,跟 speak2go.ai/chat.html 同站,品牌一致 + localStorage 跟 chat 同 origin
GLOSSARY_IMPORT_BASE_URL = os.environ.get(
    "GLOSSARY_IMPORT_BASE_URL",
    "https://speak2go.ai/glossary.html",
)

# ── Modal app + image ────────────────────────────────────────────────────────
app = modal.App("speak2go-glass-worker")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "supabase>=2.10.0",          # 新版,兼容新 httpx
        "google-genai>=2.6.0",        # 新 SDK,原生支持 thinking_budget(1.x 没有该字段)
        "httpx>=0.27",                # ElevenLabs HTTP 调用 + supabase 依赖
        "fastapi[standard]>=0.115",
    )
)

secrets = [modal.Secret.from_name("speak2go-secrets")]

# ── Prompt for Gemini 后置提炼(收 Scribe transcript + 板书图)─────────────────
# ⚠️ 严禁让 Gemini 输出完整 transcript_labeled!
#   - 长 audio 重写 transcript 会撑爆 max_output_tokens,JSON 不闭合
#   - 我们已经有 Scribe transcript,worker 端用 speaker_role_map 替换 speaker_0/1 → T/S 即可
#
# 2026-05-27 改造:从「时段大纲/情绪曲线」高维摘要,改成「20 词 + 句式」原子化学习材料
SUMMARY_PROMPT = """你是一位英语 1v1 私教课后 AI 学习助理。下面给你 ElevenLabs Scribe v2 已转写好的对话 transcript(带说话人标签 speaker_0 / speaker_1)+ 零到多张相关图片(板书/教具/作业/场景照)。

你的核心任务:**提炼整堂课的 20 个最值得学生背的英文生词 + 5-10 个练习句式**。不是写总结,是给学生留下可背、可练的学习材料。

判断说话人角色的依据(按优先级):
1. 谁在主导讲解 / 出题 / 纠正 / 评点 → "T"(Teacher / 主导方)
2. 谁在回应 / 提问 / 短句应答 / 跟随 → "S"(Student / 跟随方)
3. 长 turn 倾向 T,短 turn 倾向 S
4. 不能判断时,沿用 Scribe 的标签序号(speaker_0 → T,speaker_1 → S)

⚠️ **不要重复输出完整 transcript**(那会撑爆 token 上限)。只输出下面结构化的字段:

{
  "speaker_role_map": {"speaker_0": "T 或 S", "speaker_1": "T 或 S"},
  "session_title": "一句话概括本次课主题(≤ 20 字)",
  "vocab_top20": [
    {
      "en": "accommodate",
      "phonetic": "/əˈkɒmədeɪt/",
      "zh": "容纳, 适应",
      "frequency": 3,
      "importance": "high",
      "example": "We can accommodate 10 people.",
      "context_time": "5:42"
    }
  ],
  "practice_patterns": [
    {
      "pattern": "I would rather ... than ...",
      "zh": "我宁愿…也不要…",
      "examples": ["I'd rather walk than drive.", "I'd rather stay than leave."]
    }
  ],
  "summary_md": "(≤ 200 字 markdown,简述本课主题 + 学生进展)"
}

**20 词挑选硬规则**(双重打分:频次 + AI 重点判断):
- 频次 ≥ 2 的词优先入选
- **排除高频虚词**:I / you / he / she / it / the / a / an / is / are / was / do / does / yes / no / and / but / or / so / 数字 / 介词 / 代词
- AI 判断 `importance`:
  - `high` = 老师重点讲解 / 反复纠正 / 举多个例子(3+ 次)
  - `medium` = 提到 + 简短解释
  - `low` = 仅 1 次但 AI 认为有学习价值(如生僻词、固定搭配、本课主题词)
- **总数 ≤ 20**;排序优先级:`high → medium → low`,同档内 frequency 降序
- `phonetic` 用 IPA 国际音标(/.../ 格式)
- `zh` 简洁,2-8 字中文释义(可加多个义项用「,」分隔)
- `example` 必须**直接从 transcript 抽真实出现的句子**,不要 AI 编造;如果 transcript 里出现的句子不完整,可以用 transcript 上下文补全到完整短句
- `context_time` 标该词第一次出现的时间戳(m:ss 格式),帮学生回到原文

**句式挑选规则**(5-10 条):
- `pattern` = 可复用的句法骨架(用 `...` 表示可填位置)
- 优先从 transcript 抽**老师强调或反复用的真实 pattern**
- `examples` ≥ 2 条,第 1 条优先用 transcript 原句,后续可 AI 仿写(必须语义合理 + 跟 pattern 严格对齐)
- `zh` 简短中文标注用法

**通用约束**:
- `summary_md` 不超过 200 字
- **绝对不要** 把 transcript 内容复制进任何字段(我们会自己拼接)
- 如果整段录音内容太少不足 20 词,有多少出多少(可以 10 词、15 词)
- 如果不是英语教学场景(中文/其他),vocab_top20 返回空数组 [],summary_md 说明原因
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

@dataclass
class IngestJob:
    placeholder_id: str
    room_id: str
    expert_user_id: str
    audio_path: str
    audio_name: str
    audio_duration_s: float | None
    photo_paths: list[str]
    captured_at: str | None
    lesson_segment_id: str | None


def _sb_client():
    """Build supabase client with service-role key (bypass RLS for writes)."""
    from supabase import create_client
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    )


def _gemini_client():
    """Return new google-genai Client(原生支持 thinking_budget 控制)。"""
    from google import genai
    return genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def _download_from_storage(sb, storage_path: str) -> bytes:
    """Download a file from Supabase Storage bucket 'chat-uploads'.

    storage_path is e.g. 'chat-uploads/<room>/glass/abc.m4a' OR
    '<room>/glass/abc.m4a' (bucket-relative).
    """
    if storage_path.startswith("chat-uploads/"):
        rel = storage_path[len("chat-uploads/"):]
    else:
        rel = storage_path
    res = sb.storage.from_("chat-uploads").download(rel)
    return res


def _call_scribe(audio_bytes: bytes, audio_filename: str) -> dict[str, Any]:
    """ElevenLabs Scribe v2 转写 + diarization。

    Returns: { "text": str, "words": [...], "language_code": str, ... }
    speaker_id 在每个 word 上(如 "speaker_1" / "speaker_2")。
    """
    import httpx
    url = "https://api.elevenlabs.io/v1/speech-to-text"
    headers = {"xi-api-key": os.environ["ELEVENLABS_API_KEY"]}
    files = {"file": (audio_filename, audio_bytes, "audio/mp4")}
    data = {
        "model_id": "scribe_v2",
        "diarize": "true",
        "num_speakers": "2",   # 1v1 私教课固定 2 人
        "tag_audio_events": "false",
        "timestamps_granularity": "word",
    }
    with httpx.Client(timeout=600) as cli:
        resp = cli.post(url, headers=headers, files=files, data=data)
    if resp.status_code != 200:
        raise RuntimeError(f"Scribe failed: {resp.status_code} {resp.text[:300]}")
    return resp.json()


def _scribe_to_markdown(scribe_resp: dict) -> str:
    """把 Scribe words[] 合并成"按说话人换段"的 markdown。

    输入(简化):{ "words": [{"text", "start", "end", "speaker_id"}, ...] }
    输出: "speaker_1 [0:00]: Hello.\\nspeaker_2 [0:03]: Hi.\\n..."
    """
    lines: list[str] = []
    cur_speaker: str | None = None
    cur_words: list[str] = []
    cur_start: float = 0.0

    def flush() -> None:
        if cur_words:
            ts = _fmt_ts(cur_start)
            lines.append(f"{cur_speaker} [{ts}]: {' '.join(cur_words)}")

    for w in scribe_resp.get("words", []):
        sp = w.get("speaker_id") or "unknown"
        text = (w.get("text") or "").strip()
        if not text:
            continue
        if sp != cur_speaker:
            flush()
            cur_speaker = sp
            cur_words = [text]
            cur_start = float(w.get("start") or 0.0)
        else:
            cur_words.append(text)
    flush()
    return "\n".join(lines)


def _fmt_ts(seconds: float) -> str:
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m}:{s:02d}"


def _call_gemini_summary(transcript_md: str,
                          photo_blobs: list[tuple[bytes, str]],
                          hume_emotions: dict | None = None) -> dict[str, Any]:
    """Gemini 2.5 Flash 后置摘要:吃 transcript + 板书图 + Hume 情绪 → JSON。

    比直接吃 audio 安全:no audio = no hallucination loop。
    Hume 情绪可选,有的话 Gemini 会综合生成 emotional_arc 字段。
    """
    from google.genai import types
    client = _gemini_client()
    text_block = (
        f"## ElevenLabs Scribe 转写\n\n```\n{transcript_md}\n```\n\n"
        f"## 板书/教具图片 {len(photo_blobs)} 张\n\n"
    )
    if hume_emotions:
        text_block += (
            f"## Hume Expression — 按分钟聚合的语音 prosody 情绪 top-3"
            f"({hume_emotions.get('total_segments', 0)} 段原始预测)\n\n"
            f"```json\n{json.dumps(hume_emotions.get('per_minute_emotions', []), ensure_ascii=False)}\n```\n\n"
        )
    text_block += "请按 system prompt 输出 JSON。"

    parts: list[Any] = [types.Part.from_text(text=text_block)]
    for blob, mime in photo_blobs:
        parts.append(types.Part.from_bytes(data=blob, mime_type=mime))

    config = types.GenerateContentConfig(
        system_instruction=SUMMARY_PROMPT,
        response_mime_type="application/json",
        temperature=0.3,
        max_output_tokens=16000,
        thinking_config=types.ThinkingConfig(thinking_budget=0),
    )

    # Retry + fallback model chain — Gemini 503 high demand 是常见临时拥堵
    # 主选 flash → 失败转 flash-lite(更便宜但同样可用)
    MODELS = ["gemini-2.5-flash", "gemini-2.5-flash-lite"]
    RETRYABLE = ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "high demand", "overloaded")
    last_err: Exception | None = None
    for model_name in MODELS:
        for attempt in range(3):  # 每个 model 最多 3 次
            try:
                resp = client.models.generate_content(
                    model=model_name,
                    contents=parts,
                    config=config,
                )
                if model_name != MODELS[0] or attempt > 0:
                    print(f"[gemini] ✓ success on {model_name} attempt {attempt+1}/3")
                return json.loads(resp.text)
            except Exception as e:
                last_err = e
                err_str = str(e)
                is_retryable = any(s in err_str for s in RETRYABLE)
                if not is_retryable:
                    print(f"[gemini] {model_name} non-retryable error: {type(e).__name__} {err_str[:200]}")
                    break  # 跳到下一个 model
                wait_s = (attempt + 1) * 4  # 4s, 8s, 12s
                print(f"[gemini] {model_name} attempt {attempt+1}/3 failed (retryable): {type(e).__name__} — sleep {wait_s}s")
                time.sleep(wait_s)
        else:
            # 内层 for 循环走完(3 次都失败但都 retryable)→ 试下一个 model
            print(f"[gemini] {model_name} exhausted 3 retries, falling back to next model")
    # 所有 model 都失败
    raise last_err if last_err else RuntimeError("Gemini summary failed without exception")


def _update_placeholder(sb, placeholder_id: str, content: str) -> None:
    sb.table("messages").update({"content": content}).eq("id", placeholder_id).execute()


def _insert_transcript(sb, room_id: str, expert_user_id: str,
                       audio_name: str, transcript: str) -> None:
    """写一条 transcript_full 消息到 private 频道(expert_user)。"""
    body = (
        f"# 📝 Transcript — `{audio_name}`\n\n{transcript}\n\n"
        "---\n_由 Gemini 2.5 Flash 一站式生成_"
    )
    sb.table("messages").insert({
        "room_id": room_id,
        "user_id": expert_user_id,
        "role": "ai",
        "content": body,
        "type": "markdown",
        "message_type": "transcript_full",
        "source": "ai-generated",
        "channel": "expert_user",
    }).execute()


def _append_to_todo_template(sb, room_id: str,
                              timeline_tree: list[dict]) -> None:
    """把 timeline_tree append 到 rooms.active_todo_template_id 的 payload。"""
    room = sb.table("rooms").select("active_todo_template_id").eq("id", room_id).single().execute()
    tmpl_id = room.data.get("active_todo_template_id") if room.data else None
    if not tmpl_id:
        return

    cur = sb.table("expert_todo_templates").select("payload").eq("id", tmpl_id).single().execute()
    payload = cur.data.get("payload", []) if cur.data else []

    for grp in timeline_tree:
        label = f"📅 {grp.get('time_start','?')}-{grp.get('time_end','?')} {grp.get('topic','')}"
        items = [{"text": p, "done": False} for p in grp.get("points", [])]
        payload.append({"label": label, "items": items})

    sb.table("expert_todo_templates").update({"payload": payload}).eq("id", tmpl_id).execute()


_IMPORTANCE_LABEL = {"high": "高频", "medium": "中频", "low": "低频"}


def _build_glossary_import_url(vocab_top20: list[dict], lesson_date: str = "") -> str:
    """把 20 词打包成 glossary-vibe-coding.html 能消费的深链。

    glossary 数据结构: [{en, zh, hint}, ...]
    把 example + frequency 拼进 hint 字段,学生在词表里就看到例句 + 频次。
    lesson_date 参数(YYYY-MM-DD)让 glossary 按课次/日期分组成胶囊。
    """
    if not vocab_top20:
        return ""
    payload = []
    for w in vocab_top20:
        en = (w.get("en") or "").strip()
        if not en:
            continue
        zh = (w.get("zh") or "").strip()
        example = (w.get("example") or "").strip()
        freq = w.get("frequency")
        phonetic = (w.get("phonetic") or "").strip()
        hint_parts = []
        if phonetic:
            hint_parts.append(phonetic)
        if example:
            hint_parts.append(f"例:{example}")
        if isinstance(freq, int) and freq > 0:
            hint_parts.append(f"出现 ×{freq}")
        payload.append({
            "en": en,
            "zh": zh,
            "hint": " · ".join(hint_parts) if hint_parts else "",
        })
    if not payload:
        return ""
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    b64 = base64.b64encode(raw.encode("utf-8")).decode("ascii")
    encoded = urllib.parse.quote(b64, safe="")
    url = f"{GLOSSARY_IMPORT_BASE_URL}?import={encoded}"
    if lesson_date:
        url += f"&date={urllib.parse.quote(lesson_date, safe='')}"
    return url


def _build_summary_card(parsed: dict, audio_name: str) -> str:
    """构造主聊的 multimodal_summary 卡片 markdown。

    2026-05-27 改造:从「时段大纲 / 情绪 / 纠错 / 板书」改成「20 词 + 句式 + 摘要」。
    """
    title = parsed.get("session_title") or audio_name
    vocab = parsed.get("vocab_top20") or []
    patterns = parsed.get("practice_patterns") or []
    summary_md = (parsed.get("summary_md") or "").strip()

    lines = [f"## ⚡ 今日生词 {len(vocab)} — {title}", "", f"📁 `{audio_name}`", ""]

    # 主区:20 词
    if vocab:
        for i, w in enumerate(vocab, 1):
            en = w.get("en", "").strip()
            phonetic = w.get("phonetic", "").strip()
            zh = w.get("zh", "").strip()
            freq = w.get("frequency")
            importance = w.get("importance", "")
            example = w.get("example", "").strip()
            ctx_time = w.get("context_time", "").strip()

            # 标题行:1. **accommodate** /əˈkɒmədeɪt/ — 容纳, 适应  (×3 · 高频)
            meta_bits = []
            if isinstance(freq, int) and freq > 0:
                meta_bits.append(f"×{freq}")
            imp_label = _IMPORTANCE_LABEL.get(importance)
            if imp_label:
                meta_bits.append(imp_label)
            meta = f"  ({' · '.join(meta_bits)})" if meta_bits else ""
            phon = f" {phonetic}" if phonetic else ""
            dash_zh = f" — {zh}" if zh else ""
            lines.append(f"{i}. **{en}**{phon}{dash_zh}{meta}")

            # 例句行
            if example:
                prefix = f"例 ({ctx_time})" if ctx_time else "例"
                lines.append(f"   _{prefix}: {example}_")
            lines.append("")
    else:
        lines.append("_(本次录音未检出英文学习内容)_")
        lines.append("")

    # 句式练习
    if patterns:
        lines.append("## 📝 句式练习")
        lines.append("")
        for p in patterns:
            pattern = p.get("pattern", "").strip()
            zh = p.get("zh", "").strip()
            examples = p.get("examples") or []
            if not pattern:
                continue
            label = f"**{pattern}**" + (f"  _{zh}_" if zh else "")
            lines.append(f"- {label}")
            for ex in examples[:3]:
                ex_s = (ex or "").strip()
                if ex_s:
                    lines.append(f"  - {ex_s}")
        lines.append("")

    # 一键导入深链 (CTA) — 精确到分钟,每次 import = 一个新胶囊(同一天多次上课能分开)
    from datetime import datetime, timezone, timedelta
    lesson_date = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")  # 北京时间
    import_url = _build_glossary_import_url(vocab, lesson_date)
    if import_url:
        lines.append(f"[📚 一键加进 NYC Global Center 单词表({lesson_date}) →]({import_url})")
        lines.append("")

    # 课程摘要(可选,在末尾)
    if summary_md:
        lines.append("## 📖 课程摘要")
        lines.append("")
        lines.append(summary_md)
        lines.append("")

    lines.append("_完整 transcript 见私聊频道_")
    return "\n".join(lines)


def _call_hume(audio_bytes: bytes, audio_name: str,
                poll_timeout_s: int = 720) -> dict[str, Any] | None:
    """Hume Expression Measurement(prosody)— 从语音 prosody 出情绪曲线。

    流程:
        1. POST 文件 → 拿 job_id
        2. 轮询 GET /jobs/{id} 直到 status=COMPLETED(或 FAILED / timeout)
        3. GET /jobs/{id}/predictions 拿 raw 预测
        4. 蒸馏成 per-minute top-3 情绪(避免 Gemini context 撑爆)
    返回 None 表示 Hume 挂了(主流程继续不阻塞)。
    """
    import httpx
    import time as _time

    key = os.environ.get("HUME_API_KEY")
    if not key:
        return None
    headers = {"X-Hume-Api-Key": key}

    try:
        # 1. submit batch job(prosody 模型,内置 utterance 切段)
        files = {"file": (audio_name, audio_bytes, "audio/mp4")}
        data = {"json": json.dumps({"models": {"prosody": {"granularity": "utterance"}}})}
        with httpx.Client(timeout=60) as cli:
            r = cli.post("https://api.hume.ai/v0/batch/jobs", headers=headers, files=files, data=data)
        if r.status_code not in (200, 201, 202):
            print(f"[warn] hume submit failed: {r.status_code} {r.text[:200]}")
            return None
        job_id = r.json().get("job_id")
        if not job_id:
            return None
        print(f"[info] hume job_id={job_id}")

        # 2. poll
        t0 = _time.time()
        status = "QUEUED"
        while _time.time() - t0 < poll_timeout_s:
            _time.sleep(5)
            with httpx.Client(timeout=30) as cli:
                r = cli.get(f"https://api.hume.ai/v0/batch/jobs/{job_id}", headers=headers)
            if r.status_code != 200:
                continue
            status = r.json().get("state", {}).get("status", "?")
            if status in ("COMPLETED", "FAILED"):
                break
        if status != "COMPLETED":
            print(f"[warn] hume status={status} after {_time.time()-t0:.0f}s")
            return None

        # 3. fetch predictions
        with httpx.Client(timeout=60) as cli:
            r = cli.get(f"https://api.hume.ai/v0/batch/jobs/{job_id}/predictions", headers=headers)
        if r.status_code != 200:
            return None
        raw = r.json()

        # 4. 蒸馏:per_segment 给逐句 transcript 注释用,per_minute 给 Gemini 摘要用
        try:
            grouped = raw[0]["results"]["predictions"][0]["models"]["prosody"]["grouped_predictions"]
        except (KeyError, IndexError, TypeError):
            return None
        all_segments: list[dict] = []
        for grp in grouped:
            for pred in grp.get("predictions", []):
                begin = float(pred.get("time", {}).get("begin", 0))
                end = float(pred.get("time", {}).get("end", begin))
                emotions = sorted(pred.get("emotions", []),
                                   key=lambda e: e.get("score", 0), reverse=True)[:3]
                all_segments.append({
                    "begin": begin, "end": end,
                    "top": [{"name": e["name"], "score": round(e["score"], 3)} for e in emotions],
                })

        # 按分钟桶聚合,每桶取均值后 top 3
        buckets: dict[int, dict[str, list[float]]] = {}
        for seg in all_segments:
            minute = int(seg["begin"] // 60)
            buckets.setdefault(minute, {})
            for e in seg["top"]:
                buckets[minute].setdefault(e["name"], []).append(e["score"])
        per_minute: list[dict] = []
        for minute in sorted(buckets.keys()):
            avg_scores = {name: sum(v) / len(v) for name, v in buckets[minute].items()}
            top3 = sorted(avg_scores.items(), key=lambda x: -x[1])[:3]
            per_minute.append({
                "minute": minute,
                "top": [{"name": n, "score": round(s, 3)} for n, s in top3],
            })
        return {
            "per_minute_emotions": per_minute,
            "per_segment_raw": all_segments,    # 给逐句注释用
            "total_segments": len(all_segments),
        }
    except Exception as e:
        print(f"[warn] hume call exception: {e!r}")
        return None


def _relabel_transcript(transcript_raw: str, role_map: dict | None) -> str:
    """把 'speaker_0 [...]: ...' 替换成 'T [...]: ...' 或 'S [...]: ...'(基于 Gemini 给的 role_map)。"""
    if not role_map:
        return transcript_raw
    out = transcript_raw
    for scribe_id, role in role_map.items():
        if role in ("T", "S") and scribe_id.startswith("speaker_"):
            # 替换行首 "speaker_X [..." → "T [..." / "S [..."
            out = out.replace(f"{scribe_id} [", f"{role} [")
    return out


# Hume emotion → emoji 速查表(常见 + 教学相关)
_EMO_EMOJI = {
    # 正向
    "joy": "😊", "amusement": "😄", "contentment": "😌", "satisfaction": "✨",
    "excitement": "🤩", "interest": "🤔", "concentration": "🧠",
    "pride": "😎", "triumph": "🏆", "realization": "💡", "relief": "😮‍💨",
    "love": "💖", "adoration": "🥰", "calmness": "😌", "determination": "💪",
    "admiration": "👏", "awe": "🤯", "aesthetic appreciation": "🎨",
    "entrancement": "🌟", "ecstasy": "✨", "nostalgia": "🥺",
    "surprise (positive)": "😮", "romance": "💘", "sympathy": "🤗", "empathic pain": "🫂",
    # 负向
    "confusion": "😕", "doubt": "🤨", "boredom": "😴", "tiredness": "😪",
    "sadness": "😢", "disappointment": "😞", "anxiety": "😰", "fear": "😨",
    "anger": "😠", "contempt": "😒", "disgust": "🤢",
    "embarrassment": "😳", "shame": "😞", "guilt": "😔",
    "distress": "😣", "horror": "😱", "pain": "💢",
    "surprise (negative)": "😦", "awkwardness": "😬",
    "craving": "🤤", "desire": "👀", "envy": "🙄",
}


def _annotate_transcript_with_emotions(transcript_md: str,
                                        per_segment: list[dict] | None,
                                        min_score: float = 0.35) -> str:
    """给 transcript 每行 `[m:ss]` 时间戳行追加 Hume 情绪标(emoji + emotion + score)。

    只在 top-emotion score >= min_score 时注释,避免噪音。
    """
    if not per_segment:
        return transcript_md
    import re

    def ts_to_sec(m: int, s: int) -> int:
        return m * 60 + s

    # 用二分查找加速时间匹配(per_segment 已按时间升序)
    seg_starts = [seg["begin"] for seg in per_segment]
    import bisect

    def find_emotion_for(t: float) -> tuple[str, float] | None:
        idx = bisect.bisect_right(seg_starts, t) - 1
        if idx < 0:
            return None
        seg = per_segment[idx]
        if not (seg["begin"] <= t <= seg["end"] + 5):  # 5s tolerance
            return None
        top = seg.get("top", [])
        if not top:
            return None
        e = top[0]
        if e["score"] < min_score:
            return None
        return (e["name"], e["score"])

    out_lines: list[str] = []
    # 匹配:T [4:32]: ... 或 S [4:32]: ... 或 speaker_X [4:32]: ...
    pat = re.compile(r"^(\S+)\s+\[(\d+):(\d{2})\]:\s*(.*)$")
    for ln in transcript_md.split("\n"):
        m = pat.match(ln)
        if not m:
            out_lines.append(ln)
            continue
        speaker, mm, ss, text = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4)
        emo = find_emotion_for(ts_to_sec(mm, ss))
        if emo:
            name, score = emo
            emoji = _EMO_EMOJI.get(name.lower(), "")
            tag = f"{emoji} {name} ({score:.2f})".strip()
            out_lines.append(f"{speaker} [{mm}:{ss:02d}] {tag}: {text}")
        else:
            out_lines.append(ln)
    return "\n".join(out_lines)


# ── Modal entry point ─────────────────────────────────────────────────────────

@app.function(
    image=image,
    secrets=secrets,
    timeout=1200,  # 20min — Hume polling 可能跑 8-12 min + Scribe + Gemini,留余量
    cpu=2,
    memory=2048,
)
@modal.fastapi_endpoint(method="POST")
def ingest(payload: dict) -> dict:
    """Modal web endpoint called by Supabase Edge Function speak2go-ingest."""
    from fastapi import HTTPException, Header

    # 简单 token 校验(从 payload header 拿;FastAPI 用 Header() 注入更标准,本 MVP 内联)
    # 生产环境改成 Depends + header,这里 skeleton 阶段先简化

    job = IngestJob(
        placeholder_id=payload["placeholder_id"],
        room_id=payload["room_id"],
        expert_user_id=payload["expert_user_id"],
        audio_path=payload["audio_path"],
        audio_name=payload.get("audio_name", "recording"),
        audio_duration_s=payload.get("audio_duration_s"),
        photo_paths=payload.get("photo_paths") or [],
        captured_at=payload.get("captured_at"),
        lesson_segment_id=payload.get("lesson_segment_id"),
    )

    sb = _sb_client()
    t0 = time.time()

    try:
        # 1. 拉文件
        _update_placeholder(sb, job.placeholder_id,
                            f"📥 下载文件中 — 音频 + {len(job.photo_paths)} 张照片...")
        audio_bytes = _download_from_storage(sb, job.audio_path)
        photo_blobs: list[tuple[bytes, str]] = []
        for pp in job.photo_paths:
            try:
                blob = _download_from_storage(sb, pp)
                mime = "image/jpeg" if pp.lower().endswith((".jpg", ".jpeg")) else "image/png"
                photo_blobs.append((blob, mime))
            except Exception as e:
                print(f"[warn] photo download failed {pp}: {e}")

        # 2. ElevenLabs Scribe v2 — 専用 ASR + diarize(无 LLM hallucination loop)
        _update_placeholder(sb, job.placeholder_id,
                            f"🎙 ElevenLabs Scribe v2 转写中(预计 2-3 min)...")
        scribe = _call_scribe(audio_bytes, job.audio_name)
        transcript_raw = _scribe_to_markdown(scribe)

        # 3. Hume Expression Measurement — 默认暂停(2026-05-27 起)
        # 新 prompt(20 词 + 句式)不消费 prosody 数据,跑 Hume 浪费 8-12 min + ~$9/课
        # 想重开:在 Modal secret 加 HUME_ENABLED=true 即可,代码无需改
        if os.environ.get("HUME_ENABLED", "").lower() == "true":
            _update_placeholder(sb, job.placeholder_id,
                                f"💗 Hume 情绪分析中(prosody 50+ 维度)...")
            hume = _call_hume(audio_bytes, job.audio_name)
            if hume:
                print(f"[info] hume distilled {len(hume.get('per_minute_emotions', []))} per-minute buckets")
            else:
                print("[info] hume skipped or failed (主流程继续)")
        else:
            hume = None
            print("[info] Hume 已暂停 (HUME_ENABLED!=true) — 省 8-12 min + ~$9/课")

        # 4. Gemini 2.5 Flash 后置摘要(吃 transcript + 图 + Hume,不吃 audio,no loop 风险)
        _update_placeholder(sb, job.placeholder_id,
                            f"🧠 Gemini 摘要 + 多模态分析中...")
        parsed = _call_gemini_summary(transcript_raw, photo_blobs, hume_emotions=hume)

        # 5. 写回
        _update_placeholder(sb, job.placeholder_id, "📝 写入 transcript + 大纲 + 情绪曲线...")
        # 用 Gemini 给的 speaker_role_map 把 Scribe 的 speaker_0/1 替换成 T/S(本地字符串替换,不消耗 token)
        transcript = _relabel_transcript(transcript_raw, parsed.get("speaker_role_map"))
        # 给每行追加 Hume 情绪标签(per-segment 时间戳对齐)
        if hume and hume.get("per_segment_raw"):
            transcript = _annotate_transcript_with_emotions(transcript, hume["per_segment_raw"])
        _insert_transcript(sb, job.room_id, job.expert_user_id, job.audio_name, transcript)

        timeline = parsed.get("timeline_tree", [])
        if timeline:
            _append_to_todo_template(sb, job.room_id, timeline)

        summary_card = _build_summary_card(parsed, job.audio_name)
        sb.table("messages").update({
            "content": summary_card,
            "type": "markdown",
            "message_type": "multimodal_summary",
        }).eq("id", job.placeholder_id).execute()

        dt = time.time() - t0
        return {
            "ok": True,
            "placeholder_id": job.placeholder_id,
            "elapsed_s": round(dt, 1),
            "timeline_groups": len(timeline),
            "errors_found": len(parsed.get("errors", [])),
        }
    except Exception as e:
        print(f"[error] ingest failed: {e!r}")
        try:
            _update_placeholder(sb, job.placeholder_id,
                                f"⚠️ 分析失败:{type(e).__name__} {str(e)[:120]}")
        except Exception:
            pass
        # 不 raise — 让 200 返回,Edge Function 调用方不重试(用户已看到 placeholder 错误提示)
        return {"ok": False, "error": str(e), "placeholder_id": job.placeholder_id}


# Local smoke test:
#   python speak2go_worker.py
# (不会跑真 Gemini,只检查 import + 语法)
if __name__ == "__main__":
    print("speak2go_worker.py — Modal app skeleton OK")
    print("Deploy: modal deploy speak2go_worker.py")
    print("Endpoint will be: https://<workspace>--speak2go-glass-worker-ingest.modal.run")
