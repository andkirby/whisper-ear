"""Config loading with whisper-ear defaults."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_CONFIG: dict[str, Any] = {
    "hotkey": {"modifiers": ["option", "shift"], "key": "space"},
    "dictation": {"model": "base", "initial_prompt": "", "hotwords": ""},
    "daemon": {"unload_timeout_minutes": 5, "keep_loaded_models": ["tiny", "base"]},
    "logging": {"enabled": True, "verbose": False, "log_transcripts": False},
}


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    defaults = {
        section: value.copy() if isinstance(value, dict) else value
        for section, value in DEFAULT_CONFIG.items()
    }
    if not config_path.exists():
        return defaults
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return defaults
    for key, value in data.items():
        if isinstance(defaults.get(key), dict) and isinstance(value, dict):
            defaults[key] = {**defaults[key], **value}
        else:
            defaults[key] = value
    return defaults
