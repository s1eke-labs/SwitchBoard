from __future__ import annotations

import base64
import json
import re
from pathlib import Path

import pytest

from accounts import account_auth_path, hide_account, list_accounts, scan_current_account, set_account_custom_name, switch_account
from codex_files import current_auth_path, read_json
from config import Settings
from config_transfer import CONFIG_SCHEMA, export_config, import_config
from db import connect, init_db, now_ts
from pricing import estimate_cost


def _jwt(claims: dict[str, str]) -> str:
    payload = json.dumps(claims).encode("utf-8")
    encoded = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    return f"header.{encoded}.sig"


def _settings(tmp_path: Path) -> Settings:
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    return Settings(
        app_password="secret",
        codex_home=codex_home,
        db_path=tmp_path / "switchboard.sqlite",
        chatgpt_backend_base="https://example.test/backend-api",
        static_dir=None,
    )


def _write_auth(settings: Settings, account_id: str = "acct-current") -> None:
    (settings.codex_home / "auth.json").write_text(
        json.dumps(
            {
                "auth_mode": "chatgpt",
                "tokens": {
                    "account_id": account_id,
                    "access_token": "access",
                    "id_token": _jwt({"name": "Ada"}),
                    "refresh_token": "refresh",
                },
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_scan_current_account_unhides_and_stores_snapshot(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    init_db(settings.db_path)
    _write_auth(settings)
    with connect(settings.db_path) as conn:
        conn.execute(
            """
            INSERT INTO accounts(account_id, display_name, hidden, created_at, updated_at)
            VALUES (?, ?, 1, ?, ?)
            """,
            ("acct-current", "Old", now_ts(), now_ts()),
        )

    async def fake_fetch(_client, url: str, _token: str):
        if url.endswith("/wham/usage"):
            return {
                "primary": {"used_percent": 22, "window_minutes": 300, "resets_at": now_ts() + 60},
                "secondary": {"used_percent": 7, "window_minutes": 10080, "resets_at": now_ts() + 120},
                "plan_type": "team",
            }
        return {"user": {"name": "Ada"}}

    monkeypatch.setattr("accounts._fetch_json", fake_fetch)
    result = await scan_current_account(settings)

    assert result.status == "ok"
    assert result.account.display_name == "Old"
    assert result.account.user_name == "Ada"
    assert result.account.hidden is False
    assert result.account.five_hour is not None
    assert result.account.five_hour.remaining_percent == 78
    assert account_auth_path(settings, "acct-current").exists()
    assert read_json(account_auth_path(settings, "acct-current"))["tokens"]["account_id"] == "acct-current"


@pytest.mark.asyncio
async def test_scan_current_account_reads_wham_usage_limit_shape(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    init_db(settings.db_path)
    _write_auth(settings)
    primary_reset = now_ts() + 3600
    weekly_reset = now_ts() + 86400

    async def fake_fetch(_client, url: str, _token: str):
        if url.endswith("/wham/usage"):
            return {
                "plan_type": "team",
                "five_hour_limit": {
                    "used_percent": 51.0,
                    "remaining_percent": 49.0,
                    "window_minutes": 300,
                    "resets_at_unix": primary_reset,
                    "resets_at_local": "2026-04-26T00:46:28+08:00",
                },
                "weekly_limit": {
                    "used_percent": 70.0,
                    "remaining_percent": 30.0,
                    "window_minutes": 10080,
                    "resets_at_unix": weekly_reset,
                    "resets_at_local": "2026-05-01T11:53:21+08:00",
                },
                "credits": {"has_credits": False},
                "limit_reached": False,
                "allowed": True,
            }
        return {"user": {"name": "Ada"}}

    monkeypatch.setattr("accounts._fetch_json", fake_fetch)
    result = await scan_current_account(settings)

    assert result.account.plan_type == "team"
    assert result.account.five_hour is not None
    assert result.account.weekly is not None
    assert result.account.five_hour.remaining_percent == 49
    assert result.account.five_hour.resets_at == primary_reset
    assert result.account.weekly.remaining_percent == 30
    assert result.account.weekly.resets_at == weekly_reset


@pytest.mark.asyncio
async def test_scan_current_account_reads_raw_wham_rate_limit_shape(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = _settings(tmp_path)
    init_db(settings.db_path)
    _write_auth(settings)
    primary_reset = now_ts() + 3600
    weekly_reset = now_ts() + 86400

    async def fake_fetch(_client, url: str, _token: str):
        if url.endswith("/wham/usage"):
            return {
                "plan_type": "team",
                "rate_limit": {
                    "allowed": True,
                    "limit_reached": False,
                    "primary_window": {
                        "limit_window_seconds": 18000,
                        "reset_after_seconds": 13772,
                        "reset_at": primary_reset,
                        "used_percent": 80,
                    },
                    "secondary_window": {
                        "limit_window_seconds": 604800,
                        "reset_after_seconds": 485785,
                        "reset_at": weekly_reset,
                        "used_percent": 75,
                    },
                },
                "credits": {"has_credits": False},
            }
        return {"user": {"name": "Ada"}}

    monkeypatch.setattr("accounts._fetch_json", fake_fetch)
    result = await scan_current_account(settings)

    assert result.account.plan_type == "team"
    assert result.account.five_hour is not None
    assert result.account.weekly is not None
    assert result.account.five_hour.remaining_percent == 20
    assert result.account.five_hour.window_minutes == 300
    assert result.account.five_hour.resets_at == primary_reset
    assert result.account.weekly.remaining_percent == 25
    assert result.account.weekly.window_minutes == 10080
    assert result.account.weekly.resets_at == weekly_reset


@pytest.mark.asyncio
async def test_custom_name_overrides_scanned_name_and_can_be_cleared(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = _settings(tmp_path)
    init_db(settings.db_path)
    _write_auth(settings)

    async def fake_fetch(_client, url: str, _token: str):
        if url.endswith("/wham/usage"):
            return {
                "primary": {"used_percent": 10, "window_minutes": 300, "resets_at": now_ts() + 60},
                "secondary": {"used_percent": 20, "window_minutes": 10080, "resets_at": now_ts() + 120},
            }
        return {"user": {"name": "Ada"}}

    monkeypatch.setattr("accounts._fetch_json", fake_fetch)
    result = await scan_current_account(settings)
    generated_name = result.account.display_name
    assert re.fullmatch(r"Account-\d{4}", generated_name)
    assert result.account.custom_name is None
    assert result.account.user_name == "Ada"

    renamed = set_account_custom_name(settings, "acct-current", "Primary")
    assert renamed.display_name == "Primary"
    assert renamed.custom_name == "Primary"
    assert renamed.user_name == "Ada"

    scanned_again = await scan_current_account(settings)
    assert scanned_again.account.display_name == "Primary"
    assert scanned_again.account.custom_name == "Primary"
    assert scanned_again.account.user_name == "Ada"

    cleared = set_account_custom_name(settings, "acct-current", " ")
    assert cleared.display_name == generated_name
    assert cleared.custom_name is None
    assert cleared.user_name == "Ada"


def test_reset_limit_recovers_to_full_remaining(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    init_db(settings.db_path)
    _write_auth(settings)
    with connect(settings.db_path) as conn:
        ts = now_ts()
        conn.execute(
            """
            INSERT INTO accounts(account_id, display_name, hidden, created_at, updated_at, last_scanned_at)
            VALUES (?, ?, 0, ?, ?, ?)
            """,
            ("acct-current", "Ada", ts, ts, ts),
        )
        conn.execute(
            """
            INSERT INTO rate_limit_snapshots(
                account_id, scanned_at, five_hour_used_percent, five_hour_window_minutes, five_hour_resets_at,
                weekly_used_percent, weekly_window_minutes, weekly_resets_at, raw_json
            )
            VALUES (?, ?, 95, 300, ?, 100, 10080, ?, '{}')
            """,
            ("acct-current", ts, ts - 1, ts - 1),
        )

    account = list_accounts(settings)[0]
    assert account.five_hour is not None
    assert account.weekly is not None
    assert account.five_hour.remaining_percent == 100
    assert account.weekly.remaining_percent == 100


def test_weekly_exhaustion_zeroes_five_hour_limit(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    init_db(settings.db_path)
    _write_auth(settings)
    with connect(settings.db_path) as conn:
        ts = now_ts()
        five_hour_reset = ts + 3600
        weekly_reset = ts + 86400
        conn.execute(
            """
            INSERT INTO accounts(account_id, display_name, hidden, created_at, updated_at, last_scanned_at)
            VALUES (?, ?, 0, ?, ?, ?)
            """,
            ("acct-current", "Ada", ts, ts, ts),
        )
        conn.execute(
            """
            INSERT INTO rate_limit_snapshots(
                account_id, scanned_at, five_hour_used_percent, five_hour_window_minutes, five_hour_resets_at,
                weekly_used_percent, weekly_window_minutes, weekly_resets_at, raw_json
            )
            VALUES (?, ?, 20, 300, ?, 100, 10080, ?, '{}')
            """,
            ("acct-current", ts, five_hour_reset, weekly_reset),
        )

    account = list_accounts(settings)[0]
    assert account.five_hour is not None
    assert account.weekly is not None
    assert account.weekly.remaining_percent == 0
    assert account.five_hour.remaining_percent == 0
    assert account.five_hour.resets_at == weekly_reset


def test_init_db_migrates_custom_name_and_removes_workspace_name(tmp_path: Path) -> None:
    db_path = tmp_path / "switchboard.sqlite"
    with connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE accounts (
                account_id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                workspace_name TEXT,
                plan_type TEXT,
                hidden INTEGER NOT NULL DEFAULT 0,
                last_scanned_at INTEGER,
                last_error TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )

    init_db(db_path)

    with connect(db_path) as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(accounts)")}

    assert "custom_name" in columns
    assert "user_name" in columns
    assert "failed_scan_count" in columns
    assert "expired_at" in columns
    assert "workspace_name" not in columns


@pytest.mark.asyncio
async def test_switch_account_replaces_current_auth_and_scans(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    init_db(settings.db_path)

    async def fake_fetch(_client, url: str, _token: str):
        if url.endswith("/wham/usage"):
            return {
                "primary": {"used_percent": 10, "window_minutes": 300, "resets_at": now_ts() + 60},
                "secondary": {"used_percent": 20, "window_minutes": 10080, "resets_at": now_ts() + 120},
            }
        return {"user": {"name": "Ada"}}

    monkeypatch.setattr("accounts._fetch_json", fake_fetch)
    _write_auth(settings, "acct-one")
    await scan_current_account(settings)
    _write_auth(settings, "acct-two")
    await scan_current_account(settings)

    result = await switch_account(settings, "acct-one")

    assert result.status == "ok"
    assert result.account.account_id == "acct-one"
    assert read_json(current_auth_path(settings.codex_home))["tokens"]["account_id"] == "acct-one"


@pytest.mark.asyncio
async def test_switch_account_requires_stored_auth(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    init_db(settings.db_path)

    with pytest.raises(KeyError):
        await switch_account(settings, "missing-account")


@pytest.mark.asyncio
async def test_failed_scans_mark_account_expired_and_success_clears_status(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = _settings(tmp_path)
    init_db(settings.db_path)
    _write_auth(settings)

    async def bad_fetch(_client, _url: str, _token: str):
        return {"unexpected": True}

    monkeypatch.setattr("accounts._fetch_json", bad_fetch)
    for _ in range(3):
        result = await scan_current_account(settings)

    assert result.status == "error"
    assert result.warning is not None
    assert result.warning.code == "ACCOUNT_SCAN_WARNING"
    assert result.account.failed_scan_count == 3
    assert result.account.expired is True

    async def good_fetch(_client, url: str, _token: str):
        if url.endswith("/wham/usage"):
            return {
                "primary": {"used_percent": 10, "window_minutes": 300, "resets_at": now_ts() + 60},
                "secondary": {"used_percent": 20, "window_minutes": 10080, "resets_at": now_ts() + 120},
            }
        return {"user": {"name": "Ada"}}

    monkeypatch.setattr("accounts._fetch_json", good_fetch)
    recovered = await scan_current_account(settings)

    assert recovered.status == "ok"
    assert recovered.warning is None
    assert recovered.account.failed_scan_count == 0
    assert recovered.account.expired is False
    assert recovered.account.last_error is None


def test_hide_current_account_is_rejected(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    init_db(settings.db_path)
    _write_auth(settings)
    with connect(settings.db_path) as conn:
        ts = now_ts()
        conn.execute(
            "INSERT INTO accounts(account_id, display_name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("acct-current", "Ada", ts, ts),
        )

    with pytest.raises(ValueError):
        hide_account(settings, "acct-current")


def test_export_config_includes_display_state_without_credentials(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    init_db(settings.db_path)
    with connect(settings.db_path) as conn:
        ts = now_ts()
        conn.execute(
            """
            INSERT INTO accounts(
                account_id, display_name, custom_name, hidden, user_name, plan_type,
                last_scanned_at, last_error, created_at, updated_at
            )
            VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?)
            """,
            ("acct-one", "Account-0001", "Work", "Ada", "team", ts, "secret-ish error", ts, ts),
        )
        conn.execute(
            """
            INSERT INTO rate_limit_snapshots(
                account_id, scanned_at, five_hour_used_percent, five_hour_window_minutes,
                five_hour_resets_at, weekly_used_percent, weekly_window_minutes,
                weekly_resets_at, raw_json
            )
            VALUES (?, ?, 10, 300, ?, 20, 10080, ?, ?)
            """,
            ("acct-one", ts, ts + 60, ts + 120, '{"token":"must-not-export"}'),
        )
        conn.execute(
            """
            INSERT INTO usage_events(
                thread_id, event_index, occurred_at, model, input_tokens,
                cache_hit_tokens, cache_creation_tokens, output_tokens,
                reasoning_output_tokens, total_tokens, cost_usd, cost_known
            )
            VALUES ('thread', 1, ?, 'model', 1, 2, 3, 4, 5, 15, 0.01, 1)
            """,
            (ts,),
        )

    exported = export_config(settings).model_dump(by_alias=True)

    assert exported["schema"] == CONFIG_SCHEMA
    assert exported["accounts"] == [
        {
            "account_id": "acct-one",
            "display_name": "Account-0001",
            "custom_name": "Work",
            "hidden": True,
            "user_name": "Ada",
            "plan_type": "team",
            "expired": False,
            "current": False,
            "last_scanned_at": ts,
            "five_hour": {
                "remaining_percent": 90.0,
                "window_minutes": 300,
                "resets_at": ts + 60,
            },
            "weekly": {
                "remaining_percent": 80.0,
                "window_minutes": 10080,
                "resets_at": ts + 120,
            },
        }
    ]
    assert "token" not in json.dumps(exported)


def test_import_config_updates_existing_account_display_state(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    init_db(settings.db_path)
    with connect(settings.db_path) as conn:
        ts = now_ts()
        conn.execute(
            "INSERT INTO accounts(account_id, display_name, custom_name, hidden, created_at, updated_at) VALUES (?, ?, ?, 0, ?, ?)",
            ("acct-one", "Account-0001", "Old", ts, ts),
        )

    summary = import_config(
        settings,
        {
            "schema": CONFIG_SCHEMA,
            "accounts": [
                {
                    "account_id": "acct-one",
                    "display_name": "Ignored",
                    "custom_name": "  New Name  ",
                    "hidden": True,
                    "user_name": "  Ada  ",
                    "plan_type": " team ",
                    "expired": True,
                    "last_scanned_at": ts + 30,
                    "five_hour": {
                        "remaining_percent": 61,
                        "window_minutes": 300,
                        "resets_at": ts + 3600,
                    },
                    "weekly": {
                        "remaining_percent": 36,
                        "window_minutes": 10080,
                        "resets_at": ts + 7200,
                    },
                }
            ],
        },
    )

    assert summary.imported == 1
    assert summary.updated == 1
    with connect(settings.db_path) as conn:
        row = conn.execute("SELECT * FROM accounts WHERE account_id = 'acct-one'").fetchone()
    assert row["display_name"] == "Account-0001"
    assert row["custom_name"] == "New Name"
    assert row["hidden"] == 1
    assert row["user_name"] == "Ada"
    assert row["plan_type"] == "team"
    assert row["last_scanned_at"] == ts + 30
    assert row["expired_at"] is not None
    assert row["failed_scan_count"] == 3
    with connect(settings.db_path) as conn:
        snapshot = conn.execute("SELECT * FROM rate_limit_snapshots WHERE account_id = 'acct-one'").fetchone()
    assert snapshot["scanned_at"] == ts + 30
    assert snapshot["five_hour_used_percent"] == 39
    assert snapshot["five_hour_resets_at"] == ts + 3600
    assert snapshot["weekly_used_percent"] == 64
    assert snapshot["weekly_resets_at"] == ts + 7200


def test_import_config_creates_unknown_account_placeholder(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    init_db(settings.db_path)

    summary = import_config(
        settings,
        {
            "schema": CONFIG_SCHEMA,
            "accounts": [
                {
                    "account_id": "acct-new",
                    "display_name": "Imported Account",
                    "custom_name": "",
                    "hidden": False,
                    "user_name": "Kai Smith",
                    "plan_type": "team",
                    "expired": False,
                    "five_hour": {
                        "remaining_percent": 0,
                        "window_minutes": 300,
                        "resets_at": 1777345200,
                    },
                }
            ],
        },
    )

    assert summary.created == 1
    with connect(settings.db_path) as conn:
        row = conn.execute("SELECT * FROM accounts WHERE account_id = 'acct-new'").fetchone()
    assert row["display_name"] == "Imported Account"
    assert row["custom_name"] is None
    assert row["hidden"] == 0
    assert row["user_name"] == "Kai Smith"
    assert row["plan_type"] == "team"
    with connect(settings.db_path) as conn:
        snapshot = conn.execute("SELECT * FROM rate_limit_snapshots WHERE account_id = 'acct-new'").fetchone()
    assert snapshot["five_hour_used_percent"] == 100
    assert snapshot["five_hour_resets_at"] == 1777345200


def test_import_config_does_not_hide_current_account(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    init_db(settings.db_path)
    _write_auth(settings, "acct-current")
    with connect(settings.db_path) as conn:
        ts = now_ts()
        conn.execute(
            "INSERT INTO accounts(account_id, display_name, hidden, created_at, updated_at) VALUES (?, ?, 0, ?, ?)",
            ("acct-current", "Current", ts, ts),
        )

    import_config(
        settings,
        {
            "schema": CONFIG_SCHEMA,
            "accounts": [
                {
                    "account_id": "acct-current",
                    "display_name": "Current",
                    "custom_name": "Primary",
                    "hidden": True,
                }
            ],
        },
    )

    with connect(settings.db_path) as conn:
        row = conn.execute("SELECT hidden, custom_name FROM accounts WHERE account_id = 'acct-current'").fetchone()
    assert row["hidden"] == 0
    assert row["custom_name"] == "Primary"


def test_import_config_rejects_invalid_schema_and_account_item(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    init_db(settings.db_path)

    with pytest.raises(ValueError, match="Unsupported config schema"):
        import_config(settings, {"schema": "wrong", "accounts": []})

    with pytest.raises(ValueError, match="hidden must be a boolean"):
        import_config(
            settings,
            {
                "schema": CONFIG_SCHEMA,
                "accounts": [
                    {
                        "account_id": "acct-one",
                        "display_name": "Account",
                        "custom_name": None,
                        "hidden": "no",
                    }
                ],
            },
        )


def test_unknown_model_cost_is_zero() -> None:
    cost, known = estimate_cost("mystery-model", 1000, 100, 50)
    assert cost == 0.0
    assert known is True
