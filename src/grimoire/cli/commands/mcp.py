"""``grimoire mcp`` commands for serving the MCP JSON-RPC endpoint."""

from __future__ import annotations

import os

import click

from grimoire.api import Grimoire
from grimoire.mcp_server import build_app


@click.group("mcp")
def mcp_group() -> None:
    """Serve Grimoire runes and spells over MCP JSON-RPC."""


@mcp_group.command("serve")
@click.option("--host", default="127.0.0.1", show_default=True, help="Bind host.")
@click.option("--port", default=8765, show_default=True, type=int, help="Bind port.")
@click.option(
    "--token",
    default=None,
    help="Bearer token. Defaults to GRIMOIRE_MCP_TOKEN.",
)
@click.option("--endpoint", default="/mcp", show_default=True, help="JSON-RPC endpoint path.")
@click.pass_context
def serve_cmd(
    ctx: click.Context,
    host: str,
    port: int,
    token: str | None,
    endpoint: str,
) -> None:
    """Start the Grimoire MCP HTTP server."""
    auth_token = token or os.environ.get("GRIMOIRE_MCP_TOKEN")
    if not auth_token:
        raise click.UsageError("Pass --token or set GRIMOIRE_MCP_TOKEN")

    try:
        import uvicorn
    except ImportError as exc:
        raise click.ClickException(
            "Install Grimoire with the 'mcp' extra to use grimoire mcp serve"
        ) from exc

    repo_path = ctx.obj.get("repo_path") if ctx.obj else "."
    grim = Grimoire(repo_path)
    app = build_app(grim, auth_token=auth_token, endpoint_path=endpoint)
    click.echo(f"Serving Grimoire MCP on http://{host}:{port}{endpoint}")
    uvicorn.run(app, host=host, port=port)


__all__ = ["mcp_group"]
