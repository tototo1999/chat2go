"""
mlx-whisper provider for Apple Silicon.

封装 mlx-whisper 的 transcribe，给 asr_server.py 用。
模型常驻：第一次 transcribe 触发下载 + 加载，之后复用 ~/.cache/huggingface/hub 缓存。

模型选型见 plan：`large-v3-turbo`，中英混说 + 速度平衡点。
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# 检测 whisper 经典 token loop:1-6 字 ngram 连续重复 ≥ 10 次 → 截到 3 次
# 例如 "全部" × 200 → "全部全部全部",静音 / 不清楚段触发 context cascade 时常见
_HALLU_LOOP_RE = re.compile(r"(.{1,6}?)\1{9,}")


def _strip_loops(text: str) -> str:
    if not text:
        return text
    cleaned = _HALLU_LOOP_RE.sub(lambda m: m.group(1) * 3, text)
    if cleaned != text:
        logger.warning("whisper loop trimmed: %d → %d chars", len(text), len(cleaned))
    return cleaned

DEFAULT_MODEL = os.environ.get(
    "MLX_WHISPER_MODEL", "mlx-community/whisper-large-v3-turbo"
)

# Default initial_prompt — biases recognition toward English classroom vocab so专业词不被
# 误识(e.g., "options" 不再 → "upfing","said/says/shouted/closed" 等过去式更稳)。
# 中文段不受影响(whisper auto-detect 切到 zh 时此 prompt 影响很小)。可通过 env override 或调用方传参覆盖。
DEFAULT_INITIAL_PROMPT = os.environ.get(
    "MLX_WHISPER_INITIAL_PROMPT",
    "English 1-on-1 tutoring session between teacher and student. "
    "Topics: pronunciation, vocabulary, reading comprehension, past tense verbs. "
    "Common words: said, says, knocked, walked, shouted, closed, covers, shutters, "
    "bed, options, perfect, remember, exactly, actually, you know, right.",
)


@dataclass
class TranscribeResult:
    text: str
    language: str
    duration_sec: float
    elapsed_sec: float
    model: str
    # mlx-whisper 底层 segments,每段 {start, end, text} — 给 diarization 对齐用
    segments: list = None


def transcribe(
    audio_path: str | Path,
    *,
    language: str | None = None,  # None → 自动检测;"zh"/"en" 强制
    initial_prompt: str | None = None,
    model: str = DEFAULT_MODEL,
) -> TranscribeResult:
    """
    转写一个本地 wav/mp3 文件。

    Args:
        audio_path: 本地音频文件路径
        language: 'auto'/None 自动检测;指定 ISO-639-1 强制(zh/en)
        initial_prompt: 给模型一个提示词,提升专业词识别(比如知识点词表)
        model: HF repo id 或本地 mlx-converted 模型路径

    Returns:
        TranscribeResult
    """
    import mlx_whisper

    audio_path = str(audio_path)
    if not Path(audio_path).exists():
        raise FileNotFoundError(audio_path)

    t0 = time.time()
    kwargs: dict = {
        "path_or_hf_repo": model,
        # 防 token loop:不把前一段输出当下一段的 prompt,避免"全部全部全部..."级联
        "condition_on_previous_text": False,
    }
    if language and language != "auto":
        kwargs["language"] = language
    # 调用方未指定 → 走 DEFAULT_INITIAL_PROMPT(英语教学场景词表)
    _prompt = initial_prompt if initial_prompt is not None else DEFAULT_INITIAL_PROMPT
    if _prompt:
        kwargs["initial_prompt"] = _prompt

    result = mlx_whisper.transcribe(audio_path, **kwargs)
    elapsed = time.time() - t0

    text = _strip_loops((result.get("text") or "").strip())
    lang = result.get("language") or "unknown"

    # mlx-whisper 不直接给 duration,但 segments 末尾的 end 就是
    duration = 0.0
    raw_segs = result.get("segments") or []
    if raw_segs:
        duration = float(raw_segs[-1].get("end") or 0.0)

    # 提炼 segments 为 diarization 对齐用的精简结构(每段也跑 loop strip,防 segment 内 loop)
    segments = [
        {
            "start": float(s.get("start") or 0.0),
            "end":   float(s.get("end")   or 0.0),
            "text":  _strip_loops((s.get("text") or "").strip()),
        }
        for s in raw_segs
    ]

    logger.info(
        "mlx-whisper transcribed %s: lang=%s, dur=%.2fs, elapsed=%.2fs, chars=%d, segs=%d",
        Path(audio_path).name, lang, duration, elapsed, len(text), len(segments),
    )
    return TranscribeResult(
        text=text, language=lang, duration_sec=duration,
        elapsed_sec=elapsed, model=model, segments=segments,
    )


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", help="本地 wav/mp3 文件")
    parser.add_argument("--lang", default=None, help="zh/en/None=auto")
    parser.add_argument("--prompt", default=None)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    r = transcribe(args.audio, language=args.lang, initial_prompt=args.prompt, model=args.model)
    print(f"language: {r.language}")
    print(f"duration: {r.duration_sec:.2f}s")
    print(f"elapsed : {r.elapsed_sec:.2f}s  (RTF={r.elapsed_sec/max(r.duration_sec,0.01):.2f})")
    print(f"text    : {r.text}")
