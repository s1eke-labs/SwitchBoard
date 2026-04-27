from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from codex_files import current_account_id
from config import Settings
from db import connect, now_ts


CONFIG_SCHEMA = "switchboard.config.v1"


class ConfigLimitDTO(BaseModel):
    remaining_percent: float
    window_minutes: int | None = None
    resets_at: int | None = None


class ConfigAccountDTO(BaseModel):
    account_id: str
    display_name: str
    custom_name: str | None
    hidden: bool
    user_name: str | None = None
    plan_type: str | None = None
    expired: bool = False
    current: bool = False
    last_scanned_at: int | None = None
    five_hour: ConfigLimitDTO | None = None
    weekly: ConfigLimitDTO | None = None


class ConfigExportDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_: str = Field(alias="schema")
    exported_at: int
    accounts: list[ConfigAccountDTO]


class ConfigImportSummary(BaseModel):
    ok: bool
    imported: int
    created: int
    updated: int
    skipped: int


def export_config(settings: Settings) -> ConfigExportDTO:
    current_id = current_account_id(settings.codex_home)
    timestamp = now_ts()
    with connect(settings.db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                accounts.*,
                snapshots.five_hour_used_percent,
                snapshots.five_hour_window_minutes,
                snapshots.five_hour_resets_at,
                snapshots.weekly_used_percent,
                snapshots.weekly_window_minutes,
                snapshots.weekly_resets_at
            FROM accounts
            LEFT JOIN rate_limit_snapshots snapshots
                ON snapshots.id = (
                    SELECT id FROM rate_limit_snapshots
                    WHERE account_id = accounts.account_id
                    ORDER BY scanned_at DESC, id DESC
                    LIMIT 1
                )
            ORDER BY accounts.created_at ASC, accounts.account_id ASC
            """
        ).fetchall()
    return ConfigExportDTO(
        schema_=CONFIG_SCHEMA,
        exported_at=timestamp,
        accounts=[_account_from_row(row, current_id, timestamp) for row in rows],
    )


def _account_from_row(row, current_id: str | None, timestamp: int) -> ConfigAccountDTO:
    five_hour = _limit_from_row(
        row,
        "five_hour_used_percent",
        "five_hour_window_minutes",
        "five_hour_resets_at",
        timestamp,
    )
    weekly = _limit_from_row(
        row,
        "weekly_used_percent",
        "weekly_window_minutes",
        "weekly_resets_at",
        timestamp,
    )
    if weekly and weekly.remaining_percent <= 0:
        five_hour = ConfigLimitDTO(
            remaining_percent=0.0,
            window_minutes=five_hour.window_minutes if five_hour else None,
            resets_at=weekly.resets_at,
        )
    return ConfigAccountDTO(
        account_id=row["account_id"],
        display_name=row["display_name"],
        custom_name=row["custom_name"],
        hidden=bool(row["hidden"]),
        user_name=row["user_name"],
        plan_type=row["plan_type"],
        expired=row["expired_at"] is not None,
        current=row["account_id"] == current_id,
        last_scanned_at=row["last_scanned_at"],
        five_hour=five_hour,
        weekly=weekly,
    )


def _limit_from_row(
    row,
    used_percent_column: str,
    window_minutes_column: str,
    resets_at_column: str,
    timestamp: int,
) -> ConfigLimitDTO | None:
    used_percent = row[used_percent_column]
    window_minutes = row[window_minutes_column]
    resets_at = row[resets_at_column]
    if used_percent is None and window_minutes is None and resets_at is None:
        return None
    effective_used = 0.0 if resets_at and resets_at <= timestamp else float(used_percent or 0.0)
    remaining = max(0.0, min(100.0, 100.0 - effective_used))
    return ConfigLimitDTO(
        remaining_percent=round(remaining, 2),
        window_minutes=window_minutes,
        resets_at=resets_at,
    )


def _normalize_optional_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string or null")
    normalized = value.strip()
    return normalized or None


def _normalize_account_id(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("account_id must be a non-empty string")
    account_id = value.strip()
    if "/" in account_id or "\\" in account_id or account_id in {".", ".."}:
        raise ValueError("account_id is invalid")
    return account_id


def _safe_display_name(value: Any, account_id: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    suffix = re.sub(r"[^A-Za-z0-9_-]", "", account_id)[:12] or "account"
    return f"Imported-{suffix}"


def _normalize_hidden(value: Any) -> bool:
    if not isinstance(value, bool):
        raise ValueError("hidden must be a boolean")
    return value


def _normalize_bool(value: Any, field_name: str, default: bool = False) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean")
    return value


def _normalize_optional_int(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer or null")
    return value


def _normalize_limit(value: Any, field_name: str) -> ConfigLimitDTO | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object or null")
    remaining = value.get("remaining_percent")
    if not isinstance(remaining, (int, float)):
        raise ValueError(f"{field_name}.remaining_percent must be a number")
    remaining_float = float(remaining)
    if remaining_float < 0 or remaining_float > 100:
        raise ValueError(f"{field_name}.remaining_percent must be between 0 and 100")
    return ConfigLimitDTO(
        remaining_percent=round(remaining_float, 2),
        window_minutes=_normalize_optional_int(value.get("window_minutes"), f"{field_name}.window_minutes"),
        resets_at=_normalize_optional_int(value.get("resets_at"), f"{field_name}.resets_at"),
    )


def _normalize_account_item(value: Any) -> ConfigAccountDTO:
    if not isinstance(value, dict):
        raise ValueError("account item must be an object")
    account_id = _normalize_account_id(value.get("account_id"))
    return ConfigAccountDTO(
        account_id=account_id,
        display_name=_safe_display_name(value.get("display_name"), account_id),
        custom_name=_normalize_optional_string(value.get("custom_name"), "custom_name"),
        hidden=_normalize_hidden(value.get("hidden")),
        user_name=_normalize_optional_string(value.get("user_name"), "user_name"),
        plan_type=_normalize_optional_string(value.get("plan_type"), "plan_type"),
        expired=_normalize_bool(value.get("expired"), "expired"),
        current=_normalize_bool(value.get("current"), "current"),
        last_scanned_at=_normalize_optional_int(value.get("last_scanned_at"), "last_scanned_at"),
        five_hour=_normalize_limit(value.get("five_hour"), "five_hour"),
        weekly=_normalize_limit(value.get("weekly"), "weekly"),
    )


def _normalize_payload(payload: Any) -> list[ConfigAccountDTO]:
    if not isinstance(payload, dict):
        raise ValueError("Config import must be a JSON object")
    if payload.get("schema") != CONFIG_SCHEMA:
        raise ValueError(f"Unsupported config schema; expected {CONFIG_SCHEMA}")
    accounts = payload.get("accounts")
    if not isinstance(accounts, list):
        raise ValueError("accounts must be a list")
    return [_normalize_account_item(item) for item in accounts]


def import_config(settings: Settings, payload: Any) -> ConfigImportSummary:
    accounts = _normalize_payload(payload)
    current_id = current_account_id(settings.codex_home)
    created = 0
    updated = 0
    skipped = 0
    ts = now_ts()

    with connect(settings.db_path) as conn:
        for account in accounts:
            hidden = False if account.account_id == current_id else account.hidden
            expired_at = ts if account.expired else None
            failed_scan_count = 3 if account.expired else 0
            scanned_at = account.last_scanned_at or ts
            existing = conn.execute(
                "SELECT account_id FROM accounts WHERE account_id = ?",
                (account.account_id,),
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE accounts
                    SET
                        custom_name = ?,
                        hidden = ?,
                        user_name = ?,
                        plan_type = ?,
                        last_scanned_at = ?,
                        expired_at = ?,
                        failed_scan_count = ?,
                        updated_at = ?
                    WHERE account_id = ?
                    """,
                    (
                        account.custom_name,
                        int(hidden),
                        account.user_name,
                        account.plan_type,
                        account.last_scanned_at,
                        expired_at,
                        failed_scan_count,
                        ts,
                        account.account_id,
                    ),
                )
                _insert_limit_snapshot(conn, account, scanned_at)
                updated += 1
                continue

            conn.execute(
                """
                INSERT INTO accounts (
                    account_id, display_name, custom_name, hidden, user_name,
                    plan_type, last_scanned_at, expired_at, failed_scan_count,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    account.account_id,
                    account.display_name,
                    account.custom_name,
                    int(hidden),
                    account.user_name,
                    account.plan_type,
                    account.last_scanned_at,
                    expired_at,
                    failed_scan_count,
                    ts,
                    ts,
                ),
            )
            _insert_limit_snapshot(conn, account, scanned_at)
            created += 1

    return ConfigImportSummary(
        ok=True,
        imported=created + updated,
        created=created,
        updated=updated,
        skipped=skipped,
    )


def _used_percent_from_remaining(limit: ConfigLimitDTO | None) -> float | None:
    if limit is None:
        return None
    return round(max(0.0, min(100.0, 100.0 - limit.remaining_percent)), 2)


def _insert_limit_snapshot(conn, account: ConfigAccountDTO, scanned_at: int) -> None:
    if account.five_hour is None and account.weekly is None:
        return
    raw_json = {
        "source": CONFIG_SCHEMA,
        "five_hour": account.five_hour.model_dump() if account.five_hour else None,
        "weekly": account.weekly.model_dump() if account.weekly else None,
    }
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
            account.account_id,
            scanned_at,
            _used_percent_from_remaining(account.five_hour),
            account.five_hour.window_minutes if account.five_hour else None,
            account.five_hour.resets_at if account.five_hour else None,
            _used_percent_from_remaining(account.weekly),
            account.weekly.window_minutes if account.weekly else None,
            account.weekly.resets_at if account.weekly else None,
            json.dumps(raw_json, ensure_ascii=False),
        ),
    )
