# src/grimoire/cli/commands/spell.py
"""``grimoire spell`` — catalog and inspect spells."""

from __future__ import annotations

import json

import click

from grimoire.cli.helpers import format_table, load_repo


@click.group("spell")
def spell_group() -> None:
    """Catalog and inspect spells."""


@spell_group.command("list")
@click.option("--tags", help="Filter by comma-separated tags.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.pass_context
def spell_list(ctx: click.Context, tags: str | None, as_json: bool) -> None:
    """List all spells in the grimoire."""
    repo = load_repo(ctx)
    tag_list = [t.strip() for t in tags.split(",")] if tags else None
    spells = repo.list_spells(tags=tag_list)

    if as_json:
        data = [{"id": s.id, "name": s.name, "version": s.version, "tags": s.tags} for s in spells]
        click.echo(json.dumps(data, indent=2))
        return

    if not spells:
        click.echo("No spells found.")
        return

    rows = [[s.id, s.name, s.version, ", ".join(s.tags)] for s in spells]
    click.echo(format_table(["ID", "Name", "Version", "Tags"], rows))


@spell_group.command("show")
@click.argument("spell_id")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.pass_context
def spell_show(ctx: click.Context, spell_id: str, as_json: bool) -> None:
    """Show details of a specific spell."""
    repo = load_repo(ctx)

    try:
        spell = repo.get_spell(spell_id)
    except Exception as e:
        click.secho(str(e), fg="red", err=True)
        ctx.exit(1)
        return

    if as_json:
        click.echo(spell.model_dump_json(indent=2))
        return

    click.secho(f"Spell: {spell.name}", fg="cyan", bold=True)
    click.echo(f"  ID:      {spell.id}")
    click.echo(f"  Version: {spell.version}")
    click.echo(f"  Tags:    {', '.join(spell.tags) or '(none)'}")
    if spell.description:
        click.echo(f"  Desc:    {spell.description}")
    click.echo(f"  Hash:    {spell.content_hash or '(none)'}")
    click.echo(f"  Source:  {spell.source_path or '(inline)'}")

    if spell.variables:
        click.echo(f"\n  Variables ({len(spell.variables)}):")
        for name, spec in spell.variables.items():
            req = "required" if spec.required else "optional"
            default = f" [default: {spec.default}]" if spec.default is not None else ""
            click.echo(f"    {name}: {spec.type.value} ({req}){default}")

    if spell.raw_blocks:
        click.echo(f"\n  Blocks ({len(spell.raw_blocks)}):")
        for block in spell.raw_blocks:
            preview = block.content[:80].replace("\n", " ")
            if len(block.content) > 80:
                preview += "..."
            click.echo(f"    [{block.role.value}] {preview}")

    if spell.requires_runes:
        click.echo(f"\n  Required runes: {', '.join(spell.requires_runes)}")
    if spell.suggests_runes:
        click.echo(f"  Suggested runes: {', '.join(spell.suggests_runes)}")


@spell_group.command("vars")
@click.argument("spell_id")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.pass_context
def spell_vars(ctx: click.Context, spell_id: str, as_json: bool) -> None:
    """Show variables required by a spell."""
    repo = load_repo(ctx)

    try:
        spell = repo.get_spell(spell_id)
    except Exception as e:
        click.secho(str(e), fg="red", err=True)
        ctx.exit(1)
        return

    if as_json:
        data = {name: spec.model_dump() for name, spec in spell.variables.items()}
        click.echo(json.dumps(data, indent=2))
        return

    if not spell.variables:
        click.echo(f"Spell '{spell_id}' has no variables.")
        return

    rows = [
        [
            name,
            spec.type.value,
            "yes" if spec.required else "no",
            str(spec.default) if spec.default is not None else "-",
            spec.ask or "-",
        ]
        for name, spec in spell.variables.items()
    ]
    click.echo(format_table(["Name", "Type", "Required", "Default", "Prompt"], rows))
