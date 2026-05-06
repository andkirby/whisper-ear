"""Recording session management for dictation."""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import signal
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .runtime_paths import RuntimePaths, ensure_runtime_dir, paths


@dataclass(frozen=True)
class RecordingSession:
    session_id: str
    rec_pid: int
    audio_path: str
    started_at: str


@contextlib.contextmanager
def recording_lock(runtime_paths: RuntimePaths | None = None):
    selected = runtime_paths or paths()
    ensure_runtime_dir(selected)
    with selected.recording_lock.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def read_session(runtime_paths: RuntimePaths | None = None) -> RecordingSession | None:
    selected = runtime_paths or paths()
    try:
        data = json.loads(selected.current_session.read_text(encoding="utf-8"))
        return RecordingSession(**data)
    except Exception:
        return None


def write_session(session: RecordingSession, runtime_paths: RuntimePaths | None = None) -> None:
    selected = runtime_paths or paths()
    ensure_runtime_dir(selected)
    tmp_path = selected.current_session.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(asdict(session), indent=2), encoding="utf-8")
    tmp_path.replace(selected.current_session)


def clear_session(runtime_paths: RuntimePaths | None = None) -> None:
    selected = runtime_paths or paths()
    selected.current_session.unlink(missing_ok=True)


def is_process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def active_session(runtime_paths: RuntimePaths | None = None) -> RecordingSession | None:
    session = read_session(runtime_paths)
    if session and is_process_alive(session.rec_pid):
        return session
    return None


def cleanup_stale_recording(runtime_paths: RuntimePaths | None = None) -> int | None:
    selected = runtime_paths or paths()
    session = read_session(selected)
    cleaned_pid = None
    if session:
        cleaned_pid = session.rec_pid
        try:
            os.kill(session.rec_pid, signal.SIGTERM)
        except OSError:
            pass
        Path(session.audio_path).unlink(missing_ok=True)
    clear_session(selected)
    return cleaned_pid


def start_recording(rec_command: str, log_path: str | Path, runtime_paths: RuntimePaths | None = None) -> RecordingSession:
    selected = runtime_paths or paths()
    ensure_runtime_dir(selected)
    session_id = f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
    audio_path = selected.audio_path(session_id)
    audio_path.unlink(missing_ok=True)
    with Path(log_path).open("ab") as log:
        proc = subprocess.Popen(
            [rec_command, "-r", "48000", "-c", "1", "-q", str(audio_path)],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    session = RecordingSession(
        session_id=session_id,
        rec_pid=proc.pid,
        audio_path=str(audio_path),
        started_at=datetime.now(timezone.utc).isoformat(),
    )
    write_session(session, selected)
    time.sleep(0.1)
    if not is_process_alive(proc.pid):
        clear_session(selected)
        audio_path.unlink(missing_ok=True)
        raise RuntimeError(f"Recording failed. Check microphone permission and {log_path}")
    return session


def stop_recording(runtime_paths: RuntimePaths | None = None) -> RecordingSession | None:
    selected = runtime_paths or paths()
    session = active_session(selected)
    clear_session(selected)
    if not session:
        return None
    try:
        os.kill(session.rec_pid, signal.SIGTERM)
    except OSError:
        pass
    time.sleep(0.3)
    return session

