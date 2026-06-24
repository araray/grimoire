"""Federated event helpers for Grimoire.

This module adapts Grimoire rune metadata and MCP request/response surfaces to
the shared LLMCore ecosystem event envelope. It is opt-in and does not change
MCP dispatch or rune parsing behavior.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from typing import Any

from llmcore.observability.federation import EcosystemEvent, SourceSystem


def federate_mcp_request(
    request: Any,
    *,
    correlation_id: str | None = None,
    source_component: str = "mcp.server",
) -> EcosystemEvent:
    """Normalize a Grimoire MCP JSON-RPC request."""

    data = _mapping(request)
    method = _string_value(data.get("method")) or "unknown"
    request_id = _string_value(data.get("id"))

    return EcosystemEvent(
        event_id=_stable_event_id("grimoire-mcp-request", request_id, method),
        timestamp=datetime.now(UTC),
        source_system=SourceSystem.GRIMOIRE,
        source_component=source_component,
        category="mcp",
        event_type=f"mcp.request.{_method_label(method)}",
        severity="info",
        correlation_id=correlation_id,
        payload={
            "jsonrpc": data.get("jsonrpc"),
            "id": request_id,
            "method": method,
            "params": _json_safe(data.get("params") or {}),
        },
    )


def federate_mcp_response(
    response: Any,
    *,
    request_method: str | None = None,
    correlation_id: str | None = None,
    source_component: str = "mcp.server",
) -> EcosystemEvent:
    """Normalize a Grimoire MCP JSON-RPC response."""

    data = _mapping(response)
    error = data.get("error")
    has_error = error is not None
    method = _method_label(request_method or "unknown")
    request_id = _string_value(data.get("id"))
    status = "error" if has_error else "success"

    return EcosystemEvent(
        event_id=_stable_event_id("grimoire-mcp-response", request_id, method, status),
        timestamp=datetime.now(UTC),
        source_system=SourceSystem.GRIMOIRE,
        source_component=source_component,
        category="mcp",
        event_type=f"mcp.response.{method}.{status}",
        severity="error" if has_error else "info",
        correlation_id=correlation_id,
        payload={
            "jsonrpc": data.get("jsonrpc"),
            "id": request_id,
            "result": _json_safe(data.get("result")),
            "error": _json_safe(error),
        },
    )


def federate_mcp_tool_call(
    tool: dict[str, Any],
    arguments: dict[str, Any],
    *,
    result: dict[str, Any] | None = None,
    correlation_id: str | None = None,
    source_component: str = "mcp.executor",
) -> EcosystemEvent:
    """Normalize a Grimoire MCP tool-call attempt or result."""

    meta = tool.get("_meta") if isinstance(tool.get("_meta"), dict) else {}
    result_meta = result.get("_meta") if isinstance(result, dict) and isinstance(result.get("_meta"), dict) else {}
    call_status = _string_value(result_meta.get("grimoire.call_status")) or "requested"
    tool_name = _string_value(tool.get("name")) or _string_value(meta.get("grimoire.tool_name"))
    risk_level = _string_value(meta.get("grimoire.risk_level")) or "unknown"
    owasp_categories = _string_list(meta.get("grimoire.owasp_categories"))
    requires_approval = bool(meta.get("grimoire.requires_approval"))

    return EcosystemEvent(
        event_id=_stable_event_id("grimoire-mcp-tool-call", tool_name, call_status),
        timestamp=datetime.now(UTC),
        source_system=SourceSystem.GRIMOIRE,
        source_component=source_component,
        category="mcp",
        event_type=f"mcp.tool_call.{call_status}",
        severity=_severity_for_call_status(call_status),
        correlation_id=correlation_id,
        tags=["mcp_tool", f"risk:{risk_level}", *[f"owasp:{tag}" for tag in owasp_categories]],
        payload={
            "tool_name": tool_name,
            "arguments": _json_safe(arguments),
            "rune_id": _string_value(meta.get("grimoire.rune_id")),
            "command_name": _string_value(meta.get("grimoire.command_name")),
            "risk_level": risk_level,
            "owasp_categories": owasp_categories,
            "requires_approval": requires_approval,
            "execution_target": _string_value(meta.get("grimoire.execution_target")),
            "result": _json_safe(result),
        },
    )


def federate_rune_command(
    rune: Any,
    command: Any,
    *,
    correlation_id: str | None = None,
    source_component: str = "runes.registry",
) -> EcosystemEvent:
    """Normalize one Grimoire rune command contract."""

    rune_data = _mapping(rune)
    command_data = _mapping(command)
    rune_id = _string_value(rune_data.get("id")) or "unknown"
    command_name = _string_value(command_data.get("name")) or "unknown"
    risk_level = (
        _string_value(command_data.get("risk_level"))
        or _string_value(rune_data.get("risk_level"))
        or "unknown"
    )
    owasp_categories = _string_list(
        command_data.get("owasp_categories") or rune_data.get("owasp_categories")
    )
    requires_approval = bool(command_data.get("requires_approval")) or bool(
        rune_data.get("requires_approval")
    )

    return EcosystemEvent(
        event_id=_stable_event_id("grimoire-rune-command", rune_id, command_name),
        timestamp=datetime.now(UTC),
        source_system=SourceSystem.GRIMOIRE,
        source_component=source_component,
        category="rune",
        event_type="rune.command_registered",
        severity="warning" if requires_approval or risk_level == "high" else "info",
        correlation_id=correlation_id,
        tags=[
            f"risk:{risk_level}",
            *[str(tag) for tag in (rune_data.get("tags") or [])],
            *[f"owasp:{category}" for category in owasp_categories],
        ],
        payload={
            "rune_id": rune_id,
            "rune_name": _string_value(rune_data.get("name")),
            "command_name": command_name,
            "summary": _string_value(command_data.get("summary")),
            "risk_level": risk_level,
            "owasp_categories": owasp_categories,
            "requires_approval": requires_approval,
            "permissions": _json_safe(rune_data.get("permissions") or []),
            "side_effects": _json_safe(command_data.get("side_effects") or []),
            "execution_target": _string_value(command_data.get("execution_target")),
            "content_hash": _string_value(rune_data.get("content_hash")),
            "source_path": _string_value(rune_data.get("source_path")),
        },
    )


def federate_rune_commands(
    rune: Any,
    *,
    correlation_id: str | None = None,
    source_component: str = "runes.registry",
) -> list[EcosystemEvent]:
    """Normalize every command in a Grimoire rune contract."""

    commands = getattr(rune, "commands", None)
    if commands is None and isinstance(rune, dict):
        commands = rune.get("commands")
    if not isinstance(commands, Iterable):
        return []
    return [
        federate_rune_command(
            rune,
            command,
            correlation_id=correlation_id,
            source_component=source_component,
        )
        for command in commands
    ]


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        mapped = model_dump(mode="json")
        if isinstance(mapped, dict):
            return dict(mapped)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        mapped = to_dict()
        if isinstance(mapped, dict):
            return dict(mapped)
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    return {}


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if is_dataclass(value) and not isinstance(value, type):
        return _json_safe(asdict(value))
    enum_value = getattr(value, "value", None)
    if enum_value is not None:
        return str(enum_value)
    return str(value)


def _string_value(value: Any) -> str | None:
    if value is None:
        return None
    enum_value = getattr(value, "value", None)
    if enum_value is not None:
        return str(enum_value)
    return str(value)


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value]
    return [str(value)]


def _method_label(method: str) -> str:
    return method.replace("/", "_").replace(".", "_")


def _stable_event_id(prefix: str, *parts: Any) -> str:
    normalized = [str(part) for part in parts if part is not None and str(part) != ""]
    return "-".join([prefix, *normalized]) if normalized else prefix


def _severity_for_call_status(status: str) -> str:
    if status in {"failed", "blocked", "unavailable"}:
        return "error"
    if status == "pending_approval":
        return "warning"
    return "info"


__all__ = [
    "EcosystemEvent",
    "SourceSystem",
    "federate_mcp_request",
    "federate_mcp_response",
    "federate_mcp_tool_call",
    "federate_rune_command",
    "federate_rune_commands",
]
