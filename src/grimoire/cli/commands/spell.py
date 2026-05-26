# src/grimoire/cli/commands/spell.py
"""``grimoire spell`` — catalog and inspect spells."""

from __future__ import annotations

import json
from pathlib import Path

import click

from grimoire.cli.helpers import format_table, load_repo
from grimoire.models import MessageBlock, MessageRole, Spell


def _read_block_content(text: str | None, file: str | None, label: str) -> str | None:
    """Resolve block content from an inline string or a file path (``-`` = stdin)."""
    if text is not None:
        return text
    if file is not None:
        if file == "-":
            return click.get_text_stream("stdin").read()
        return Path(file).read_text(encoding="utf-8")
    return None


def _parse_tags(tags: str | None) -> list[str]:
    return [t.strip() for t in tags.split(",") if t.strip()] if tags else []


def _parse_attributes(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise click.ClickException(f"--attributes is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise click.ClickException("--attributes must be a JSON object (mapping)")
    return data


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


# ── Write verbs (WS-G1) ───────────────────────────────────────────────────────


@spell_group.command("new")
@click.argument("spell_id")
@click.option("--name", help="Human-readable spell name (defaults to the id).")
@click.option("--version", default="1.0.0", show_default=True, help="Spell version.")
@click.option("--tags", help="Comma-separated tags.")
@click.option("--description", help="Spell description.")
@click.option("--attributes", help="Opaque app attributes as a JSON object.")
@click.option("--system", help="Inline SYSTEM block content.")
@click.option("--system-file", help="File with SYSTEM block content ('-' for stdin).")
@click.option("--user", help="Inline USER block content.")
@click.option("--user-file", help="File with USER block content ('-' for stdin).")
@click.option("--overwrite", is_flag=True, help="Overwrite an existing spell file.")
@click.pass_context
def spell_new(
    ctx: click.Context,
    spell_id: str,
    name: str | None,
    version: str,
    tags: str | None,
    description: str | None,
    attributes: str | None,
    system: str | None,
    system_file: str | None,
    user: str | None,
    user_file: str | None,
    overwrite: bool,
) -> None:
    """Create a new spell and write it to the repo's primary spell directory."""
    repo = load_repo(ctx)

    system_content = _read_block_content(system, system_file, "SYSTEM")
    user_content = _read_block_content(user, user_file, "USER")
    blocks: list[MessageBlock] = []
    if system_content:
        blocks.append(MessageBlock(role=MessageRole.SYSTEM, content=system_content.strip()))
    if user_content:
        blocks.append(MessageBlock(role=MessageRole.USER, content=user_content.strip()))
    if not blocks:
        click.secho("Error: at least one of --system/--user (or *-file) is required.", fg="red", err=True)
        ctx.exit(1)
        return

    try:
        spell = Spell(
            id=spell_id,
            name=name or spell_id,
            version=version,
            tags=_parse_tags(tags),
            description=description,
            attributes=_parse_attributes(attributes),
            raw_blocks=blocks,
        )
        path = repo.write_spell(spell, overwrite=overwrite)
    except Exception as e:
        click.secho(str(e), fg="red", err=True)
        ctx.exit(1)
        return

    click.secho(f"Wrote spell '{spell_id}' -> {path}", fg="green")


@spell_group.command("edit")
@click.argument("spell_id")
@click.option("--name", help="New name.")
@click.option("--version", help="New version.")
@click.option("--tags", help="Replace tags (comma-separated).")
@click.option("--description", help="New description.")
@click.option("--attributes", help="Replace opaque attributes (JSON object).")
@click.option("--system", help="Replace SYSTEM block content.")
@click.option("--system-file", help="File with SYSTEM block content ('-' for stdin).")
@click.option("--user", help="Replace USER block content.")
@click.option("--user-file", help="File with USER block content ('-' for stdin).")
@click.pass_context
def spell_edit(
    ctx: click.Context,
    spell_id: str,
    name: str | None,
    version: str | None,
    tags: str | None,
    description: str | None,
    attributes: str | None,
    system: str | None,
    system_file: str | None,
    user: str | None,
    user_file: str | None,
) -> None:
    """Edit an existing spell in place (only provided fields change)."""
    repo = load_repo(ctx)

    try:
        existing = repo.get_spell(spell_id)
    except Exception as e:
        click.secho(str(e), fg="red", err=True)
        ctx.exit(1)
        return

    # Start from the existing blocks, replacing SYSTEM/USER where given.
    system_content = _read_block_content(system, system_file, "SYSTEM")
    user_content = _read_block_content(user, user_file, "USER")
    block_map = {b.role: b.content for b in existing.raw_blocks}
    if system_content is not None:
        block_map[MessageRole.SYSTEM] = system_content.strip()
    if user_content is not None:
        block_map[MessageRole.USER] = user_content.strip()
    # Preserve original ordering for unchanged roles; append newly-added ones.
    ordered_roles = [b.role for b in existing.raw_blocks]
    for role in (MessageRole.SYSTEM, MessageRole.USER):
        if role in block_map and role not in ordered_roles:
            ordered_roles.append(role)
    blocks = [MessageBlock(role=r, content=block_map[r]) for r in ordered_roles if r in block_map]

    try:
        updated = Spell(
            id=existing.id,
            name=name if name is not None else existing.name,
            version=version if version is not None else existing.version,
            tags=_parse_tags(tags) if tags is not None else list(existing.tags),
            description=description if description is not None else existing.description,
            license=existing.license,
            attributes=_parse_attributes(attributes) if attributes is not None else dict(existing.attributes),
            variables=existing.variables,
            requires_runes=list(existing.requires_runes),
            suggests_runes=list(existing.suggests_runes),
            runes_export=existing.runes_export,
            output_contract=existing.output_contract,
            raw_blocks=blocks,
        )
        path = repo.update_spell(updated)
    except Exception as e:
        click.secho(str(e), fg="red", err=True)
        ctx.exit(1)
        return

    click.secho(f"Updated spell '{spell_id}' -> {path}", fg="green")


@spell_group.command("rm")
@click.argument("spell_id")
@click.option("--yes", is_flag=True, help="Skip confirmation.")
@click.pass_context
def spell_rm(ctx: click.Context, spell_id: str, yes: bool) -> None:
    """Delete a spell file and remove it from the repo index."""
    repo = load_repo(ctx)

    if not yes and not click.confirm(f"Delete spell '{spell_id}'?"):
        click.echo("Aborted.")
        return

    try:
        repo.delete_spell(spell_id)
    except Exception as e:
        click.secho(str(e), fg="red", err=True)
        ctx.exit(1)
        return

    click.secho(f"Deleted spell '{spell_id}'.", fg="green")
