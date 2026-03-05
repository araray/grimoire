# src/grimoire/cli/helpers.py
"""Shared CLI helpers for loading repos, formatting, and output."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import click
import yaml

from grimoire.models import VariableSpec, VariableType
from grimoire.store.repo import GrimoireRepo

logger = logging.getLogger(__name__)


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


def load_profiles(
    repo: GrimoireRepo,
    profile_names: list[str],
) -> dict[str, Any]:
    """
    Load and merge profile overlays from the grimoire's profiles/ directory.

    Each profile name is resolved against the repo's profile_paths.
    Files are loaded as YAML and merged in order (last wins).

    Args:
        repo: Loaded grimoire repository.
        profile_names: Profile names (e.g. ``["user/aaiv", "env/prod"]``).

    Returns:
        Merged profile variables dict.
    """
    if not profile_names:
        return {}

    merged: dict[str, Any] = {}

    for name in profile_names:
        found = False
        for profile_dir_str in repo.manifest.profile_paths:
            profile_dir = repo.root / profile_dir_str
            # Try name as-is, then with .yaml extension
            candidates = [
                profile_dir / f"{name}.yaml",
                profile_dir / f"{name}.yml",
                profile_dir / name,
            ]
            for candidate in candidates:
                if candidate.is_file():
                    try:
                        data = yaml.safe_load(candidate.read_text(encoding="utf-8"))
                        if isinstance(data, dict):
                            merged.update(data)
                            logger.debug("Loaded profile '%s' from %s", name, candidate)
                            found = True
                            break
                    except Exception as e:
                        click.secho(
                            f"Warning: failed to load profile '{name}' from {candidate}: {e}",
                            fg="yellow",
                            err=True,
                        )
            if found:
                break

        if not found:
            click.secho(f"Warning: profile '{name}' not found", fg="yellow", err=True)

    return merged


def prompt_for_variable(name: str, spec: VariableSpec) -> Any:
    """
    Interactively prompt for a variable value with type validation.

    Args:
        name: Variable name.
        spec: Variable specification (type, constraints, ask text).

    Returns:
        Validated value in the correct Python type.
    """
    prompt_text = spec.ask or f"Enter value for '{name}'"
    type_hint = f" ({spec.type.value})"

    if spec.type == VariableType.BOOLEAN:
        default = spec.default if spec.default is not None else None
        return click.confirm(prompt_text, default=default)

    if spec.type == VariableType.CHOICE and spec.choices:
        click.echo(f"{prompt_text}:")
        for i, choice in enumerate(spec.choices, 1):
            click.echo(f"  {i}. {choice}")
        while True:
            raw = click.prompt("Choice number", type=int)
            if 1 <= raw <= len(spec.choices):
                return spec.choices[raw - 1]
            click.secho(f"  Must be 1-{len(spec.choices)}", fg="yellow")

    if spec.type == VariableType.MULTILINE:
        click.echo(f"{prompt_text}{type_hint} (enter blank line to finish):")
        lines: list[str] = []
        while True:
            line = click.prompt("", default="", show_default=False)
            if line == "":
                break
            lines.append(line)
        return "\n".join(lines)

    if spec.type in (VariableType.INTEGER, VariableType.FLOAT):
        type_cls = int if spec.type == VariableType.INTEGER else float
        while True:
            raw_val = click.prompt(f"{prompt_text}{type_hint}", type=type_cls)
            if spec.min_value is not None and raw_val < spec.min_value:
                click.secho(f"  Must be >= {spec.min_value}", fg="yellow")
                continue
            if spec.max_value is not None and raw_val > spec.max_value:
                click.secho(f"  Must be <= {spec.max_value}", fg="yellow")
                continue
            return raw_val

    if spec.type == VariableType.LIST:
        click.echo(f"{prompt_text} (comma-separated):")
        raw_str = click.prompt("", default="", show_default=False)
        return [item.strip() for item in raw_str.split(",") if item.strip()]

    if spec.type == VariableType.JSON:
        import json as _json

        click.echo(f"{prompt_text} (JSON value):")
        while True:
            raw_json = click.prompt("", default="", show_default=False)
            try:
                return _json.loads(raw_json)
            except _json.JSONDecodeError as exc:
                click.secho(f"  Invalid JSON: {exc}", fg="yellow")

    if spec.type == VariableType.PATH:
        from pathlib import Path as _Path

        while True:
            raw_path = click.prompt(f"{prompt_text} (filesystem path)")
            p = _Path(raw_path)
            if not p.exists():
                click.secho(f"  Path does not exist: {raw_path}", fg="yellow")
                if click.confirm("  Use anyway?", default=False):
                    return raw_path
            else:
                return str(p)

    # Default: string
    return click.prompt(f"{prompt_text}{type_hint}")


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
        sep.join(cell.ljust(w) for cell, w in zip(row, widths, strict=False)) for row in rows
    ]

    return "\n".join([header_line, divider, *data_lines])
