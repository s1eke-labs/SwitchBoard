from __future__ import annotations

import base64
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from config import Settings


SORT_UPDATED_AT_MS = "COALESCE(updated_at_ms, updated_at * 1000)"
SESSIONS_ORDER_BY = f"{SORT_UPDATED_AT_MS} DESC, id DESC"
SESSION_EVENT_PREVIEW_CHARS = 4_000
SESSION_USER_INDEX_PREVIEW_CHARS = 160
SESSION_EVENT_PAYLOAD_TYPES = {
    "user_message",
    "message",
    "agent_message",
    "function_call",
    "function_call_output",
    "reasoning",
    "token_count",
    "task_started",
    "task_complete",
}


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
    id: str | None = None
    line_no: int | None = None
    kind: str
    timestamp: str | None = None
    title: str | None = None
    text: str | None = None
    name: str | None = None
    arguments: Any = None
    data: Any = None


class SessionDetail(BaseModel):
    summary: SessionSummary
    raw_event_count: int
    event_count: int


class SessionEventPreview(BaseModel):
    id: str
    line_no: int
    kind: str
    timestamp: str | None = None
    title: str | None = None
    name: str | None = None
    body_preview: str
    body_truncated: bool
    body_bytes: int


class SessionUserIndexItem(BaseModel):
    id: str
    line_no: int
    event_index: int
    timestamp: str | None = None
    body_preview: str
    body_bytes: int


class SessionUserIndexResponse(BaseModel):
    items: list[SessionUserIndexItem]


class SessionEventsResponse(BaseModel):
    items: list[SessionEventPreview]
    next_cursor: str | None
    raw_event_count: int | None = None
    event_count: int | None = None


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


def _encode_cursor(updated_at_ms: int, thread_id: str) -> str:
    payload = json.dumps({"updated_at_ms": updated_at_ms, "thread_id": thread_id}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str | None) -> tuple[int, str] | None:
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
    updated_at_ms = payload.get("updated_at_ms")
    thread_id = payload.get("thread_id")
    if not isinstance(updated_at_ms, int) or not isinstance(thread_id, str) or not thread_id:
        raise ValueError("Invalid cursor")
    return updated_at_ms, thread_id


