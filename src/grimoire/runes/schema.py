"""JSON Schema adapters for rune command contracts."""

from __future__ import annotations

from typing import Any

from grimoire.models import CommandSpec, ParamSpec, RuneSpec

_JSON_SCHEMA_TYPE_ALIASES = {
    "bool": "boolean",
}


def param_to_json_schema(param: ParamSpec) -> dict[str, Any]:
    """Convert a rune parameter to a JSON Schema property schema."""
    schema: dict[str, Any] = {
        "type": _JSON_SCHEMA_TYPE_ALIASES.get(param.type, param.type or "string")
    }
    if param.description:
        schema["description"] = param.description
    if param.enum:
        schema["enum"] = param.enum
    if param.pattern:
        schema["pattern"] = param.pattern
    if param.minimum is not None:
        schema["minimum"] = param.minimum
    if param.maximum is not None:
        schema["maximum"] = param.maximum
    if param.default is not None:
        schema["default"] = param.default
    return schema


def command_parameters_schema(cmd: CommandSpec) -> dict[str, Any]:
    """Convert a rune command's parameters to an object JSON Schema."""
    properties: dict[str, Any] = {}
    required: list[str] = []

    for param in cmd.params:
        properties[param.name] = param_to_json_schema(param)
        if param.required:
            required.append(param.name)

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required
    return schema


def command_to_openai_tool_schema(
    cmd: CommandSpec,
    rune: RuneSpec,
    *,
    function_name: str | None = None,
) -> dict[str, Any]:
    """Convert a rune command to an OpenAI-compatible tool/function schema."""
    return {
        "type": "function",
        "function": {
            "name": function_name or f"{rune.id.replace('/', '__')}__{cmd.name}",
            "description": cmd.summary or f"{rune.name}: {cmd.name}",
            "parameters": command_parameters_schema(cmd),
        },
    }


__all__ = [
    "command_parameters_schema",
    "command_to_openai_tool_schema",
    "param_to_json_schema",
]
