from __future__ import annotations

import importlib

import pytest

from config import Settings, get_settings, validate_runtime_settings


@pytest.fixture(autouse=True)
def clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _base_env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setenv("SWITCHBOARD_DB", str(tmp_path / "switchboard.sqlite"))


def test_get_settings_parses_cookie_secure_env(monkeypatch, tmp_path) -> None:
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    _base_env(monkeypatch, tmp_path)
    monkeypatch.setenv("SWITCHBOARD_COOKIE_SECURE", "yes")

    settings = get_settings()

    assert settings.cookie_secure is True


def test_get_settings_rejects_invalid_cookie_secure_env(monkeypatch, tmp_path) -> None:
    _base_env(monkeypatch, tmp_path)
    monkeypatch.setenv("SWITCHBOARD_COOKIE_SECURE", "sometimes")

    with pytest.raises(RuntimeError, match="SWITCHBOARD_COOKIE_SECURE must be a boolean value"):
        get_settings()


def test_validate_runtime_settings_requires_existing_codex_home(tmp_path) -> None:
    settings = Settings(
        app_password="secret",
        codex_home=tmp_path / "missing",
        db_path=tmp_path / "switchboard.sqlite",
        chatgpt_backend_base="https://example.test/backend-api",
        static_dir=None,
    )

    with pytest.raises(RuntimeError, match="CODEX_HOME does not exist"):
        validate_runtime_settings(settings)


def test_validate_runtime_settings_requires_directory(tmp_path) -> None:
    codex_home = tmp_path / "codex.txt"
    codex_home.write_text("not a directory", encoding="utf-8")
    settings = Settings(
        app_password="secret",
        codex_home=codex_home,
        db_path=tmp_path / "switchboard.sqlite",
        chatgpt_backend_base="https://example.test/backend-api",
        static_dir=None,
    )

    with pytest.raises(RuntimeError, match="CODEX_HOME is not a directory"):
        validate_runtime_settings(settings)


def test_create_app_validates_runtime_settings(monkeypatch, tmp_path) -> None:
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    _base_env(monkeypatch, tmp_path)

    import main

    importlib.reload(main)
    calls: list[Settings] = []

    def capture_validation(settings: Settings) -> None:
        calls.append(settings)

    monkeypatch.setattr(main, "validate_runtime_settings", capture_validation)

    main.create_app()

    assert len(calls) == 1
    assert calls[0].codex_home == codex_home
