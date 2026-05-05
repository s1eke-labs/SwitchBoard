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

CREATE TABLE IF NOT EXISTS image_conversations (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS image_jobs (
    id TEXT PRIMARY KEY,
    submission_id TEXT,
    conversation_id TEXT,
    prompt TEXT NOT NULL,
    model TEXT,
    size TEXT NOT NULL,
    quality TEXT NOT NULL,
    n INTEGER NOT NULL DEFAULT 1,
    response_format TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    previous_response_id TEXT,
    upstream_response_id TEXT,
    upstream_metadata_json TEXT,
    result_json TEXT,
    error_json TEXT,
    source TEXT NOT NULL DEFAULT 'local_ui',
    dispatcher_id TEXT,
    source_task_id TEXT,
    idempotency_key TEXT,
    priority INTEGER NOT NULL DEFAULT 0,
    lease_owner TEXT,
    lease_token TEXT,
    lease_expires_at INTEGER,
    started_at INTEGER,
    finished_at INTEGER,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    external_payload_json TEXT,
    external_delivery_status TEXT,
    external_delivery_error_json TEXT,
    local_deleted_at INTEGER,
    FOREIGN KEY(submission_id) REFERENCES image_submissions(id) ON DELETE SET NULL,
    FOREIGN KEY(conversation_id) REFERENCES image_conversations(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_image_jobs_status_created
    ON image_jobs(status, created_at, id);

CREATE INDEX IF NOT EXISTS idx_image_jobs_created
    ON image_jobs(created_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS image_submissions (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    dispatcher_id TEXT,
    source_task_id TEXT,
    idempotency_key TEXT,
    queue TEXT NOT NULL,
    priority INTEGER NOT NULL,
    status TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    external_delivery_status TEXT,
    external_delivery_error_json TEXT,
    external_status_reported_status TEXT,
    external_status_reported_at INTEGER,
    external_status_report_error_json TEXT,
    error_json TEXT,
    metadata_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_image_submissions_created
    ON image_submissions(created_at DESC, id DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_image_submissions_local_idempotency
    ON image_submissions(source, idempotency_key)
    WHERE idempotency_key IS NOT NULL AND source != 'external_dispatcher';

CREATE TABLE IF NOT EXISTS image_task_dispatcher_config (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    name TEXT,
    api_base_url TEXT,
    paused INTEGER NOT NULL DEFAULT 0,
    runner_id TEXT,
    runner_status TEXT NOT NULL DEFAULT 'unconfigured',
    heartbeat_interval_seconds INTEGER,
    poll_interval_seconds INTEGER,
    last_heartbeat_at INTEGER,
    last_claim_at INTEGER,
    current_source_task_id TEXT,
    last_error TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS image_task_dispatchers (
    id TEXT PRIMARY KEY,
    name TEXT,
    api_base_url TEXT,
    paused INTEGER NOT NULL DEFAULT 0,
    runner_id TEXT,
    runner_status TEXT NOT NULL DEFAULT 'unconfigured',
    heartbeat_interval_seconds INTEGER,
    poll_interval_seconds INTEGER,
    last_heartbeat_at INTEGER,
    last_claim_at INTEGER,
    current_source_task_id TEXT,
    last_error TEXT,
    deleted_at INTEGER,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_image_task_dispatchers_deleted
    ON image_task_dispatchers(deleted_at, updated_at DESC);

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


def _migrate_images(conn: sqlite3.Connection) -> None:
    columns = _columns(conn, "image_jobs")
    if "submission_id" not in columns:
        conn.execute("ALTER TABLE image_jobs ADD COLUMN submission_id TEXT")
    if "conversation_id" not in columns:
        conn.execute("ALTER TABLE image_jobs ADD COLUMN conversation_id TEXT")
    if "previous_response_id" not in columns:
        conn.execute("ALTER TABLE image_jobs ADD COLUMN previous_response_id TEXT")
    if "upstream_response_id" not in columns:
        conn.execute("ALTER TABLE image_jobs ADD COLUMN upstream_response_id TEXT")
    if "upstream_metadata_json" not in columns:
        conn.execute("ALTER TABLE image_jobs ADD COLUMN upstream_metadata_json TEXT")
    if "n" not in columns:
        conn.execute("ALTER TABLE image_jobs ADD COLUMN n INTEGER NOT NULL DEFAULT 1")
    added_columns = {
        "source": "TEXT NOT NULL DEFAULT 'local_ui'",
        "dispatcher_id": "TEXT",
        "source_task_id": "TEXT",
        "idempotency_key": "TEXT",
        "priority": "INTEGER NOT NULL DEFAULT 0",
        "lease_owner": "TEXT",
        "lease_token": "TEXT",
        "lease_expires_at": "INTEGER",
        "started_at": "INTEGER",
        "finished_at": "INTEGER",
        "attempt_count": "INTEGER NOT NULL DEFAULT 0",
        "external_payload_json": "TEXT",
        "external_delivery_status": "TEXT",
        "external_delivery_error_json": "TEXT",
        "local_deleted_at": "INTEGER",
    }
    for column_name, column_type in added_columns.items():
        if column_name not in columns:
            conn.execute(f"ALTER TABLE image_jobs ADD COLUMN {column_name} {column_type}")
    submission_columns = _columns(conn, "image_submissions")
    submission_added_columns = {
        "dispatcher_id": "TEXT",
        "external_status_reported_status": "TEXT",
        "external_status_reported_at": "INTEGER",
        "external_status_report_error_json": "TEXT",
        "error_json": "TEXT",
    }
    for column_name, column_type in submission_added_columns.items():
        if column_name not in submission_columns:
            conn.execute(f"ALTER TABLE image_submissions ADD COLUMN {column_name} {column_type}")
    now = now_ts()
    dispatcher_columns = _columns(conn, "image_task_dispatchers")
    if dispatcher_columns:
        legacy = conn.execute("SELECT * FROM image_task_dispatcher_config WHERE id = 1").fetchone()
        existing_default = conn.execute("SELECT id FROM image_task_dispatchers WHERE id = 'default'").fetchone()
        if legacy is not None and existing_default is None:
            conn.execute(
                """
                INSERT INTO image_task_dispatchers (
                    id, name, api_base_url, paused, runner_id, runner_status,
                    heartbeat_interval_seconds, poll_interval_seconds,
                    last_heartbeat_at, last_claim_at, current_source_task_id,
                    last_error, deleted_at, created_at, updated_at
                )
                VALUES ('default', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
                """,
                (
                    legacy["name"],
                    legacy["api_base_url"],
                    int(legacy["paused"] or 0),
                    legacy["runner_id"],
                    legacy["runner_status"] or "unconfigured",
                    legacy["heartbeat_interval_seconds"],
                    legacy["poll_interval_seconds"],
                    legacy["last_heartbeat_at"],
                    legacy["last_claim_at"],
                    legacy["current_source_task_id"],
                    legacy["last_error"],
                    int(legacy["created_at"] or now),
                    int(legacy["updated_at"] or now),
                ),
            )
    conn.execute("UPDATE image_submissions SET dispatcher_id = 'default' WHERE source = 'external_dispatcher' AND dispatcher_id IS NULL")
    conn.execute("UPDATE image_jobs SET dispatcher_id = 'default' WHERE source = 'external_dispatcher' AND dispatcher_id IS NULL")
    for row in conn.execute("SELECT id, source, source_task_id, idempotency_key, created_at, updated_at FROM image_jobs WHERE submission_id IS NULL"):
        submission_id = f"legacy-{row['id']}"
        source = str(row["source"] or "local_ui")
        conn.execute(
            """
            INSERT OR IGNORE INTO image_submissions (
                id, source, dispatcher_id, source_task_id, idempotency_key, queue, priority, status,
                created_at, updated_at, external_delivery_status, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, 'default', 0, 'accepted', ?, ?, NULL, NULL)
            """,
            (
                submission_id,
                source,
                "default" if source == "external_dispatcher" else None,
                row["source_task_id"],
                row["idempotency_key"],
                int(row["created_at"] or now),
                int(row["updated_at"] or now),
            ),
        )
        conn.execute("UPDATE image_jobs SET submission_id = ? WHERE id = ?", (submission_id, row["id"]))
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_image_jobs_conversation_created
            ON image_jobs(conversation_id, created_at ASC, id ASC)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_image_jobs_claim
            ON image_jobs(status, priority DESC, created_at ASC, id ASC)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_image_jobs_lease
            ON image_jobs(status, lease_expires_at)
        """
    )
    conn.execute("DROP INDEX IF EXISTS idx_image_submissions_source_idempotency")
    conn.execute("DROP INDEX IF EXISTS idx_image_submissions_source_task")
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_image_submissions_local_idempotency
            ON image_submissions(source, idempotency_key)
            WHERE idempotency_key IS NOT NULL AND source != 'external_dispatcher'
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_image_submissions_dispatcher_idempotency
            ON image_submissions(dispatcher_id, idempotency_key)
            WHERE idempotency_key IS NOT NULL AND source = 'external_dispatcher'
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_image_submissions_dispatcher_task
            ON image_submissions(dispatcher_id, source_task_id)
            WHERE source_task_id IS NOT NULL AND source = 'external_dispatcher'
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_image_jobs_dispatcher_status
            ON image_jobs(dispatcher_id, status, created_at)
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
        _migrate_images(conn)


def now_ts() -> int:
    return int(time.time())


def rows(conn: sqlite3.Connection, query: str, params: tuple = ()) -> Iterator[sqlite3.Row]:
    yield from conn.execute(query, params)
