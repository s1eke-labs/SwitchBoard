from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from pydantic import BaseModel

from config import Settings
from db import connect
from pricing import estimate_cost
from sessions import _readonly_connect, _state_db_path, iso_to_ts


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
RANGE_SPECS = (
    UsageRangeSpec("24h", 60 * 60 * 24, "hour"),
    UsageRangeSpec("7d", 60 * 60 * 24 * 7, "day"),
    UsageRangeSpec("30d", 60 * 60 * 24 * 30, "day"),
    UsageRangeSpec("90d", 60 * 60 * 24 * 90, "week"),
)
_USAGE_STORAGE_LOCK = RLock()


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


def _discover_rollouts(settings: Settings) -> list[RolloutSource]:
    sources: dict[Path, RolloutSource] = {}
    thread_rows = _thread_rows(settings)
    for row in thread_rows:
        rollout_path = Path(row["rollout_path"])
        if not rollout_path.is_absolute():
            rollout_path = settings.codex_home / rollout_path
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
                    app_conn.execute(
                        """
                        INSERT OR IGNORE INTO usage_events (
                            thread_id, event_index, occurred_at, model, input_tokens,
                            cache_hit_tokens, cache_creation_tokens, output_tokens,
                            reasoning_output_tokens, total_tokens, cost_usd, cost_known
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            source.thread_id,
                            index,
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


def sync_usage_events(settings: Settings) -> None:
    with _USAGE_STORAGE_LOCK:
        _sync_usage_events(settings)


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
