import json

from whisper_ear.recording import RecordingSession, clear_session, read_session, write_session
from whisper_ear.runtime_paths import paths


def test_session_write_is_readable(monkeypatch, tmp_path):
    monkeypatch.setenv("WISPER_RUNTIME_DIR", str(tmp_path))
    runtime_paths = paths()
    session = RecordingSession(
        session_id="s1",
        rec_pid=123,
        audio_path=str(tmp_path / "audio.wav"),
        started_at="2026-05-06T00:00:00Z",
    )

    write_session(session, runtime_paths)

    assert read_session(runtime_paths) == session
    assert json.loads(runtime_paths.current_session.read_text())["session_id"] == "s1"


def test_clear_session_removes_session(monkeypatch, tmp_path):
    monkeypatch.setenv("WISPER_RUNTIME_DIR", str(tmp_path))
    runtime_paths = paths()
    write_session(
        RecordingSession("s1", 123, str(tmp_path / "audio.wav"), "now"),
        runtime_paths,
    )

    clear_session(runtime_paths)

    assert read_session(runtime_paths) is None

