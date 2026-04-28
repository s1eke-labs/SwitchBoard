from __future__ import annotations

import tomllib
from pathlib import Path

from version import USER_AGENT, __version__


def test_runtime_version_matches_project_metadata() -> None:
    with (Path(__file__).parents[1] / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]

    assert __version__ == project["version"]
    assert USER_AGENT == f"SwitchBoard/{project['version']}"
