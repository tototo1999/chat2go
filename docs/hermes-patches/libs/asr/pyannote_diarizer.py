"""
pyannote.audio speaker diarization provider for speak2go.

输入一段音频文件,输出 [(start, end, speaker_id)] timeline。
pipeline 模型常驻:首次 diarize 触发下载 + 加载,之后复用 ~/.cache/huggingface/hub。

依赖:
  pip install pyannote.audio==3.1.1
  环境变量 HF_TOKEN (用户从 https://huggingface.co/settings/tokens 拿)
  License accept: https://huggingface.co/pyannote/speaker-diarization-3.1

设计要点:
  - lazy import — 模块层不 import pyannote,避免没装时 asr_server.py 整个起不来
  - pipeline 缓存到全局 _PIPELINE,只首次创建
  - MPS (Apple Silicon GPU) 优先,失败回 CPU
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.environ.get(
    "PYANNOTE_MODEL", "pyannote/speaker-diarization-3.1"
)

# 全局 pipeline 缓存,避免每次 diarize 重新加载模型
_PIPELINE = None
_PIPELINE_DEVICE = None


@dataclass
class DiarizeResult:
    """diarize 返回结构。

    segments: [(start_sec, end_sec, speaker_id_str), ...] — 按 start 升序
    duration_sec: 输入音频时长
    elapsed_sec: diarize 自身耗时(不含模型加载)
    device: 用的设备 ('mps' | 'cpu')
    """
    segments: list
    duration_sec: float
    elapsed_sec: float
    device: str


def _get_pipeline(hf_token: str | None = None):
    """加载并缓存 diarization pipeline。"""
    global _PIPELINE, _PIPELINE_DEVICE
    if _PIPELINE is not None:
        return _PIPELINE

    from pyannote.audio import Pipeline
    import torch

    token = hf_token or os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if not token:
        raise RuntimeError(
            "pyannote-diarizer 需要 HF_TOKEN 环境变量。"
            "去 https://huggingface.co/settings/tokens 拿,并到 "
            "https://huggingface.co/pyannote/speaker-diarization-3.1 接 license。"
        )

    t0 = time.time()
    pipeline = Pipeline.from_pretrained(DEFAULT_MODEL, token=token)

    # 优先 MPS,失败回 CPU
    device = "cpu"
    try:
        if torch.backends.mps.is_available():
            pipeline.to(torch.device("mps"))
            device = "mps"
    except Exception as e:
        logger.warning("pyannote: MPS 不可用回 CPU: %s", e)
        pipeline.to(torch.device("cpu"))

    _PIPELINE = pipeline
    _PIPELINE_DEVICE = device
    logger.info("pyannote pipeline loaded on %s (elapsed=%.2fs)", device, time.time() - t0)
    return _PIPELINE


def diarize(
    audio_path: str | Path,
    *,
    num_speakers: int | None = None,  # 已知人数(1v1 传 2)→ 加速 + 准
    min_speakers: int | None = None,
    max_speakers: int | None = None,
    hf_token: str | None = None,
) -> DiarizeResult:
    """对单文件做 speaker diarization。

    Args:
        audio_path: 本地 wav/mp3/m4a 路径
        num_speakers: 已知说话人总数(1v1 课传 2,加速且更准)
        min_speakers/max_speakers: 范围式约束,与 num_speakers 互斥
        hf_token: 显式传 HF token (默认读 env)

    Returns:
        DiarizeResult
    """
    audio_path = str(audio_path)
    if not Path(audio_path).exists():
        raise FileNotFoundError(audio_path)

    pipeline = _get_pipeline(hf_token=hf_token)

    kwargs = {}
    if num_speakers is not None:
        kwargs["num_speakers"] = num_speakers
    else:
        if min_speakers is not None:
            kwargs["min_speakers"] = min_speakers
        if max_speakers is not None:
            kwargs["max_speakers"] = max_speakers

    t0 = time.time()
    output = pipeline(audio_path, **kwargs)
    elapsed = time.time() - t0

    # pyannote 4.x: pipeline 返回 DiarizeOutput,Annotation 在 .speaker_diarization
    # 3.x: pipeline 直接返回 Annotation
    annotation = getattr(output, "speaker_diarization", output)

    # 抽出 (start, end, speaker) 三元组
    segments = [
        (float(turn.start), float(turn.end), str(speaker))
        for turn, _, speaker in annotation.itertracks(yield_label=True)
    ]
    segments.sort(key=lambda s: s[0])

    duration = segments[-1][1] if segments else 0.0
    speakers = sorted({s[2] for s in segments})

    logger.info(
        "pyannote diarized %s: speakers=%d (%s), turns=%d, dur=%.2fs, elapsed=%.2fs",
        Path(audio_path).name, len(speakers), speakers,
        len(segments), duration, elapsed,
    )
    return DiarizeResult(
        segments=segments, duration_sec=duration,
        elapsed_sec=elapsed, device=_PIPELINE_DEVICE or "cpu",
    )


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", help="本地 wav/mp3/m4a 文件")
    parser.add_argument("--num-speakers", type=int, default=None)
    args = parser.parse_args()
    r = diarize(args.audio, num_speakers=args.num_speakers)
    print(f"device  : {r.device}")
    print(f"duration: {r.duration_sec:.2f}s")
    print(f"elapsed : {r.elapsed_sec:.2f}s  (RTF={r.elapsed_sec/max(r.duration_sec,0.01):.2f})")
    print(f"turns   : {len(r.segments)}")
    for start, end, spk in r.segments[:20]:
        print(f"  {start:6.2f}-{end:6.2f}  {spk}")
