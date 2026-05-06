"""Client for the whisper-ear daemon Unix socket RPC."""

from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any

from .runtime_paths import RuntimePaths, paths


class DaemonClientError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def request(
    payload: dict[str, Any],
    runtime_paths: RuntimePaths | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    selected = runtime_paths or paths()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(timeout)
            client.connect(str(selected.socket))
            client.sendall(json.dumps(payload).encode("utf-8") + b"\n")
            chunks: list[bytes] = []
            while True:
                chunk = client.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
                if b"\n" in chunk:
                    break
    except FileNotFoundError as exc:
        raise DaemonClientError("not_running", "Daemon socket does not exist") from exc
    except (ConnectionRefusedError, socket.timeout, OSError) as exc:
        raise DaemonClientError("connection_failed", str(exc)) from exc
    raw = b"".join(chunks).split(b"\n", 1)[0]
    if not raw:
        raise DaemonClientError("empty_response", "Daemon returned an empty response")
    try:
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise DaemonClientError("invalid_response", "Daemon returned invalid JSON") from exc
    if not data.get("ok", False):
        error = data.get("error", {})
        raise DaemonClientError(error.get("code", "error"), error.get("message", "Daemon error"))
    return data


def status(runtime_paths: RuntimePaths | None = None, timeout: float = 2.0) -> dict[str, Any]:
    return request({"method": "status"}, runtime_paths=runtime_paths, timeout=timeout)


def transcribe(
    file_path: str | Path,
    language: str | None = None,
    runtime_paths: RuntimePaths | None = None,
    timeout: float = 60.0,
) -> str:
    data = request(
        {"method": "transcribe", "file": str(file_path), "language": language},
        runtime_paths=runtime_paths,
        timeout=timeout,
    )
    return data.get("text", "")


def warmup(
    delay_seconds: float = 0,
    runtime_paths: RuntimePaths | None = None,
    timeout: float = 2.0,
) -> dict[str, Any]:
    return request(
        {"method": "warmup", "delay_seconds": delay_seconds},
        runtime_paths=runtime_paths,
        timeout=timeout,
    )


def shutdown(runtime_paths: RuntimePaths | None = None, timeout: float = 2.0) -> None:
    request({"method": "shutdown"}, runtime_paths=runtime_paths, timeout=timeout)
