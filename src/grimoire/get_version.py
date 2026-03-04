# src/grimoire/get_version.py
"""Version extraction from pyproject.toml (fallback when not installed)."""

import pathlib
import tomllib


def _get_version_from_pyproject() -> str:
    """Read and return the 'version' from pyproject.toml."""
    project_root = pathlib.Path(__file__).parent.parent.parent
    pyproject = project_root / "pyproject.toml"
    content = pyproject.read_text(encoding="utf-8")
    data = tomllib.loads(content)
    if "project" in data and "version" in data["project"]:
        return data["project"]["version"]
    raise RuntimeError("Version not found in pyproject.toml")
