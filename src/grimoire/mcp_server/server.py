"""FastAPI application factory for Grimoire's MCP JSON-RPC endpoint."""

import json
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from grimoire.api import Grimoire
from grimoire.mcp_server.auth import AUTH_TOKEN_STATE_KEY, require_bearer_token
from grimoire.mcp_server.handlers import MCPRequestHandler


def build_app(
    grimoire: Grimoire,
    *,
    auth_token: str,
    endpoint_path: str = "/mcp",
    server_name: str = "grimoire",
    server_version: str | None = None,
) -> Any:
    """Build a FastAPI app that exposes Grimoire runes over MCP JSON-RPC."""
    if not auth_token:
        raise ValueError("auth_token is required for the Grimoire MCP server")

    try:
        from fastapi import Depends, FastAPI, Request
        from fastapi.responses import JSONResponse
    except ImportError as exc:  # pragma: no cover - depends on optional install extras
        raise RuntimeError(
            "Install Grimoire with the 'mcp' extra to use grimoire.mcp_server"
        ) from exc

    resolved_version = server_version or _package_version()
    handler = MCPRequestHandler(
        grimoire,
        server_name=server_name,
        server_version=resolved_version,
    )

    app = FastAPI(title="Grimoire MCP Server", version=resolved_version)
    setattr(app.state, AUTH_TOKEN_STATE_KEY, auth_token)
    app.state.grimoire_mcp_handler = handler

    async def _auth_dependency(request: Request) -> None:
        require_bearer_token(request)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "server": server_name}

    @app.post(endpoint_path)
    async def mcp_rpc(
        request: Request,
        _auth: None = Depends(_auth_dependency),
    ) -> JSONResponse:
        payload = await _json_payload(request)
        response = handler.handle_payload(payload)
        return JSONResponse(response)

    return app


async def _json_payload(request: Any) -> Any:
    try:
        return await request.json()
    except json.JSONDecodeError:
        return None


def _package_version() -> str:
    try:
        return version("grimoire")
    except PackageNotFoundError:
        return "unknown"


__all__ = ["build_app"]
