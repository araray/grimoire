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
import re
from collections.abc import Iterable, Mapping
from typing import Any

import yaml

from grimoire.bind.base import Binder, BindFormat, BindResult, BindTarget, BoundFile
from grimoire.models import CommandSpec, ParamSpec, Permission, RiskLevel, RuneSpec, Spell
from grimoire.runes.schema import command_parameters_schema
from grimoire.store.repo import GrimoireRepo

logger = logging.getLogger(__name__)


_SLUG_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def _get_field(source: Any, name: str, default: Any = None) -> Any:
    if isinstance(source, Mapping):
        return source.get(name, default)
    return getattr(source, name, default)


def _slug(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    if not text:
        text = fallback
    return _SLUG_RE.sub("_", text).strip("._-") or fallback


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Iterable) and not isinstance(value, Mapping):
        return [str(item) for item in value if item is not None and str(item)]
    return [str(value)]


def _as_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _risk_level(value: Any) -> RiskLevel:
    if isinstance(value, RiskLevel):
        return value
    if value is None:
        return RiskLevel.LOW
    try:
        return RiskLevel(str(value).strip().lower())
    except ValueError:
        return RiskLevel.LOW


def _permissions(value: Any) -> list[Permission]:
    permissions: list[Permission] = []
    for item in _as_str_list(value):
        try:
            permissions.append(Permission(item))
        except ValueError:
            logger.debug("Ignoring unknown wairu tool permission %r", item)
    return permissions


def _schema_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if value is None:
        return {}
    return {"type": str(value)}


def _parameter_items(parameters: Any) -> list[tuple[str, Mapping[str, Any], bool]]:
    if not isinstance(parameters, Mapping):
        return []

    if isinstance(parameters.get("properties"), Mapping):
        required_names = set(_as_str_list(parameters.get("required")))
        return [
            (str(name), _schema_mapping(schema), str(name) in required_names)
            for name, schema in parameters["properties"].items()
        ]

    return [
        (str(name), _schema_mapping(schema), _as_bool(_schema_mapping(schema).get("required")))
        for name, schema in parameters.items()
    ]


def _param_spec(name: str, schema: Mapping[str, Any], required: bool) -> ParamSpec:
    enum = schema.get("enum")
    return ParamSpec(
        name=name,
        type=str(schema.get("type") or "string"),
        required=required,
        default=schema.get("default"),
        description=schema.get("description"),
        minimum=_as_number(schema.get("minimum")),
        maximum=_as_number(schema.get("maximum")),
        enum=[str(item) for item in enum] if isinstance(enum, list) else None,
        pattern=str(schema["pattern"]) if schema.get("pattern") is not None else None,
    )


def wairu_tool_to_rune(
    tool: Any,
    *,
    plugin_name: str = "wairu",
    rune_id_prefix: str = "wairu/plugins",
    version: str = "1.0.0",
    tags: list[str] | None = None,
) -> RuneSpec:
    """
    Convert a Wairu-style tool definition into a canonical rune contract.

    The input may be a Wairu ``ToolDefinition`` dataclass, a dict produced by a
    plugin manifest, or any object exposing compatible attributes. This keeps
    grimoire independent from wairu while still giving runtimes a shared
    contract surface for prompt/tool introspection.
    """
    tool_name = str(_get_field(tool, "name", "tool"))
    plugin_slug = _slug(plugin_name, "wairu")
    tool_slug = _slug(tool_name, "tool")
    prefix = rune_id_prefix.strip("/") or "wairu/plugins"
    risk = _risk_level(_get_field(tool, "risk_level", None))
    requires_approval = _as_bool(_get_field(tool, "requires_approval", False))
    owasp_categories = list(
        dict.fromkeys(
            [
                *_as_str_list(_get_field(tool, "owasp_categories", [])),
                *_as_str_list(_get_field(tool, "owasp", [])),
            ]
        )
    )

    params = [
        _param_spec(name, schema, required)
        for name, schema, required in _parameter_items(_get_field(tool, "parameters", {}))
    ]
    description = _get_field(tool, "description", None)
    command = CommandSpec(
        name=tool_name,
        summary=description,
        params=params,
        side_effects=_as_str_list(_get_field(tool, "side_effects", [])),
        risk_level=risk,
        owasp_categories=owasp_categories,
        requires_approval=requires_approval,
        execution_target=_get_field(tool, "execution_target", None),
    )

    owasp_tags = [f"owasp:{tag}" for tag in owasp_categories]
    rune_tags = [
        "wairu",
        "plugin",
        f"plugin:{plugin_slug}",
        *_as_str_list(tags),
        *_as_str_list(_get_field(tool, "tags", [])),
        *owasp_tags,
    ]

    return RuneSpec(
        id=f"{prefix}/{plugin_slug}/{tool_slug}",
        name=f"{plugin_name}.{tool_name}",
        version=version,
        description=description,
        tags=list(dict.fromkeys(rune_tags)),
        owasp_categories=owasp_categories,
        platforms=_as_str_list(_get_field(tool, "platforms", ["any"])) or ["any"],
        risk_level=risk,
        permissions=_permissions(_get_field(tool, "permissions", [])),
        requires_approval=requires_approval,
        commands=[command],
        mappings={
            "wairu.plugin": plugin_name,
            "wairu.tool": tool_name,
            "wairu.qualified_tool": f"{plugin_name}.{tool_name}",
        },
    )


