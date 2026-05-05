from __future__ import annotations

import sqlite3

from config import Settings
from db import connect, now_ts


def _validate_account_id(account_id: str) -> None:
    if not account_id or "/" in account_id or "\\" in account_id or account_id in {".", ".."}:
        raise ValueError("Invalid account_id")


def observe_account_usage_conn(conn: sqlite3.Connection, account_id: str, observed_at: int | None = None) -> None:
    _validate_account_id(account_id)
    ts = observed_at if observed_at is not None else now_ts()
    open_interval = conn.execute(
        """
        SELECT account_id
        FROM account_usage_intervals
        WHERE ended_at IS NULL
        ORDER BY started_at DESC, id DESC
        LIMIT 1
        """
    ).fetchone()
    if open_interval and open_interval["account_id"] == account_id:
        return

    conn.execute(
        """
        UPDATE account_usage_intervals
        SET ended_at = ?, updated_at = ?
        WHERE ended_at IS NULL AND account_id <> ?
        """,
        (ts, ts, account_id),
    )
    current_interval = conn.execute(
        """
        SELECT id
        FROM account_usage_intervals
        WHERE account_id = ? AND ended_at IS NULL
        LIMIT 1
        """,
        (account_id,),
    ).fetchone()
    if current_interval:
        return

    conn.execute(
        """
        INSERT INTO account_usage_intervals(account_id, started_at, ended_at, created_at, updated_at)
        VALUES (?, ?, NULL, ?, ?)
        """,
        (account_id, ts, ts, ts),
    )


def observe_account_usage(settings: Settings, account_id: str, observed_at: int | None = None) -> None:
    with connect(settings.db_path) as conn:
        observe_account_usage_conn(conn, account_id, observed_at)
