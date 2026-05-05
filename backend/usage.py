from __future__ import annotations

import base64
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from pydantic import BaseModel

from account_usage import observe_account_usage_conn
from config import Settings
from codex_files import current_account_id
from db import connect
from pricing import estimate_cost
from sessions import _readonly_connect, _state_db_path, iso_to_ts, resolve_rollout_path


class UsageEventDTO(BaseModel):
    thread_id: str
    event_index: int
    occurred_at: int
    model: str | None
    input_tokens: int
    cache_creation_tokens: int
    cache_hit_tokens: int
    output_tokens: int
    reasoning_output_tokens: int
    total_tokens: int
    cost_usd: float | None
    cost_known: bool


class UsageEventsResponse(BaseModel):
    items: list[UsageEventDTO]


class UsageRequestLogDTO(BaseModel):
    id: str
    thread_id: str
    event_index: int
    account_id: str | None
    account_display_name: str | None
    occurred_at: int
    billing_model: str | None
    input_tokens: int
    cache_creation_tokens: int
    cache_hit_tokens: int
    output_tokens: int
    reasoning_output_tokens: int
    total_tokens: int
    total_cost_usd: float | None
    cost_known: bool


class UsageRequestLogSummaryDTO(BaseModel):
    request_count: int
    input_tokens: int
    cache_creation_tokens: int
    cache_hit_tokens: int
    output_tokens: int
    reasoning_output_tokens: int
    total_tokens: int
    total_cost_usd: float | None
    cost_known: bool
    unknown_cost_events: int


class UsageRequestLogsResponse(BaseModel):
    items: list[UsageRequestLogDTO]
    next_cursor: str | None
    total_count: int
    summary: UsageRequestLogSummaryDTO


class UsageAggregatePointDTO(BaseModel):
    bucket_start: int
    bucket_end: int
    input_tokens: int
    cache_creation_tokens: int
    cache_hit_tokens: int
    output_tokens: int
    reasoning_output_tokens: int
    total_tokens: int
    cost_usd: float | None
    cost_known: bool
    unknown_cost_events: int
    event_count: int


class UsageRangeAggregateDTO(BaseModel):
    range_key: str
    bucket: str
    range_start: int
    range_end: int
    event_count: int
    items: list[UsageAggregatePointDTO]


class UsageAggregatesResponse(BaseModel):
    generated_at: int
    ranges: dict[str, UsageRangeAggregateDTO]


@dataclass(frozen=True)
class UsageRangeSpec:
    key: str
    seconds: int
    bucket: str


@dataclass(frozen=True)
class RolloutSource:
    thread_id: str
    path: Path
    model: str | None
    fallback_timestamp: int


@dataclass(frozen=True)
class RolloutStat:
    mtime_ns: int
    size_bytes: int


AGGREGATION_REFRESH_SECONDS = 10 * 60
UNASSIGNED_ACCOUNT_FILTER = "__unassigned__"
RANGE_SPECS = (
    UsageRangeSpec("24h", 60 * 60 * 24, "hour"),
    UsageRangeSpec("7d", 60 * 60 * 24 * 7, "day"),
    UsageRangeSpec("30d", 60 * 60 * 24 * 30, "day"),
    UsageRangeSpec("90d", 60 * 60 * 24 * 90, "week"),
)
_USAGE_STORAGE_LOCK = RLock()


def _request_log_id(thread_id: str, event_index: int) -> str:
    return f"{thread_id}:{event_index}"


