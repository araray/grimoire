# src/grimoire/bind/llmcore.py
"""
llmcore binding target.

Exports grimoire artifacts into formats consumable by llmcore:

1. **Prompt registry bundle**: JSON files per spell containing prompt
   metadata, message templates, snippets, and variable schemas.
   Loadable by llmcore's ``PromptRegistry``.

2. **Activity definitions** (from runes): JSON files describing
   tool/activity contracts with risk levels and parameter schemas,
   compatible with llmcore's ``ActivityRegistry``.

References:
    Spec §10.1, §14.2
"""

from __future__ import annotations

import json
import logging
from typing import Any

from grimoire.bind.base import Binder, BindFormat, BindResult, BindTarget, BoundFile
from grimoire.models import CommandSpec, MessageRole, RuneSpec, Spell
from grimoire.store.repo import GrimoireRepo

logger = logging.getLogger(__name__)


def _spell_to_registry_entry(spell: Spell) -> dict[str, Any]:
    """
    Convert a spell to an llmcore prompt registry entry.

    Produces a JSON-serializable dict matching llmcore's
    prompt template structure.
    """
    # Build messages array
    messages: list[dict[str, str]] = []
    for block in spell.raw_blocks:
        role_map = {
            MessageRole.SYSTEM: "system",
            MessageRole.DEVELOPER: "developer",
            MessageRole.USER: "user",
            MessageRole.ASSISTANT_PREFILL: "assistant",
        }
        messages.append(
            {
                "role": role_map.get(block.role, block.role.value.lower()),
                "content": block.content,
            }
        )

    # Build variable schema
    var_schema: dict[str, Any] = {}
    for name, spec in spell.variables.items():
        var_entry: dict[str, Any] = {
            "type": spec.type.value,
            "required": spec.required,
        }
        if spec.default is not None:
            var_entry["default"] = spec.default
        if spec.description:
            var_entry["description"] = spec.description
        if spec.choices:
            var_entry["choices"] = spec.choices
        if spec.min_value is not None:
            var_entry["min"] = spec.min_value
        if spec.max_value is not None:
            var_entry["max"] = spec.max_value
        var_schema[name] = var_entry

    entry: dict[str, Any] = {
        "id": spell.id,
        "name": spell.name,
        "version": spell.version,
        "tags": spell.tags,
        "messages": messages,
        "variables": var_schema,
    }

    if spell.content_hash:
        entry["content_hash"] = spell.content_hash
    if spell.description:
        entry["description"] = spell.description
    if spell.requires_runes:
        entry["requires_runes"] = spell.requires_runes
    if spell.suggests_runes:
        entry["suggests_runes"] = spell.suggests_runes
    if spell.output_contract:
        entry["output_contract"] = {
            "type": spell.output_contract.type.value,
        }
        if spell.output_contract.json_schema:
            entry["output_contract"]["schema"] = spell.output_contract.json_schema

    return entry


def _command_to_tool_schema(cmd: CommandSpec, rune: RuneSpec) -> dict[str, Any]:
    """Convert a rune command to an OpenAI-compatible tool/function schema."""
    properties: dict[str, Any] = {}
    required: list[str] = []

    for param in cmd.params:
        prop: dict[str, Any] = {"type": param.type}
        if param.description:
            prop["description"] = param.description
        if param.enum:
            prop["enum"] = param.enum
        if param.minimum is not None:
            prop["minimum"] = param.minimum
        if param.maximum is not None:
            prop["maximum"] = param.maximum
        if param.default is not None:
            prop["default"] = param.default
        properties[param.name] = prop

        if param.required:
            required.append(param.name)

    schema: dict[str, Any] = {
        "type": "function",
        "function": {
            "name": f"{rune.id.replace('/', '_')}_{cmd.name}",
            "description": cmd.summary or f"{rune.name}: {cmd.name}",
            "parameters": {
                "type": "object",
                "properties": properties,
            },
        },
    }

    if required:
        schema["function"]["parameters"]["required"] = required

    return schema


