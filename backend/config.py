from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


REMOVED_DATA_PATH_ENV_VARS = (
    "SWITCHBOARD_DB",
    "SWITCHBOARD_AUTH_VAULT",
    "SWITCHBOARD_IMAGE_OUTPUT_DIR",
)


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


def _default_data_dir() -> Path:
    data_dir = Path("/data")
    if data_dir.exists() and data_dir.is_dir():
        return data_dir
    return Path.cwd() / "data"


def _default_db_path(data_dir: Path) -> Path:
    return data_dir / "switchboard.sqlite"


def _default_auth_vault_dir(data_dir: Path) -> Path:
    return data_dir / "auth-vault"


def _default_image_output_dir(data_dir: Path) -> Path:
    return data_dir / "images"


def _parse_bool_env(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    value = raw_value.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be a boolean value like 1/0, true/false, yes/no, or on/off.")


def _reject_removed_data_path_env_vars() -> None:
    removed = [name for name in REMOVED_DATA_PATH_ENV_VARS if os.getenv(name) is not None]
    if removed:
        names = ", ".join(removed)
        raise RuntimeError(f"{names} were removed. Set SWITCHBOARD_DATA_DIR instead.")


@dataclass(frozen=True)
class Settings:
    app_password: str
    codex_home: Path
    db_path: Path
    chatgpt_backend_base: str
    static_dir: Path | None
    data_dir: Path | None = None
    auth_vault_dir: Path | None = None
    cookie_name: str = "switchboard_session"
    cookie_max_age_seconds: int = 60 * 60 * 24 * 7
    cookie_secure: bool = False
    image_model: str = "gpt-image-2"
    image_responses_model: str = "gpt-5.4-mini"
    image_responses_path: str = "/codex/responses"
    image_timeout_seconds: float = 300.0
    image_max_prompt_chars: int = 4000
    image_output_dir: Path | None = None
    image_debug: bool = False


def validate_runtime_settings(settings: Settings) -> None:
    if not settings.codex_home.exists():
        raise RuntimeError(f"CODEX_HOME does not exist: {settings.codex_home}")
    if not settings.codex_home.is_dir():
        raise RuntimeError(f"CODEX_HOME is not a directory: {settings.codex_home}")


def _parse_float_env(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a number.") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be greater than 0.")
    return value


def _parse_int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer.") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be greater than 0.")
    return value


@lru_cache
def get_settings() -> Settings:
    _load_dotenv()
    _reject_removed_data_path_env_vars()
    password = os.getenv("APP_PASSWORD", "")
    if not password:
        raise RuntimeError("APP_PASSWORD must be set before starting SwitchBoard.")

    static_dir_raw = os.getenv("SWITCHBOARD_STATIC_DIR")
    data_dir = Path(os.getenv("SWITCHBOARD_DATA_DIR", str(_default_data_dir()))).expanduser()
    image_responses_path = os.getenv("SWITCHBOARD_IMAGE_RESPONSES_PATH", "/codex/responses").strip()
    if not image_responses_path.startswith("/") and not image_responses_path.startswith(("http://", "https://")):
        image_responses_path = f"/{image_responses_path}"
    return Settings(
        app_password=password,
        codex_home=Path(os.getenv("CODEX_HOME", str(_default_codex_home()))).expanduser(),
        data_dir=data_dir,
        db_path=_default_db_path(data_dir),
        chatgpt_backend_base=os.getenv(
            "CHATGPT_BACKEND_BASE", "https://chatgpt.com/backend-api"
        ).rstrip("/"),
        static_dir=Path(static_dir_raw).expanduser() if static_dir_raw else None,
        auth_vault_dir=_default_auth_vault_dir(data_dir),
        cookie_secure=_parse_bool_env("SWITCHBOARD_COOKIE_SECURE", default=False),
        image_model=os.getenv("SWITCHBOARD_IMAGE_MODEL", "gpt-image-2"),
        image_responses_model=os.getenv("SWITCHBOARD_IMAGE_RESPONSES_MODEL", "gpt-5.4-mini"),
        image_responses_path=image_responses_path,
        image_timeout_seconds=_parse_float_env("SWITCHBOARD_IMAGE_TIMEOUT_SECONDS", 300.0),
        image_max_prompt_chars=_parse_int_env("SWITCHBOARD_IMAGE_MAX_PROMPT_CHARS", 4000),
        image_output_dir=_default_image_output_dir(data_dir),
        image_debug=_parse_bool_env("SWITCHBOARD_IMAGE_DEBUG", default=False),
    )
