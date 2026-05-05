#!/usr/bin/env python3
"""
Fast dictation: transcribe a WAV file and output plain text to stdout.

Designed to be called by bin/dictate after mic recording stops.
Reuses the same faster-whisper setup as transcribe.py.

Usage:
  python3 dictate.py recording.wav
  python3 dictate.py recording.wav --model base       # faster, lower quality
  python3 dictate.py recording.wav --language en       # skip language detection
"""

import sys
import os
import argparse

# Suppress HF Hub telemetry/rate-limit noise
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

from faster_whisper import WhisperModel

MODELS = [
    "tiny", "base", "small", "medium",
    "large-v1", "large-v2", "large-v3",
    "large-v3-turbo", "distil-large-v3", "distil-large-v3.5",
]


def main():
    parser = argparse.ArgumentParser(description="Transcribe audio to plain text (stdout)")
    parser.add_argument("input", help="Audio file (WAV/MP3/etc.)")
    parser.add_argument("--model", "-m", default="base",
                        choices=MODELS,
                        help="Whisper model (default: base — optimised for speed)")
    parser.add_argument("--language", "-l", default=None,
                        help="Language code (e.g. en, de, ru). Auto-detects if omitted.")
    args = parser.parse_args()

    model = WhisperModel(args.model, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(
        args.input,
        language=args.language,
        vad_filter=True,
    )

    text = " ".join(s.text.strip() for s in segments)
    print(text)


if __name__ == "__main__":
    main()
