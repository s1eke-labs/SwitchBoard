from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any


def _project_metadata() -> dict[str, Any]:
    with Path(__file__).with_name("pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)["project"]


__version__ = str(_project_metadata()["version"])
USER_AGENT = f"SwitchBoard/{__version__}"
