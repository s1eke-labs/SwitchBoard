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


def test_login_uses_constant_time_compare(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setenv("SWITCHBOARD_DB", str(tmp_path / "switchboard.sqlite"))
    (tmp_path / "codex").mkdir()

    import config

    config.get_settings.cache_clear()
    import main

    importlib.reload(main)
    compared: list[tuple[str, str]] = []
    original_compare = main.hmac.compare_digest

    def capture_compare(left: str, right: str) -> bool:
        compared.append((left, right))
        return original_compare(left, right)

    monkeypatch.setattr(main.hmac, "compare_digest", capture_compare)
    client = TestClient(main.create_app())

    response = client.post("/api/auth/login", json={"password": "secret"})

    assert response.status_code == 200
    assert compared == [("secret", "secret")]


def test_sessions_api_returns_bad_request_for_invalid_cursor(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setenv("SWITCHBOARD_DB", str(tmp_path / "switchboard.sqlite"))
    (tmp_path / "codex").mkdir()

    import config

    config.get_settings.cache_clear()
    import main

    importlib.reload(main)

    def fail_cursor(*args, **kwargs):
        raise ValueError("Invalid cursor")

    monkeypatch.setattr(main, "list_sessions", fail_cursor)
    client = TestClient(main.create_app())
    assert client.post("/api/auth/login", json={"password": "secret"}).status_code == 200

    response = client.get("/api/sessions", params={"cursor": "broken"})

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid cursor"}
