"""MCP server support for exposing Grimoire runes as tools."""

from grimoire.mcp_server.executor import MCPToolExecutor
from grimoire.mcp_server.handlers import MCPHandlerError, MCPRequestHandler
from grimoire.mcp_server.models import JSONRPCError, JSONRPCRequest, JSONRPCResponse
from grimoire.mcp_server.server import build_app

__all__ = [
    "JSONRPCError",
    "JSONRPCRequest",
    "JSONRPCResponse",
    "MCPHandlerError",
    "MCPRequestHandler",
    "MCPToolExecutor",
    "build_app",
]
