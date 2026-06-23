"""Procedural spell discovery helpers."""

from __future__ import annotations

from .documents import (
    DEFAULT_PROCEDURAL_COLLECTION,
    build_spell_index_document,
    metadata_list,
    spell_document_id,
)
from .indexer import ProceduralIndexer
from .linear_scan import find_spells_by_intent_linear, spell_matches_filters
from .models import IntentMatch, ProceduralSearchResult, SpellIndexDocument
from .retriever import ProceduralRetriever, normalize_procedural_results

__all__ = [
    "DEFAULT_PROCEDURAL_COLLECTION",
    "IntentMatch",
    "ProceduralIndexer",
    "ProceduralRetriever",
    "ProceduralSearchResult",
    "SpellIndexDocument",
    "build_spell_index_document",
    "find_spells_by_intent_linear",
    "metadata_list",
    "normalize_procedural_results",
    "spell_document_id",
    "spell_matches_filters",
]
