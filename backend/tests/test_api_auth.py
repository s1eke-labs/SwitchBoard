from __future__ import annotations

import importlib

from fastapi.testclient import TestClient


def test_api_requires_login(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setenv("SWITCHBOARD_DB", str(tmp_path / "switchboard.sqlite"))
    (tmp_path / "codex").mkdir()

    import config

    config.get_settings.cache_clear()
    import main

    importlib.reload(main)
    client = TestClient(main.create_app())

    assert client.get("/api/accounts").status_code == 401
    assert client.post("/api/auth/login", json={"password": "bad"}).status_code == 401
    login = client.post("/api/auth/login", json={"password": "secret"})
    assert login.status_code == 200
    assert client.get("/api/accounts").status_code == 200
