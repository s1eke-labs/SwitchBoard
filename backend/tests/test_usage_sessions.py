from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import usage
from config import Settings
from db import connect, init_db
from sessions import get_session_detail, get_session_event, list_session_events, list_session_user_index, list_sessions
from usage import get_usage_events, get_usage_request_logs


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


def _create_state(
    settings: Settings,
    rollout: Path,
    stored_rollout_path: str | None = None,
    extra_threads: list[tuple[str, str]] | None = None,
    model: str | None = "gpt-5.5",
) -> None:
    conn = sqlite3.connect(settings.codex_home / "state_5.sqlite")
    conn.execute(
        """
        CREATE TABLE threads (
            id TEXT PRIMARY KEY,
            rollout_path TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            source TEXT NOT NULL,
            model_provider TEXT NOT NULL,
            cwd TEXT NOT NULL,
            title TEXT NOT NULL,
            sandbox_policy TEXT NOT NULL,
            approval_mode TEXT NOT NULL,
            tokens_used INTEGER NOT NULL DEFAULT 0,
            has_user_event INTEGER NOT NULL DEFAULT 0,
            archived INTEGER NOT NULL DEFAULT 0,
            archived_at INTEGER,
            git_sha TEXT,
            git_branch TEXT,
            git_origin_url TEXT,
            cli_version TEXT NOT NULL DEFAULT '',
            first_user_message TEXT NOT NULL DEFAULT '',
            agent_nickname TEXT,
            agent_role TEXT,
            memory_mode TEXT NOT NULL DEFAULT 'enabled',
            model TEXT,
            reasoning_effort TEXT,
            agent_path TEXT,
            created_at_ms INTEGER,
            updated_at_ms INTEGER
        )
        """
    )
    conn.execute(
        """
        INSERT INTO threads (
            id, rollout_path, created_at, updated_at, source, model_provider, cwd, title,
            sandbox_policy, approval_mode, tokens_used, model, created_at_ms, updated_at_ms
        )
        VALUES (?, ?, 1000, 1100, 'cli', 'openai', '/repo', 'Build app',
                'workspace-write', 'on-request', 100, ?, 1000000, 1100000)
        """,
        ("thread-1", stored_rollout_path or str(rollout), model),
    )
    for index, (thread_id, title) in enumerate(extra_threads or [], start=2):
        conn.execute(
            """
            INSERT INTO threads (
                id, rollout_path, created_at, updated_at, source, model_provider, cwd, title,
                sandbox_policy, approval_mode, tokens_used, model, created_at_ms, updated_at_ms
            )
            VALUES (?, ?, ?, ?, 'cli', 'openai', '/repo', ?,
                    'workspace-write', 'on-request', 100, 'gpt-5.5', ?, ?)
            """,
            (thread_id, str(rollout), 1000 + index, 1100 + index, title, 1000000 + index, 1100000 + index),
        )
    conn.commit()
    conn.close()


