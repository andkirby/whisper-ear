from whisper_ear import dictate_cli


def test_schedule_model_warmup_uses_config_delay(monkeypatch, tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        '{"daemon":{"warm_model_on_recording_start":true,"warm_model_delay_seconds":7}}',
        encoding="utf-8",
    )
    calls = []
    monkeypatch.setattr(dictate_cli, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(dictate_cli, "warmup", lambda delay, timeout: calls.append((delay, timeout)))

    dictate_cli.schedule_model_warmup()

    assert calls == [(7.0, 2.0)]


def test_schedule_model_warmup_can_be_disabled(monkeypatch, tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        '{"daemon":{"warm_model_on_recording_start":false}}',
        encoding="utf-8",
    )
    calls = []
    monkeypatch.setattr(dictate_cli, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(dictate_cli, "warmup", lambda delay, timeout: calls.append((delay, timeout)))

    dictate_cli.schedule_model_warmup()

    assert calls == []


def test_transcription_timeout_uses_config(monkeypatch, tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        '{"daemon":{"transcription_timeout_seconds":240}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(dictate_cli, "CONFIG_PATH", str(config_path))

    assert dictate_cli.transcription_timeout_seconds() == 240.0


def test_transcription_timeout_falls_back_for_invalid_config(monkeypatch, tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        '{"daemon":{"transcription_timeout_seconds":"slow"}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(dictate_cli, "CONFIG_PATH", str(config_path))

    assert dictate_cli.transcription_timeout_seconds() == 180.0


def test_dictation_language_uses_config(monkeypatch, tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        '{"dictation":{"language":"ru"}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(dictate_cli, "CONFIG_PATH", str(config_path))

    assert dictate_cli.dictation_language() == "ru"


def test_dictation_language_defaults_to_auto_detect(monkeypatch, tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        '{"dictation":{"language":"   "}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(dictate_cli, "CONFIG_PATH", str(config_path))

    assert dictate_cli.dictation_language() is None
