from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Iterator


SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS accounts (
    account_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    custom_name TEXT,
    user_name TEXT,
    plan_type TEXT,
    hidden INTEGER NOT NULL DEFAULT 0,
    last_scanned_at INTEGER,
    last_error TEXT,
    failed_scan_count INTEGER NOT NULL DEFAULT 0,
    expired_at INTEGER,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS rate_limit_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL,
    scanned_at INTEGER NOT NULL,
    five_hour_used_percent REAL,
    five_hour_window_minutes INTEGER,
    five_hour_resets_at INTEGER,
    weekly_used_percent REAL,
    weekly_window_minutes INTEGER,
    weekly_resets_at INTEGER,
    raw_json TEXT NOT NULL,
    FOREIGN KEY(account_id) REFERENCES accounts(account_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_rate_limit_snapshots_account_scanned
    ON rate_limit_snapshots(account_id, scanned_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS usage_events (
    thread_id TEXT NOT NULL,
    event_index INTEGER NOT NULL,
    account_id TEXT,
    occurred_at INTEGER NOT NULL,
    model TEXT,
    input_tokens INTEGER NOT NULL,
    cache_hit_tokens INTEGER NOT NULL,
    cache_creation_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    reasoning_output_tokens INTEGER NOT NULL,
    total_tokens INTEGER NOT NULL,
    cost_usd REAL,
    cost_known INTEGER NOT NULL,
    PRIMARY KEY(thread_id, event_index)
);

CREATE INDEX IF NOT EXISTS idx_usage_events_occurred_at
    ON usage_events(occurred_at);

CREATE TABLE IF NOT EXISTS account_usage_intervals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL,
    started_at INTEGER NOT NULL,
    ended_at INTEGER,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_account_usage_intervals_open
    ON account_usage_intervals(ended_at, started_at);

CREATE INDEX IF NOT EXISTS idx_account_usage_intervals_account_range
    ON account_usage_intervals(account_id, started_at, ended_at);

CREATE TABLE IF NOT EXISTS usage_source_scans (
    path TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    mtime_ns INTEGER NOT NULL,
    size_bytes INTEGER NOT NULL,
    byte_offset INTEGER NOT NULL,
    line_count INTEGER NOT NULL,
    last_model TEXT
);

CREATE TABLE IF NOT EXISTS usage_aggregate_points (
    range_key TEXT NOT NULL,
    bucket TEXT NOT NULL,
    bucket_start INTEGER NOT NULL,
    bucket_end INTEGER NOT NULL,
    input_tokens INTEGER NOT NULL,
    cache_hit_tokens INTEGER NOT NULL,
    cache_creation_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    reasoning_output_tokens INTEGER NOT NULL,
    total_tokens INTEGER NOT NULL,
    cost_usd REAL,
    cost_known INTEGER NOT NULL,
    unknown_cost_events INTEGER NOT NULL,
    event_count INTEGER NOT NULL,
    PRIMARY KEY(range_key, bucket_start)
);

CREATE INDEX IF NOT EXISTS idx_usage_aggregate_points_range
    ON usage_aggregate_points(range_key, bucket_start);

CREATE TABLE IF NOT EXISTS usage_aggregate_runs (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    generated_at INTEGER NOT NULL,
    source_event_count INTEGER NOT NULL,
    source_max_occurred_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS scan_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT,
    started_at INTEGER NOT NULL,
    finished_at INTEGER,
    status TEXT NOT NULL,
    error TEXT
);

CREATE TABLE IF NOT EXISTS image_jobs (
    id TEXT PRIMARY KEY,
    prompt TEXT NOT NULL,
    model TEXT,
    size TEXT NOT NULL,
    quality TEXT NOT NULL,
    response_format TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    result_json TEXT,
    error_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_image_jobs_status_created
    ON image_jobs(status, created_at, id);

CREATE INDEX IF NOT EXISTS idx_image_jobs_created
    ON image_jobs(created_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS image_job_references (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    original_file_name TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    file_name TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    FOREIGN KEY(job_id) REFERENCES image_jobs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_image_job_references_job_position
    ON image_job_references(job_id, position);
"""


def _columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table_name})")}


def _migrate_accounts(conn: sqlite3.Connection) -> None:
    columns = _columns(conn, "accounts")
    if "custom_name" not in columns:
        conn.execute("ALTER TABLE accounts ADD COLUMN custom_name TEXT")
    if "user_name" not in columns:
        conn.execute("ALTER TABLE accounts ADD COLUMN user_name TEXT")
    if "failed_scan_count" not in columns:
        conn.execute("ALTER TABLE accounts ADD COLUMN failed_scan_count INTEGER NOT NULL DEFAULT 0")
    if "expired_at" not in columns:
        conn.execute("ALTER TABLE accounts ADD COLUMN expired_at INTEGER")
    if "workspace_name" in columns:
        conn.execute("ALTER TABLE accounts DROP COLUMN workspace_name")


def _migrate_usage_events(conn: sqlite3.Connection) -> None:
    columns = _columns(conn, "usage_events")
    if "account_id" not in columns:
        conn.execute("ALTER TABLE usage_events ADD COLUMN account_id TEXT")
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_usage_events_account_occurred
            ON usage_events(account_id, occurred_at)
        """
    )


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        _migrate_accounts(conn)
        _migrate_usage_events(conn)


def now_ts() -> int:
    return int(time.time())


def rows(conn: sqlite3.Connection, query: str, params: tuple = ()) -> Iterator[sqlite3.Row]:
    yield from conn.execute(query, params)
