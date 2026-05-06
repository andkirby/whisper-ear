#!/usr/bin/env python3
"""
dictated.py — Dictation daemon. Keeps whisper model in memory.

Usage:
  dictated.py start          # start daemon in background
  dictated.py stop           # stop daemon
  dictated.py status         # check if running
  dictated.py transcribe F   # send file to running daemon, get text
  dictated.py serve          # run daemon loop
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from whisper_ear.config import load_config
from whisper_ear.daemon_client import DaemonClientError, shutdown, status, transcribe
from whisper_ear.runtime_paths import ensure_runtime_dir, paths


ROOT = Path(__file__).resolve().parent
RUNTIME = paths()
MODEL_NAME = os.environ.get("DICTATE_MODEL", "base")
INITIAL_PROMPT = os.environ.get("DICTATE_INITIAL_PROMPT") or None
HOTWORDS = os.environ.get("DICTATE_HOTWORDS") or None
CONFIG_PATH = os.environ.get("DICTATE_CONFIG") or str(ROOT / "config.json")
VAD_PARAMETERS: dict[str, Any] | None = None
UNLOAD_TIMEOUT_MINUTES = 5
KEEP_LOADED_MODELS = ["tiny", "base"]
LOAD_MODEL_ON_START = False
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"


def daemon_log(message: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        ensure_runtime_dir(RUNTIME)
        with RUNTIME.log.open("a", encoding="utf-8") as log:
            log.write(f"[{timestamp}] {message}\n")
    except Exception:
        pass


def load_daemon_config() -> None:
    global MODEL_NAME, INITIAL_PROMPT, HOTWORDS, VAD_PARAMETERS, UNLOAD_TIMEOUT_MINUTES, KEEP_LOADED_MODELS, LOAD_MODEL_ON_START
    config = load_config(CONFIG_PATH)
    dictation = config.get("dictation", {})
    if not os.environ.get("DICTATE_MODEL"):
        MODEL_NAME = dictation.get("model", MODEL_NAME)
    if not os.environ.get("DICTATE_INITIAL_PROMPT"):
        INITIAL_PROMPT = dictation.get("initial_prompt") or None
    if not os.environ.get("DICTATE_HOTWORDS"):
        HOTWORDS = dictation.get("hotwords") or None
    configured_vad = dictation.get("vad_parameters")
    VAD_PARAMETERS = configured_vad if isinstance(configured_vad, dict) else None
    daemon = config.get("daemon", {})
    UNLOAD_TIMEOUT_MINUTES = daemon.get("unload_timeout_minutes", UNLOAD_TIMEOUT_MINUTES)
    KEEP_LOADED_MODELS = daemon.get("keep_loaded_models", KEEP_LOADED_MODELS)
    LOAD_MODEL_ON_START = bool(daemon.get("load_model_on_start", LOAD_MODEL_ON_START))


def should_keep_loaded(model: str | None = None) -> bool:
    return (model or MODEL_NAME) in KEEP_LOADED_MODELS


def is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def is_running() -> bool:
    if not RUNTIME.pid.exists():
        return False
    try:
        pid = int(RUNTIME.pid.read_text(encoding="utf-8").strip())
    except ValueError:
        RUNTIME.pid.unlink(missing_ok=True)
        return False
    if is_pid_alive(pid):
        return True
    RUNTIME.pid.unlink(missing_ok=True)
    RUNTIME.socket.unlink(missing_ok=True)
    return False


def ok_response(**values: Any) -> dict[str, Any]:
    return {"ok": True, **values}


def error_response(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message}}


class DictationDaemon:
    def __init__(self):
        self.model = None
        self.state = "starting"
        self.last_request_time: float | None = None
        self.last_error: dict[str, str] | None = None
        self.should_stop = False
        self.state_lock = threading.RLock()
        self.model_lock = threading.Lock()
        self.transcription_lock = threading.Lock()
        self.warmup_thread: threading.Thread | None = None

    def status_payload(self) -> dict[str, Any]:
        with self.state_lock:
            return ok_response(
                pid=os.getpid(),
                state=self.state,
                model=MODEL_NAME,
                keep_loaded=should_keep_loaded(),
                last_error=self.last_error,
            )

    def load_model(self) -> None:
        with self.model_lock:
            if self.model is not None:
                return
            self.state = "loading"
            daemon_log(f"loading model {MODEL_NAME}")
            try:
                from faster_whisper import WhisperModel

                started = time.time()
                self.model = WhisperModel(MODEL_NAME, device="cpu", compute_type="int8")
                daemon_log(f"model {MODEL_NAME} loaded ({time.time() - started:.1f}s)")
                self.state = "loaded"
                self.last_error = None
            except Exception as exc:
                with self.state_lock:
                    self.state = "unloaded"
                    self.last_error = {"code": "model_load_failed", "message": str(exc)}
                daemon_log(f"model load error: {exc}")
                raise

    def warm_model(self, delay_seconds: float = 0) -> dict[str, Any]:
        if self.model is not None:
            return ok_response(state=self.state, warmup_started=False)
        if self.warmup_thread and self.warmup_thread.is_alive():
            return ok_response(state=self.state, warmup_started=False)

        delay = max(0.0, delay_seconds)

        def run() -> None:
            daemon_log(f"warming model in {delay:.1f}s")
            deadline = time.time() + delay
            while not self.should_stop and time.time() < deadline:
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                time.sleep(min(0.25, remaining))
            if self.should_stop or self.model is not None:
                return
            try:
                self.load_model()
                if self.last_request_time is None:
                    self.last_request_time = time.time()
            except Exception:
                pass

        self.warmup_thread = threading.Thread(target=run, daemon=True)
        self.warmup_thread.start()
        return ok_response(state=self.state, warmup_started=True, delay_seconds=delay)

    def unload_if_idle(self) -> None:
        if should_keep_loaded() or self.model is None or self.last_request_time is None:
            return
        if time.time() - self.last_request_time <= UNLOAD_TIMEOUT_MINUTES * 60:
            return
        daemon_log(f"unloading model {MODEL_NAME} after idle timeout")
        self.model = None
        with self.state_lock:
            self.state = "unloaded"
        gc.collect()

    def transcribe_file(self, payload: dict[str, Any]) -> dict[str, Any]:
        audio_path = Path(str(payload.get("file", "")))
        if not audio_path.is_file():
            return error_response("file_not_found", f"Audio file not found: {audio_path}")

        if not self.transcription_lock.acquire(blocking=False):
            return error_response("busy", "A transcription is already running")
        try:
            try:
                self.load_model()
            except Exception as exc:
                return error_response("model_load_failed", str(exc))

            language = payload.get("language")
            with self.state_lock:
                self.state = "transcribing"
            self.last_request_time = time.time()
            try:
                segments, _ = self.model.transcribe(
                    str(audio_path),
                    language=language,
                    vad_filter=True,
                    vad_parameters=VAD_PARAMETERS,
                    initial_prompt=INITIAL_PROMPT,
                    hotwords=HOTWORDS,
                )
                text = " ".join(segment.text.strip() for segment in segments).strip()
                daemon_log(f"transcribed {len(text)} chars")
                with self.state_lock:
                    self.state = "loaded"
                    self.last_error = None
                if not text:
                    return error_response("no_speech", "No speech detected")
                return ok_response(text=text)
            except Exception as exc:
                with self.state_lock:
                    self.state = "loaded" if self.model is not None else "unloaded"
                    self.last_error = {"code": "transcription_failed", "message": str(exc)}
                daemon_log(f"transcription error: {exc}")
                return error_response("transcription_failed", str(exc))
        finally:
            self.transcription_lock.release()

    def handle(self, payload: dict[str, Any]) -> dict[str, Any]:
        method = payload.get("method")
        if method == "status":
            return self.status_payload()
        if method == "transcribe":
            return self.transcribe_file(payload)
        if method == "warmup":
            try:
                delay_seconds = float(payload.get("delay_seconds") or 0)
            except (TypeError, ValueError):
                return error_response("invalid_request", "delay_seconds must be a number")
            return self.warm_model(delay_seconds)
        if method == "shutdown":
            self.should_stop = True
            self.state = "stopping"
            return ok_response(state="stopping")
        return error_response("invalid_request", f"Unsupported method: {method}")

    def serve(self) -> None:
        ensure_runtime_dir(RUNTIME)
        RUNTIME.pid.write_text(str(os.getpid()), encoding="utf-8")
        RUNTIME.socket.unlink(missing_ok=True)

        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(RUNTIME.socket))
        server.listen(8)
        server.settimeout(0.5)
        daemon_log(f"listening on {RUNTIME.socket}")

        def stop(_sig, _frame):
            self.should_stop = True
            self.state = "stopping"

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)

        try:
            if LOAD_MODEL_ON_START:
                try:
                    self.load_model()
                except Exception:
                    pass
            else:
                with self.state_lock:
                    self.state = "unloaded"

            while not self.should_stop:
                self.unload_if_idle()
                try:
                    conn, _ = server.accept()
                except socket.timeout:
                    continue
                threading.Thread(target=self.respond, args=(conn,), daemon=True).start()
        finally:
            server.close()
            RUNTIME.socket.unlink(missing_ok=True)
            RUNTIME.pid.unlink(missing_ok=True)
            daemon_log("stopped")

    def respond(self, conn: socket.socket) -> None:
        with conn:
            response = self.read_and_handle(conn)
            conn.sendall(json.dumps(response).encode("utf-8") + b"\n")

    def read_and_handle(self, conn: socket.socket) -> dict[str, Any]:
        conn.settimeout(2.0)
        chunks: list[bytes] = []
        try:
            while True:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
                if b"\n" in chunk:
                    break
            raw = b"".join(chunks).split(b"\n", 1)[0]
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                return error_response("invalid_request", "Request must be a JSON object")
            return self.handle(payload)
        except json.JSONDecodeError:
            return error_response("invalid_request", "Malformed JSON")
        except Exception as exc:
            daemon_log(f"request error: {exc}")
            return error_response("transcription_failed", str(exc))


def cmd_start() -> None:
    load_daemon_config()
    ensure_runtime_dir(RUNTIME)
    if is_running():
        print(f"Already running (PID {RUNTIME.pid.read_text(encoding='utf-8').strip()})")
        return

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

    deadline = time.time() + 30
    last_error = "daemon did not become ready"
    while time.time() < deadline:
        try:
            data = status(timeout=1.0)
            last_error = data.get("last_error") or {}
            if last_error.get("code") == "model_load_failed":
                print(f"Daemon failed to load model: {last_error.get('message')}", file=sys.stderr)
                sys.exit(1)
            if data.get("state") in {"loaded", "unloaded"}:
                print(f"Daemon started (PID {data.get('pid')})")
                return
        except DaemonClientError as exc:
            last_error = exc.message
        time.sleep(0.5)

    print(f"Daemon failed to start: {last_error}", file=sys.stderr)
    sys.exit(1)


def cmd_stop() -> None:
    if not is_running():
        print("Not running")
        return
    try:
        shutdown(timeout=2.0)
    except DaemonClientError:
        pass
    time.sleep(0.3)
    if not is_running():
        print("Stopped")
        return
    pid = int(RUNTIME.pid.read_text(encoding="utf-8").strip())
    os.kill(pid, signal.SIGTERM)
    time.sleep(0.3)
    if is_running():
        os.kill(pid, signal.SIGKILL)
        print("Killed")
    else:
        print("Stopped")


def cmd_status() -> None:
    load_daemon_config()
    if not is_running():
        print("Not running")
        return
    try:
        data = status(timeout=2.0)
    except DaemonClientError as exc:
        print(f"Running (PID {RUNTIME.pid.read_text(encoding='utf-8').strip()}, state=unknown, error={exc.code})")
        return

    prompt = "on" if INITIAL_PROMPT else "off"
    hotwords = "on" if HOTWORDS else "off"
    parts = [
        f"PID {data.get('pid')}",
        f"model={data.get('model', MODEL_NAME)}",
        f"state={data.get('state', 'unknown')}",
    ]
    if data.get("keep_loaded"):
        parts.append("keep_loaded=yes")
    else:
        parts.append(f"unload_after={UNLOAD_TIMEOUT_MINUTES}m")
    parts.append(f"initial_prompt={prompt}")
    parts.append(f"hotwords={hotwords}")
    print(f"Running ({', '.join(parts)})")


def cmd_transcribe(audio_path: str, language: str | None = None) -> None:
    load_daemon_config()
    if not is_running():
        print("Daemon not running - starting...", file=sys.stderr)
        cmd_start()
    try:
        print(transcribe(audio_path, language=language, timeout=90.0))
    except DaemonClientError as exc:
        if exc.code == "no_speech":
            print("")
            return
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        sys.exit(1)


def cmd_serve() -> None:
    load_daemon_config()
    DictationDaemon().serve()


def main() -> None:
    parser = argparse.ArgumentParser(description="Dictation daemon (keeps Whisper in memory)")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("start", help="Start daemon")
    sub.add_parser("stop", help="Stop daemon")
    sub.add_parser("status", help="Check status")
    sub.add_parser("serve", help="Run daemon loop")
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
