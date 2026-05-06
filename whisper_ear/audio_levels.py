"""Audio level helpers for live SoX WAV files."""

from __future__ import annotations

import math
import struct
from pathlib import Path

SAMPLE_RATE = 48000
SAMPLE_BYTES = 4
WAV_HEADER_BYTES = 44
DEFAULT_WINDOW_SECONDS = 0.15
DEFAULT_NORMALIZATION = 2e8


def rms_level_from_pcm_i32(raw: bytes, normalization: float = DEFAULT_NORMALIZATION) -> float:
    sample_count = len(raw) // SAMPLE_BYTES
    if sample_count < 100:
        return 0.0
    samples = struct.unpack(f"<{sample_count}i", raw[: sample_count * SAMPLE_BYTES])
    rms = math.sqrt(sum(sample * sample for sample in samples) / sample_count)
    return min(1.0, rms / normalization)


def read_wav_tail_level(
    wav_path: str | Path,
    window_seconds: float = DEFAULT_WINDOW_SECONDS,
    sample_rate: int = SAMPLE_RATE,
) -> float:
    path = Path(wav_path)
    try:
        file_size = path.stat().st_size
        if file_size < 200:
            return 0.0
        chunk_bytes = int(sample_rate * SAMPLE_BYTES * window_seconds)
        start = max(WAV_HEADER_BYTES, file_size - chunk_bytes)
        with path.open("rb") as audio:
            audio.seek(start)
            raw = audio.read()
        return rms_level_from_pcm_i32(raw)
    except Exception:
        return 0.0