def _rune_to_activity_definition(rune: RuneSpec) -> dict[str, Any]:
    """
    Convert a rune to an llmcore ActivityDefinition-compatible structure.

    Maps rune risk levels, permissions, and commands to llmcore's
    activity model (RiskLevel, ParameterSchema, etc.).
    """
    commands: list[dict[str, Any]] = []
    for cmd in rune.commands:
        cmd_entry: dict[str, Any] = {
            "name": cmd.name,
            "summary": cmd.summary,
            "risk_level": (cmd.risk_level or rune.risk_level).value
            if (cmd.risk_level or rune.risk_level)
            else "low",
            "requires_approval": cmd.requires_approval or rune.requires_approval,
            "side_effects": cmd.side_effects,
        }

        # Parameter schemas
        params: list[dict[str, Any]] = []
        for p in cmd.params:
            param_entry: dict[str, Any] = {
                "name": p.name,
                "type": p.type,
                "required": p.required,
            }
            if p.default is not None:
                param_entry["default"] = p.default
            if p.description:
                param_entry["description"] = p.description
            params.append(param_entry)
        cmd_entry["parameters"] = params

        # Tool schema for function-calling capable models
        cmd_entry["tool_schema"] = _command_to_tool_schema(cmd, rune)

        commands.append(cmd_entry)

    return {
        "id": rune.id,
        "name": rune.name,
        "version": rune.version,
        "description": rune.description,
        "tags": rune.tags,
        "risk_level": rune.risk_level.value,
        "permissions": [p.value for p in rune.permissions],
        "platforms": rune.platforms,
        "commands": commands,
        "content_hash": rune.content_hash,
    }


class LLMCoreBinder(Binder):
    """
    Bind grimoire artifacts to llmcore-compatible formats.

    Produces:
        - ``prompts/`` directory with one JSON per spell
        - ``activities/`` directory with one JSON per rune
        - ``manifest.json`` index file
    """

    @property
    def target(self) -> BindTarget:
        return BindTarget.LLMCORE

    @property
    def default_format(self) -> BindFormat:
        return BindFormat.REGISTRY_BUNDLE

    def bind(
        self,
        repo: GrimoireRepo,
        *,
        fmt: BindFormat | None = None,
        spell_ids: list[str] | None = None,
        rune_ids: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> BindResult:
        """Export spells and runes to llmcore registry format."""
        fmt = fmt or self.default_format
        result = BindResult(
            target=self.target,
            format=fmt,
            metadata={"grimoire": repo.manifest.name, "version": repo.manifest.version},
        )

        # Select spells
        if spell_ids:
            spells = []
            for sid in spell_ids:
                try:
                    spells.append(repo.get_spell(sid))
                except Exception:
                    result.warnings.append(f"Spell '{sid}' not found, skipped")
        else:
            spells = repo.list_spells(tags=tags)

        # Select runes
        if rune_ids:
            runes = []
            for rid in rune_ids:
                try:
                    runes.append(repo.get_rune(rid))
                except Exception:
                    result.warnings.append(f"Rune '{rid}' not found, skipped")
        else:
            runes = repo.list_runes(tags=tags)

        # Generate prompt files
        prompt_entries: list[dict[str, Any]] = []
        for spell in spells:
            try:
                entry = _spell_to_registry_entry(spell)
                safe_id = spell.id.replace("/", "_")
                result.files.append(
                    BoundFile(
                        relative_path=f"prompts/{safe_id}.json",
                        content=json.dumps(entry, indent=2),
                        description=f"Prompt registry entry for {spell.id}",
                    )
                )
                prompt_entries.append({"id": spell.id, "file": f"prompts/{safe_id}.json"})
            except Exception as e:
                result.warnings.append(f"Failed to bind spell '{spell.id}': {e}")

        # Generate activity files
        activity_entries: list[dict[str, Any]] = []
        for rune in runes:
            try:
                activity = _rune_to_activity_definition(rune)
                safe_id = rune.id.replace("/", "_")
                result.files.append(
                    BoundFile(
                        relative_path=f"activities/{safe_id}.json",
                        content=json.dumps(activity, indent=2),
                        description=f"Activity definition for {rune.id}",
                    )
                )
                activity_entries.append({"id": rune.id, "file": f"activities/{safe_id}.json"})
            except Exception as e:
                result.warnings.append(f"Failed to bind rune '{rune.id}': {e}")

        # Generate manifest
        manifest = {
            "grimoire": repo.manifest.name,
            "version": repo.manifest.version,
            "prompts": prompt_entries,
            "activities": activity_entries,
        }
        result.files.append(
            BoundFile(
                relative_path="manifest.json",
                content=json.dumps(manifest, indent=2),
                description="llmcore registry manifest",
            )
        )

        result.metadata["prompt_count"] = len(prompt_entries)
        result.metadata["activity_count"] = len(activity_entries)
        return result
