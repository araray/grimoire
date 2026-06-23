"""JSON-RPC method dispatch for the Grimoire MCP server."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from grimoire.api import Grimoire
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
    ) -> None:
        self._grimoire = grimoire
        self._server_name = server_name
        self._server_version = server_version
        self._protocol_version = protocol_version

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


def _is_string_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, str | bytes) and all(
        isinstance(item, str) for item in value
    )


__all__ = [
    "DEFAULT_PROTOCOL_VERSION",
    "ERROR_INTERNAL",
    "ERROR_INVALID_PARAMS",
    "ERROR_INVALID_REQUEST",
    "ERROR_METHOD_NOT_FOUND",
    "MCPHandlerError",
    "MCPRequestHandler",
]
