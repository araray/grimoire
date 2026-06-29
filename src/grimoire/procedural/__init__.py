"""Procedural spell discovery helpers."""

from __future__ import annotations

from .documents import (
    DEFAULT_PROCEDURAL_COLLECTION,
    build_rune_command_index_documents,
    build_spell_index_document,
    metadata_list,
    rune_command_document_id,
    spell_document_id,
)
from .indexer import ProceduralIndexer
from .linear_scan import (
    find_spells_by_intent_linear,
    find_tools_by_intent_linear,
    spell_matches_filters,
    tool_matches_filters,
)
from .models import IntentMatch, ProceduralSearchResult, SpellIndexDocument, ToolIntentMatch
from .retriever import ProceduralRetriever, normalize_procedural_results

__all__ = [
    "DEFAULT_PROCEDURAL_COLLECTION",
    "IntentMatch",
    "ProceduralIndexer",
    "ProceduralRetriever",
    "ProceduralSearchResult",
    "SpellIndexDocument",
    "ToolIntentMatch",
    "build_rune_command_index_documents",
    "build_spell_index_document",
    "find_spells_by_intent_linear",
    "find_tools_by_intent_linear",
    "metadata_list",
    "normalize_procedural_results",
    "rune_command_document_id",
    "spell_document_id",
    "spell_matches_filters",
    "tool_matches_filters",
]
