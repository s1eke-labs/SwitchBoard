from __future__ import annotations

import base64
import json
import os
import secrets
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel

from codex_files import current_account_id, current_auth_path, read_json
from config import Settings
from db import connect, now_ts


ACCOUNT_EXPIRED_FAILURES = 3


class LimitDTO(BaseModel):
    used_percent: float | None
    remaining_percent: float
    window_minutes: int | None
    resets_at: int | None


class AccountDTO(BaseModel):
    account_id: str
    display_name: str
    custom_name: str | None
    user_name: str | None
    current: bool
    hidden: bool
    plan_type: str | None
    five_hour: LimitDTO | None
    weekly: LimitDTO | None
    last_scanned_at: int | None
    last_error: str | None
    failed_scan_count: int
    expired: bool


class ScanResult(BaseModel):
    account: AccountDTO
    status: str
    error: str | None = None


def _decode_jwt_claims(token: str | None) -> dict[str, Any]:
    if not token or token.count(".") < 2:
        return {}
    try:
        payload = token.split(".", 2)[1]
        payload += "=" * (-len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload.encode("ascii"))
        value = json.loads(decoded)
    except (ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _first_string(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _walk_dicts(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _extract_profile(value: Any, claims: dict[str, Any]) -> str | None:
    user_name = _first_string(
        claims.get("name"),
        claims.get("given_name"),
        claims.get("preferred_username"),
        claims.get("email"),
    )

    for item in _walk_dicts(value):
        user_name = _first_string(
            user_name,
            item.get("name"),
            item.get("display_name"),
            item.get("email"),
            item.get("username"),
        )
    return user_name


def _random_display_name(conn: sqlite3.Connection) -> str:
    for _ in range(100):
        candidate = f"Account-{secrets.randbelow(10_000):04d}"
        if conn.execute("SELECT 1 FROM accounts WHERE display_name = ?", (candidate,)).fetchone() is None:
            return candidate
    return f"Account-{now_ts() % 10_000:04d}"


def _as_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _as_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _normalize_limit(value: dict[str, Any]) -> dict[str, Any]:
    used_percent = _as_float(value.get("used_percent"))
    remaining_percent = _as_float(value.get("remaining_percent"))
    if used_percent is None and remaining_percent is not None:
        used_percent = max(0.0, min(100.0, 100.0 - remaining_percent))
    resets_at = _as_int(value.get("resets_at"))
    if resets_at is None:
        resets_at = _as_int(value.get("resets_at_unix"))
    return {
        "used_percent": used_percent,
        "remaining_percent": remaining_percent,
        "window_minutes": _as_int(value.get("window_minutes")),
        "resets_at": resets_at,
        "resets_at_local": value.get("resets_at_local"),
    }


def _normalize_window(value: dict[str, Any]) -> dict[str, Any]:
    window_seconds = _as_int(value.get("limit_window_seconds"))
    window_minutes = _as_int(value.get("window_minutes"))
    if window_minutes is None and window_seconds is not None:
        window_minutes = int(window_seconds / 60)

    used_percent = _as_float(value.get("used_percent"))
    remaining_percent = _as_float(value.get("remaining_percent"))
    if used_percent is None and remaining_percent is not None:
        used_percent = max(0.0, min(100.0, 100.0 - remaining_percent))

    resets_at = _as_int(value.get("resets_at"))
    if resets_at is None:
        resets_at = _as_int(value.get("resets_at_unix"))
    if resets_at is None:
        resets_at = _as_int(value.get("reset_at"))

    return {
        "used_percent": used_percent,
        "remaining_percent": remaining_percent,
        "window_minutes": window_minutes,
        "resets_at": resets_at,
        "resets_at_local": value.get("resets_at_local"),
    }


def _extract_rate_limits(value: Any) -> dict[str, Any]:
    for item in _walk_dicts(value):
        five_hour = item.get("five_hour_limit")
        weekly = item.get("weekly_limit")
        if isinstance(five_hour, dict) and isinstance(weekly, dict):
            return {
                "plan_type": item.get("plan_type"),
                "primary": _normalize_limit(five_hour),
                "secondary": _normalize_limit(weekly),
                "credits": item.get("credits"),
                "limit_reached": item.get("limit_reached"),
                "allowed": item.get("allowed"),
            }
        rate_limit = item.get("rate_limit")
        if isinstance(rate_limit, dict):
            primary_window = rate_limit.get("primary_window")
            secondary_window = rate_limit.get("secondary_window")
            if isinstance(primary_window, dict) and isinstance(secondary_window, dict):
                return {
                    "plan_type": item.get("plan_type"),
                    "primary": _normalize_window(primary_window),
                    "secondary": _normalize_window(secondary_window),
                    "credits": item.get("credits"),
                    "limit_reached": rate_limit.get("limit_reached"),
                    "allowed": rate_limit.get("allowed"),
                }
        primary = item.get("primary")
        secondary = item.get("secondary")
        if isinstance(primary, dict) and isinstance(secondary, dict):
            normalized = dict(item)
            normalized["primary"] = _normalize_limit(primary)
            normalized["secondary"] = _normalize_limit(secondary)
            return normalized
    return {}


def _payload_shape(value: Any) -> str:
    if isinstance(value, dict):
        keys = ", ".join(sorted(str(key) for key in value.keys())[:12])
        return f"object keys: {keys or 'none'}"
    if isinstance(value, list):
        return f"list length: {len(value)}"
    return type(value).__name__


def _limit_from_snapshot(
    used_percent: float | None,
    window_minutes: int | None,
    resets_at: int | None,
    timestamp: int | None = None,
) -> LimitDTO | None:
    if used_percent is None and resets_at is None and window_minutes is None:
        return None
    now = timestamp or now_ts()
    effective_used = 0.0 if resets_at and resets_at <= now else float(used_percent or 0.0)
    remaining = max(0.0, min(100.0, 100.0 - effective_used))
    return LimitDTO(
        used_percent=round(effective_used, 2),
        remaining_percent=round(remaining, 2),
        window_minutes=window_minutes,
        resets_at=resets_at,
    )


def _latest_snapshot(conn: sqlite3.Connection, account_id: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT * FROM rate_limit_snapshots
        WHERE account_id = ?
        ORDER BY scanned_at DESC, id DESC
        LIMIT 1
        """,
        (account_id,),
    ).fetchone()


def _account_dto(row: sqlite3.Row, snapshot: sqlite3.Row | None, current_id: str | None) -> AccountDTO:
    five_hour = None
    weekly = None
    if snapshot:
        five_hour = _limit_from_snapshot(
            snapshot["five_hour_used_percent"],
            snapshot["five_hour_window_minutes"],
            snapshot["five_hour_resets_at"],
        )
        weekly = _limit_from_snapshot(
            snapshot["weekly_used_percent"],
            snapshot["weekly_window_minutes"],
            snapshot["weekly_resets_at"],
        )
    return AccountDTO(
        account_id=row["account_id"],
        display_name=row["custom_name"] or row["display_name"],
        custom_name=row["custom_name"],
        user_name=row["user_name"],
        current=row["account_id"] == current_id,
        hidden=bool(row["hidden"]),
        plan_type=row["plan_type"],
        five_hour=five_hour,
        weekly=weekly,
        last_scanned_at=row["last_scanned_at"],
        last_error=row["last_error"],
        failed_scan_count=row["failed_scan_count"],
        expired=row["expired_at"] is not None,
    )


def _sort_key(account: AccountDTO) -> tuple[int, int, int, float]:
    if account.current:
        return (0, 0, 0, 0.0)
    weekly_remaining = account.weekly.remaining_percent if account.weekly else 100.0
    five_remaining = account.five_hour.remaining_percent if account.five_hour else 100.0
    weekly_exhausted = weekly_remaining <= 0
    return (1, 1 if account.expired else 0, 1 if weekly_exhausted else 0, -five_remaining)


def list_accounts(settings: Settings) -> list[AccountDTO]:
    current_id = current_account_id(settings.codex_home)
    with connect(settings.db_path) as conn:
        result = []
        for row in conn.execute("SELECT * FROM accounts WHERE hidden = 0"):
            result.append(_account_dto(row, _latest_snapshot(conn, row["account_id"]), current_id))
    return sorted(result, key=_sort_key)


def hide_account(settings: Settings, account_id: str) -> None:
    current_id = current_account_id(settings.codex_home)
    if account_id == current_id:
        raise ValueError("Cannot hide the current Codex account")
    with connect(settings.db_path) as conn:
        updated = conn.execute(
            "UPDATE accounts SET hidden = 1, updated_at = ? WHERE account_id = ?",
            (now_ts(), account_id),
        ).rowcount
        if updated == 0:
            raise KeyError(account_id)


def set_account_custom_name(settings: Settings, account_id: str, custom_name: str | None) -> AccountDTO:
    normalized_name = custom_name.strip() if isinstance(custom_name, str) else ""
    value = normalized_name or None
    current_id = current_account_id(settings.codex_home)
    with connect(settings.db_path) as conn:
        updated = conn.execute(
            "UPDATE accounts SET custom_name = ?, updated_at = ? WHERE account_id = ?",
            (value, now_ts(), account_id),
        ).rowcount
        if updated == 0:
            raise KeyError(account_id)
        row = conn.execute("SELECT * FROM accounts WHERE account_id = ?", (account_id,)).fetchone()
        return _account_dto(row, _latest_snapshot(conn, account_id), current_id)


async def _fetch_json(client: httpx.AsyncClient, url: str, access_token: str) -> Any:
    response = await client.get(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "User-Agent": "SwitchBoard/0.1",
        },
    )
    response.raise_for_status()
    return response.json()


def _auth_tokens(auth: dict[str, Any]) -> tuple[str, str]:
    tokens = auth.get("tokens")
    if not isinstance(tokens, dict):
        raise ValueError("auth.json does not contain ChatGPT tokens")
    account_id = tokens.get("account_id")
    access_token = tokens.get("access_token")
    if not isinstance(account_id, str) or not account_id:
        raise ValueError("auth.json does not contain tokens.account_id")
    if not isinstance(access_token, str) or not access_token:
        raise ValueError("auth.json does not contain tokens.access_token")
    return account_id, access_token


def _account_vault_dir(settings: Settings, account_id: str) -> Path:
    if not account_id or "/" in account_id or "\\" in account_id or account_id in {".", ".."}:
        raise ValueError("Invalid account_id")
    return settings.codex_home / "switchboard" / "accounts" / account_id


def account_auth_path(settings: Settings, account_id: str) -> Path:
    return _account_vault_dir(settings, account_id) / "auth.json"


def _write_private_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    tmp_path = path.with_name(f".{path.name}.tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False)
    os.chmod(tmp_path, 0o600)
    os.replace(tmp_path, path)
    os.chmod(path, 0o600)


def save_account_auth(settings: Settings, account_id: str, auth: dict[str, Any]) -> None:
    _write_private_json(account_auth_path(settings, account_id), auth)


def switch_account_auth(settings: Settings, account_id: str) -> None:
    stored_path = account_auth_path(settings, account_id)
    if not stored_path.exists():
        raise KeyError(account_id)
    auth = read_json(stored_path)
    stored_account_id, _ = _auth_tokens(auth)
    if stored_account_id != account_id:
        raise ValueError("Stored auth account_id does not match requested account")
    _write_private_json(current_auth_path(settings.codex_home), auth)


async def switch_account(settings: Settings, account_id: str) -> ScanResult:
    switch_account_auth(settings, account_id)
    return await scan_current_account(settings)


def _upsert_account(
    conn: sqlite3.Connection,
    account_id: str,
    user_name: str | None,
    plan_type: str | None,
    last_error: str | None,
) -> None:
    ts = now_ts()
    display_name = _random_display_name(conn)
    failed_scan_count_sql = "0" if last_error is None else "accounts.failed_scan_count + 1"
    expired_at_sql = "NULL" if last_error is None else f"CASE WHEN accounts.failed_scan_count + 1 >= {ACCOUNT_EXPIRED_FAILURES} THEN COALESCE(accounts.expired_at, excluded.updated_at) ELSE accounts.expired_at END"
    conn.execute(
        """
        INSERT INTO accounts (
            account_id, display_name, user_name, plan_type,
            hidden, last_scanned_at, last_error, failed_scan_count, expired_at, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(account_id) DO UPDATE SET
            user_name = excluded.user_name,
            plan_type = COALESCE(excluded.plan_type, accounts.plan_type),
            hidden = 0,
            last_scanned_at = excluded.last_scanned_at,
            last_error = excluded.last_error,
            failed_scan_count = """ + failed_scan_count_sql + """,
            expired_at = """ + expired_at_sql + """,
            updated_at = excluded.updated_at
        """,
        (
            account_id,
            display_name,
            user_name,
            plan_type,
            ts,
            last_error,
            1 if last_error else 0,
            None,
            ts,
            ts,
        ),
    )


async def scan_current_account(settings: Settings) -> ScanResult:
    auth_path = current_auth_path(settings.codex_home)
    if not auth_path.exists():
        raise FileNotFoundError(f"{auth_path} does not exist")

    auth = read_json(auth_path)
    account_id, access_token = _auth_tokens(auth)
    tokens = auth["tokens"]
    save_account_auth(settings, account_id, auth)

    id_claims = _decode_jwt_claims(tokens.get("id_token"))
    profile_payload: Any = {}
    usage_payload: Any = {}
    last_error: str | None = None

    with connect(settings.db_path) as conn:
        scan_id = conn.execute(
            "INSERT INTO scan_runs(account_id, started_at, status) VALUES (?, ?, ?)",
            (account_id, now_ts(), "running"),
        ).lastrowid

    try:
        timeout = httpx.Timeout(12.0, connect=5.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            usage_payload = await _fetch_json(
                client, f"{settings.chatgpt_backend_base}/wham/usage", access_token
            )
            try:
                profile_payload = await _fetch_json(
                    client, f"{settings.chatgpt_backend_base}/api/accounts", access_token
                )
            except httpx.HTTPError:
                profile_payload = {}
    except (httpx.HTTPError, ValueError) as exc:
        last_error = str(exc)

    rate_limits = _extract_rate_limits(usage_payload)
    if not rate_limits and last_error is None:
        last_error = f"Usage response did not contain rate limits ({_payload_shape(usage_payload)})"
    user_name = _extract_profile(profile_payload, id_claims)
    plan_type = rate_limits.get("plan_type") if isinstance(rate_limits.get("plan_type"), str) else None

    with connect(settings.db_path) as conn:
        _upsert_account(
            conn,
            account_id,
            user_name,
            plan_type,
            last_error,
        )
        if rate_limits:
            primary = rate_limits.get("primary") or {}
            secondary = rate_limits.get("secondary") or {}
            conn.execute(
                """
                INSERT INTO rate_limit_snapshots (
                    account_id, scanned_at,
                    five_hour_used_percent, five_hour_window_minutes, five_hour_resets_at,
                    weekly_used_percent, weekly_window_minutes, weekly_resets_at,
                    raw_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    account_id,
                    now_ts(),
                    primary.get("used_percent"),
                    primary.get("window_minutes"),
                    primary.get("resets_at"),
                    secondary.get("used_percent"),
                    secondary.get("window_minutes"),
                    secondary.get("resets_at"),
                    json.dumps(rate_limits, ensure_ascii=False),
                ),
            )
        conn.execute(
            "UPDATE scan_runs SET finished_at = ?, status = ?, error = ? WHERE id = ?",
            (now_ts(), "error" if last_error else "ok", last_error, scan_id),
        )
        row = conn.execute("SELECT * FROM accounts WHERE account_id = ?", (account_id,)).fetchone()
        account = _account_dto(row, _latest_snapshot(conn, account_id), account_id)

    return ScanResult(account=account, status="error" if last_error else "ok", error=last_error)
