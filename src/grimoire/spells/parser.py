# src/grimoire/spells/parser.py
"""
Spell file parser.

Parses ``*.spell.md`` files with the canonical format:

    ---
    id: engineering/bug_root_cause
    name: Root cause analysis
    version: 1.0.0
    variables:
      issue_title:
        type: string
        required: true
    ...
    ---

    # SYSTEM
    System prompt content...

    # DEVELOPER
    Developer context...

    # USER
    User instructions...

The parser:
    1. Extracts YAML front-matter (between ``---`` delimiters).
    2. Splits the body into message blocks keyed by ``# ROLE`` headers.
    3. Validates and constructs a ``Spell`` model.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import yaml

from grimoire.exceptions import SpellParseError, SpellValidationError
from grimoire.models import (
    MessageBlock,
    MessageRole,
    OutputContract,
    RuneExportConfig,
    Spell,
    VariableSpec,
)

logger = logging.getLogger(__name__)

# Pattern for matching message block headers: "# SYSTEM", "# USER", etc.
_BLOCK_HEADER_RE = re.compile(
    r"^#\s+(SYSTEM|DEVELOPER|USER|ASSISTANT_PREFILL)\s*$",
    re.MULTILINE,
)

# Valid front-matter keys (for warning on unknowns)
_KNOWN_FM_KEYS = frozenset(
    {
        "id",
        "name",
        "version",
        "tags",
        "description",
        "license",
        "variables",
        "requires_runes",
        "suggests_runes",
        "runes_export",
        "output_contract",
    }
)


def _split_frontmatter(text: str) -> tuple[str, str]:
    """
    Split a spell file into YAML front-matter and markdown body.

    Args:
        text: Full file contents.

    Returns:
        (frontmatter_yaml, body_markdown) tuple.

    Raises:
        SpellParseError: If front-matter delimiters are missing or malformed.
    """
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        raise SpellParseError("Spell file must start with YAML front-matter (---)")

    # Find the closing ---
    # The opening --- may be preceded by whitespace/BOM
    first_delim = stripped.index("---")
    rest = stripped[first_delim + 3 :]
    second_delim = rest.find("\n---")
    if second_delim == -1:
        raise SpellParseError("No closing '---' for YAML front-matter")

    fm_text = rest[:second_delim]
    body = rest[second_delim + 4 :]  # skip "\n---"

    return fm_text.strip(), body.strip()


def _parse_blocks(body: str) -> list[MessageBlock]:
    """
    Parse markdown body into message blocks.

    Splits on ``# ROLE`` headers and returns ordered MessageBlock list.

    Args:
        body: The markdown body after front-matter.

    Returns:
        List of MessageBlock instances.

    Raises:
        SpellParseError: If no recognized message blocks are found.
    """
    # Find all header positions
    matches = list(_BLOCK_HEADER_RE.finditer(body))
    if not matches:
        # If no headers, treat entire body as a USER block
        content = body.strip()
        if content:
            return [MessageBlock(role=MessageRole.USER, content=content)]
        raise SpellParseError("Spell body contains no message blocks and no content")

    blocks: list[MessageBlock] = []
    for i, match in enumerate(matches):
        role_str = match.group(1)
        role = MessageRole(role_str)

        # Content runs from after this header to the start of the next header (or end)
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        content = body[start:end].strip()

        if content:
            blocks.append(MessageBlock(role=role, content=content))

    return blocks


def _parse_variables(raw: dict | None) -> dict[str, VariableSpec]:
    """
    Parse variable schema from front-matter.

    Args:
        raw: The ``variables`` dict from YAML front-matter.

    Returns:
        Validated dict of variable name → VariableSpec.

    Raises:
        SpellValidationError: If variable schema is invalid.
    """
    if not raw:
        return {}

    variables: dict[str, VariableSpec] = {}
    for name, spec_data in raw.items():
        if isinstance(spec_data, str):
            # Shorthand: "issue_title: string" → VariableSpec(type=string)
            variables[name] = VariableSpec(type=spec_data)
        elif isinstance(spec_data, dict):
            try:
                variables[name] = VariableSpec(**spec_data)
            except Exception as e:
                raise SpellValidationError(f"Invalid variable spec for '{name}': {e}") from e
        else:
            raise SpellValidationError(
                f"Variable '{name}' must be a string (type shorthand) or dict, got {type(spec_data)}"
            )
    return variables


def parse_spell(text: str, source_path: str | None = None) -> Spell:
    """
    Parse a spell from its text content.

    Args:
        text: Full ``*.spell.md`` file contents.
        source_path: Optional path for provenance tracking.

    Returns:
        A validated Spell model.

    Raises:
        SpellParseError: If file structure is invalid.
        SpellValidationError: If data fails validation.
    """
    fm_text, body = _split_frontmatter(text)

    # Parse YAML front-matter
    try:
        fm: dict = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError as e:
        raise SpellParseError(f"Invalid YAML front-matter: {e}") from e

    if not isinstance(fm, dict):
        raise SpellParseError(f"Front-matter must be a mapping, got {type(fm)}")

    # Warn on unknown keys
    unknown = set(fm.keys()) - _KNOWN_FM_KEYS
    if unknown:
        logger.warning(f"Unknown front-matter keys in spell: {unknown}")

    # Required fields
    spell_id = fm.get("id")
    if not spell_id:
        raise SpellValidationError("Spell front-matter must include 'id'")

    name = fm.get("name", spell_id)

    # Parse variables
    variables = _parse_variables(fm.get("variables"))

    # Parse rune export config
    runes_export = None
    if "runes_export" in fm:
        try:
            runes_export = RuneExportConfig(**fm["runes_export"])
        except Exception as e:
            raise SpellValidationError(f"Invalid runes_export: {e}") from e

    # Parse output contract
    output_contract = None
    if "output_contract" in fm:
        try:
            output_contract = OutputContract(**fm["output_contract"])
        except Exception as e:
            raise SpellValidationError(f"Invalid output_contract: {e}") from e

    # Parse message blocks
    blocks = _parse_blocks(body)

    try:
        return Spell(
            id=spell_id,
            name=name,
            version=fm.get("version", "1.0.0"),
            tags=fm.get("tags", []),
            description=fm.get("description"),
            license=fm.get("license"),
            variables=variables,
            requires_runes=fm.get("requires_runes", []),
            suggests_runes=fm.get("suggests_runes", []),
            runes_export=runes_export,
            output_contract=output_contract,
            raw_blocks=blocks,
            source_path=source_path,
        )
    except Exception as e:
        raise SpellValidationError(f"Failed to construct Spell: {e}") from e


def parse_spell_file(path: str | Path) -> Spell:
    """
    Parse a spell from a file path.

    Args:
        path: Path to a ``*.spell.md`` file.

    Returns:
        A validated Spell model.
    """
    p = Path(path)
    if not p.exists():
        raise SpellParseError(f"Spell file not found: {p}")
    if not p.suffix == ".md" and not p.name.endswith(".spell.md"):
        logger.warning(f"Spell file '{p.name}' does not follow *.spell.md convention")

    text = p.read_text(encoding="utf-8")
    return parse_spell(text, source_path=str(p))
