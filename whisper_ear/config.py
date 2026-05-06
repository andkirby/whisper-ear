"""Config loading with whisper-ear defaults."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any


DEFAULT_CONFIG: dict[str, Any] = {
    "hotkey": {"modifiers": ["option", "shift"], "key": "space"},
    "dictation": {
        "model": "base",
        "language": None,
        "initial_prompt": "",
        "hotwords": "",
        "vad_parameters": {
            "threshold": 0.45,
            "min_speech_duration_ms": 150,
            "min_silence_duration_ms": 500,
            "speech_pad_ms": 250,
        },
    },
    "daemon": {
        "unload_timeout_minutes": 5,
        "keep_loaded_models": ["tiny", "base"],
        "load_model_on_start": False,
        "warm_model_on_recording_start": True,
        "warm_model_delay_seconds": 5,
        "transcription_timeout_seconds": 180,
    },
    "recording": {"keep_recent_recordings": 0},
    "logging": {"enabled": True, "verbose": False, "log_transcripts": False},
}


def merge_dicts(defaults: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(defaults)
    for key, value in overrides.items():
        if isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key] = merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    defaults = deepcopy(DEFAULT_CONFIG)
    if not config_path.exists():
        return defaults
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return defaults
    return merge_dicts(defaults, data)
