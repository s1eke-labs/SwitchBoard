from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from config import Settings


AUTH_VAULT_KEY_FILE = ".auth-vault.key"
ENCRYPTED_AUTH_SCHEMA = "switchboard.auth.encrypted.v1"


def auth_vault_key_path(settings: Settings) -> Path:
    vault_root = settings.auth_vault_dir or settings.db_path.parent / "auth-vault"
    return vault_root / AUTH_VAULT_KEY_FILE


def _missing_parents(path: Path) -> list[Path]:
    missing = []
    candidate = path
    while not candidate.exists():
        missing.append(candidate)
        parent = candidate.parent
        if parent == candidate:
            break
        candidate = parent
    return missing


def _ensure_private_parent(path: Path) -> None:
    missing = _missing_parents(path.parent)
    path.parent.mkdir(parents=True, exist_ok=True)
    for parent in reversed(missing):
        os.chmod(parent, 0o700)
    os.chmod(path.parent, 0o700)


def ensure_auth_vault_key(settings: Settings) -> bytes:
    key_path = auth_vault_key_path(settings)
    if not key_path.exists():
        _ensure_private_parent(key_path)
        key = Fernet.generate_key()
        try:
            fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(key)
                handle.write(b"\n")
            return key
        except FileExistsError:
            pass
    key = key_path.read_bytes().strip()
    try:
        base64.urlsafe_b64decode(key)
        Fernet(key)
    except (ValueError, TypeError) as exc:
        raise ValueError("Auth vault key file is invalid") from exc
    os.chmod(key_path, 0o600)
    return key


def _fernet(settings: Settings) -> Fernet:
    return Fernet(ensure_auth_vault_key(settings))


def encrypted_auth_payload(value: Any) -> bool:
    return isinstance(value, dict) and value.get("schema") == ENCRYPTED_AUTH_SCHEMA


def encrypt_auth(settings: Settings, auth: dict[str, Any]) -> dict[str, str]:
    plaintext = json.dumps(auth, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ciphertext = _fernet(settings).encrypt(plaintext).decode("ascii")
    return {
        "schema": ENCRYPTED_AUTH_SCHEMA,
        "ciphertext": ciphertext,
    }


def decrypt_auth(settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    if not encrypted_auth_payload(payload):
        return payload
    ciphertext = payload.get("ciphertext")
    if not isinstance(ciphertext, str) or not ciphertext:
        raise ValueError("Stored auth is encrypted but missing ciphertext")
    try:
        plaintext = _fernet(settings).decrypt(ciphertext.encode("ascii"))
        value = json.loads(plaintext.decode("utf-8"))
    except (InvalidToken, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Stored auth could not be decrypted") from exc
    if not isinstance(value, dict):
        raise ValueError("Stored auth did not decrypt to a JSON object")
    return value
