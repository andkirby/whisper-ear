"""Runtime path helpers for whisper-ear."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimePaths:
    root: Path
    socket: Path
    pid: Path
    log: Path
    recording_lock: Path
    current_session: Path

    def audio_path(self, session_id: str) -> Path:
        return self.root / f"audio-{session_id}.wav"


def runtime_dir() -> Path:
    configured = os.environ.get("WHISPER_EAR_RUNTIME_DIR") or os.environ.get("WISPER_RUNTIME_DIR")
    if configured:
        return Path(configured).expanduser()
    tmp = os.environ.get("TMPDIR") or tempfile.gettempdir()
    root = Path(tmp) / "whisper-ear"
    if len(str(root / "dictated.sock")) >= 100:
        root = Path("/tmp") / f"whisper-ear-{os.getuid()}"
    return root


def paths() -> RuntimePaths:
    root = runtime_dir()
    return RuntimePaths(
        root=root,
        socket=root / "dictated.sock",
        pid=root / "daemon.pid",
        log=root / "daemon.log",
        recording_lock=root / "recording.lock",
        current_session=root / "current-session.json",
    )


def ensure_runtime_dir(runtime_paths: RuntimePaths | None = None) -> Path:
    selected = runtime_paths or paths()
    selected.root.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        selected.root.chmod(0o700)
    except OSError:
        pass
    return selected.root
