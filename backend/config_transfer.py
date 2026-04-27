from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from codex_files import current_account_id
from config import Settings
from db import connect, now_ts


CONFIG_SCHEMA = "switchboard.config.v1"


class ConfigAccountDTO(BaseModel):
    account_id: str
    display_name: str
    custom_name: str | None
    hidden: bool


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
    with connect(settings.db_path) as conn:
        rows = conn.execute(
            """
            SELECT account_id, display_name, custom_name, hidden
            FROM accounts
            ORDER BY created_at ASC, account_id ASC
            """
        ).fetchall()
    return ConfigExportDTO(
        schema_=CONFIG_SCHEMA,
        exported_at=now_ts(),
        accounts=[
            ConfigAccountDTO(
                account_id=row["account_id"],
                display_name=row["display_name"],
                custom_name=row["custom_name"],
                hidden=bool(row["hidden"]),
            )
            for row in rows
        ],
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


def _normalize_account_item(value: Any) -> ConfigAccountDTO:
    if not isinstance(value, dict):
        raise ValueError("account item must be an object")
    account_id = _normalize_account_id(value.get("account_id"))
    return ConfigAccountDTO(
        account_id=account_id,
        display_name=_safe_display_name(value.get("display_name"), account_id),
        custom_name=_normalize_optional_string(value.get("custom_name"), "custom_name"),
        hidden=_normalize_hidden(value.get("hidden")),
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
            existing = conn.execute(
                "SELECT account_id FROM accounts WHERE account_id = ?",
                (account.account_id,),
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE accounts
                    SET custom_name = ?, hidden = ?, updated_at = ?
                    WHERE account_id = ?
                    """,
                    (account.custom_name, int(hidden), ts, account.account_id),
                )
                updated += 1
                continue

            conn.execute(
                """
                INSERT INTO accounts (
                    account_id, display_name, custom_name, hidden, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (account.account_id, account.display_name, account.custom_name, int(hidden), ts, ts),
            )
            created += 1

    return ConfigImportSummary(
        ok=True,
        imported=created + updated,
        created=created,
        updated=updated,
        skipped=skipped,
    )
