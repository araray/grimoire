"""Data models for procedural spell discovery."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from grimoire.models import CommandSpec, RuneSpec, Spell


@dataclass(frozen=True)
class SpellIndexDocument:
    """One spell serialized for procedural retrieval indexing."""

    document_id: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProceduralSearchResult:
    """Normalized result returned by a procedural retriever."""

    spell_id: str
    score: float
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    highlight: str = ""
    artifact_type: str = "spell"
    rune_id: str = ""
    command_name: str = ""


@dataclass(frozen=True)
class IntentMatch:
    """A spell matched to a natural-language intent query."""

    spell: Spell
    score: float
    highlight: str = ""


@dataclass(frozen=True)
class ToolIntentMatch:
    """A rune command matched to a natural-language capability query."""

    rune: RuneSpec
    command: CommandSpec
    score: float
    highlight: str = ""


__all__ = [
    "IntentMatch",
    "ProceduralSearchResult",
    "SpellIndexDocument",
    "ToolIntentMatch",
]
