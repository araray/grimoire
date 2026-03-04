# src/grimoire/cli/commands/rune.py
"""``grimoire rune`` — skills manager: discover and validate rune contracts."""

from __future__ import annotations

import json

import click

from grimoire.cli.helpers import format_table, load_repo
from grimoire.validate.rules import validate_rune as validate_rune_rule


@click.group("rune")
def rune_group() -> None:
    """Discover and manage rune contracts (skill definitions)."""


@rune_group.command("list")
@click.option("--tags", help="Filter by comma-separated tags.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.pass_context
def rune_list(ctx: click.Context, tags: str | None, as_json: bool) -> None:
    """List all runes in the grimoire."""
    repo = load_repo(ctx)
    tag_list = [t.strip() for t in tags.split(",")] if tags else None
    runes = repo.list_runes(tags=tag_list)

    if as_json:
        data = [
            {
                "id": r.id,
                "name": r.name,
                "version": r.version,
                "tags": r.tags,
                "risk": r.risk_level.value,
                "commands": [c.name for c in r.commands],
            }
            for r in runes
        ]
        click.echo(json.dumps(data, indent=2))
        return

    if not runes:
        click.echo("No runes found.")
        return

    rows = [
        [
            r.id,
            r.name,
            r.risk_level.value,
            str(len(r.commands)),
            ", ".join(r.tags),
        ]
        for r in runes
    ]
    click.echo(format_table(["ID", "Name", "Risk", "Cmds", "Tags"], rows))


@rune_group.command("show")
@click.argument("rune_id")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.pass_context
def rune_show(ctx: click.Context, rune_id: str, as_json: bool) -> None:
    """Show details of a specific rune."""
    repo = load_repo(ctx)

    try:
        rune = repo.get_rune(rune_id)
    except Exception as e:
        click.secho(str(e), fg="red", err=True)
        ctx.exit(1)
        return

    if as_json:
        click.echo(rune.model_dump_json(indent=2))
        return

    click.secho(f"Rune: {rune.name}", fg="cyan", bold=True)
    click.echo(f"  ID:          {rune.id}")
    click.echo(f"  Version:     {rune.version}")
    click.echo(f"  Risk:        {rune.risk_level.value}")
    click.echo(f"  Platforms:   {', '.join(rune.platforms)}")
    click.echo(f"  Permissions: {', '.join(p.value for p in rune.permissions) or '(none)'}")
    if rune.description:
        click.echo(f"  Description: {rune.description}")

    if rune.commands:
        click.echo(f"\n  Commands ({len(rune.commands)}):")
        for cmd in rune.commands:
            params_str = ", ".join(f"{p.name}: {p.type}" for p in cmd.params)
            click.echo(f"    {cmd.name}({params_str})")
            if cmd.summary:
                click.echo(f"      {cmd.summary}")
            if cmd.side_effects:
                click.echo(f"      Side effects: {', '.join(cmd.side_effects)}")


@rune_group.command("validate")
@click.argument("rune_id", required=False)
@click.pass_context
def rune_validate(ctx: click.Context, rune_id: str | None) -> None:
    """Validate rune contract(s)."""
    repo = load_repo(ctx)

    if rune_id:
        try:
            rune = repo.get_rune(rune_id)
        except Exception as e:
            click.secho(str(e), fg="red", err=True)
            ctx.exit(1)
            return
        runes = [rune]
    else:
        runes = repo.list_runes()

    has_errors = False
    for rune in runes:
        result = validate_rune_rule(rune)
        if result.diagnostics:
            for d in result.diagnostics:
                color = {"error": "red", "warning": "yellow", "info": "blue"}
                click.secho(
                    f"[{d.severity.value.upper()}] {rune.id}: {d.message}",
                    fg=color.get(d.severity.value, "white"),
                )
            if not result.ok:
                has_errors = True
        else:
            click.secho(f"✓ {rune.id}", fg="green")

    if has_errors:
        ctx.exit(1)
