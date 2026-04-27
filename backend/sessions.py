from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from config import Settings


class SessionSummary(BaseModel):
    thread_id: str
    title: str
    cwd: str
    model_provider: str
    model: str | None
    created_at: int | None
    updated_at: int | None
    tokens_used: int
    archived: bool


class SessionListResponse(BaseModel):
    items: list[SessionSummary]
    next_cursor: str | None
    total_count: int


class SessionEvent(BaseModel):
    kind: str
    timestamp: str | None = None
    title: str | None = None
    text: str | None = None
    name: str | None = None
    arguments: Any = None
    data: Any = None


class SessionDetail(BaseModel):
    summary: SessionSummary
    events: list[SessionEvent]
    raw_event_count: int


def _readonly_connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _state_db_path(settings: Settings) -> Path:
    return settings.codex_home / "state_5.sqlite"


def _parse_time(value: str | None) -> int | None:
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        return int(datetime.fromisoformat(normalized).timestamp())
    except ValueError:
        return None


def _summary_from_row(row: sqlite3.Row) -> SessionSummary:
    created = row["created_at_ms"] if "created_at_ms" in row.keys() else None
    updated = row["updated_at_ms"] if "updated_at_ms" in row.keys() else None
    return SessionSummary(
        thread_id=row["id"],
        title=row["title"] or row["first_user_message"] or "Untitled session",
        cwd=row["cwd"],
        model_provider=row["model_provider"],
        model=row["model"],
        created_at=int(created / 1000) if created else row["created_at"],
        updated_at=int(updated / 1000) if updated else row["updated_at"],
        tokens_used=row["tokens_used"],
        archived=bool(row["archived"]),
    )


