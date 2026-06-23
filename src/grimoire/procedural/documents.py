"""Build procedural retrieval documents from spells."""

from __future__ import annotations

from typing import Any

from grimoire.models import BlueprintStatus, SemanticBlueprint, Spell

from .models import SpellIndexDocument

DEFAULT_PROCEDURAL_COLLECTION = "grimoire/spells"


def spell_document_id(spell: Spell) -> str:
    """Return the stable index document id for a spell version."""
    return f"{spell.id}@{spell.version}"


def build_spell_index_document(spell: Spell) -> SpellIndexDocument:
    """Serialize a spell into a Semantiscan-compatible retrieval document."""
    blueprint = spell.semantic_blueprint
    content_parts = [spell.effective_intent]
    if blueprint is not None:
        content_parts.append(blueprint.to_retrieval_text())
    if spell.description:
        content_parts.append(spell.description)
    if spell.tags:
        content_parts.append("Tags: " + ", ".join(spell.tags))

    metadata = _spell_metadata(spell, blueprint)
    return SpellIndexDocument(
        document_id=spell_document_id(spell),
        content="\n\n".join(dict.fromkeys(part for part in content_parts if part.strip())),
        metadata=metadata,
    )


def _spell_metadata(spell: Spell, blueprint: SemanticBlueprint | None) -> dict[str, Any]:
    participant_roles: list[str] = []
    participant_semantic_roles: list[str] = []
    keywords: list[str] = []
    status = BlueprintStatus.ACTIVE.value
    domain = ""
    scene_goal = ""
    action = ""

    if blueprint is not None:
        participant_roles = [participant.role for participant in blueprint.participants]
        participant_semantic_roles = [
            participant.semantic_role.value for participant in blueprint.participants
        ]
        keywords = list(blueprint.keywords)
        status = blueprint.status.value
        domain = blueprint.domain or ""
        scene_goal = blueprint.scene_goal
        action = blueprint.action_to_complete

    return {
        "artifact_type": "spell",
        "spell_id": spell.id,
        "version": spell.version,
        "name": spell.name,
        "domain": domain,
        "status": status,
        "scene_goal": scene_goal,
        "action": action,
        "participant_roles": ",".join(participant_roles),
        "participant_semantic_roles": ",".join(participant_semantic_roles),
        "keywords": ",".join(keywords),
        "tags": ",".join(spell.tags),
        "has_blueprint": blueprint is not None,
        "content_hash": spell.content_hash or "",
    }


def metadata_list(metadata: dict[str, Any], key: str) -> list[str]:
    """Read a comma-separated metadata field as a list."""
    value = metadata.get(key)
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return []


__all__ = [
    "DEFAULT_PROCEDURAL_COLLECTION",
    "build_spell_index_document",
    "metadata_list",
    "spell_document_id",
]
