from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


def _load_dotenv() -> None:
    env_path = Path.cwd() / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _default_codex_home() -> Path:
    mounted = Path("/host-codex")
    if mounted.exists() and mounted.is_dir():
        return mounted
    return Path.home() / ".codex"


def _default_db_path() -> Path:
    data_dir = Path("/data")
    if data_dir.exists() and data_dir.is_dir():
        return data_dir / "switchboard.sqlite"
    return Path.cwd() / "data" / "switchboard.sqlite"


@dataclass(frozen=True)
class Settings:
    app_password: str
    codex_home: Path
    db_path: Path
    chatgpt_backend_base: str
    static_dir: Path | None
    cookie_name: str = "switchboard_session"
    cookie_max_age_seconds: int = 60 * 60 * 24 * 7


@lru_cache
def get_settings() -> Settings:
    _load_dotenv()
    password = os.getenv("APP_PASSWORD", "")
    if not password:
        raise RuntimeError("APP_PASSWORD must be set before starting SwitchBoard.")

    static_dir_raw = os.getenv("SWITCHBOARD_STATIC_DIR")
    return Settings(
        app_password=password,
        codex_home=Path(os.getenv("CODEX_HOME", str(_default_codex_home()))).expanduser(),
        db_path=Path(os.getenv("SWITCHBOARD_DB", str(_default_db_path()))).expanduser(),
        chatgpt_backend_base=os.getenv(
            "CHATGPT_BACKEND_BASE", "https://chatgpt.com/backend-api"
        ).rstrip("/"),
        static_dir=Path(static_dir_raw).expanduser() if static_dir_raw else None,
    )
