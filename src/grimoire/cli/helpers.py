# src/grimoire/cli/helpers.py
"""Shared CLI helpers for loading repos, formatting, and output."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click
import yaml

from grimoire.store.repo import GrimoireRepo


def load_repo(ctx: click.Context) -> GrimoireRepo:
    """Load the grimoire repo from the CLI context."""
    repo_path = ctx.obj["repo_path"]
    try:
        return GrimoireRepo.load(repo_path)
    except Exception as e:
        click.secho(f"Error loading grimoire repo at '{repo_path}': {e}", fg="red", err=True)
        ctx.exit(1)
        raise SystemExit(1) from None  # Unreachable, but satisfies type checker


def load_vars_from_files(vars_files: list[str]) -> dict[str, Any]:
    """Load and merge variables from YAML files."""
    merged: dict[str, Any] = {}
    for vf in vars_files:
        try:
            data = yaml.safe_load(Path(vf).read_text(encoding="utf-8"))
            if isinstance(data, dict):
                merged.update(data)
        except Exception as e:
            click.secho(f"Warning: failed to load vars from '{vf}': {e}", fg="yellow", err=True)
    return merged


def write_output(ctx: click.Context, content: str) -> None:
    """Write content to --out file or stdout."""
    output_path = ctx.obj.get("output_path")
    if output_path:
        Path(output_path).write_text(content, encoding="utf-8")
        click.secho(f"Written to {output_path}", fg="green", err=True)
    else:
        click.echo(content)


def format_table(headers: list[str], rows: list[list[str]]) -> str:
    """Format a simple text table."""
    if not rows:
        return "(empty)"

    # Calculate column widths
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(widths):
                widths[i] = max(widths[i], len(cell))

    # Format
    sep = "  "
    header_line = sep.join(h.ljust(w) for h, w in zip(headers, widths, strict=False))
    divider = sep.join("-" * w for w in widths)
    data_lines = [
        sep.join(cell.ljust(w) for cell, w in zip(row, widths, strict=False))
        for row in rows
    ]

    return "\n".join([header_line, divider, *data_lines])
