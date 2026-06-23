"""Build procedural retrieval documents from spells."""

from __future__ import annotations

from typing import Any

from grimoire.models import BlueprintStatus, CommandSpec, RuneSpec, SemanticBlueprint, Spell

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


def rune_command_document_id(rune: RuneSpec, command: CommandSpec) -> str:
    """Return the stable index document id for one rune command."""
    return f"{rune.id}@{rune.version}::{command.name}"


def build_rune_command_index_documents(rune: RuneSpec) -> list[SpellIndexDocument]:
    """Serialize each rune command into a procedural retrieval document."""
    return [
        SpellIndexDocument(
            document_id=rune_command_document_id(rune, command),
            content=_rune_command_content(rune, command),
            metadata=_rune_command_metadata(rune, command),
        )
        for command in rune.commands
    ]


def _rune_command_content(rune: RuneSpec, command: CommandSpec) -> str:
    parts = [
        f"Rune: {rune.name}",
        f"Command: {command.name}",
    ]
    if command.summary:
        parts.append(f"Capability: {command.summary}")
    if rune.description:
        parts.append(f"Rune description: {rune.description}")
    if rune.tags:
        parts.append("Tags: " + ", ".join(rune.tags))
    if rune.permissions:
        parts.append("Permissions: " + ", ".join(permission.value for permission in rune.permissions))
    if command.side_effects:
        parts.append("Side effects: " + ", ".join(command.side_effects))
    if command.params:
        params = []
        for param in command.params:
            description = f" - {param.description}" if param.description else ""
            params.append(f"{param.name} ({param.type}){description}")
        parts.append("Parameters: " + "; ".join(params))
    return "\n".join(parts)


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


def _rune_command_metadata(rune: RuneSpec, command: CommandSpec) -> dict[str, Any]:
    risk_level = command.risk_level or rune.risk_level
    return {
        "artifact_type": "rune_command",
        "rune_id": rune.id,
        "command_name": command.name,
        "tool_name": f"{rune.id}::{command.name}",
        "version": rune.version,
        "name": rune.name,
        "summary": command.summary or "",
        "risk_level": risk_level.value if risk_level else "",
        "requires_approval": command.requires_approval or rune.requires_approval,
        "permissions": ",".join(permission.value for permission in rune.permissions),
        "execution_target": command.execution_target or "",
        "tags": ",".join(rune.tags),
        "content_hash": rune.content_hash or "",
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
    "build_rune_command_index_documents",
    "build_spell_index_document",
    "metadata_list",
    "rune_command_document_id",
    "spell_document_id",
]