def list_sessions(
    settings: Settings,
    query: str | None = None,
    cwd: str | None = None,
    from_ts: int | None = None,
    to_ts: int | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> SessionListResponse:
    db_path = _state_db_path(settings)
    if not db_path.exists():
        return SessionListResponse(items=[], next_cursor=None, total_count=0)
    offset = int(cursor or 0)
    safe_limit = max(1, min(limit, 100))
    filters = ["archived = 0"]
    params: list[Any] = []
    if query:
        filters.append("(title LIKE ? OR first_user_message LIKE ? OR cwd LIKE ?)")
        like = f"%{query}%"
        params.extend([like, like, like])
    if cwd:
        filters.append("cwd = ?")
        params.append(cwd)
    if from_ts:
        filters.append("updated_at >= ?")
        params.append(from_ts)
    if to_ts:
        filters.append("updated_at <= ?")
        params.append(to_ts)
    where = " AND ".join(filters)
    sql = f"""
        SELECT *
        FROM threads
        WHERE {where}
        ORDER BY updated_at_ms DESC, id DESC
        LIMIT ? OFFSET ?
    """
    with _readonly_connect(db_path) as conn:
        count_row = conn.execute(f"SELECT COUNT(*) AS total_count FROM threads WHERE {where}", tuple(params)).fetchone()
        rows = list(conn.execute(sql, (*params, safe_limit + 1, offset)))
    items = [_summary_from_row(row) for row in rows[:safe_limit]]
    next_cursor = str(offset + safe_limit) if len(rows) > safe_limit else None
    return SessionListResponse(items=items, next_cursor=next_cursor, total_count=int(count_row["total_count"]))


def _text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text") or item.get("output_text") or item.get("input_text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return ""


def _truncate(value: str, max_len: int = 20_000) -> str:
    if len(value) <= max_len:
        return value
    return value[:max_len] + "\n...[truncated]"


def _normalize_event(line: dict[str, Any]) -> SessionEvent | None:
    payload = line.get("payload") if isinstance(line.get("payload"), dict) else {}
    timestamp = line.get("timestamp")
    payload_type = payload.get("type")

    if line.get("type") == "session_meta":
        return SessionEvent(
            kind="metadata",
            timestamp=timestamp,
            title="Session",
            data={
                "id": payload.get("id"),
                "cwd": payload.get("cwd"),
                "model_provider": payload.get("model_provider"),
                "timestamp": payload.get("timestamp"),
            },
        )
    if line.get("type") == "turn_context":
        return SessionEvent(
            kind="metadata",
            timestamp=timestamp,
            title="Turn context",
            data={
                "cwd": payload.get("cwd"),
                "model": payload.get("model"),
                "effort": payload.get("effort"),
                "approval_mode": payload.get("approval_policy"),
                "sandbox": payload.get("sandbox_policy"),
            },
        )
    if payload_type == "user_message":
        text = payload.get("message") or _text_from_content(payload.get("text_elements"))
        return SessionEvent(kind="user", timestamp=timestamp, text=_truncate(str(text or "")))
    if payload_type == "message":
        role = payload.get("role") or "assistant"
        text = _text_from_content(payload.get("content"))
        return SessionEvent(kind=str(role), timestamp=timestamp, text=_truncate(text))
    if payload_type == "agent_message":
        return SessionEvent(kind="assistant", timestamp=timestamp, text=_truncate(str(payload.get("message") or "")))
    if payload_type == "function_call":
        return SessionEvent(
            kind="tool_call",
            timestamp=timestamp,
            name=payload.get("name"),
            arguments=payload.get("arguments"),
        )
    if payload_type == "function_call_output":
        output = payload.get("output")
        return SessionEvent(kind="tool_output", timestamp=timestamp, text=_truncate(str(output or "")))
    if payload_type == "reasoning":
        return SessionEvent(kind="reasoning", timestamp=timestamp, data=payload)
    if payload_type == "token_count":
        return SessionEvent(kind="token_count", timestamp=timestamp, data=payload.get("info"))
    if payload_type in {"task_started", "task_complete"}:
        return SessionEvent(kind="metadata", timestamp=timestamp, title=str(payload_type), data=payload)
    return None


def _resolve_rollout_path(settings: Settings, stored_path: str, thread_id: str) -> Path:
    rollout_path = Path(stored_path)
    candidates: list[Path] = []
    if rollout_path.is_absolute():
        candidates.append(rollout_path)
        if "sessions" in rollout_path.parts:
            sessions_index = rollout_path.parts.index("sessions")
            candidates.append(settings.codex_home / Path(*rollout_path.parts[sessions_index:]))
    else:
        candidates.append(settings.codex_home / rollout_path)

    for candidate in candidates:
        if candidate.exists():
            return candidate

    sessions_dir = settings.codex_home / "sessions"
    if sessions_dir.exists():
        for candidate in sessions_dir.rglob(f"*{thread_id}.jsonl"):
            return candidate

    return candidates[0] if candidates else rollout_path


def get_session_detail(settings: Settings, thread_id: str) -> SessionDetail:
    db_path = _state_db_path(settings)
    if not db_path.exists():
        raise KeyError(thread_id)
    with _readonly_connect(db_path) as conn:
        row = conn.execute("SELECT * FROM threads WHERE id = ?", (thread_id,)).fetchone()
    if row is None:
        raise KeyError(thread_id)
    summary = _summary_from_row(row)
    rollout_path = _resolve_rollout_path(settings, row["rollout_path"], thread_id)
    events: list[SessionEvent] = []
    raw_count = 0
    if rollout_path.exists():
        with rollout_path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                raw_count += 1
                try:
                    line = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue
                if isinstance(line, dict):
                    event = _normalize_event(line)
                    if event:
                        events.append(event)
    return SessionDetail(summary=summary, events=events, raw_event_count=raw_count)


def iso_to_ts(value: str | None) -> int | None:
    if value is None:
        return None
    if value.isdigit():
        return int(value)
    parsed = _parse_time(value)
    if parsed is not None:
        return parsed
    return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp())
