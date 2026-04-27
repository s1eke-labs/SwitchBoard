from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import usage
from config import Settings
from db import init_db
from sessions import get_session_detail, list_sessions
from usage import get_usage_events


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
                'workspace-write', 'on-request', 100, 'gpt-5.5', 1000000, 1100000)
        """,
        ("thread-1", stored_rollout_path or str(rollout)),
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
    assert [event.kind for event in detail.events] == ["user", "assistant", "token_count"]

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

    assert len(all_sessions.items) == 2
    assert all_sessions.total_count == 4
    assert all_sessions.next_cursor == "2"
    assert len(filtered.items) == 1
    assert filtered.total_count == 2
    assert filtered.next_cursor == "1"


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
    assert [event.kind for event in detail.events] == ["user", "assistant", "token_count"]


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
