from __future__ import annotations

from pathlib import Path

import security
from fastapi import Response

from config import Settings
from security import clear_login_cookie, make_session_cookie, set_login_cookie, verify_session_cookie


def _settings(tmp_path: Path, *, cookie_secure: bool = False) -> Settings:
    codex_home = tmp_path / "codex"
    codex_home.mkdir(parents=True)
    return Settings(
        app_password="secret",
        codex_home=codex_home,
        db_path=tmp_path / "switchboard.sqlite",
        chatgpt_backend_base="https://example.test/backend-api",
        static_dir=None,
        cookie_secure=cookie_secure,
    )


def test_verify_session_cookie_rejects_tampering(monkeypatch, tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setattr(security.time, "time", lambda: 1_000)
    cookie = make_session_cookie(settings)
    issued_at, signature = cookie.split(".", 1)
    tampered = "a" if signature[0] != "a" else "b"

    assert verify_session_cookie(settings, f"{issued_at}.{tampered}{signature[1:]}") is False


def test_verify_session_cookie_rejects_expired_value(monkeypatch, tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setattr(security.time, "time", lambda: 1_000)
    cookie = make_session_cookie(settings)
    monkeypatch.setattr(security.time, "time", lambda: 1_000 + settings.cookie_max_age_seconds + 1)

    assert verify_session_cookie(settings, cookie) is False


def test_set_login_cookie_uses_configured_secure_flag(tmp_path: Path) -> None:
    insecure_response = Response()
    secure_response = Response()

    set_login_cookie(insecure_response, _settings(tmp_path / "insecure", cookie_secure=False))
    set_login_cookie(secure_response, _settings(tmp_path / "secure", cookie_secure=True))

    insecure_header = insecure_response.headers["set-cookie"]
    secure_header = secure_response.headers["set-cookie"]

    assert "HttpOnly" in insecure_header
    assert "SameSite=lax" in insecure_header
    assert "Secure" not in insecure_header
    assert "Secure" in secure_header


def test_clear_login_cookie_preserves_cookie_security_attributes(tmp_path: Path) -> None:
    response = Response()

    clear_login_cookie(response, _settings(tmp_path, cookie_secure=True))

    header = response.headers["set-cookie"]
    assert "Max-Age=0" in header
    assert "HttpOnly" in header
    assert "SameSite=lax" in header
    assert "Secure" in header
