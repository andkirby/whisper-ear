from whisper_ear.config import load_config


def test_load_config_returns_defaults_for_missing_file(tmp_path):
    config = load_config(tmp_path / "missing.json")

    assert config["dictation"]["model"] == "base"
    assert config["dictation"]["vad_parameters"]["threshold"] == 0.45
    assert config["dictation"]["vad_parameters"]["min_silence_duration_ms"] == 500
    assert config["daemon"]["keep_loaded_models"] == ["tiny", "base"]


def test_load_config_merges_nested_sections(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        '{"dictation":{"model":"small","vad_parameters":{"threshold":0.6}}}',
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config["dictation"]["model"] == "small"
    assert config["dictation"]["initial_prompt"] == ""
    assert config["dictation"]["vad_parameters"]["threshold"] == 0.6
    assert config["dictation"]["vad_parameters"]["speech_pad_ms"] == 250
    assert config["hotkey"]["key"] == "space"
