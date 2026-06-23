"""In-memory fallback intent matching for small spell libraries."""

from __future__ import annotations

import re

from grimoire.models import BlueprintStatus, SemanticRole, Spell

from .documents import build_spell_index_document
from .models import IntentMatch

_TOKEN_RE = re.compile(r"[a-z0-9_]+")


def find_spells_by_intent_linear(
    query: str,
    spells: list[Spell],
    *,
    top_k: int = 5,
    filter_domain: str | None = None,
    filter_semantic_role: SemanticRole | str | None = None,
    include_deprecated: bool = False,
) -> list[IntentMatch]:
    """Rank spells by token overlap against their procedural intent text."""
    query_tokens = _tokens(query)
    if not query_tokens or top_k <= 0:
        return []

    scored: list[IntentMatch] = []
    for spell in spells:
        if not spell_matches_filters(
            spell,
            filter_domain=filter_domain,
            filter_semantic_role=filter_semantic_role,
            include_deprecated=include_deprecated,
        ):
            continue
        doc = build_spell_index_document(spell)
        spell_tokens = _tokens(doc.content)
        if not spell_tokens:
            continue
        score = len(query_tokens & spell_tokens) / len(query_tokens | spell_tokens)
        if score <= 0:
            continue
        scored.append(IntentMatch(spell=spell, score=score, highlight=spell.effective_intent))

    return sorted(scored, key=lambda match: (-match.score, match.spell.id))[:top_k]


def spell_matches_filters(
    spell: Spell,
    *,
    filter_domain: str | None = None,
    filter_semantic_role: SemanticRole | str | None = None,
    include_deprecated: bool = False,
) -> bool:
    """Return whether a spell satisfies procedural intent filters."""
    blueprint = spell.semantic_blueprint
    if blueprint is None:
        return not filter_domain and not filter_semantic_role

    if not include_deprecated and blueprint.status == BlueprintStatus.DEPRECATED:
        return False
    if filter_domain and blueprint.domain != filter_domain:
        return False
    if filter_semantic_role:
        role = (
            filter_semantic_role.value
            if isinstance(filter_semantic_role, SemanticRole)
            else str(filter_semantic_role)
        )
        if role not in {participant.semantic_role.value for participant in blueprint.participants}:
            return False
    return True


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall((text or "").lower()))


__all__ = ["find_spells_by_intent_linear", "spell_matches_filters"]