def _encode_request_log_cursor(occurred_at: int, thread_id: str, event_index: int) -> str:
    payload = json.dumps(
        {"occurred_at": occurred_at, "thread_id": thread_id, "event_index": event_index},
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_request_log_cursor(cursor: str | None) -> tuple[int, str, int] | None:
    if cursor is None:
        return None
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        decoded = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        payload = json.loads(decoded)
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid cursor") from exc
    if not isinstance(payload, dict):
        raise ValueError("Invalid cursor")
    occurred_at = payload.get("occurred_at")
    thread_id = payload.get("thread_id")
    event_index = payload.get("event_index")
    if not isinstance(occurred_at, int) or not isinstance(thread_id, str) or not isinstance(event_index, int):
        raise ValueError("Invalid cursor")
    if not thread_id or event_index < 0:
        raise ValueError("Invalid cursor")
    return occurred_at, thread_id, event_index


def _utc_now_ts() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def _floor_to_interval(seconds: int, interval: int) -> int:
    return seconds - (seconds % interval)


def _bucket_start(seconds: int, bucket: str) -> int:
    date = datetime.fromtimestamp(seconds, tz=timezone.utc)
    if bucket == "hour":
        return int(date.replace(minute=0, second=0, microsecond=0).timestamp())

    date = date.replace(hour=0, minute=0, second=0, microsecond=0)
    if bucket == "week":
        date = date - timedelta(days=date.weekday())
    return int(date.timestamp())


def _next_bucket_start(seconds: int, bucket: str) -> int:
    date = datetime.fromtimestamp(seconds, tz=timezone.utc)
    if bucket == "hour":
        date = date + timedelta(hours=1)
    elif bucket == "day":
        date = date + timedelta(days=1)
    else:
        date = date + timedelta(days=7)
    return int(date.timestamp())


def _parse_event_timestamp(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def _token_usage(payload: dict[str, Any]) -> dict[str, int] | None:
    info = payload.get("info")
    if not isinstance(info, dict):
        return None
    usage = info.get("last_token_usage")
    if not isinstance(usage, dict):
        return None
    return {
        "input_tokens": int(usage.get("input_tokens") or 0),
        "cached_input_tokens": int(usage.get("cached_input_tokens") or 0),
        "output_tokens": int(usage.get("output_tokens") or 0),
        "reasoning_output_tokens": int(usage.get("reasoning_output_tokens") or 0),
        "total_tokens": int(usage.get("total_tokens") or 0),
    }


def _thread_rows(settings: Settings) -> list[sqlite3.Row]:
    db_path = _state_db_path(settings)
    if not db_path.exists():
        return []
    with _readonly_connect(db_path) as conn:
        return list(conn.execute("SELECT id, rollout_path, model, updated_at FROM threads"))


def _rollout_id_from_path(path: Path) -> str:
    name = path.stem
    if name.startswith("rollout-") and "-" in name:
        return name.rsplit("-", 1)[-1]
    return str(path)


def _fallback_timestamp(path: Path) -> int:
    try:
        return int(path.stat().st_mtime)
    except OSError:
        return 0


def _rollout_stat(path: Path) -> RolloutStat | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return RolloutStat(mtime_ns=stat.st_mtime_ns, size_bytes=stat.st_size)


def _account_id_at(conn: sqlite3.Connection, occurred_at: int) -> str | None:
    row = conn.execute(
        """
        SELECT account_id
        FROM account_usage_intervals
        WHERE started_at <= ? AND (ended_at IS NULL OR ended_at > ?)
        ORDER BY started_at DESC, id DESC
        LIMIT 1
        """,
        (occurred_at, occurred_at),
    ).fetchone()
    return row["account_id"] if row else None


def _discover_rollouts(settings: Settings) -> list[RolloutSource]:
    sources: dict[Path, RolloutSource] = {}
    thread_rows = _thread_rows(settings)
    for row in thread_rows:
        rollout_path = resolve_rollout_path(settings, row["rollout_path"], row["id"])
        sources[rollout_path] = RolloutSource(
            thread_id=row["id"],
            path=rollout_path,
            model=row["model"],
            fallback_timestamp=row["updated_at"],
        )

    if thread_rows:
        return list(sources.values())

    sessions_dir = settings.codex_home / "sessions"
    if sessions_dir.exists():
        for path in sessions_dir.rglob("*.jsonl"):
            sources.setdefault(
                path,
                RolloutSource(
                    thread_id=_rollout_id_from_path(path),
                    path=path,
                    model=None,
                    fallback_timestamp=_fallback_timestamp(path),
                ),
            )
    return list(sources.values())


def _model_from_line(line: dict[str, Any], current_model: str | None) -> str | None:
    payload = line.get("payload")
    if not isinstance(payload, dict):
        return current_model
    for key in ("model",):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    if payload.get("type") == "session_meta":
        value = payload.get("model")
        if isinstance(value, str) and value:
            return value
    return current_model


def _sync_usage_events(settings: Settings) -> None:
    sources = _discover_rollouts(settings)
    if not sources:
        return
    with connect(settings.db_path) as app_conn:
        current_id = current_account_id(settings.codex_home)
        if current_id:
            observe_account_usage_conn(app_conn, current_id)
        for source in sources:
            stat = _rollout_stat(source.path)
            if stat is None:
                continue
            path_key = str(source.path)
            scan = app_conn.execute(
                """
                SELECT *
                FROM usage_source_scans
                WHERE path = ?
                """,
                (path_key,),
            ).fetchone()
            if (
                scan
                and scan["thread_id"] == source.thread_id
                and scan["mtime_ns"] == stat.mtime_ns
                and scan["size_bytes"] == stat.size_bytes
            ):
                continue

            byte_offset = 0
            line_count = 0
            model = source.model
            if scan and scan["thread_id"] == source.thread_id and stat.size_bytes >= int(scan["byte_offset"]):
                byte_offset = int(scan["byte_offset"])
                line_count = int(scan["line_count"])
                model = scan["last_model"] or model
            else:
                if scan:
                    app_conn.execute("DELETE FROM usage_events WHERE thread_id = ?", (scan["thread_id"],))
                app_conn.execute("DELETE FROM usage_events WHERE thread_id = ?", (source.thread_id,))

            with source.path.open("r", encoding="utf-8") as handle:
                handle.seek(byte_offset)
                while True:
                    raw_line = handle.readline()
                    if raw_line == "":
                        break
                    index = line_count
                    line_count += 1
                    try:
                        line = json.loads(raw_line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(line, dict):
                        continue
                    model = _model_from_line(line, model)
                    payload = line.get("payload")
                    if not isinstance(payload, dict) or payload.get("type") != "token_count":
                        continue
                    usage = _token_usage(payload)
                    if usage is None:
                        continue
                    occurred_at = _parse_event_timestamp(line.get("timestamp")) or source.fallback_timestamp
                    input_tokens = usage["input_tokens"]
                    cache_hit_tokens = usage["cached_input_tokens"]
                    cache_creation_tokens = max(input_tokens - cache_hit_tokens, 0)
                    output_tokens = usage["output_tokens"]
                    cost, known = estimate_cost(model, input_tokens, cache_hit_tokens, output_tokens)
                    account_id = _account_id_at(app_conn, occurred_at)
                    app_conn.execute(
                        """
                        INSERT OR IGNORE INTO usage_events (
                            thread_id, event_index, account_id, occurred_at, model, input_tokens,
                            cache_hit_tokens, cache_creation_tokens, output_tokens,
                            reasoning_output_tokens, total_tokens, cost_usd, cost_known
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            source.thread_id,
                            index,
                            account_id,
                            occurred_at,
                            model,
                            input_tokens,
                            cache_hit_tokens,
                            cache_creation_tokens,
                            output_tokens,
                            usage["reasoning_output_tokens"],
                            usage["total_tokens"],
                            cost,
                            1 if known else 0,
                        ),
                    )
                byte_offset = handle.tell()

            app_conn.execute(
                """
                INSERT INTO usage_source_scans (
                    path, thread_id, mtime_ns, size_bytes, byte_offset, line_count, last_model
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    thread_id = excluded.thread_id,
                    mtime_ns = excluded.mtime_ns,
                    size_bytes = excluded.size_bytes,
                    byte_offset = excluded.byte_offset,
                    line_count = excluded.line_count,
                    last_model = excluded.last_model
                """,
                (path_key, source.thread_id, stat.mtime_ns, stat.size_bytes, byte_offset, line_count, model),
            )


def _mark_unknown_cost_events_zero(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        UPDATE usage_events
        SET cost_usd = 0.0, cost_known = 1
        WHERE cost_known = 0 OR cost_usd IS NULL
        """
    )


def sync_usage_events(settings: Settings) -> None:
    with _USAGE_STORAGE_LOCK:
        _sync_usage_events(settings)
        with connect(settings.db_path) as conn:
            _mark_unknown_cost_events_zero(conn)


def _new_aggregate_point(bucket_start: int, bucket: str) -> dict[str, Any]:
    return {
        "bucket_start": bucket_start,
        "bucket_end": _next_bucket_start(bucket_start, bucket),
        "input_tokens": 0,
        "cache_creation_tokens": 0,
        "cache_hit_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
        "total_tokens": 0,
        "known_cost_usd": 0.0,
        "unknown_cost_events": 0,
        "event_count": 0,
    }


def _seed_aggregate_points(range_start: int, range_end: int, bucket: str) -> dict[int, dict[str, Any]]:
    points: dict[int, dict[str, Any]] = {}
    current = _bucket_start(range_start, bucket)
    last = _bucket_start(range_end, bucket)
    while current <= last:
        points[current] = _new_aggregate_point(current, bucket)
        next_start = _next_bucket_start(current, bucket)
        if next_start <= current:
            break
        current = next_start
    return points


def _usage_events_fingerprint(conn: sqlite3.Connection) -> tuple[int, int]:
    row = conn.execute(
        """
        SELECT COUNT(*) AS event_count, COALESCE(MAX(occurred_at), 0) AS max_occurred_at
        FROM usage_events
        """
    ).fetchone()
    return int(row["event_count"]), int(row["max_occurred_at"])


def _aggregation_due(
    run: sqlite3.Row | None,
    now: int,
    source_event_count: int,
    source_max_occurred_at: int,
) -> bool:
    if run is None:
        return True
    if int(run["source_event_count"]) != source_event_count:
        return True
    if int(run["source_max_occurred_at"]) != source_max_occurred_at:
        return True
    return int(run["generated_at"]) <= now - AGGREGATION_REFRESH_SECONDS


def _rebuild_usage_aggregates(
    conn: sqlite3.Connection,
    generated_at: int,
    source_event_count: int,
    source_max_occurred_at: int,
) -> None:
    conn.execute("DELETE FROM usage_aggregate_points")
    for spec in RANGE_SPECS:
        range_start = generated_at - spec.seconds
        points = _seed_aggregate_points(range_start, generated_at, spec.bucket)
        rows = conn.execute(
            """
            SELECT occurred_at, input_tokens, cache_creation_tokens, cache_hit_tokens,
                   output_tokens, reasoning_output_tokens, total_tokens, cost_usd, cost_known
            FROM usage_events
            WHERE occurred_at >= ? AND occurred_at <= ?
            """,
            (range_start, generated_at),
        )
        for row in rows:
            point = points.get(_bucket_start(row["occurred_at"], spec.bucket))
            if point is None:
                continue
            point["input_tokens"] += row["input_tokens"]
            point["cache_creation_tokens"] += row["cache_creation_tokens"]
            point["cache_hit_tokens"] += row["cache_hit_tokens"]
            point["output_tokens"] += row["output_tokens"]
            point["reasoning_output_tokens"] += row["reasoning_output_tokens"]
            point["total_tokens"] += row["total_tokens"]
            point["event_count"] += 1
            if row["cost_known"] and row["cost_usd"] is not None:
                point["known_cost_usd"] += float(row["cost_usd"])
            else:
                point["unknown_cost_events"] += 1

        for point in points.values():
            cost_known = point["event_count"] > 0 and point["unknown_cost_events"] == 0
            cost_usd = point["known_cost_usd"] if cost_known else None
            conn.execute(
                """
                INSERT INTO usage_aggregate_points (
                    range_key, bucket, bucket_start, bucket_end, input_tokens,
                    cache_hit_tokens, cache_creation_tokens, output_tokens,
                    reasoning_output_tokens, total_tokens, cost_usd, cost_known,
                    unknown_cost_events, event_count
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    spec.key,
                    spec.bucket,
                    point["bucket_start"],
                    point["bucket_end"],
                    point["input_tokens"],
                    point["cache_hit_tokens"],
                    point["cache_creation_tokens"],
                    point["output_tokens"],
                    point["reasoning_output_tokens"],
                    point["total_tokens"],
                    cost_usd,
                    1 if cost_known else 0,
                    point["unknown_cost_events"],
                    point["event_count"],
                ),
            )

    conn.execute(
        """
        INSERT INTO usage_aggregate_runs (
            id, generated_at, source_event_count, source_max_occurred_at
        )
        VALUES (1, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            generated_at = excluded.generated_at,
            source_event_count = excluded.source_event_count,
            source_max_occurred_at = excluded.source_max_occurred_at
        """,
        (generated_at, source_event_count, source_max_occurred_at),
    )


def _ensure_usage_aggregates(settings: Settings) -> int:
    with _USAGE_STORAGE_LOCK:
        _sync_usage_events(settings)
        now = _utc_now_ts()
        generated_at = _floor_to_interval(now, AGGREGATION_REFRESH_SECONDS)
        with connect(settings.db_path) as conn:
            _mark_unknown_cost_events_zero(conn)
            source_event_count, source_max_occurred_at = _usage_events_fingerprint(conn)
            run = conn.execute("SELECT * FROM usage_aggregate_runs WHERE id = 1").fetchone()
            if not _aggregation_due(run, now, source_event_count, source_max_occurred_at):
                return int(run["generated_at"])
            _rebuild_usage_aggregates(conn, generated_at, source_event_count, source_max_occurred_at)
            return generated_at


def _aggregate_point_from_row(row: sqlite3.Row) -> UsageAggregatePointDTO:
    return UsageAggregatePointDTO(
        bucket_start=row["bucket_start"],
        bucket_end=row["bucket_end"],
        input_tokens=row["input_tokens"],
        cache_creation_tokens=row["cache_creation_tokens"],
        cache_hit_tokens=row["cache_hit_tokens"],
        output_tokens=row["output_tokens"],
        reasoning_output_tokens=row["reasoning_output_tokens"],
        total_tokens=row["total_tokens"],
        cost_usd=row["cost_usd"],
        cost_known=bool(row["cost_known"]),
        unknown_cost_events=row["unknown_cost_events"],
        event_count=row["event_count"],
    )


def get_usage_aggregates(settings: Settings) -> UsageAggregatesResponse:
    generated_at = _ensure_usage_aggregates(settings)
    with connect(settings.db_path) as conn:
        rows = list(
            conn.execute(
                """
                SELECT *
                FROM usage_aggregate_points
                ORDER BY range_key ASC, bucket_start ASC
                """
            )
        )
    points_by_range: dict[str, list[UsageAggregatePointDTO]] = {spec.key: [] for spec in RANGE_SPECS}
    for row in rows:
        points_by_range.setdefault(row["range_key"], []).append(_aggregate_point_from_row(row))

    return UsageAggregatesResponse(
        generated_at=generated_at,
        ranges={
            spec.key: UsageRangeAggregateDTO(
                range_key=spec.key,
                bucket=spec.bucket,
                range_start=generated_at - spec.seconds,
                range_end=generated_at,
                event_count=sum(point.event_count for point in points_by_range[spec.key]),
                items=points_by_range[spec.key],
            )
            for spec in RANGE_SPECS
        },
    )


def get_usage_events(settings: Settings, from_value: str | None, to_value: str | None) -> UsageEventsResponse:
    sync_usage_events(settings)
    now = _utc_now_ts()
    from_ts = iso_to_ts(from_value) if from_value else now - 60 * 60 * 24 * 7
    to_ts = iso_to_ts(to_value) if to_value else now
    with connect(settings.db_path) as conn:
        rows = list(
            conn.execute(
                """
                SELECT *
                FROM usage_events
                WHERE occurred_at >= ? AND occurred_at <= ?
                ORDER BY occurred_at ASC
                """,
                (from_ts, to_ts),
            )
        )
    return UsageEventsResponse(
        items=[
            UsageEventDTO(
                thread_id=row["thread_id"],
                event_index=row["event_index"],
                occurred_at=row["occurred_at"],
                model=row["model"],
                input_tokens=row["input_tokens"],
                cache_creation_tokens=row["cache_creation_tokens"],
                cache_hit_tokens=row["cache_hit_tokens"],
                output_tokens=row["output_tokens"],
                reasoning_output_tokens=row["reasoning_output_tokens"],
                total_tokens=row["total_tokens"],
                cost_usd=row["cost_usd"],
                cost_known=bool(row["cost_known"]),
            )
            for row in rows
        ]
    )


def _request_log_from_row(row: sqlite3.Row) -> UsageRequestLogDTO:
    return UsageRequestLogDTO(
        id=_request_log_id(row["thread_id"], row["event_index"]),
        thread_id=row["thread_id"],
        event_index=row["event_index"],
        account_id=row["account_id"],
        account_display_name=row["account_display_name"],
        occurred_at=row["occurred_at"],
        billing_model=row["model"],
        input_tokens=row["input_tokens"],
        cache_creation_tokens=row["cache_creation_tokens"],
        cache_hit_tokens=row["cache_hit_tokens"],
        output_tokens=row["output_tokens"],
        reasoning_output_tokens=row["reasoning_output_tokens"],
        total_tokens=row["total_tokens"],
        total_cost_usd=row["cost_usd"],
        cost_known=bool(row["cost_known"]),
    )


def _request_log_summary_from_row(row: sqlite3.Row) -> UsageRequestLogSummaryDTO:
    request_count = int(row["request_count"])
    unknown_cost_events = int(row["unknown_cost_events"])
    return UsageRequestLogSummaryDTO(
        request_count=request_count,
        input_tokens=int(row["input_tokens"] or 0),
        cache_creation_tokens=int(row["cache_creation_tokens"] or 0),
        cache_hit_tokens=int(row["cache_hit_tokens"] or 0),
        output_tokens=int(row["output_tokens"] or 0),
        reasoning_output_tokens=int(row["reasoning_output_tokens"] or 0),
        total_tokens=int(row["total_tokens"] or 0),
        total_cost_usd=round(float(row["known_cost_usd"] or 0), 8) if unknown_cost_events == 0 else None,
        cost_known=unknown_cost_events == 0,
        unknown_cost_events=unknown_cost_events,
    )


def get_usage_request_logs(
    settings: Settings,
    from_value: str | None = None,
    to_value: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
    page: int = 1,
    account_id: str | None = None,
) -> UsageRequestLogsResponse:
    cursor_value = _decode_request_log_cursor(cursor)
    if page < 1:
        raise ValueError("Invalid page")
    sync_usage_events(settings)
    now = _utc_now_ts()
    from_ts = iso_to_ts(from_value) if from_value else now - 60 * 60 * 24
    to_ts = iso_to_ts(to_value) if to_value else now
    safe_limit = max(1, min(limit, 100))
    filters = ["occurred_at >= ?", "occurred_at <= ?"]
    params: list[Any] = [from_ts, to_ts]
    if account_id == UNASSIGNED_ACCOUNT_FILTER:
        filters.append("account_id IS NULL")
    elif account_id:
        filters.append("account_id = ?")
        params.append(account_id)
    page_filters = list(filters)
    page_params = list(params)
    if cursor_value is not None:
        cursor_occurred_at, cursor_thread_id, cursor_event_index = cursor_value
        page_filters.append(
            """
            (
                occurred_at < ?
                OR (occurred_at = ? AND thread_id < ?)
                OR (occurred_at = ? AND thread_id = ? AND event_index < ?)
            )
            """
        )
        page_params.extend(
            [
                cursor_occurred_at,
                cursor_occurred_at,
                cursor_thread_id,
                cursor_occurred_at,
                cursor_thread_id,
                cursor_event_index,
            ]
        )

    where = " AND ".join(page_filters)
    count_where = " AND ".join(filters)
    with connect(settings.db_path) as conn:
        summary_row = conn.execute(
            f"""
            SELECT
                COUNT(*) AS request_count,
                COALESCE(SUM(input_tokens), 0) AS input_tokens,
                COALESCE(SUM(cache_creation_tokens), 0) AS cache_creation_tokens,
                COALESCE(SUM(cache_hit_tokens), 0) AS cache_hit_tokens,
                COALESCE(SUM(output_tokens), 0) AS output_tokens,
                COALESCE(SUM(reasoning_output_tokens), 0) AS reasoning_output_tokens,
                COALESCE(SUM(total_tokens), 0) AS total_tokens,
                COALESCE(SUM(CASE WHEN cost_known = 1 AND cost_usd IS NOT NULL THEN cost_usd ELSE 0 END), 0) AS known_cost_usd,
                COALESCE(SUM(CASE WHEN cost_known = 1 AND cost_usd IS NOT NULL THEN 0 ELSE 1 END), 0) AS unknown_cost_events
            FROM usage_events
            WHERE {count_where}
            """,
            tuple(params),
        ).fetchone()
        if cursor_value is None and page > 1:
            boundary = conn.execute(
                f"""
                SELECT occurred_at, thread_id, event_index
                FROM usage_events
                WHERE {count_where}
                ORDER BY occurred_at DESC, thread_id DESC, event_index DESC
                LIMIT 1 OFFSET ?
                """,
                (*params, (page - 1) * safe_limit - 1),
            ).fetchone()
            if boundary is None:
                return UsageRequestLogsResponse(
                    items=[],
                    next_cursor=None,
                    total_count=int(summary_row["request_count"]),
                    summary=_request_log_summary_from_row(summary_row),
                )
            page_filters.append(
                """
                (
                    occurred_at < ?
                    OR (occurred_at = ? AND thread_id < ?)
                    OR (occurred_at = ? AND thread_id = ? AND event_index < ?)
                )
                """
            )
            page_params.extend(
                [
                    boundary["occurred_at"],
                    boundary["occurred_at"],
                    boundary["thread_id"],
                    boundary["occurred_at"],
                    boundary["thread_id"],
                    boundary["event_index"],
                ]
            )
            where = " AND ".join(page_filters)
        rows = list(
            conn.execute(
                f"""
                SELECT
                    usage_events.*,
                    COALESCE(accounts.custom_name, accounts.display_name, usage_events.account_id) AS account_display_name
                FROM (
                    SELECT *
                    FROM usage_events
                    WHERE {where}
                    ORDER BY occurred_at DESC, thread_id DESC, event_index DESC
                    LIMIT ?
                ) AS usage_events
                LEFT JOIN accounts ON accounts.account_id = usage_events.account_id
                ORDER BY usage_events.occurred_at DESC, usage_events.thread_id DESC, usage_events.event_index DESC
                """,
                (*page_params, safe_limit + 1),
            )
        )

    page_rows = rows[:safe_limit]
    next_cursor = None
    if len(rows) > safe_limit:
        last = page_rows[-1]
        next_cursor = _encode_request_log_cursor(last["occurred_at"], last["thread_id"], last["event_index"])

    return UsageRequestLogsResponse(
        items=[_request_log_from_row(row) for row in page_rows],
        next_cursor=next_cursor,
        total_count=int(summary_row["request_count"]),
        summary=_request_log_summary_from_row(summary_row),
    )
