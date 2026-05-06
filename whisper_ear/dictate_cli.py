"""CLI controller for toggle dictation."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from .daemon_client import DaemonClientError, transcribe
from .paste import paste_text
from .recording import active_session, recording_lock, start_recording, stop_recording
from .runtime_paths import ensure_runtime_dir, paths


ROOT = Path(__file__).resolve().parents[1]
DICTATED = ROOT / "dictated.py"
REC_LOG = Path("/tmp/dictate_rec.log")


def find_rec() -> str | None:
    for candidate in ("/opt/homebrew/bin/rec", "/usr/local/bin/rec", "rec"):
        resolved = shutil.which(candidate) if "/" not in candidate else candidate
        if resolved and Path(resolved).exists():
            return resolved
    return None


def daemon_status_text() -> str:
    result = subprocess.run(
        [sys.executable, str(DICTATED), "status"],
        cwd=str(ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    return result.stdout.strip()


def ensure_daemon_running() -> None:
    if "Running" in daemon_status_text():
        return
    print("Starting dictation daemon...", file=sys.stderr)
    result = subprocess.run(
        [sys.executable, str(DICTATED), "start"],
        cwd=str(ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stdout.strip() or "Dictation daemon failed to start")


def check_setup() -> int:
    rec = find_rec()
    print(f"Python: {sys.executable}")
    print(f"rec: {rec or 'not found'}")
    print(daemon_status_text())
    return 0 if rec else 1


def toggle_dictation() -> int:
    runtime_paths = paths()
    ensure_runtime_dir(runtime_paths)
    rec = find_rec()
    if not rec:
        print("SoX rec not found. Run: brew install sox", file=sys.stderr)
        return 1

    print(f"Model: {os.environ.get('DICTATE_MODEL', 'base')}")
    ensure_daemon_running()

    with recording_lock(runtime_paths):
        session = active_session(runtime_paths)
        if session:
            stopped = stop_recording(runtime_paths)
            if not stopped:
                print("No active recording")
                return 0
            print("Stopped recording")
            print("Transcribing...")
            try:
                text = transcribe(stopped.audio_path, timeout=90.0)
            except DaemonClientError as exc:
                if exc.code == "no_speech":
                    print("No speech detected")
                    Path(stopped.audio_path).unlink(missing_ok=True)
                    return 0
                print(f"Error: {exc.message}")
                Path(stopped.audio_path).unlink(missing_ok=True)
                return 1
            if text:
                paste_text(text)
                print("Pasted to active app")
                print(text[:120] + ("..." if len(text) > 120 else ""))
            else:
                print("No speech detected")
            Path(stopped.audio_path).unlink(missing_ok=True)
            return 0

        session = start_recording(rec, REC_LOG, runtime_paths)
        print(f"Recording... press hotkey again to stop")
        print(f"Audio: {session.audio_path}")
        return 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        return check_setup()
    try:
        return toggle_dictation()
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
