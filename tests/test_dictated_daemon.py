import dictated


def test_warm_model_loads_after_delay(monkeypatch):
    daemon = dictated.DictationDaemon()
    calls = []

    def fake_load_model():
        calls.append("loaded")
        daemon.model = object()
        daemon.state = "loaded"

    monkeypatch.setattr(daemon, "load_model", fake_load_model)

    response = daemon.warm_model(delay_seconds=0)
    daemon.warmup_thread.join(timeout=2)

    assert response["warmup_started"] is True
    assert calls == ["loaded"]
    assert daemon.state == "loaded"


def test_warmup_request_rejects_invalid_delay():
    daemon = dictated.DictationDaemon()

    response = daemon.handle({"method": "warmup", "delay_seconds": "soon"})

    assert response["ok"] is False
    assert response["error"]["code"] == "invalid_request"
