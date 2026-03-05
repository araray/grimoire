# src/grimoire/skilldocs/parser.py
"""
SkillDoc parser.

Parses ``*.skilldoc.md`` files (markdown + YAML frontmatter) into
:class:`~grimoire.models.SkillDoc` instances.

File format::

    ---
    id: skills/git/workflow
    name: Git Workflow Guide
    version: 1.0.0
    tags: [git, devtools, vcs]
    sections:
      - id: branching
        tags: [branching, workflow]
      - id: rebase
        tags: [rebase, history]
    ---

    ## branching

    Content about branching strategy...

    ## rebase

    Content about interactive rebase...

Sections are split by ``## heading`` lines; each heading's text is used as
the section ID if no explicit ``sections`` list is provided in the frontmatter.
If a ``sections`` list is provided it is used for metadata (tags per section);
the actual content is still split by headings.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml

from grimoire.exceptions import SkillDocParseError
from grimoire.models import SkillDoc, SkillDocSection

logger = logging.getLogger(__name__)

# Regex to split on ## headings (level-2 only, per spec §7)
_HEADING_RE = re.compile(r"^## (.+)$", re.MULTILINE)


def parse_skilldoc(data: dict[str, Any], body: str, source_path: str | Path | None = None) -> SkillDoc:
    """
    Parse a SkillDoc from frontmatter dict + markdown body.

    Args:
        data: YAML frontmatter dict.
        body: Markdown body (after frontmatter).
        source_path: Optional path for error messages.

    Returns:
        Validated ``SkillDoc`` instance.

    Raises:
        SkillDocParseError: If required fields are missing or body is unparseable.
    """
    loc = str(source_path) if source_path else "<dict>"
    try:
        # Section metadata from frontmatter (optional)
        section_meta: dict[str, dict[str, Any]] = {}
        for sec_def in data.get("sections", []):
            if isinstance(sec_def, dict) and "id" in sec_def:
                section_meta[sec_def["id"]] = sec_def

        # Split body into sections by ## headings
        sections = _split_sections(body.strip(), section_meta)

        skilldoc = SkillDoc(
            id=data["id"],
            name=data["name"],
            version=data.get("version", "1.0.0"),
            description=data.get("description"),
            tags=data.get("tags", []),
            sections=sections,
            source_path=str(source_path) if source_path else None,
        )
        return skilldoc
    except SkillDocParseError:
        raise
    except KeyError as e:
        raise SkillDocParseError(f"Missing required field {e} in skilldoc at {loc}") from e
    except Exception as e:
        raise SkillDocParseError(f"Failed to parse skilldoc at {loc}: {e}") from e


def parse_skilldoc_file(path: str | Path) -> SkillDoc:
    """
    Parse a ``*.skilldoc.md`` file.

    Args:
        path: Path to the skilldoc file.

    Returns:
        Validated ``SkillDoc`` instance.

    Raises:
        SkillDocParseError: If the file cannot be read or parsed.
    """
    p = Path(path)
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError as e:
        raise SkillDocParseError(f"Cannot read skilldoc file {p}: {e}") from e

    # Split frontmatter from body
    frontmatter, body = _split_frontmatter(raw, p)
    return parse_skilldoc(frontmatter, body, source_path=p)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _split_frontmatter(text: str, path: Path) -> tuple[dict[str, Any], str]:
    """
    Split YAML frontmatter from markdown body.

    Returns (frontmatter_dict, body_text).
    Raises SkillDocParseError if frontmatter is missing or invalid.
    """
    text = text.lstrip()
    if not text.startswith("---"):
        raise SkillDocParseError(
            f"SkillDoc {path} must start with YAML frontmatter (--- ... ---)"
        )
    # Find closing ---
    end = text.find("\n---", 3)
    if end == -1:
        raise SkillDocParseError(f"SkillDoc {path}: unclosed frontmatter (missing closing ---)")

    fm_text = text[3:end].strip()
    body = text[end + 4:].strip()  # skip past closing ---\n

    try:
        fm = yaml.safe_load(fm_text)
    except yaml.YAMLError as e:
        raise SkillDocParseError(f"SkillDoc {path}: invalid frontmatter YAML: {e}") from e

    if not isinstance(fm, dict):
        raise SkillDocParseError(f"SkillDoc {path}: frontmatter must be a mapping")

    return fm, body


def _split_sections(
    body: str,
    section_meta: dict[str, dict[str, Any]],
) -> list[SkillDocSection]:
    """
    Split markdown body into sections at ## headings.

    If ``section_meta`` contains metadata for a section ID, that metadata
    (tags, description) is applied.
    """
    matches = list(_HEADING_RE.finditer(body))
    if not matches:
        # Whole body is a single unnamed section
        if body.strip():
            return [SkillDocSection(id="main", heading="main", content=body.strip())]
        return []

    sections: list[SkillDocSection] = []
    for i, match in enumerate(matches):
        heading_text = match.group(1).strip()
        # Derive section ID: lowercase, spaces→underscores
        sec_id = heading_text.lower().replace(" ", "_")

        # Content spans from after this heading to just before the next
        content_start = match.end()
        content_end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        content = body[content_start:content_end].strip()

        # Merge metadata from frontmatter section list
        meta = section_meta.get(sec_id, {})
        tags = meta.get("tags", [])

        sections.append(
            SkillDocSection(
                id=sec_id,
                heading=heading_text,
                content=content,
                tags=tags,
            )
        )

    return sections
