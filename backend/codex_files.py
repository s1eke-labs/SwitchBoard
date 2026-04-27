from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} does not contain a JSON object")
    return value


def current_auth_path(codex_home: Path) -> Path:
    return codex_home / "auth.json"


def current_account_id(codex_home: Path) -> str | None:
    path = current_auth_path(codex_home)
    if not path.exists():
        return None
    try:
        auth = read_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    tokens = auth.get("tokens")
    if isinstance(tokens, dict) and isinstance(tokens.get("account_id"), str):
        return tokens["account_id"]
    return None