def _write_rollout(path: Path) -> None:
    rows = [
        {
            "type": "event_msg",
            "timestamp": "2026-04-25T00:00:00Z",
            "payload": {"type": "user_message", "message": "hello"},
        },
        {
            "type": "response_item",
            "timestamp": "2026-04-25T00:01:00Z",
            "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "hi"}]},
        },
        {
            "type": "event_msg",
            "timestamp": "2026-04-25T00:02:00Z",
            "payload": {
                "type": "token_count",
                "info": {
                    "last_token_usage": {
                        "input_tokens": 1000,
                        "cached_input_tokens": 400,
                        "output_tokens": 50,
                        "reasoning_output_tokens": 10,
                        "total_tokens": 1050,
                    }
                },
            },
        },
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")


def _append_usage_row(path: Path, timestamp: str, input_tokens: int) -> None:
    row = {
        "type": "event_msg",
        "timestamp": timestamp,
        "payload": {
            "type": "token_count",
            "info": {
                "last_token_usage": {
                    "input_tokens": input_tokens,
                    "cached_input_tokens": 0,
                    "output_tokens": 10,
                    "reasoning_output_tokens": 0,
                    "total_tokens": input_tokens + 10,
                }
            },
        },
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n" + json.dumps(row))


def test_sessions_and_usage_events_from_rollout(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    init_db(settings.db_path)
    rollout = settings.codex_home / "rollout.jsonl"
    _write_rollout(rollout)
    _create_state(settings, rollout)

    listed = list_sessions(settings)
    assert listed.items[0].thread_id == "thread-1"
    assert listed.total_count == 1

    detail = get_session_detail(settings, "thread-1")
    assert detail.raw_event_count == 3
    assert detail.event_count == 3

    first_page = list_session_events(settings, "thread-1", limit=2)
    second_page = list_session_events(settings, "thread-1", cursor=first_page.next_cursor, limit=2)
    assert [event.kind for event in first_page.items] == ["user", "assistant"]
    assert first_page.next_cursor is not None
    assert [event.kind for event in second_page.items] == ["token_count"]
    assert second_page.next_cursor is None
    assert get_session_event(settings, "thread-1", first_page.items[1].line_no).text == "hi"

    events = get_usage_events(settings, "1777075200", "1777161600")
    assert len(events.items) == 1
    event = events.items[0]
    assert event.occurred_at == 1777075320
    assert event.input_tokens == 1000
    assert event.cache_hit_tokens == 400
    assert event.cache_creation_tokens == 600
    assert event.output_tokens == 50
    assert event.cost_usd is not None


def test_session_list_reports_total_count_with_filters(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    init_db(settings.db_path)
    rollout = settings.codex_home / "rollout.jsonl"
    _write_rollout(rollout)
    _create_state(
        settings,
        rollout,
        extra_threads=[
            ("thread-2", "Second build"),
            ("thread-3", "Usage report"),
            ("thread-4", "Usage cleanup"),
        ],
    )

    all_sessions = list_sessions(settings, limit=2)
    filtered = list_sessions(settings, query="Usage", limit=1)
    filtered_second_page = list_sessions(settings, query="Usage", limit=1, cursor=filtered.next_cursor)
    all_sessions_second_page = list_sessions(settings, limit=2, cursor=all_sessions.next_cursor)
    all_sessions_second_page_by_page = list_sessions(settings, limit=2, page=2)
    filtered_second_page_by_page = list_sessions(settings, query="Usage", limit=1, page=2)
    out_of_range = list_sessions(settings, limit=2, page=99)

    assert [item.thread_id for item in all_sessions.items] == ["thread-4", "thread-3"]
    assert all_sessions.total_count == 4
    assert all_sessions.next_cursor is not None
    assert [item.thread_id for item in all_sessions_second_page.items] == ["thread-2", "thread-1"]
    assert [item.thread_id for item in all_sessions_second_page_by_page.items] == ["thread-2", "thread-1"]
    assert all_sessions_second_page.next_cursor is None
    assert [item.thread_id for item in filtered.items] == ["thread-4"]
    assert filtered.total_count == 2
    assert filtered.next_cursor is not None
    assert [item.thread_id for item in filtered_second_page.items] == ["thread-3"]
    assert [item.thread_id for item in filtered_second_page_by_page.items] == ["thread-3"]
    assert filtered_second_page.next_cursor is None
    assert out_of_range.items == []
    assert out_of_range.total_count == 4
    assert out_of_range.next_cursor is None


def test_session_list_rejects_malformed_cursor(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    init_db(settings.db_path)

    with pytest.raises(ValueError, match="Invalid cursor"):
        list_sessions(settings, cursor="not-a-valid-cursor")


def test_session_list_rejects_invalid_page(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    init_db(settings.db_path)

    with pytest.raises(ValueError, match="Invalid page"):
        list_sessions(settings, page=0)


def test_session_detail_remaps_absolute_rollout_under_codex_home(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    init_db(settings.db_path)
    rollout = settings.codex_home / "sessions" / "2026" / "04" / "25" / "rollout-thread-1.jsonl"
    rollout.parent.mkdir(parents=True)
    _write_rollout(rollout)
    _create_state(
        settings,
        rollout,
        stored_rollout_path="/host/home/.codex/sessions/2026/04/25/rollout-thread-1.jsonl",
    )

    detail = get_session_detail(settings, "thread-1")

    assert detail.raw_event_count == 3
    assert detail.event_count == 3


def test_session_detail_counts_events_with_single_rollout_read(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    init_db(settings.db_path)
    rollout = settings.codex_home / "rollout.jsonl"
    _write_rollout(rollout)
    _create_state(settings, rollout)
    original_open = Path.open
    rollout_open_count = 0

    def counting_open(path: Path, *args, **kwargs):
        nonlocal rollout_open_count
        if path == rollout:
            rollout_open_count += 1
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", counting_open)

    detail = get_session_detail(settings, "thread-1")

    assert detail.raw_event_count == 3
    assert detail.event_count == 3
    assert rollout_open_count == 1


def test_session_detail_resolves_rollout_from_filename_date_without_recursive_scan(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = _settings(tmp_path)
    init_db(settings.db_path)
    filename = "rollout-2026-04-25T00-00-00-thread-1.jsonl"
    rollout = settings.codex_home / "sessions" / "2026" / "04" / "25" / filename
    rollout.parent.mkdir(parents=True)
    _write_rollout(rollout)
    _create_state(settings, rollout, stored_rollout_path=f"/stale/codex/{filename}")

    def fail_rglob(path: Path, pattern: str):
        raise AssertionError(f"unexpected recursive rollout scan: {path} {pattern}")

    monkeypatch.setattr(Path, "rglob", fail_rglob)

    detail = get_session_detail(settings, "thread-1")

    assert detail.raw_event_count == 3
    assert detail.event_count == 3


def test_session_detail_missing_rollout_does_not_recursive_scan(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = _settings(tmp_path)
    init_db(settings.db_path)
    (settings.codex_home / "sessions").mkdir()
    missing_rollout = settings.codex_home / "missing-rollout-thread-1.jsonl"
    _create_state(settings, missing_rollout, stored_rollout_path="/stale/codex/missing-rollout-thread-1.jsonl")

    def fail_rglob(path: Path, pattern: str):
        raise AssertionError(f"unexpected recursive rollout scan: {path} {pattern}")

    monkeypatch.setattr(Path, "rglob", fail_rglob)

    detail = get_session_detail(settings, "thread-1")

    assert detail.raw_event_count == 0
    assert detail.event_count == 0


def test_session_event_preview_truncates_without_truncating_full_event(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    init_db(settings.db_path)
    rollout = settings.codex_home / "rollout.jsonl"
    full_output = "x" * 5001
    row = {
        "type": "response_item",
        "timestamp": "2026-04-25T00:01:00Z",
        "payload": {"type": "function_call_output", "output": full_output},
    }
    rollout.write_text(json.dumps(row), encoding="utf-8")
    _create_state(settings, rollout)

    page = list_session_events(settings, "thread-1")
    full_event = get_session_event(settings, "thread-1", page.items[0].line_no)

    assert page.items[0].body_truncated is True
    assert len(page.items[0].body_preview) == 4000
    assert full_event.text == full_output


def test_session_user_index_lists_user_events_with_event_indexes(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    init_db(settings.db_path)
    rollout = settings.codex_home / "rollout.jsonl"
    rows = [
        {
            "type": "event_msg",
            "timestamp": "2026-04-25T00:00:00Z",
            "payload": {"type": "user_message", "message": "first user message"},
        },
        {
            "type": "response_item",
            "timestamp": "2026-04-25T00:01:00Z",
            "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "reply"}]},
        },
        {
            "type": "event_msg",
            "timestamp": "2026-04-25T00:02:00Z",
            "payload": {"type": "user_message", "message": "second user message"},
        },
    ]
    rollout.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    _create_state(settings, rollout)

    index = list_session_user_index(settings, "thread-1")

    assert [item.body_preview for item in index.items] == ["first user message", "second user message"]
    assert [item.event_index for item in index.items] == [0, 2]
    assert [item.line_no for item in index.items] == [1, 3]
    assert index.items[0].body_bytes == len("first user message".encode("utf-8"))


def test_session_events_skip_duplicate_response_item_user_messages(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    init_db(settings.db_path)
    rollout = settings.codex_home / "rollout.jsonl"
    rows = [
        {
            "type": "response_item",
            "timestamp": "2026-04-25T00:00:00Z",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "duplicated user message"}],
            },
        },
        {
            "type": "event_msg",
            "timestamp": "2026-04-25T00:00:00Z",
            "payload": {"type": "user_message", "message": "duplicated user message"},
        },
        {
            "type": "response_item",
            "timestamp": "2026-04-25T00:01:00Z",
            "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "reply"}]},
        },
    ]
    rollout.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    _create_state(settings, rollout)

    detail = get_session_detail(settings, "thread-1")
    page = list_session_events(settings, "thread-1")
    index = list_session_user_index(settings, "thread-1")

    assert detail.raw_event_count == 3
    assert detail.event_count == 2
    assert [(event.kind, event.line_no, event.body_preview) for event in page.items] == [
        ("user", 2, "duplicated user message"),
        ("assistant", 3, "reply"),
    ]
    assert [(item.line_no, item.event_index, item.body_preview) for item in index.items] == [
        (2, 0, "duplicated user message")
    ]


def test_session_events_skip_duplicate_assistant_message_sources(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    init_db(settings.db_path)
    rollout = settings.codex_home / "rollout.jsonl"
    rows = [
        {
            "type": "event_msg",
            "timestamp": "2026-04-25T00:00:00Z",
            "payload": {"type": "user_message", "message": "hello"},
        },
        {
            "type": "response_item",
            "timestamp": "2026-04-25T00:01:00Z",
            "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "same reply"}]},
        },
        {
            "type": "event_msg",
            "timestamp": "2026-04-25T00:01:00Z",
            "payload": {"type": "agent_message", "message": "same reply"},
        },
        {
            "type": "event_msg",
            "timestamp": "2026-04-25T00:02:00Z",
            "payload": {"type": "token_count", "info": {"last_token_usage": {"total_tokens": 10}}},
        },
    ]
    rollout.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    _create_state(settings, rollout)

    detail = get_session_detail(settings, "thread-1")
    first_page = list_session_events(settings, "thread-1", limit=2)
    second_page = list_session_events(settings, "thread-1", cursor=first_page.next_cursor, limit=2)
    index = list_session_user_index(settings, "thread-1")

    assert detail.raw_event_count == 4
    assert detail.event_count == 3
    assert [(event.kind, event.line_no, event.body_preview) for event in first_page.items] == [
        ("user", 1, "hello"),
        ("assistant", 2, "same reply"),
    ]
    assert first_page.next_cursor is not None
    assert [(event.kind, event.line_no) for event in second_page.items] == [("token_count", 4)]
    assert second_page.next_cursor is None
    assert [(item.line_no, item.event_index, item.body_preview) for item in index.items] == [(1, 0, "hello")]


def test_session_events_keep_agent_message_without_response_item(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    init_db(settings.db_path)
    rollout = settings.codex_home / "rollout.jsonl"
    rows = [
        {
            "type": "event_msg",
            "timestamp": "2026-04-25T00:00:00Z",
            "payload": {"type": "user_message", "message": "hello"},
        },
        {
            "type": "event_msg",
            "timestamp": "2026-04-25T00:01:00Z",
            "payload": {"type": "agent_message", "message": "agent-only reply"},
        },
    ]
    rollout.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    _create_state(settings, rollout)

    detail = get_session_detail(settings, "thread-1")
    page = list_session_events(settings, "thread-1")

    assert detail.event_count == 2
    assert [(event.kind, event.line_no, event.body_preview) for event in page.items] == [
        ("user", 1, "hello"),
        ("assistant", 2, "agent-only reply"),
    ]


def test_usage_events_fall_back_to_sessions_directory(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    init_db(settings.db_path)
    sessions_dir = settings.codex_home / "sessions" / "2026" / "04" / "25"
    sessions_dir.mkdir(parents=True)
    rollout = sessions_dir / "rollout-2026-04-25T00-00-00-thread-2.jsonl"
    _write_rollout(rollout)

    events = get_usage_events(settings, "1777075200", "1777161600")

    assert len(events.items) == 1
    assert events.items[0].input_tokens == 1000
    assert events.items[0].cache_hit_tokens == 400


def test_usage_events_remap_absolute_rollout_under_codex_home(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    init_db(settings.db_path)
    rollout = settings.codex_home / "sessions" / "2026" / "04" / "25" / "rollout-thread-1.jsonl"
    rollout.parent.mkdir(parents=True)
    _write_rollout(rollout)
    _create_state(
        settings,
        rollout,
        stored_rollout_path="/home/debian/.codex/sessions/2026/04/25/rollout-thread-1.jsonl",
    )

    events = get_usage_events(settings, "1777075200", "1777161600")

    assert len(events.items) == 1
    assert events.items[0].thread_id == "thread-1"
    assert events.items[0].input_tokens == 1000
    assert events.items[0].cache_hit_tokens == 400


def test_usage_request_logs_default_to_recent_day(monkeypatch, tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    init_db(settings.db_path)
    rollout = settings.codex_home / "rollout.jsonl"
    _write_rollout(rollout)
    _append_usage_row(rollout, "2026-04-23T00:00:00Z", 2000)
    _create_state(settings, rollout)
    monkeypatch.setattr(usage, "_utc_now_ts", lambda: 1777078800)

    logs = get_usage_request_logs(settings)

    assert logs.total_count == 1
    assert logs.summary.request_count == 1
    assert logs.summary.total_tokens == 1050
    assert logs.summary.cache_hit_tokens == 400
    assert logs.summary.total_cost_usd is not None
    assert logs.next_cursor is None
    assert len(logs.items) == 1
    assert logs.items[0].id == "thread-1:2"
    assert logs.items[0].billing_model == "gpt-5.5"
    assert logs.items[0].input_tokens == 1000
    assert logs.items[0].output_tokens == 50
    assert logs.items[0].total_cost_usd is not None


def test_usage_request_logs_filter_and_paginate_descending(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    init_db(settings.db_path)
    rollout = settings.codex_home / "rollout.jsonl"
    _write_rollout(rollout)
    _append_usage_row(rollout, "2026-04-25T00:03:00Z", 2000)
    _append_usage_row(rollout, "2026-04-25T00:03:00Z", 3000)
    _create_state(settings, rollout)

    first_page = get_usage_request_logs(settings, "1777075200", "1777161600", limit=2)
    second_page = get_usage_request_logs(settings, "1777075200", "1777161600", limit=2, cursor=first_page.next_cursor)
    second_page_by_page = get_usage_request_logs(settings, "1777075200", "1777161600", limit=2, page=2)
    out_of_range = get_usage_request_logs(settings, "1777075200", "1777161600", limit=2, page=99)

    assert first_page.total_count == 3
    assert first_page.summary.request_count == 3
    assert first_page.summary.input_tokens == 6000
    assert first_page.summary.output_tokens == 70
    assert [item.input_tokens for item in first_page.items] == [3000, 2000]
    assert first_page.next_cursor is not None
    assert [item.input_tokens for item in second_page.items] == [1000]
    assert [item.input_tokens for item in second_page_by_page.items] == [1000]
    assert second_page.next_cursor is None
    assert out_of_range.items == []
    assert out_of_range.total_count == 3
    assert out_of_range.next_cursor is None


def test_usage_request_logs_reject_invalid_page(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    init_db(settings.db_path)

    with pytest.raises(ValueError, match="Invalid page"):
        get_usage_request_logs(settings, page=0)


def test_usage_request_logs_unknown_model_has_zero_cost(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    init_db(settings.db_path)
    rollout = settings.codex_home / "rollout.jsonl"
    _write_rollout(rollout)
    _create_state(settings, rollout, model="mystery-model")

    logs = get_usage_request_logs(settings, "1777075200", "1777161600")

    assert len(logs.items) == 1
    assert logs.items[0].billing_model == "mystery-model"
    assert logs.items[0].total_cost_usd == 0.0
    assert logs.items[0].cost_known is True
    assert logs.summary.total_cost_usd == 0.0
    assert logs.summary.cost_known is True
    assert logs.summary.unknown_cost_events == 0


def test_usage_events_migration_keeps_existing_events_unassigned(tmp_path: Path) -> None:
    db_path = tmp_path / "switchboard.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE usage_events (
            thread_id TEXT NOT NULL,
            event_index INTEGER NOT NULL,
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
        )
        """
    )
    conn.execute(
        """
        INSERT INTO usage_events(
            thread_id, event_index, occurred_at, model, input_tokens, cache_hit_tokens,
            cache_creation_tokens, output_tokens, reasoning_output_tokens, total_tokens, cost_usd, cost_known
        )
        VALUES ('thread-old', 1, 1777075320, 'gpt-5.5', 100, 0, 100, 10, 0, 110, 0.01, 1)
        """
    )
    conn.commit()
    conn.close()

    init_db(db_path)

    with sqlite3.connect(db_path) as migrated:
        migrated.row_factory = sqlite3.Row
        columns = {row["name"] for row in migrated.execute("PRAGMA table_info(usage_events)")}
        row = migrated.execute("SELECT account_id FROM usage_events WHERE thread_id = 'thread-old'").fetchone()
        interval_table = migrated.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'account_usage_intervals'"
        ).fetchone()

    assert "account_id" in columns
    assert row["account_id"] is None
    assert interval_table is not None


def test_usage_request_logs_attribute_events_and_filter_by_account(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    init_db(settings.db_path)
    rollout = settings.codex_home / "rollout.jsonl"
    _write_rollout(rollout)
    _append_usage_row(rollout, "2026-04-25T00:03:00Z", 2000)
    _append_usage_row(rollout, "2026-04-25T00:04:00Z", 3000)
    _create_state(settings, rollout)
    with connect(settings.db_path) as conn:
        conn.execute(
            "INSERT INTO accounts(account_id, display_name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("acct-one", "Ada", 1777075200, 1777075200),
        )
        conn.execute(
            "INSERT INTO accounts(account_id, display_name, custom_name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("acct-two", "Grace", "Team Grace", 1777075200, 1777075200),
        )
        conn.execute(
            """
            INSERT INTO account_usage_intervals(account_id, started_at, ended_at, created_at, updated_at)
            VALUES
                ('acct-one', 1777075200, 1777075380, 1777075200, 1777075380),
                ('acct-two', 1777075380, 1777075420, 1777075380, 1777075420)
            """
        )

    all_logs = get_usage_request_logs(settings, "1777075200", "1777161600")
    acct_one = get_usage_request_logs(settings, "1777075200", "1777161600", account_id="acct-one")
    acct_two = get_usage_request_logs(settings, "1777075200", "1777161600", account_id="acct-two")
    unassigned = get_usage_request_logs(settings, "1777075200", "1777161600", account_id="__unassigned__")

    assert all_logs.total_count == 3
    assert acct_one.total_count == 1
    assert acct_one.summary.request_count == 1
    assert acct_one.summary.input_tokens == 1000
    assert acct_one.items[0].account_id == "acct-one"
    assert acct_one.items[0].account_display_name == "Ada"
    assert acct_two.total_count == 1
    assert acct_two.summary.input_tokens == 2000
    assert acct_two.items[0].account_id == "acct-two"
    assert acct_two.items[0].account_display_name == "Team Grace"
    assert unassigned.total_count == 1
    assert unassigned.summary.input_tokens == 3000
    assert unassigned.items[0].account_id is None
    assert unassigned.items[0].account_display_name is None


def test_usage_aggregates_are_precomputed_for_all_ranges(monkeypatch, tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    init_db(settings.db_path)
    rollout = settings.codex_home / "rollout.jsonl"
    _write_rollout(rollout)
    _create_state(settings, rollout)
    monkeypatch.setattr(usage, "_utc_now_ts", lambda: 1777086300)

    aggregates = usage.get_usage_aggregates(settings)

    assert aggregates.generated_at == 1777086000
    assert set(aggregates.ranges) == {"24h", "7d", "30d", "90d"}
    assert aggregates.ranges["24h"].bucket == "hour"
    assert aggregates.ranges["7d"].bucket == "day"
    assert aggregates.ranges["30d"].bucket == "day"
    assert aggregates.ranges["90d"].bucket == "week"
    assert aggregates.ranges["24h"].event_count == 1

    event_hour = next(point for point in aggregates.ranges["24h"].items if point.event_count)
    assert event_hour.bucket_start == 1777075200
    assert event_hour.bucket_end == 1777078800
    assert event_hour.input_tokens == 1000
    assert event_hour.cache_hit_tokens == 400
    assert event_hour.cache_creation_tokens == 600
    assert event_hour.output_tokens == 50
    assert event_hour.cost_usd is not None

    monkeypatch.setattr(usage, "_utc_now_ts", lambda: 1777086500)
    cached = usage.get_usage_aggregates(settings)
    assert cached.generated_at == 1777086000

    monkeypatch.setattr(usage, "_utc_now_ts", lambda: 1777086601)
    refreshed = usage.get_usage_aggregates(settings)
    assert refreshed.generated_at == 1777086600


def test_usage_sync_skips_unchanged_rollouts(monkeypatch, tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    init_db(settings.db_path)
    rollout = settings.codex_home / "rollout.jsonl"
    _write_rollout(rollout)
    _create_state(settings, rollout)
    monkeypatch.setattr(usage, "_utc_now_ts", lambda: 1777086300)

    usage.get_usage_aggregates(settings)

    def fail_loads(_: str) -> dict:
        raise AssertionError("unchanged rollout was parsed again")

    monkeypatch.setattr(usage.json, "loads", fail_loads)
    cached = usage.get_usage_aggregates(settings)

    assert cached.generated_at == 1777086000


def test_usage_sync_reads_only_appended_rollout_lines(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    init_db(settings.db_path)
    rollout = settings.codex_home / "rollout.jsonl"
    _write_rollout(rollout)
    _create_state(settings, rollout)

    first = get_usage_events(settings, "1777075200", "1777161600")
    assert len(first.items) == 1

    _append_usage_row(rollout, "2026-04-25T00:03:00Z", 2000)
    second = get_usage_events(settings, "1777075200", "1777161600")

    assert [event.input_tokens for event in second.items] == [1000, 2000]