def _encode_event_cursor(line_no: int) -> str:
    payload = json.dumps({"line_no": line_no}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_event_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        decoded = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        payload = json.loads(decoded)
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid event cursor") from exc
    if not isinstance(payload, dict):
        raise ValueError("Invalid event cursor")
    line_no = payload.get("line_no")
    if not isinstance(line_no, int) or line_no < 0:
        raise ValueError("Invalid event cursor")
    return line_no


def list_sessions(
    settings: Settings,
    query: str | None = None,
    cwd: str | None = None,
    from_ts: int | None = None,
    to_ts: int | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> SessionListResponse:
    cursor_value = _decode_cursor(cursor)
    db_path = _state_db_path(settings)
    if not db_path.exists():
        return SessionListResponse(items=[], next_cursor=None, total_count=0)
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
    page_filters = list(filters)
    page_params = list(params)
    if cursor_value is not None:
        updated_at_ms, thread_id = cursor_value
        page_filters.append(f"({SORT_UPDATED_AT_MS} < ? OR ({SORT_UPDATED_AT_MS} = ? AND id < ?))")
        page_params.extend([updated_at_ms, updated_at_ms, thread_id])

    where = " AND ".join(page_filters)
    count_where = " AND ".join(filters)
    sql = f"""
        SELECT *, {SORT_UPDATED_AT_MS} AS sort_updated_at_ms
        FROM threads
        WHERE {where}
        ORDER BY {SESSIONS_ORDER_BY}
        LIMIT ?
    """
    with _readonly_connect(db_path) as conn:
        count_row = conn.execute(
            f"SELECT COUNT(*) AS total_count FROM threads WHERE {count_where}",
            tuple(params),
        ).fetchone()
        rows = list(conn.execute(sql, (*page_params, safe_limit + 1)))
    items = [_summary_from_row(row) for row in rows[:safe_limit]]
    next_cursor = None
    if len(rows) > safe_limit:
        last_row = rows[safe_limit - 1]
        next_cursor = _encode_cursor(int(last_row["sort_updated_at_ms"]), last_row["id"])
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


def _truncate(value: str, max_len: int | None = 20_000) -> str:
    if max_len is None:
        return value
    if len(value) <= max_len:
        return value
    return value[:max_len] + "\n...[truncated]"


def _normalize_event(line: dict[str, Any], line_no: int | None = None, max_text_len: int | None = 20_000) -> SessionEvent | None:
    payload = line.get("payload") if isinstance(line.get("payload"), dict) else {}
    timestamp = line.get("timestamp")
    payload_type = payload.get("type")
    event_id = f"line-{line_no}" if line_no is not None else None

    if line.get("type") == "session_meta":
        return SessionEvent(
            id=event_id,
            line_no=line_no,
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
            id=event_id,
            line_no=line_no,
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
        return SessionEvent(id=event_id, line_no=line_no, kind="user", timestamp=timestamp, text=_truncate(str(text or ""), max_text_len))
    if payload_type == "message":
        role = payload.get("role") or "assistant"
        if role == "user":
            return None
        text = _text_from_content(payload.get("content"))
        return SessionEvent(id=event_id, line_no=line_no, kind=str(role), timestamp=timestamp, text=_truncate(text, max_text_len))
    if payload_type == "agent_message":
        return SessionEvent(id=event_id, line_no=line_no, kind="assistant", timestamp=timestamp, text=_truncate(str(payload.get("message") or ""), max_text_len))
    if payload_type == "function_call":
        return SessionEvent(
            id=event_id,
            line_no=line_no,
            kind="tool_call",
            timestamp=timestamp,
            name=payload.get("name"),
            arguments=payload.get("arguments"),
        )
    if payload_type == "function_call_output":
        output = payload.get("output")
        return SessionEvent(id=event_id, line_no=line_no, kind="tool_output", timestamp=timestamp, text=_truncate(str(output or ""), max_text_len))
    if payload_type == "reasoning":
        return SessionEvent(id=event_id, line_no=line_no, kind="reasoning", timestamp=timestamp, data=payload)
    if payload_type == "token_count":
        return SessionEvent(id=event_id, line_no=line_no, kind="token_count", timestamp=timestamp, data=payload.get("info"))
    if payload_type in {"task_started", "task_complete"}:
        return SessionEvent(id=event_id, line_no=line_no, kind="metadata", timestamp=timestamp, title=str(payload_type), data=payload)
    return None


def _is_session_event_line(line: dict[str, Any]) -> bool:
    if line.get("type") in {"session_meta", "turn_context"}:
        return True
    payload = line.get("payload") if isinstance(line.get("payload"), dict) else {}
    if payload.get("type") == "message" and payload.get("role") == "user":
        return False
    return payload.get("type") in SESSION_EVENT_PAYLOAD_TYPES


def _event_body(event: SessionEvent) -> str:
    if event.text is not None:
        return event.text
    if event.arguments is not None:
        return json.dumps(event.arguments, ensure_ascii=False, indent=2)
    if event.data is not None:
        return json.dumps(event.data, ensure_ascii=False, indent=2)
    return ""


def _event_preview(event: SessionEvent) -> SessionEventPreview:
    if event.line_no is None or event.id is None:
        raise ValueError("Session event is missing line metadata")
    body = _event_body(event)
    body_bytes = len(body.encode("utf-8"))
    body_truncated = len(body) > SESSION_EVENT_PREVIEW_CHARS
    return SessionEventPreview(
        id=event.id,
        line_no=event.line_no,
        kind=event.kind,
        timestamp=event.timestamp,
        title=event.title,
        name=event.name,
        body_preview=body[:SESSION_EVENT_PREVIEW_CHARS],
        body_truncated=body_truncated,
        body_bytes=body_bytes,
    )


def _user_index_item(event: SessionEvent, event_index: int) -> SessionUserIndexItem:
    if event.line_no is None or event.id is None:
        raise ValueError("Session event is missing line metadata")
    body = _event_body(event)
    return SessionUserIndexItem(
        id=event.id,
        line_no=event.line_no,
        event_index=event_index,
        timestamp=event.timestamp,
        body_preview=body[:SESSION_USER_INDEX_PREVIEW_CHARS],
        body_bytes=len(body.encode("utf-8")),
    )


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


def _session_context(settings: Settings, thread_id: str) -> tuple[SessionSummary, Path]:
    db_path = _state_db_path(settings)
    if not db_path.exists():
        raise KeyError(thread_id)
    with _readonly_connect(db_path) as conn:
        row = conn.execute("SELECT * FROM threads WHERE id = ?", (thread_id,)).fetchone()
    if row is None:
        raise KeyError(thread_id)
    summary = _summary_from_row(row)
    rollout_path = _resolve_rollout_path(settings, row["rollout_path"], thread_id)
    return summary, rollout_path


def _session_event_counts(rollout_path: Path) -> tuple[int, int]:
    raw_count = 0
    event_count = 0
    if not rollout_path.exists():
        return raw_count, event_count
    with rollout_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            raw_count += 1
            try:
                line = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if isinstance(line, dict) and _is_session_event_line(line):
                event_count += 1
    return raw_count, event_count


def get_session_detail(settings: Settings, thread_id: str) -> SessionDetail:
    summary, rollout_path = _session_context(settings, thread_id)
    raw_count, event_count = _session_event_counts(rollout_path)
    return SessionDetail(summary=summary, raw_event_count=raw_count, event_count=event_count)


def list_session_events(settings: Settings, thread_id: str, cursor: str | None = None, limit: int = 100) -> SessionEventsResponse:
    _, rollout_path = _session_context(settings, thread_id)
    after_line_no = _decode_event_cursor(cursor)
    safe_limit = max(1, min(limit, 200))
    items: list[SessionEventPreview] = []
    last_seen_line_no = after_line_no
    next_cursor = None

    if not rollout_path.exists():
        return SessionEventsResponse(items=[], next_cursor=None)

    with rollout_path.open("r", encoding="utf-8") as handle:
        for line_no, raw_line in enumerate(handle, start=1):
            if line_no <= after_line_no:
                continue
            try:
                line = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if not isinstance(line, dict):
                continue
            event = _normalize_event(line, line_no=line_no)
            if event is None:
                continue
            if len(items) < safe_limit:
                items.append(_event_preview(event))
                last_seen_line_no = line_no
                continue
            next_cursor = _encode_event_cursor(last_seen_line_no)
            break

    return SessionEventsResponse(
        items=items,
        next_cursor=next_cursor,
    )


def list_session_user_index(settings: Settings, thread_id: str) -> SessionUserIndexResponse:
    _, rollout_path = _session_context(settings, thread_id)
    items: list[SessionUserIndexItem] = []
    event_index = 0

    if not rollout_path.exists():
        return SessionUserIndexResponse(items=items)

    with rollout_path.open("r", encoding="utf-8") as handle:
        for line_no, raw_line in enumerate(handle, start=1):
            try:
                line = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if not isinstance(line, dict):
                continue
            event = _normalize_event(line, line_no=line_no)
            if event is None:
                continue
            if event.kind == "user":
                items.append(_user_index_item(event, event_index))
            event_index += 1

    return SessionUserIndexResponse(items=items)


def get_session_event(settings: Settings, thread_id: str, line_no: int) -> SessionEvent:
    if line_no < 1:
        raise KeyError(line_no)
    _, rollout_path = _session_context(settings, thread_id)
    if rollout_path.exists():
        with rollout_path.open("r", encoding="utf-8") as handle:
            for current_line_no, raw_line in enumerate(handle, start=1):
                if current_line_no != line_no:
                    continue
                try:
                    line = json.loads(raw_line)
                except json.JSONDecodeError:
                    raise KeyError(line_no) from None
                if isinstance(line, dict):
                    event = _normalize_event(line, line_no=current_line_no, max_text_len=None)
                    if event:
                        return event
                raise KeyError(line_no)
    raise KeyError(line_no)


def iso_to_ts(value: str | None) -> int | None:
    if value is None:
        return None
    if value.isdigit():
        return int(value)
    parsed = _parse_time(value)
    if parsed is not None:
        return parsed
    return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp())
