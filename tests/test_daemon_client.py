import json
import shutil
import socket
import tempfile
import threading

import pytest

from whisper_ear.daemon_client import DaemonClientError, status, warmup
from whisper_ear.runtime_paths import ensure_runtime_dir, paths


def short_runtime_dir():
    return tempfile.mkdtemp(prefix="whisper-ear-test-", dir="/tmp")


def serve_once(socket_path, response):
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(socket_path))
    server.listen(1)

    def run():
        conn, _ = server.accept()
        with conn:
            conn.recv(4096)
            conn.sendall(json.dumps(response).encode("utf-8") + b"\n")
        server.close()

    thread = threading.Thread(target=run)
    thread.start()
    return thread


def serve_once_capture(socket_path, response, captured):
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(socket_path))
    server.listen(1)

    def run():
        conn, _ = server.accept()
        with conn:
            raw = conn.recv(4096).split(b"\n", 1)[0]
            captured.append(json.loads(raw.decode("utf-8")))
            conn.sendall(json.dumps(response).encode("utf-8") + b"\n")
        server.close()

    thread = threading.Thread(target=run)
    thread.start()
    return thread


def test_status_reads_framed_json(monkeypatch):
    runtime_dir = short_runtime_dir()
    monkeypatch.setenv("WISPER_RUNTIME_DIR", runtime_dir)
    runtime_paths = paths()
    ensure_runtime_dir(runtime_paths)
    thread = serve_once(runtime_paths.socket, {"ok": True, "state": "loaded"})

    data = status(runtime_paths)
    thread.join(timeout=2)
    shutil.rmtree(runtime_dir, ignore_errors=True)

    assert data["state"] == "loaded"


def test_status_raises_structured_error(monkeypatch):
    runtime_dir = short_runtime_dir()
    monkeypatch.setenv("WISPER_RUNTIME_DIR", runtime_dir)
    runtime_paths = paths()
    ensure_runtime_dir(runtime_paths)
    thread = serve_once(
        runtime_paths.socket,
        {"ok": False, "error": {"code": "busy", "message": "Already transcribing"}},
    )

    with pytest.raises(DaemonClientError) as exc_info:
        status(runtime_paths)
    thread.join(timeout=2)
    shutil.rmtree(runtime_dir, ignore_errors=True)

    assert exc_info.value.code == "busy"


def test_warmup_sends_delay(monkeypatch):
    runtime_dir = short_runtime_dir()
    monkeypatch.setenv("WISPER_RUNTIME_DIR", runtime_dir)
    runtime_paths = paths()
    ensure_runtime_dir(runtime_paths)
    captured = []
    thread = serve_once_capture(
        runtime_paths.socket,
        {"ok": True, "warmup_started": True, "delay_seconds": 5},
        captured,
    )

    data = warmup(5, runtime_paths)
    thread.join(timeout=2)
    shutil.rmtree(runtime_dir, ignore_errors=True)

    assert captured == [{"method": "warmup", "delay_seconds": 5}]
    assert data["warmup_started"] is True
