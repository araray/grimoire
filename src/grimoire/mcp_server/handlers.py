"""JSON-RPC method dispatch for the Grimoire MCP server."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from grimoire.api import Grimoire
from grimoire.mcp_server.executor import MCPToolExecutor
from grimoire.mcp_server.models import JSONRPCError, JSONRPCId, JSONRPCRequest, JSONRPCResponse

logger = logging.getLogger(__name__)

DEFAULT_PROTOCOL_VERSION = "2024-11-05"
ERROR_INVALID_REQUEST = -32600
ERROR_METHOD_NOT_FOUND = -32601
ERROR_INVALID_PARAMS = -32602
ERROR_INTERNAL = -32603


@dataclass(slots=True)
class MCPHandlerError(Exception):
    """Error raised by MCP method handlers."""

    code: int
    message: str
    data: Any | None = None


class MCPRequestHandler:
    """Dispatch JSON-RPC requests to the supported MCP methods."""

    def __init__(
        self,
        grimoire: Grimoire,
        *,
        server_name: str = "grimoire",
        server_version: str = "unknown",
        protocol_version: str = DEFAULT_PROTOCOL_VERSION,
        tool_executor: MCPToolExecutor | None = None,
    ) -> None:
        self._grimoire = grimoire
        self._server_name = server_name
        self._server_version = server_version
        self._protocol_version = protocol_version
        self._tool_executor = tool_executor or MCPToolExecutor(callables={})

    def handle_payload(self, payload: Any) -> dict[str, Any]:
        """Handle one JSON-RPC request payload and return a response dict."""
        if not isinstance(payload, dict):
            return self._error_response(
                None,
                ERROR_INVALID_REQUEST,
                "JSON-RPC request must be an object",
            )

        request_id: JSONRPCId = payload.get("id")
        try:
            request = JSONRPCRequest.model_validate(payload)
        except ValidationError as exc:
            return self._error_response(
                request_id,
                ERROR_INVALID_REQUEST,
                "Invalid JSON-RPC request",
                data=exc.errors(include_url=False, include_context=False),
            )

        try:
            result = self._dispatch(request.method, request.params)
        except MCPHandlerError as exc:
            return self._error_response(request.id, exc.code, exc.message, data=exc.data)
        except Exception:  # pragma: no cover - defensive boundary for service mode
            logger.exception("Unhandled MCP request failure for method %s", request.method)
            return self._error_response(request.id, ERROR_INTERNAL, "Internal error")

        response = JSONRPCResponse(id=request.id, result=result)
        return response.model_dump(exclude_none=True)

    def _dispatch(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "initialize":
            return self._handle_initialize(params)
        if method == "tools/list":
            return self._handle_tools_list(params)
        if method == "tools/call":
            return self._handle_tools_call(params)
        if method == "prompts/list":
            return self._handle_prompts_list(params)
        if method == "prompts/get":
            return self._handle_prompts_get(params)
        raise MCPHandlerError(ERROR_METHOD_NOT_FOUND, f"Unsupported MCP method: {method}")

    def _handle_initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        requested_protocol = params.get("protocolVersion")
        protocol_version = (
            requested_protocol if isinstance(requested_protocol, str) else self._protocol_version
        )
        return {
            "protocolVersion": protocol_version,
            "capabilities": {
                "tools": {
                    "listChanged": False,
                },
                "prompts": {
                    "listChanged": False,
                },
            },
            "serverInfo": {
                "name": self._server_name,
                "version": self._server_version,
            },
        }

    def _handle_tools_list(self, params: dict[str, Any]) -> dict[str, Any]:
        rune_ids = _optional_string_list(params, "rune_ids", "runeIds")
        tags = _optional_string_list(params, "tags")

        manifest = self._grimoire.to_mcp_tool_manifest(rune_ids=rune_ids, tags=tags)
        return {
            "tools": manifest["tools"],
            "_meta": {
                "grimoire.schema_version": manifest["schema_version"],
            },
        }

    def _handle_tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
        tool_name = _required_string(params, "name")
        arguments = params.get("arguments", {})
        if not isinstance(arguments, dict):
            raise MCPHandlerError(
                ERROR_INVALID_PARAMS,
                "Parameter 'arguments' must be an object",
            )

        tool = self._tool_by_name(tool_name)
        if tool is None:
            raise MCPHandlerError(ERROR_INVALID_PARAMS, f"Unknown MCP tool: {tool_name}")
        _validate_tool_arguments(tool, arguments)
        return self._tool_executor.call_tool(tool, arguments)

    def _handle_prompts_list(self, params: dict[str, Any]) -> dict[str, Any]:
        tags = _optional_string_list(params, "tags")
        prompts = [_spell_to_mcp_prompt(spell) for spell in self._grimoire.list_spells(tags=tags)]
        return {
            "prompts": prompts,
            "_meta": {
                "grimoire.schema_version": "grimoire.mcp_prompt_manifest.v1",
            },
        }

    def _handle_prompts_get(self, params: dict[str, Any]) -> dict[str, Any]:
        name = _required_string(params, "name")
        arguments = params.get("arguments", {})
        if not isinstance(arguments, dict):
            raise MCPHandlerError(
                ERROR_INVALID_PARAMS,
                "Parameter 'arguments' must be an object",
            )
        strict = params.get("strict", True)
        if not isinstance(strict, bool):
            raise MCPHandlerError(ERROR_INVALID_PARAMS, "Parameter 'strict' must be a boolean")

        try:
            spell = self._grimoire.get_spell(name)
            conjured = self._grimoire.conjure_spell(name, variables=arguments, strict=strict)
        except Exception as exc:
            raise MCPHandlerError(ERROR_INVALID_PARAMS, str(exc)) from exc

        return {
            "description": spell.description or spell.name,
            "messages": [
                {
                    "role": message["role"],
                    "content": {
                        "type": "text",
                        "text": message["content"],
                    },
                }
                for message in conjured.to_messages("openai")
            ],
            "_meta": {
                "grimoire.spell_id": spell.id,
                "grimoire.spell_version": spell.version,
                "grimoire.content_hash": spell.content_hash,
                "grimoire.tags": list(spell.tags),
                "grimoire.provenance": conjured.provenance.model_dump(mode="json")
                if conjured.provenance is not None
                else None,
            },
        }

    def _tool_by_name(self, tool_name: str) -> dict[str, Any] | None:
        manifest = self._grimoire.to_mcp_tool_manifest()
        for tool in manifest["tools"]:
            if tool.get("name") == tool_name:
                return tool
        return None

    def _error_response(
        self,
        request_id: JSONRPCId,
        code: int,
        message: str,
        *,
        data: Any | None = None,
    ) -> dict[str, Any]:
        response = JSONRPCResponse(
            id=request_id,
            error=JSONRPCError(code=code, message=message, data=data),
        )
        return response.model_dump(exclude_none=True)


def _optional_string_list(params: dict[str, Any], *names: str) -> list[str] | None:
    for name in names:
        if name not in params:
            continue
        value = params[name]
        if value is None:
            return None
        if _is_string_sequence(value):
            return list(value)
        raise MCPHandlerError(
            ERROR_INVALID_PARAMS,
            f"Parameter {name!r} must be a list of strings",
        )
    return None


def _required_string(params: dict[str, Any], name: str) -> str:
    value = params.get(name)
    if isinstance(value, str) and value:
        return value
    raise MCPHandlerError(ERROR_INVALID_PARAMS, f"Parameter {name!r} must be a string")


def _is_string_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, str | bytes) and all(
        isinstance(item, str) for item in value
    )


def _spell_to_mcp_prompt(spell: Any) -> dict[str, Any]:
    return {
        "name": spell.id,
        "description": spell.description or spell.name,
        "arguments": [
            {
                "name": name,
                "description": spec.ask or spec.description or "",
                "required": bool(spec.required),
            }
            for name, spec in spell.variables.items()
        ],
        "_meta": {
            "grimoire.spell_id": spell.id,
            "grimoire.spell_name": spell.name,
            "grimoire.spell_version": spell.version,
            "grimoire.tags": list(spell.tags),
            "grimoire.content_hash": spell.content_hash,
        },
    }


def _validate_tool_arguments(tool: dict[str, Any], arguments: dict[str, Any]) -> None:
    schema = tool.get("inputSchema")
    if not isinstance(schema, dict):
        return

    required = schema.get("required", [])
    if isinstance(required, list):
        for name in required:
            if isinstance(name, str) and name not in arguments:
                raise MCPHandlerError(
                    ERROR_INVALID_PARAMS,
                    f"Missing required argument {name!r} for tool {tool.get('name')}",
                )

    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        return
    for name, value in arguments.items():
        spec = properties.get(name)
        if not isinstance(spec, dict):
            continue
        expected = spec.get("type")
        if isinstance(expected, list):
            expected_types = [str(item) for item in expected]
        elif isinstance(expected, str):
            expected_types = [expected]
        else:
            continue
        if not _argument_matches_type(value, expected_types):
            expected_label = "|".join(expected_types)
            raise MCPHandlerError(
                ERROR_INVALID_PARAMS,
                (
                    f"Argument {name!r} for tool {tool.get('name')} must be "
                    f"{expected_label}"
                ),
            )


def _argument_matches_type(value: Any, expected_types: list[str]) -> bool:
    if "null" in expected_types and value is None:
        return True
    checks = {
        "string": lambda item: isinstance(item, str),
        "boolean": lambda item: isinstance(item, bool),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, int | float) and not isinstance(item, bool),
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
    }
    return any(checks[kind](value) for kind in expected_types if kind in checks)


__all__ = [
    "DEFAULT_PROTOCOL_VERSION",
    "ERROR_INTERNAL",
    "ERROR_INVALID_PARAMS",
    "ERROR_INVALID_REQUEST",
    "ERROR_METHOD_NOT_FOUND",
    "MCPHandlerError",
    "MCPRequestHandler",
]
