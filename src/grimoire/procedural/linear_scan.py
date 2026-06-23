"""In-memory fallback intent matching for small spell libraries."""

from __future__ import annotations

import re

from grimoire.models import BlueprintStatus, RiskLevel, RuneSpec, SemanticRole, Spell

from .documents import build_rune_command_index_documents, build_spell_index_document
from .models import IntentMatch, ToolIntentMatch

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


def find_tools_by_intent_linear(
    query: str,
    runes: list[RuneSpec],
    *,
    top_k: int = 5,
    tags: list[str] | None = None,
    max_risk: RiskLevel | str | None = None,
    include_requires_approval: bool = True,
) -> list[ToolIntentMatch]:
    """Rank rune commands by token overlap against their procedural tool text."""
    query_tokens = _tokens(query)
    if not query_tokens or top_k <= 0:
        return []

    scored: list[ToolIntentMatch] = []
    for rune in runes:
        if not _rune_matches_filters(
            rune,
            tags=tags,
            max_risk=max_risk,
            include_requires_approval=include_requires_approval,
        ):
            continue
        command_docs = build_rune_command_index_documents(rune)
        for command, doc in zip(rune.commands, command_docs, strict=False):
            if not tool_matches_filters(
                rune,
                command_name=command.name,
                tags=tags,
                max_risk=max_risk,
                include_requires_approval=include_requires_approval,
            ):
                continue
            doc_tokens = _tokens(doc.content)
            if not doc_tokens:
                continue
            score = len(query_tokens & doc_tokens) / len(query_tokens | doc_tokens)
            if score <= 0:
                continue
            scored.append(
                ToolIntentMatch(
                    rune=rune,
                    command=command,
                    score=score,
                    highlight=command.summary or rune.description or rune.name,
                )
            )

    return sorted(
        scored,
        key=lambda match: (-match.score, match.rune.id, match.command.name),
    )[:top_k]


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


def tool_matches_filters(
    rune: RuneSpec,
    *,
    command_name: str,
    tags: list[str] | None = None,
    max_risk: RiskLevel | str | None = None,
    include_requires_approval: bool = True,
) -> bool:
    """Return whether a rune command satisfies procedural tool filters."""
    if not _rune_matches_filters(
        rune,
        tags=tags,
        max_risk=max_risk,
        include_requires_approval=include_requires_approval,
    ):
        return False
    command = rune.get_command(command_name)
    if command is None:
        return False
    if (command.requires_approval or rune.requires_approval) and not include_requires_approval:
        return False
    command_risk = command.risk_level or rune.risk_level
    if max_risk is not None and not _risk_allowed(command_risk, max_risk):
        return False
    return True


def _rune_matches_filters(
    rune: RuneSpec,
    *,
    tags: list[str] | None,
    max_risk: RiskLevel | str | None,
    include_requires_approval: bool,
) -> bool:
    if tags and not set(tags).issubset(set(rune.tags)):
        return False
    if not include_requires_approval and rune.requires_approval:
        return False
    if max_risk is not None and not _risk_allowed(rune.risk_level, max_risk):
        return False
    return True


def _risk_allowed(risk: RiskLevel | str | None, max_risk: RiskLevel | str) -> bool:
    if risk is None:
        return True
    risk_value = RiskLevel(risk) if isinstance(risk, str) else risk
    max_value = RiskLevel(max_risk) if isinstance(max_risk, str) else max_risk
    order = {
        RiskLevel.NONE: 0,
        RiskLevel.LOW: 1,
        RiskLevel.MEDIUM: 2,
        RiskLevel.HIGH: 3,
    }
    return order[risk_value] <= order[max_value]


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall((text or "").lower()))


__all__ = [
    "find_spells_by_intent_linear",
    "find_tools_by_intent_linear",
    "spell_matches_filters",
    "tool_matches_filters",
]
