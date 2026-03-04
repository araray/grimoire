# src/grimoire/rituals/parser.py
"""
Ritual file parser.

Parses ``*.ritual.yaml`` files into :class:`~grimoire.models.Ritual` models.

File format::

    id: rituals/rca_loop
    name: RCA Loop
    version: 1.0.0
    description: Optional description
    tags: [engineering, debugging]
    steps:
      - id: step_1
        spell: engineering/bug_root_cause
        conjure:
          vars:
            inherit: true
        output:
          capture: rca_report
      - id: step_2
        when: "{{ rca_report.contains('NEEDED_INPUTS') }}"
        spell: engineering/request_missing_inputs
        conjure:
          ask_missing: true

Recognised ``conjure`` sub-keys:
    - ``vars.inherit`` (bool) — pass parent context variables into this step.
    - ``vars.<name>`` (any) — explicit variable overrides.
    - ``ask_missing`` (bool) — prompt interactively for missing required vars.

Recognised ``output`` sub-keys:
    - ``capture`` (str) — store conjured text into this context variable name.
    - ``format`` (str) — ``"text"`` or ``"messages"`` (default ``"text"``).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from grimoire.exceptions import RitualParseError
from grimoire.models import Ritual, RitualStep

logger = logging.getLogger(__name__)


def parse_ritual(data: dict[str, Any], source_path: str | Path | None = None) -> Ritual:
    """
    Parse a ritual from an already-loaded dict.

    Args:
        data: Dict parsed from a ``*.ritual.yaml`` file.
        source_path: Optional file path for error reporting.

    Returns:
        Populated :class:`~grimoire.models.Ritual` instance.

    Raises:
        RitualParseError: If the data is malformed.
    """
    src = str(source_path) if source_path else "<unknown>"

    if not isinstance(data, dict):
        raise RitualParseError(f"Ritual data must be a mapping, got {type(data).__name__} ({src})")

    ritual_id = data.get("id")
    if not ritual_id:
        raise RitualParseError(f"Ritual missing required 'id' field ({src})")

    if not isinstance(ritual_id, str):
        raise RitualParseError(f"Ritual 'id' must be a string ({src})")

    name = data.get("name", ritual_id)
    if not isinstance(name, str):
        raise RitualParseError(f"Ritual 'name' must be a string ({src})")

    # Parse steps
    raw_steps = data.get("steps", [])
    if not isinstance(raw_steps, list):
        raise RitualParseError(f"Ritual 'steps' must be a list ({src})")

    steps: list[RitualStep] = []
    for i, step_data in enumerate(raw_steps):
        if not isinstance(step_data, dict):
            raise RitualParseError(f"Step {i} in ritual '{ritual_id}' must be a mapping ({src})")
        if "id" not in step_data:
            raise RitualParseError(
                f"Step {i} in ritual '{ritual_id}' is missing required 'id' ({src})"
            )
        try:
            steps.append(RitualStep(**step_data))
        except Exception as e:
            raise RitualParseError(
                f"Step '{step_data.get('id', i)}' in ritual '{ritual_id}' is invalid: {e} ({src})"
            ) from e

    # Parse optional fields
    tags = data.get("tags", [])
    if not isinstance(tags, list):
        raise RitualParseError(f"Ritual 'tags' must be a list ({src})")

    try:
        return Ritual(
            id=ritual_id,
            name=name,
            version=str(data.get("version", "1.0.0")),
            description=data.get("description"),
            tags=[str(t) for t in tags],
            steps=steps,
            source_path=str(source_path) if source_path else None,
        )
    except Exception as e:
        raise RitualParseError(f"Failed to construct Ritual from '{src}': {e}") from e


def parse_ritual_file(path: str | Path) -> Ritual:
    """
    Parse a ``*.ritual.yaml`` file from disk.

    Args:
        path: Path to the ritual YAML file.

    Returns:
        Populated :class:`~grimoire.models.Ritual` instance.

    Raises:
        RitualParseError: If the file cannot be read or is malformed.
    """
    p = Path(path)
    if not p.exists():
        raise RitualParseError(f"Ritual file not found: {p}")

    try:
        raw = p.read_text(encoding="utf-8")
    except OSError as e:
        raise RitualParseError(f"Cannot read ritual file {p}: {e}") from e

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        raise RitualParseError(f"Invalid YAML in ritual file {p}: {e}") from e

    return parse_ritual(data, source_path=p)
