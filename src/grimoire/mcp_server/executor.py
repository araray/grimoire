"""Conservative MCP tool-call execution boundary for Grimoire runes."""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

ToolCallable = Callable[..., Any]


@dataclass(slots=True)
class MCPToolExecutor:
    """Execute MCP tool calls through an explicit in-memory callable registry.

    Grimoire owns rune metadata, not host execution policy. The executor
    therefore only runs callables that the host application explicitly
    registered. High-risk or approval-gated runes return a pending approval
    response instead of executing.
    """

    callables: Mapping[str, ToolCallable]
    allowed_tools: set[str] | None = None

    def call_tool(self, tool: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
        """Run one MCP tool call or return a structured non-execution result."""
        tool_name = str(tool.get("name") or "")
        meta = tool.get("_meta") if isinstance(tool.get("_meta"), dict) else {}
        if not tool_name:
            return _error_result("Tool manifest entry has no name")

        if self.allowed_tools is not None and tool_name not in self.allowed_tools:
            return _error_result(
                f"Tool is not allowlisted: {tool_name}",
                status="blocked",
                meta=meta,
            )

        execution_target = str(meta.get("grimoire.execution_target") or "local")
        if execution_target == "remote":
            return _error_result(
                "Remote execution targets are not callable through the Grimoire MCP server",
                status="blocked",
                meta=meta,
            )

        if bool(meta.get("grimoire.requires_approval")):
            return {
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"Approval required before executing {tool_name} "
                            f"(risk={meta.get('grimoire.risk_level', 'unknown')})."
                        ),
                    }
                ],
                "isError": False,
                "_meta": {
                    **_result_meta(meta),
                    "grimoire.call_status": "pending_approval",
                    "grimoire.pending_tool": tool_name,
                    "grimoire.arguments": arguments,
                },
            }

        implementation = self._implementation_for(tool_name, meta)
        if implementation is None:
            return _error_result(
                f"No callable registered for MCP tool: {tool_name}",
                status="unavailable",
                meta=meta,
            )

        try:
            result = implementation(**arguments)
        except TypeError:
            try:
                result = implementation(arguments)
            except Exception as exc:  # pragma: no cover - defensive fallback
                return _error_result(str(exc), status="failed", meta=meta)
        except Exception as exc:
            return _error_result(str(exc), status="failed", meta=meta)

        if inspect.isawaitable(result):
            return _error_result(
                "Async MCP tool callables are not supported by this sync executor",
                status="failed",
                meta=meta,
            )

        return {
            "content": [{"type": "text", "text": _result_text(result)}],
            "isError": False,
            "_meta": {
                **_result_meta(meta),
                "grimoire.call_status": "executed",
            },
        }

    def _implementation_for(
        self,
        tool_name: str,
        meta: dict[str, Any],
    ) -> ToolCallable | None:
        rune_id = str(meta.get("grimoire.rune_id") or "")
        command_name = str(meta.get("grimoire.command_name") or "")
        keys = [tool_name]
        if rune_id and command_name:
            keys.append(f"{rune_id}:{command_name}")
        for key in keys:
            implementation = self.callables.get(key)
            if implementation is not None:
                return implementation
        return None


def _error_result(
    message: str,
    *,
    status: str = "failed",
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": message}],
        "isError": True,
        "_meta": {
            **_result_meta(meta or {}),
            "grimoire.call_status": status,
        },
    }


def _result_meta(meta: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "grimoire.rune_id",
        "grimoire.command_name",
        "grimoire.risk_level",
        "grimoire.requires_approval",
        "grimoire.owasp_categories",
        "grimoire.execution_target",
        "grimoire.tool_name",
    )
    return {key: meta[key] for key in keys if key in meta}


def _result_text(result: Any) -> str:
    if isinstance(result, str):
        return result
    try:
        return json.dumps(result, indent=2, sort_keys=True, default=str)
    except TypeError:
        return str(result)


__all__ = ["MCPToolExecutor", "ToolCallable"]
