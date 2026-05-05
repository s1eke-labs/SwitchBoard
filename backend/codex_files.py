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


def auth_tokens(auth: dict[str, Any]) -> tuple[str, str]:
    tokens = auth.get("tokens")
    if not isinstance(tokens, dict):
        raise ValueError("auth.json does not contain ChatGPT tokens")
    account_id = tokens.get("account_id")
    if not isinstance(account_id, str) or not account_id:
        raise ValueError("auth.json does not contain tokens.account_id")
    access_token = auth_access_token(auth)
    return account_id, access_token


def auth_access_token(auth: dict[str, Any]) -> str:
    tokens = auth.get("tokens")
    if not isinstance(tokens, dict):
        raise ValueError("auth.json does not contain ChatGPT tokens")
    access_token = tokens.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise ValueError("auth.json does not contain tokens.access_token")
    return access_token


def current_account_id(codex_home: Path) -> str | None:
    path = current_auth_path(codex_home)
    if not path.exists():
        return None
    try:
        auth = read_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    try:
        account_id, _ = auth_tokens(auth)
    except ValueError:
        return None
    return account_id
