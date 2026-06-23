"""Bearer-token authentication helpers for the Grimoire MCP server."""

from __future__ import annotations

from hmac import compare_digest
from typing import Any

AUTH_TOKEN_STATE_KEY = "grimoire_mcp_auth_token"


def require_bearer_token(request: Any) -> None:
    """FastAPI dependency that validates ``Authorization: Bearer <token>``."""
    from fastapi import HTTPException

    expected_token = getattr(request.app.state, AUTH_TOKEN_STATE_KEY, None)
    if not expected_token:
        raise HTTPException(status_code=503, detail="MCP auth token is not configured")

    authorization = request.headers.get("authorization", "")
    scheme, separator, credential = authorization.partition(" ")
    if separator and scheme.lower() == "bearer" and compare_digest(credential, expected_token):
        return

    raise HTTPException(
        status_code=401,
        detail="Missing or invalid bearer token",
        headers={"WWW-Authenticate": "Bearer"},
    )


__all__ = ["AUTH_TOKEN_STATE_KEY", "require_bearer_token"]
