# src/grimoire/bind/wairu.py
"""
Wairu binding target.

Exports rune contracts as wairu tool packs — YAML files describing
tool definitions with risk levels, approval requirements, and
parameter schemas compatible with wairu's plugin tool format.

Optionally includes augmentation promptlets (approval guidance,
tool-use policy) as companion files.

References:
    Spec §10.1, §14.3
"""

from __future__ import annotations

import json
import logging
from typing import Any

import yaml

from grimoire.bind.base import Binder, BindFormat, BindResult, BindTarget, BoundFile
from grimoire.models import RuneSpec, Spell
from grimoire.store.repo import GrimoireRepo

logger = logging.getLogger(__name__)


def _rune_to_tool_pack(rune: RuneSpec) -> dict[str, Any]:
    """
    Convert a rune contract to a wairu tool pack entry.

    Maps rune commands to wairu's tool definition format with
    risk/approval metadata.
    """
    tools: list[dict[str, Any]] = []

    for cmd in rune.commands:
        # Build JSON-schema-style parameter definition
        properties: dict[str, Any] = {}
        required: list[str] = []

        for param in cmd.params:
            prop: dict[str, Any] = {"type": param.type}
            if param.description:
                prop["description"] = param.description
            if param.default is not None:
                prop["default"] = param.default
            if param.enum:
                prop["enum"] = param.enum
            if param.minimum is not None:
                prop["minimum"] = param.minimum
            if param.maximum is not None:
                prop["maximum"] = param.maximum
            properties[param.name] = prop

            if param.required:
                required.append(param.name)

        tool: dict[str, Any] = {
            "name": cmd.name,
            "description": cmd.summary or f"{rune.name}: {cmd.name}",
            "risk_level": (cmd.risk_level or rune.risk_level).value
            if (cmd.risk_level or rune.risk_level)
            else "low",
            "requires_approval": cmd.requires_approval or rune.requires_approval,
            "side_effects": cmd.side_effects,
            "parameters": {
                "type": "object",
                "properties": properties,
            },
        }

        if required:
            tool["parameters"]["required"] = required

        # Examples
        if cmd.examples:
            tool["examples"] = [{"call": ex.call, "expect": ex.expect} for ex in cmd.examples]

        tools.append(tool)

    return {
        "id": rune.id,
        "name": rune.name,
        "version": rune.version,
        "description": rune.description,
        "tags": rune.tags,
        "risk_level": rune.risk_level.value,
        "permissions": [p.value for p in rune.permissions],
        "platforms": rune.platforms,
        "tools": tools,
        "_source": "grimoire",
        "_content_hash": rune.content_hash,
    }


def _spell_to_augmentation(spell: Spell) -> dict[str, Any]:
    """
    Convert a spell to a wairu augmentation prompt entry.

    Used for tool-policy promptlets (approval guidance, risk warnings)
    that wairu can inject into agent context.
    """
    # Combine blocks into a single text
    parts: list[str] = []
    for block in spell.raw_blocks:
        parts.append(block.content)

    return {
        "id": spell.id,
        "name": spell.name,
        "tags": spell.tags,
        "content": "\n\n".join(parts),
        "variables": {
            name: {
                "type": spec.type.value,
                "required": spec.required,
                "default": spec.default,
            }
            for name, spec in spell.variables.items()
        },
    }


class WairuBinder(Binder):
    """
    Bind grimoire rune contracts to wairu tool pack format.

    Produces:
        - ``tools/`` directory with one YAML per rune
        - ``augmentations/`` directory with tool-policy spells (if tagged 'agentic')
        - ``tool_manifest.json`` index file
    """

    @property
    def target(self) -> BindTarget:
        return BindTarget.WAIRU

    @property
    def default_format(self) -> BindFormat:
        return BindFormat.TOOL_PACK

    def bind(
        self,
        repo: GrimoireRepo,
        *,
        fmt: BindFormat | None = None,
        spell_ids: list[str] | None = None,
        rune_ids: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> BindResult:
        """Export runes as wairu tool packs and optionally spells as augmentations."""
        fmt = fmt or self.default_format
        result = BindResult(
            target=self.target,
            format=fmt,
            metadata={"grimoire": repo.manifest.name, "version": repo.manifest.version},
        )

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

        # Generate tool pack files (YAML)
        tool_entries: list[dict[str, Any]] = []
        for rune in runes:
            try:
                pack = _rune_to_tool_pack(rune)
                safe_id = rune.id.replace("/", "_")
                content = yaml.dump(pack, default_flow_style=False, sort_keys=False)
                result.files.append(
                    BoundFile(
                        relative_path=f"tools/{safe_id}.yaml",
                        content=content,
                        description=f"Wairu tool pack for {rune.id}",
                    )
                )
                tool_entries.append(
                    {
                        "id": rune.id,
                        "file": f"tools/{safe_id}.yaml",
                        "risk_level": rune.risk_level.value,
                        "command_count": len(rune.commands),
                    }
                )
            except Exception as e:
                result.warnings.append(f"Failed to bind rune '{rune.id}': {e}")

        # Find agentic spells for augmentation prompts
        agentic_spells: list[Spell] = []
        if spell_ids:
            for sid in spell_ids:
                try:
                    agentic_spells.append(repo.get_spell(sid))
                except Exception:
                    pass
        else:
            # Auto-detect agentic spells by tag
            agentic_spells = repo.list_spells(tags=["agentic"])

        augmentation_entries: list[dict[str, Any]] = []
        for spell in agentic_spells:
            try:
                aug = _spell_to_augmentation(spell)
                safe_id = spell.id.replace("/", "_")
                content = yaml.dump(aug, default_flow_style=False, sort_keys=False)
                result.files.append(
                    BoundFile(
                        relative_path=f"augmentations/{safe_id}.yaml",
                        content=content,
                        description=f"Augmentation prompt for {spell.id}",
                    )
                )
                augmentation_entries.append(
                    {
                        "id": spell.id,
                        "file": f"augmentations/{safe_id}.yaml",
                    }
                )
            except Exception as e:
                result.warnings.append(f"Failed to bind augmentation '{spell.id}': {e}")

        # Generate manifest
        manifest = {
            "grimoire": repo.manifest.name,
            "version": repo.manifest.version,
            "tools": tool_entries,
            "augmentations": augmentation_entries,
        }
        result.files.append(
            BoundFile(
                relative_path="tool_manifest.json",
                content=json.dumps(manifest, indent=2),
                description="Wairu tool pack manifest",
            )
        )

        result.metadata["tool_count"] = len(tool_entries)
        result.metadata["augmentation_count"] = len(augmentation_entries)

        if not runes and not agentic_spells:
            result.warnings.append("No runes or agentic spells matched the filter criteria")

        return result
