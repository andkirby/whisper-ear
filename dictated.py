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

Auto-unload: models NOT in keep_loaded_models are unloaded after
unload_timeout_minutes of inactivity. The daemon keeps running but
releases the model from memory. Next request reloads it (~0.8s).
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
STATUS_FILE = DAEMON_DIR / "status.json"
LOG_FILE = DAEMON_DIR / "daemon.log"


def daemon_log(message):
    """Append to daemon log file."""
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")
    except Exception:
        pass
MODEL_NAME = os.environ.get("DICTATE_MODEL", "base")
INITIAL_PROMPT = os.environ.get("DICTATE_INITIAL_PROMPT") or None
HOTWORDS = os.environ.get("DICTATE_HOTWORDS") or None
CONFIG_PATH = os.environ.get("DICTATE_CONFIG", "")

# Defaults (overridden by config.json)
UNLOAD_TIMEOUT_MINUTES = 5
KEEP_LOADED_MODELS = ["tiny", "base"]

os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"


def load_daemon_config():
    """Load daemon settings from config.json if available."""
    global UNLOAD_TIMEOUT_MINUTES, KEEP_LOADED_MODELS

    config_file = CONFIG_PATH or str(Path(__file__).resolve().parent / "config.json")
    try:
        with open(config_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        daemon_cfg = data.get("daemon", {})
        if "unload_timeout_minutes" in daemon_cfg:
            UNLOAD_TIMEOUT_MINUTES = daemon_cfg["unload_timeout_minutes"]
        if "keep_loaded_models" in daemon_cfg:
            KEEP_LOADED_MODELS = daemon_cfg["keep_loaded_models"]
    except Exception:
        pass


def should_keep_loaded(model=None):
    """Check if the model should stay loaded permanently."""
    name = model or MODEL_NAME
    return name in KEEP_LOADED_MODELS


def write_status(state, model=None):
    """Write daemon status for external queries."""
    STATUS_FILE.write_text(json.dumps({
        "state": state,
        "model": model or MODEL_NAME,
        "pid": os.getpid(),
        "keep_loaded": should_keep_loaded(model),
    }))


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

    READY_FILE.unlink(missing_ok=True)

    env = os.environ.copy()
    if CONFIG_PATH:
        env["DICTATE_CONFIG"] = CONFIG_PATH

    subprocess.Popen(
        [sys.executable, __file__, "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        env=env,
    )

    # Wait for daemon to signal ready (model loaded)
    for _ in range(60):
        if READY_FILE.exists():
            pid = PID_FILE.read_text().strip()
            print(f"✓ Daemon started (PID {pid})")
            return
        time.sleep(0.5)

    print("✗ Daemon failed to start — try 'dictated.py serve' for logs", file=sys.stderr)
    sys.exit(1)


def cmd_serve():
    """Main daemon loop with auto-unload support."""
    ensure_dir()
    PID_FILE.write_text(str(os.getpid()))
    READY_FILE.unlink(missing_ok=True)
    REQUEST_FILE.unlink(missing_ok=True)
    RESPONSE_FILE.unlink(missing_ok=True)
    STATUS_FILE.unlink(missing_ok=True)

    load_daemon_config()

    def shutdown(sig, frame):
        for f in [PID_FILE, REQUEST_FILE, RESPONSE_FILE, READY_FILE, STATUS_FILE]:
            f.unlink(missing_ok=True)
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    from faster_whisper import WhisperModel

    model = None
    last_request_time = None

    def load_model():
        nonlocal model
        daemon_log(f"loading model {MODEL_NAME}…")
        t0 = time.time()
        model = WhisperModel(MODEL_NAME, device="cpu", compute_type="int8")
        load_time = time.time() - t0
        daemon_log(f"model {MODEL_NAME} loaded ({load_time:.1f}s)")
        READY_FILE.write_text(f"model={MODEL_NAME} load={load_time:.1f}s")
        write_status("loaded")
        return load_time

    def unload_model():
        nonlocal model
        daemon_log(f"unloading model {MODEL_NAME} (idle timeout)")
        model = None
        READY_FILE.unlink(missing_ok=True)
        write_status("unloaded")
        import gc
        gc.collect()
        daemon_log(f"model {MODEL_NAME} unloaded, memory released")

    # Initial load
    load_time = load_model()

    keep_loaded = should_keep_loaded()
    timeout_secs = UNLOAD_TIMEOUT_MINUTES * 60

    while True:
        # Check for unload timeout
        if (
            not keep_loaded
            and model is not None
            and last_request_time is not None
            and (time.time() - last_request_time) > timeout_secs
        ):
            unload_model()
            last_request_time = None

        if REQUEST_FILE.exists():
            try:
                req = json.loads(REQUEST_FILE.read_text())
                REQUEST_FILE.unlink(missing_ok=True)
            except (json.JSONDecodeError, FileNotFoundError):
                time.sleep(0.1)
                continue

            # Reload model if unloaded
            if model is None:
                daemon_log(f"model unloaded, reloading {MODEL_NAME}…")
                load_model()

            last_request_time = time.time()
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
                daemon_log(f"transcribed {len(text)} chars")
            except Exception as e:
                text = ""
                daemon_log(f"transcription error: {e}")

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
    if not is_running():
        print("Not running")
        return
    pid = PID_FILE.read_text().strip()

    # Try to read detailed status
    state = "unknown"
    model = MODEL_NAME
    keep_loaded = False
    if STATUS_FILE.exists():
        try:
            data = json.loads(STATUS_FILE.read_text())
            state = data.get("state", "unknown")
            model = data.get("model", MODEL_NAME)
            keep_loaded = data.get("keep_loaded", False)
        except Exception:
            pass

    ready = READY_FILE.exists()
    prompt = "on" if INITIAL_PROMPT else "off"
    hotwords = "on" if HOTWORDS else "off"

    parts = [f"PID {pid}", f"model={model}", f"state={state}"]
    if keep_loaded:
        parts.append("keep_loaded=yes")
    else:
        parts.append(f"unload_after={UNLOAD_TIMEOUT_MINUTES}m")
    parts.append(f"ready={ready}")
    parts.append(f"initial_prompt={prompt}")
    parts.append(f"hotwords={hotwords}")

    print(f"Running ({', '.join(parts)})")


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
