"""
SpeechBrain ECAPA-TDNN 声纹注册 + 比对.

用于 speak2go 1v1 课堂区分老师 / 学生:
- 开课前给老师 / 学生各录 10s 注册声纹 → compute_embedding → 落 profiles.voice_embedding
- 实时转写每段 → compute_embedding → cosine(emb, expert) vs cosine(emb, student) → 大者为该段角色
- 都低于阈值 → 'unknown',前端弱化显示

模型: speechbrain/spkrec-ecapa-voxceleb (~80MB)
"""

from __future__ import annotations

import io
import logging
import os
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.environ.get("SPEAKER_MODEL", "speechbrain/spkrec-ecapa-voxceleb")
DEFAULT_THRESHOLD = float(os.environ.get("SPEAKER_SIMILARITY_THRESHOLD", "0.6"))

_MODEL_CACHE: dict = {}


def _get_model(model_name: str = DEFAULT_MODEL):
    """懒加载并 cache,模型常驻内存。"""
    if model_name in _MODEL_CACHE:
        return _MODEL_CACHE[model_name]

    from speechbrain.inference.speaker import EncoderClassifier

    savedir = Path.home() / ".cache" / "speechbrain" / model_name.replace("/", "_")
    savedir.mkdir(parents=True, exist_ok=True)

    logger.info("Loading ECAPA model %s (first time may download ~80MB)…", model_name)
    classifier = EncoderClassifier.from_hparams(
        source=model_name,
        savedir=str(savedir),
        run_opts={"device": "cpu"},  # MPS 加速可改 "mps",但 1v1 课 CPU 完全够
    )
    _MODEL_CACHE[model_name] = classifier
    logger.info("ECAPA model loaded.")
    return classifier


def compute_embedding(audio_path: str | Path, model: str = DEFAULT_MODEL) -> np.ndarray:
    """从一段 wav 算 192 维声纹 embedding (numpy float32)。"""
    import soundfile as sf
    import torch
    import torchaudio

    audio_path = str(audio_path)
    classifier = _get_model(model)

    # soundfile 不依赖 torchcodec,直接读 wav/flac/aiff/mp3(libsndfile 1.2+)
    data, sr = sf.read(audio_path, dtype="float32", always_2d=False)
    if data.ndim > 1:
        data = data.mean(axis=1)  # 多通道 → mono
    signal = torch.from_numpy(data).unsqueeze(0)  # (1, samples)

    # ECAPA 要求 16kHz
    if sr != 16000:
        signal = torchaudio.functional.resample(signal, sr, 16000)

    emb = classifier.encode_batch(signal).squeeze().cpu().numpy()
    return emb.astype(np.float32)


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    """余弦相似度,值在 [-1, 1],越大越相似。"""
    a = a.flatten()
    b = b.flatten()
    denom = (np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def assign_speaker(
    seg_emb: np.ndarray,
    expert_emb: np.ndarray,
    student_emb: np.ndarray,
    *,
    threshold: float = DEFAULT_THRESHOLD,
) -> tuple[str, float, float]:
    """
    给一段录音的 embedding 分配 role。

    Returns:
        (role, sim_expert, sim_student)
        role ∈ {'expert', 'user', 'unknown'}
    """
    sim_e = cosine(seg_emb, expert_emb)
    sim_s = cosine(seg_emb, student_emb)
    if sim_e > sim_s and sim_e >= threshold:
        return "expert", sim_e, sim_s
    if sim_s > sim_e and sim_s >= threshold:
        return "user", sim_e, sim_s
    return "unknown", sim_e, sim_s


def embedding_to_bytes(emb: np.ndarray) -> bytes:
    """序列化用于落 Supabase bytea 字段。"""
    buf = io.BytesIO()
    np.save(buf, emb.astype(np.float32))
    return buf.getvalue()


def embedding_from_bytes(data: bytes) -> np.ndarray:
    buf = io.BytesIO(data)
    return np.load(buf, allow_pickle=False).astype(np.float32)


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    parser = argparse.ArgumentParser(description="ECAPA 声纹小工具")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_emb = sub.add_parser("embed", help="算 embedding")
    p_emb.add_argument("audio")

    p_cmp = sub.add_parser("compare", help="比对两段音频")
    p_cmp.add_argument("a")
    p_cmp.add_argument("b")

    p_asgn = sub.add_parser("assign", help="给一段音频分配老师/学生")
    p_asgn.add_argument("seg")
    p_asgn.add_argument("expert_ref")
    p_asgn.add_argument("student_ref")

    args = parser.parse_args()

    if args.cmd == "embed":
        emb = compute_embedding(args.audio)
        print(f"shape={emb.shape}  norm={np.linalg.norm(emb):.4f}")
        print(emb[:8], "…")

    elif args.cmd == "compare":
        ea = compute_embedding(args.a)
        eb = compute_embedding(args.b)
        sim = cosine(ea, eb)
        verdict = "SAME" if sim >= DEFAULT_THRESHOLD else "DIFF"
        print(f"cosine = {sim:.4f}  → {verdict}  (threshold={DEFAULT_THRESHOLD})")

    elif args.cmd == "assign":
        es = compute_embedding(args.seg)
        ee = compute_embedding(args.expert_ref)
        eu = compute_embedding(args.student_ref)
        role, se, su = assign_speaker(es, ee, eu)
        print(f"role={role}  sim(expert)={se:.4f}  sim(student)={su:.4f}")
