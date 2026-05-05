#!/usr/bin/env python3
"""
dictated.py — Dictation daemon. Keeps whisper model in memory.

Usage:
  dictated.py start          # start daemon in background
  dictated.py stop           # stop daemon
  dictated.py status         # check if running
  dictated.py transcribe F   # send file to running daemon, get text
  dictated.py serve          # run daemon loop (used internally by start)

Protocol: writes request file, daemon picks it up, writes response file.
"""

import sys
import os
import json
import time
import signal
import subprocess
import argparse
from pathlib import Path

DAEMON_DIR = Path("/tmp/dictated")
REQUEST_FILE = DAEMON_DIR / "request.json"
RESPONSE_FILE = DAEMON_DIR / "response.json"
PID_FILE = DAEMON_DIR / "daemon.pid"
READY_FILE = DAEMON_DIR / "ready"
MODEL_NAME = os.environ.get("DICTATE_MODEL", "base")
INITIAL_PROMPT = os.environ.get("DICTATE_INITIAL_PROMPT") or None
HOTWORDS = os.environ.get("DICTATE_HOTWORDS") or None

os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"


def ensure_dir():
    DAEMON_DIR.mkdir(exist_ok=True)


def is_running():
    if not PID_FILE.exists():
        return False
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, ValueError):
        PID_FILE.unlink(missing_ok=True)
        return False


def wait_for_response(timeout=30):
    """Poll for response file, return text content."""
    start = time.time()
    while time.time() - start < timeout:
        if RESPONSE_FILE.exists():
            time.sleep(0.05)
            data = json.loads(RESPONSE_FILE.read_text())
            RESPONSE_FILE.unlink(missing_ok=True)
            return data.get("text", "")
        time.sleep(0.05)
    return ""


def cmd_start():
    ensure_dir()
    if is_running():
        print(f"Already running (PID {PID_FILE.read_text().strip()})")
        return

    # Start as a fresh process (not fork — avoids CTranslate2 threading issues)
    READY_FILE.unlink(missing_ok=True)

    subprocess.Popen(
        [sys.executable, __file__, "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )

    # Wait for daemon to signal ready (model loaded)
    for _ in range(60):  # up to 30s
        if READY_FILE.exists():
            pid = PID_FILE.read_text().strip()
            print(f"✓ Daemon started (PID {pid})")
            return
        time.sleep(0.5)

    print("✗ Daemon failed to start — try 'dictated.py serve' for logs", file=sys.stderr)
    sys.exit(1)


def cmd_serve():
    """Main daemon loop — load model once, process requests. Runs as its own process."""
    ensure_dir()
    PID_FILE.write_text(str(os.getpid()))
    READY_FILE.unlink(missing_ok=True)
    REQUEST_FILE.unlink(missing_ok=True)
    RESPONSE_FILE.unlink(missing_ok=True)

    def shutdown(sig, frame):
        PID_FILE.unlink(missing_ok=True)
        REQUEST_FILE.unlink(missing_ok=True)
        RESPONSE_FILE.unlink(missing_ok=True)
        READY_FILE.unlink(missing_ok=True)
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    from faster_whisper import WhisperModel

    t0 = time.time()
    model = WhisperModel(MODEL_NAME, device="cpu", compute_type="int8")
    load_time = time.time() - t0

    # Signal ready
    READY_FILE.write_text(f"model={MODEL_NAME} load={load_time:.1f}s")

    while True:
        if REQUEST_FILE.exists():
            try:
                req = json.loads(REQUEST_FILE.read_text())
                REQUEST_FILE.unlink(missing_ok=True)
            except (json.JSONDecodeError, FileNotFoundError):
                time.sleep(0.1)
                continue

            audio_path = req.get("file", "")
            language = req.get("language")

            try:
                segments, _ = model.transcribe(
                    audio_path,
                    language=language,
                    vad_filter=True,
                    initial_prompt=INITIAL_PROMPT,
                    hotwords=HOTWORDS,
                )
                text = " ".join(s.text.strip() for s in segments)
            except Exception:
                text = ""

            RESPONSE_FILE.write_text(json.dumps({"text": text}))

        time.sleep(0.05)


def cmd_stop():
    if not is_running():
        print("Not running")
        return
    pid = int(PID_FILE.read_text().strip())
    os.kill(pid, signal.SIGTERM)
    time.sleep(0.3)
    if not is_running():
        print("✓ Stopped")
    else:
        os.kill(pid, signal.SIGKILL)
        print("✓ Killed")


def cmd_status():
    if is_running():
        pid = PID_FILE.read_text().strip()
        ready = READY_FILE.exists()
        prompt = "on" if INITIAL_PROMPT else "off"
        hotwords = "on" if HOTWORDS else "off"
        print(f"Running (PID {pid}, model={MODEL_NAME}, ready={ready}, initial_prompt={prompt}, hotwords={hotwords})")
    else:
        print("Not running")


def cmd_transcribe(audio_path, language=None):
    if not is_running():
        print("Daemon not running — starting…", file=sys.stderr)
        cmd_start()

    ensure_dir()
    REQUEST_FILE.write_text(json.dumps({
        "file": str(audio_path),
        "language": language,
    }))

    text = wait_for_response()
    print(text)


def main():
    parser = argparse.ArgumentParser(description="Dictation daemon (keeps Whisper in memory)")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("start", help="Start daemon")
    sub.add_parser("stop", help="Stop daemon")
    sub.add_parser("status", help="Check status")
    sub.add_parser("serve", help="Run daemon loop (internal)")

    tr = sub.add_parser("transcribe", help="Transcribe a file via daemon")
    tr.add_argument("file", help="Audio file path")
    tr.add_argument("--language", "-l", default=None)

    args = parser.parse_args()

    if args.command == "start":
        cmd_start()
    elif args.command == "stop":
        cmd_stop()
    elif args.command == "status":
        cmd_status()
    elif args.command == "serve":
        cmd_serve()
    elif args.command == "transcribe":
        cmd_transcribe(args.file, args.language)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
