from __future__ import annotations

import base64
import json
import os
import re
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel

from codex_files import current_account_id, current_auth_path, read_json
from config import Settings
from db import connect, now_ts
from issues import IssueDetail, scan_warning_from_message
from version import USER_AGENT


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
    usage_started_at: int
    usage_ended_at: int | None
    usage_seconds: int


class ScanResult(BaseModel):
    account: AccountDTO
    status: str
    warning: IssueDetail | None = None


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


def _extract_profile(claims: dict[str, Any]) -> str | None:
    return _first_string(
        claims.get("name"),
        claims.get("given_name"),
        claims.get("preferred_username"),
        claims.get("email"),
    )


def _display_name_base(user_name: str | None) -> str:
    if not user_name:
        return "Account"
    token = user_name.strip().split()[0]
    if "@" in token:
        token = token.split("@", 1)[0].split(".", 1)[0]
    base = "".join(char for char in token if char.isalnum() or char in {"-", "_"}).strip("-_")
    return base or "Account"


def _legacy_random_display_name(value: str) -> bool:
    return re.fullmatch(r"Account-\d{4}", value) is not None


def _next_display_name(conn: sqlite3.Connection, account_id: str, user_name: str | None) -> str:
    base = _display_name_base(user_name)
    pattern = re.compile(rf"^{re.escape(base)}-(\d+)$")
    used_numbers: set[int] = set()
    used_names: set[str] = set()
    for row in conn.execute("SELECT account_id, display_name FROM accounts"):
        display_name = row["display_name"]
        if row["account_id"] != account_id:
            used_names.add(display_name)
        match = pattern.fullmatch(display_name)
        if match and not (base == "Account" and _legacy_random_display_name(display_name)):
            used_numbers.add(int(match.group(1)))

    number = 1
    while True:
        candidate = f"{base}-{number:02d}"
        if number not in used_numbers and candidate not in used_names:
            return candidate
        number += 1


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
    usage_started_at = int(row["created_at"])
    usage_ended_at = row["expired_at"]
    usage_end = int(usage_ended_at) if usage_ended_at is not None else now_ts()
    usage_seconds = max(0, usage_end - usage_started_at)
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
        if weekly and weekly.remaining_percent <= 0:
            five_hour = LimitDTO(
                used_percent=100.0,
                remaining_percent=0.0,
                window_minutes=five_hour.window_minutes if five_hour else None,
                resets_at=weekly.resets_at,
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
        usage_started_at=usage_started_at,
        usage_ended_at=usage_ended_at,
        usage_seconds=usage_seconds,
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
            "User-Agent": USER_AGENT,
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


def _can_chown() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0


def _nearest_existing_parent(path: Path) -> Path:
    candidate = path
    while not candidate.exists():
        parent = candidate.parent
        if parent == candidate:
            break
        candidate = parent
    return candidate


def _missing_parents(path: Path) -> list[Path]:
    missing = []
    candidate = path
    while not candidate.exists():
        missing.append(candidate)
        parent = candidate.parent
        if parent == candidate:
            break
        candidate = parent
    return missing


def _ensure_private_parent(path: Path) -> os.stat_result | None:
    owner_source = _nearest_existing_parent(path.parent)
    owner_stat = owner_source.stat() if owner_source.exists() else None
    missing = _missing_parents(path.parent)
    path.parent.mkdir(parents=True, exist_ok=True)
    if owner_stat and _can_chown():
        for parent in reversed(missing):
            os.chown(parent, owner_stat.st_uid, owner_stat.st_gid)
    os.chmod(path.parent, 0o700)
    return owner_stat


def _write_private_json(path: Path, value: dict[str, Any]) -> None:
    existing_stat = path.stat() if path.exists() else None
    parent_stat = _ensure_private_parent(path)
    owner_stat = existing_stat or parent_stat
    tmp_path = path.with_name(f".{path.name}.tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False)
    if owner_stat and _can_chown():
        os.chown(tmp_path, owner_stat.st_uid, owner_stat.st_gid)
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
    existing = conn.execute("SELECT display_name FROM accounts WHERE account_id = ?", (account_id,)).fetchone()
    display_name = (
        _next_display_name(conn, account_id, user_name)
        if existing is None or _legacy_random_display_name(existing["display_name"])
        else existing["display_name"]
    )
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
            display_name = excluded.display_name,
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
    except (httpx.HTTPError, ValueError) as exc:
        last_error = str(exc)

    rate_limits = _extract_rate_limits(usage_payload)
    if not rate_limits and last_error is None:
        last_error = f"Usage response did not contain rate limits ({_payload_shape(usage_payload)})"
    user_name = _extract_profile(id_claims)
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

    return ScanResult(
        account=account,
        status="error" if last_error else "ok",
        warning=scan_warning_from_message(last_error) if last_error else None,
    )
