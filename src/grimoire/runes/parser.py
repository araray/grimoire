# src/grimoire/runes/parser.py
"""
Rune file parser.

Parses ``*.rune.yaml`` files containing skill contracts.

Format (see spec §8.1):

    ---
    id: devtools/git
    name: Git (read-only diagnostics)
    version: 1.0.0
    description: Common git commands for diagnostics.
    tags: [devtools, vcs]
    risk_level: low
    permissions: [read_fs]
    commands:
      - name: status
        summary: Show working tree status
        params:
          - name: porcelain
            type: bool
            required: false
            default: true
        returns:
          type: object
          properties:
            stdout: { type: string }
        side_effects: []
    ...
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from grimoire.exceptions import RuneParseError, RuneValidationError
from grimoire.models import (
    CommandExample,
    CommandSpec,
    ParamSpec,
    ReturnSpec,
    RuneSpec,
)

logger = logging.getLogger(__name__)


def _parse_params(raw_params: list[dict] | None) -> list[ParamSpec]:
    """Parse command parameter list."""
    if not raw_params:
        return []
    params: list[ParamSpec] = []
    for p in raw_params:
        try:
            params.append(ParamSpec(**p))
        except Exception as e:
            name = p.get("name", "<unknown>")
            raise RuneValidationError(f"Invalid param '{name}': {e}") from e
    return params


def _parse_commands(raw_commands: list[dict] | None) -> list[CommandSpec]:
    """Parse command list from YAML data."""
    if not raw_commands:
        return []

    commands: list[CommandSpec] = []
    for cmd_data in raw_commands:
        cmd_name = cmd_data.get("name")
        if not cmd_name:
            raise RuneValidationError("Command must have a 'name' field")

        # Parse nested structures
        params = _parse_params(cmd_data.get("params"))

        returns = None
        if "returns" in cmd_data:
            try:
                returns = ReturnSpec(**cmd_data["returns"])
            except Exception as e:
                raise RuneValidationError(
                    f"Invalid return spec for command '{cmd_name}': {e}"
                ) from e

        examples: list[CommandExample] = []
        for ex in cmd_data.get("examples", []):
            try:
                examples.append(CommandExample(**ex))
            except Exception as e:
                raise RuneValidationError(
                    f"Invalid example in command '{cmd_name}': {e}"
                ) from e

        try:
            commands.append(CommandSpec(
                name=cmd_name,
                summary=cmd_data.get("summary"),
                params=params,
                returns=returns,
                side_effects=cmd_data.get("side_effects", []),
                risk_level=cmd_data.get("risk_level"),
                requires_approval=cmd_data.get("requires_approval", False),
                examples=examples,
            ))
        except Exception as e:
            raise RuneValidationError(
                f"Failed to construct command '{cmd_name}': {e}"
            ) from e

    return commands


def parse_rune(data: dict, source_path: str | None = None) -> RuneSpec:
    """
    Parse a rune from a YAML-loaded dictionary.

    Args:
        data: Parsed YAML dict.
        source_path: Optional file path for provenance.

    Returns:
        Validated RuneSpec model.

    Raises:
        RuneParseError: If data structure is invalid.
        RuneValidationError: If validation fails.
    """
    if not isinstance(data, dict):
        raise RuneParseError(f"Rune data must be a mapping, got {type(data)}")

    rune_id = data.get("id")
    if not rune_id:
        raise RuneValidationError("Rune must have an 'id' field")

    name = data.get("name", rune_id)
    commands = _parse_commands(data.get("commands"))

    try:
        return RuneSpec(
            id=rune_id,
            name=name,
            version=data.get("version", "1.0.0"),
            description=data.get("description"),
            tags=data.get("tags", []),
            platforms=data.get("platforms", ["any"]),
            risk_level=data.get("risk_level", "low"),
            permissions=data.get("permissions", []),
            requires_approval=data.get("requires_approval", False),
            commands=commands,
            source_path=source_path,
        )
    except Exception as e:
        raise RuneValidationError(f"Failed to construct RuneSpec: {e}") from e


def parse_rune_file(path: str | Path) -> RuneSpec:
    """
    Parse a rune from a ``*.rune.yaml`` file.

    Args:
        path: Path to the YAML file.

    Returns:
        Validated RuneSpec.

    Raises:
        RuneParseError: If file cannot be read or parsed.
    """
    p = Path(path)
    if not p.exists():
        raise RuneParseError(f"Rune file not found: {p}")

    try:
        text = p.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise RuneParseError(f"Invalid YAML in {p}: {e}") from e

    if data is None:
        raise RuneParseError(f"Empty rune file: {p}")

    return parse_rune(data, source_path=str(p))
