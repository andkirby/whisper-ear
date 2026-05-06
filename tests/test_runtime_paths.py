from whisper_ear.runtime_paths import ensure_runtime_dir, paths


def test_runtime_paths_use_configured_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("WISPER_RUNTIME_DIR", str(tmp_path))

    runtime_paths = paths()

    assert runtime_paths.socket == tmp_path / "dictated.sock"
    assert runtime_paths.audio_path("abc") == tmp_path / "audio-abc.wav"


def test_ensure_runtime_dir_creates_private_dir(monkeypatch, tmp_path):
    runtime_dir = tmp_path / "runtime"
    monkeypatch.setenv("WISPER_RUNTIME_DIR", str(runtime_dir))

    ensure_runtime_dir()

    assert runtime_dir.exists()

