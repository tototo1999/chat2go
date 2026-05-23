"""
合并 whisper 转写 segments + pyannote diarization timeline → speaker-labeled turns。

输入:
  whisper_segments: list[{start, end, text}]    — mlx_whisper_provider 输出
  diarization:      list[(start, end, speaker)]  — pyannote_diarizer 输出

输出:
  list[{start, end, speaker_id, text}]   — 按 start 升序的 turns

合并算法:
  每条 whisper segment 在 diarization timeline 上找重叠时长最大的 speaker。
  连续相同 speaker 的 turn 合并成一段(老师/学生连续说几句不要拆开)。

speaker → T/S 映射:
  累加每个 speaker 总说话时长,长 = T (teacher),其它 = S/S2/S3 (按总时长降序编号)。
  1v1 场景就是 T + S,直接命名;多人场景 T + S1/S2/...。
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Iterable

logger = logging.getLogger(__name__)


def _overlap_seconds(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    """两段时间的重叠时长(秒)。无重叠返回 0。"""
    s = max(a_start, b_start)
    e = min(a_end, b_end)
    return max(0.0, e - s)


def assign_speakers_to_segments(
    whisper_segments: list[dict],
    diarization: list[tuple[float, float, str]],
) -> list[dict]:
    """每条 whisper segment 找重叠最大的 speaker。

    返回 [{start, end, text, speaker_id}],speaker_id 可能是 'unknown' (无重叠 diarization)。
    """
    out = []
    for seg in whisper_segments:
        ws, we, text = seg["start"], seg["end"], seg.get("text", "")
        best_spk, best_overlap = "unknown", 0.0
        for ds, de, spk in diarization:
            ov = _overlap_seconds(ws, we, ds, de)
            if ov > best_overlap:
                best_overlap = ov
                best_spk = spk
        out.append({
            "start": ws, "end": we, "text": text,
            "speaker_id": best_spk,
        })
    return out


def merge_consecutive_same_speaker(segments: list[dict]) -> list[dict]:
    """连续同 speaker 的 segment 合并成一个 turn。"""
    if not segments:
        return []
    merged = []
    cur = dict(segments[0])
    cur["text"] = cur["text"].strip()
    for s in segments[1:]:
        if s["speaker_id"] == cur["speaker_id"]:
            cur["end"] = s["end"]
            # 用空格拼接(zh/en 都 OK,后续渲染时自然衔接)
            cur["text"] = (cur["text"] + " " + s["text"].strip()).strip()
        else:
            merged.append(cur)
            cur = dict(s)
            cur["text"] = cur["text"].strip()
    merged.append(cur)
    return merged


def map_speakers_by_total_time(
    diarization: list[tuple[float, float, str]],
) -> dict[str, str]:
    """[已弃用 2026-05-22] 按累计说话时长降序;老师纠音学生跟读场景翻车
    (学生重复跟读多 → 总时长长 → 误判为老师)。保留供历史对比/回退。
    """
    totals: dict[str, float] = defaultdict(float)
    for ds, de, spk in diarization:
        totals[spk] += max(0.0, de - ds)
    if not totals:
        return {}
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    mapping: dict[str, str] = {}
    for i, (spk_id, _dur) in enumerate(ranked):
        if i == 0:
            mapping[spk_id] = "T"
        elif len(ranked) == 2:
            mapping[spk_id] = "S"
        else:
            mapping[spk_id] = f"S{i}"
    return mapping


def map_speakers_by_text_metrics(
    tagged_segments: list[dict],
) -> dict[str, str]:
    """按复合得分降序给 speaker 起名:得分高 = T。

    多信号(2026-05-22 第二轮加 #3、#4):
      1) avg_chars_per_segment       → 排除"短词重复"型学生
      2) unique_words / total_words   → 排除"读书"型长句但词汇窄
      3) question_rate (?/段)         → 老师爱问"right?" / "you know?" / "make sense?"
      4) teach_marker_rate(动词/标记) → 老师用 "good/perfect/remember/look/try/say/exactly"

    最终:score = avg × (0.5 + uniq) × (1 + 0.3·q_rate + 0.3·tm_rate)
    """
    import re as _re
    # 教学标记词:老师高频,学生几乎不说(收集来自真实英语 1v1 课的高频 marker)
    TEACH_MARKERS = {
        "good", "perfect", "exactly", "nice", "great", "right",
        "remember", "look", "try", "say", "actually", "told", "important",
        "yes", "no", "okay", "now", "first", "next",
    }
    chars_total: dict[str, int] = defaultdict(int)
    seg_count: dict[str, int] = defaultdict(int)
    words_all: dict[str, list] = defaultdict(list)
    q_count: dict[str, int] = defaultdict(int)
    tm_count: dict[str, int] = defaultdict(int)
    for s in tagged_segments:
        sid = s.get("speaker_id")
        if not sid or sid == "unknown":
            continue
        text = (s.get("text") or "").strip()
        if not text:
            continue
        chars_total[sid] += len(text)
        seg_count[sid] += 1
        # 简易分词:英文按空格,中文按字
        _words = _re.findall(r"[A-Za-z]+|[一-鿿]", text.lower())
        words_all[sid].extend(_words)
        q_count[sid] += text.count("?")
        for w in _words:
            if w in TEACH_MARKERS:
                tm_count[sid] += 1

    if not chars_total:
        return {}

    scores: dict[str, float] = {}
    debug: dict[str, dict] = {}
    for sid in chars_total:
        avg = chars_total[sid] / max(1, seg_count[sid])
        words = words_all[sid]
        uniq_ratio = (len(set(words)) / max(1, len(words))) if words else 0.0
        q_rate = q_count[sid] / max(1, seg_count[sid])
        tm_rate = tm_count[sid] / max(1, len(words))
        # 复合:基础(长度×多样性)× 教学风格 boost
        base = avg * (0.5 + uniq_ratio)
        teach_boost = 1.0 + 0.3 * q_rate + 0.3 * tm_rate
        scores[sid] = base * teach_boost
        debug[sid] = {
            "segs": seg_count[sid], "chars": chars_total[sid],
            "avg_chars": round(avg, 1),
            "uniq_ratio": round(uniq_ratio, 2),
            "q_rate": round(q_rate, 2),
            "tm_rate": round(tm_rate, 2),
            "base": round(base, 1),
            "boost": round(teach_boost, 2),
            "score": round(scores[sid], 1),
        }

    logger.info("speaker text metrics: %s", debug)
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    mapping: dict[str, str] = {}
    for i, (spk_id, _sc) in enumerate(ranked):
        if i == 0:
            mapping[spk_id] = "T"
        elif len(ranked) == 2:
            mapping[spk_id] = "S"
        else:
            mapping[spk_id] = f"S{i}"
    return mapping


def merge(
    whisper_segments: list[dict],
    diarization: list[tuple[float, float, str]],
) -> list[dict]:
    """完整合并:重叠对齐 → 连续合并 → 映射 speaker 名称。

    输入:
      whisper_segments — mlx_whisper TranscribeResult.segments
      diarization      — pyannote_diarizer DiarizeResult.segments

    输出:
      list[{start, end, text, speaker_id, speaker_label}]
      speaker_id   — 原始 pyannote ID (SPEAKER_00 等)
      speaker_label — 人类友好 (T / S / S2)
    """
    if not whisper_segments:
        return []

    if not diarization:
        # diarize 没出 timeline,降级:全部标 unknown
        logger.warning("merger: 空 diarization,全部 turn 标 unknown")
        return [
            {**s, "speaker_id": "unknown", "speaker_label": "?"}
            for s in whisper_segments
        ]

    tagged = assign_speakers_to_segments(whisper_segments, diarization)
    # 2026-05-22:启发式从"总时长"改为"avg_chars × uniq_ratio",抗"跟读多但句短"
    spk_map = map_speakers_by_text_metrics(tagged)
    turns = merge_consecutive_same_speaker(tagged)

    for t in turns:
        t["speaker_label"] = spk_map.get(t["speaker_id"], "?")

    logger.info(
        "merger: %d whisper segs → %d turns, speaker_map=%s",
        len(whisper_segments), len(turns), spk_map,
    )
    return turns


def turns_to_markdown(turns: list[dict]) -> str:
    """把 turns 渲染成 Markdown 字符串,每个 turn 一行 `**T:** text`。"""
    lines = []
    for t in turns:
        label = t.get("speaker_label", "?")
        text = (t.get("text") or "").strip()
        if not text:
            continue
        lines.append(f"**{label}:** {text}")
    return "\n\n".join(lines)


if __name__ == "__main__":
    # 单元测试:模拟一段 1v1 对话
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    whisper = [
        {"start": 0.0,  "end": 3.0,  "text": "Hello, how are you today?"},
        {"start": 3.5,  "end": 5.0,  "text": "I'm good, thanks."},
        {"start": 5.5,  "end": 10.0, "text": "Great, let's start with vocab review."},
        {"start": 10.5, "end": 12.0, "text": "Okay."},
    ]
    diariz = [
        (0.0, 3.0, "SPEAKER_00"),
        (3.5, 5.0, "SPEAKER_01"),
        (5.5, 10.0, "SPEAKER_00"),
        (10.5, 12.0, "SPEAKER_01"),
    ]
    out = merge(whisper, diariz)
    for t in out:
        print(f"{t['start']:5.2f}-{t['end']:5.2f}  {t['speaker_label']}: {t['text']}")
    print("---")
    print(turns_to_markdown(out))