def wairu_tools_to_runes(
    tools: Iterable[Any],
    *,
    plugin_name: str = "wairu",
    rune_id_prefix: str = "wairu/plugins",
    version: str = "1.0.0",
    tags: list[str] | None = None,
) -> list[RuneSpec]:
    """Convert an iterable of Wairu-style tools into rune contracts."""
    return [
        wairu_tool_to_rune(
            tool,
            plugin_name=plugin_name,
            rune_id_prefix=rune_id_prefix,
            version=version,
            tags=tags,
        )
        for tool in tools
    ]


def register_wairu_plugin_tools(
    target: Any,
    tools: Iterable[Any],
    *,
    plugin_name: str = "wairu",
    rune_id_prefix: str = "wairu/plugins",
    version: str = "1.0.0",
    tags: list[str] | None = None,
    overwrite: bool = True,
) -> list[RuneSpec]:
    """
    Register Wairu plugin tools as in-memory runes on a Grimoire facade or repo.

    This is intentionally an in-memory runtime helper. Persistent rune authoring
    should still go through Grimoire's on-disk rune files or a future public rune
    write API.
    """
    runes = wairu_tools_to_runes(
        tools,
        plugin_name=plugin_name,
        rune_id_prefix=rune_id_prefix,
        version=version,
        tags=tags,
    )

    repo = _get_field(target, "_repo", target)
    registry = _get_field(repo, "_runes", None)
    if not isinstance(registry, dict):
        raise TypeError("target must be a Grimoire facade or GrimoireRepo-like object")

    for rune in runes:
        if not overwrite and rune.id in registry:
            raise ValueError(f"Rune already registered: {rune.id}")
        registry[rune.id] = rune

    engine = _get_field(target, "_engine", None)
    engine_runes = _get_field(engine, "_runes", None)
    if isinstance(engine_runes, dict):
        for rune in runes:
            engine_runes[rune.id] = rune

    # 0.4.0: a Grimoire facade memoizes catalog/tool_schemas — invalidate so
    # freshly registered runtime runes are immediately visible (guarded:
    # bare GrimoireRepo targets have no caches).
    invalidate = getattr(target, "invalidate_caches", None)
    if callable(invalidate):
        invalidate()

    return runes


def _rune_to_tool_pack(rune: RuneSpec) -> dict[str, Any]:
    """
    Convert a rune contract to a wairu tool pack entry.

    Maps rune commands to wairu's tool definition format with
    risk/approval metadata.
    """
    tools: list[dict[str, Any]] = []

    for cmd in rune.commands:
        tool: dict[str, Any] = {
            "name": cmd.name,
            "description": cmd.summary or f"{rune.name}: {cmd.name}",
            "risk_level": (cmd.risk_level or rune.risk_level).value
            if (cmd.risk_level or rune.risk_level)
            else "low",
            "owasp_categories": cmd.owasp_categories or rune.owasp_categories,
            "requires_approval": cmd.requires_approval or rune.requires_approval,
            "side_effects": cmd.side_effects,
            "parameters": command_parameters_schema(cmd),
        }

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
        "owasp_categories": rune.owasp_categories,
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

        return result.compute_hash()
