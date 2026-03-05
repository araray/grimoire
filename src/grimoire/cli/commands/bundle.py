# src/grimoire/cli/commands/bundle.py
"""``grimoire bundle`` — manage and inspect Bundle composition recipes."""

from __future__ import annotations

import json

import click

from grimoire.cli.helpers import load_repo
from grimoire.validate.rules import validate_bundle


@click.group("bundle")
def bundle_group() -> None:
    """Manage prompt bundles (composition recipes)."""


@bundle_group.command("list")
@click.option("--tag", "tags", multiple=True, help="Filter by tag (repeatable, AND logic).")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.pass_context
def bundle_list(ctx: click.Context, tags: tuple[str, ...], as_json: bool) -> None:
    """List all bundles in the repo."""
    repo = load_repo(ctx)
    bundles = repo.list_bundles(tags=list(tags) if tags else None)

    if as_json:
        click.echo(
            json.dumps(
                [
                    {
                        "id": b.id,
                        "name": b.name,
                        "version": b.version,
                        "base_template": b.base_template,
                        "tags": b.tags,
                        "content_hash": b.content_hash,
                    }
                    for b in bundles
                ],
                indent=2,
            )
        )
        return

    if not bundles:
        click.echo("No bundles found.")
        return

    from grimoire.cli.helpers import format_table

    rows = [
        [
            b.id,
            b.name,
            b.base_template,
            ", ".join(b.tags) if b.tags else "",
            b.content_hash or "",
        ]
        for b in bundles
    ]
    click.echo(format_table(["ID", "NAME", "BASE TEMPLATE", "TAGS", "HASH"], rows))


@bundle_group.command("show")
@click.argument("bundle_id")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.pass_context
def bundle_show(ctx: click.Context, bundle_id: str, as_json: bool) -> None:
    """Show details of a bundle."""
    repo = load_repo(ctx)
    try:
        bundle = repo.get_bundle(bundle_id)
    except Exception as e:
        click.secho(str(e), fg="red", err=True)
        ctx.exit(1)
        return

    if as_json:
        data: dict = {
            "id": bundle.id,
            "name": bundle.name,
            "version": bundle.version,
            "description": bundle.description,
            "tags": bundle.tags,
            "base_template": bundle.base_template,
            "overlays": bundle.overlays,
            "inject": bundle.inject.model_dump() if bundle.inject else None,
            "tools": bundle.tools,
            "variants": [
                {
                    "id": v.id,
                    "when": v.when,
                    "inject": v.inject.model_dump() if v.inject else None,
                    "variable_overrides": v.variable_overrides,
                }
                for v in bundle.variants
            ],
            "content_hash": bundle.content_hash,
            "source_path": bundle.source_path,
        }
        click.echo(json.dumps(data, indent=2))
        return

    click.echo(f"\n  Bundle: {bundle.name} [{bundle.id}]")
    click.echo(f"  Version: {bundle.version}")
    if bundle.description:
        click.echo(f"  Description: {bundle.description}")
    click.secho(f"  Hash: {bundle.content_hash}", fg="cyan")
    click.echo(f"  Base template: {bundle.base_template}")

    if bundle.overlays:
        click.echo(f"  Overlays: {', '.join(bundle.overlays)}")

    if bundle.inject:
        click.echo("  Inject:")
        inj = bundle.inject
        for label, ids in [
            ("system_prepend", inj.system_prepend),
            ("system_append", inj.system_append),
            ("user_prepend", inj.user_prepend),
            ("user_append", inj.user_append),
        ]:
            if ids:
                click.echo(f"    {label}: {', '.join(ids)}")

    if bundle.tools:
        click.echo("  Tools:")
        for group, rune_ids in bundle.tools.items():
            click.echo(f"    {group}: {', '.join(rune_ids)}")

    if bundle.variants:
        click.echo(f"  Variants ({len(bundle.variants)}):")
        for v in bundle.variants:
            when_str = ", ".join(f"{k}={val!r}" for k, val in v.when.items())
            click.echo(f"    [{v.id}]  when: {when_str or '(always)'}")


@bundle_group.command("validate")
@click.argument("bundle_id", required=False)
@click.pass_context
def bundle_validate(ctx: click.Context, bundle_id: str | None) -> None:
    """Validate one or all bundles in the repo."""
    repo = load_repo(ctx)

    bundles = [repo.get_bundle(bundle_id)] if bundle_id else repo.list_bundles()
    total_errors = 0
    total_warnings = 0

    for bundle in bundles:
        result = validate_bundle(bundle, repo)
        if not result.diagnostics:
            click.secho(f"  ✓ {bundle.id}", fg="green")
            continue

        errors = result.errors
        warnings = result.warnings
        total_errors += len(errors)
        total_warnings += len(warnings)

        color = "red" if errors else "yellow"
        icon = "✗" if errors else "⚠"
        click.secho(f"  {icon} {bundle.id}", fg=color)
        for d in result.diagnostics:
            sev_color = {"error": "red", "warning": "yellow", "info": "cyan"}.get(
                d.severity.value, "white"
            )
            click.secho(f"      [{d.severity.value.upper()}] {d.message}", fg=sev_color)

    click.echo()
    if total_errors:
        click.secho(f"  {total_errors} error(s), {total_warnings} warning(s)", fg="red")
        ctx.exit(1)
    else:
        click.secho(f"  All bundles valid ({total_warnings} warning(s))", fg="green")


@bundle_group.command("assemble")
@click.argument("bundle_id")
@click.option("--context", "ctx_pairs", multiple=True, help="Context key=value for variant selection.")
@click.option("--format", "output_format", default=None, help="Output format (overrides --format).")
@click.option("--json", "as_json", is_flag=True, help="Output assembled spell as JSON.")
@click.pass_context
def bundle_assemble(
    ctx: click.Context,
    bundle_id: str,
    ctx_pairs: tuple[str, ...],
    output_format: str | None,
    as_json: bool,
) -> None:
    """
    Assemble a bundle into a conjurable spell and show the result.

    This performs stages 1-5 of assembly (base spell load, variant selection,
    promptlet injection, tool exposure) and prints the resulting assembled spell.
    It does NOT conjure variables — use ``grimoire conjure`` for that.
    """
    from grimoire.bundles.assembler import BundleAssembler

    repo = load_repo(ctx)
    try:
        bundle = repo.get_bundle(bundle_id)
    except Exception as e:
        click.secho(str(e), fg="red", err=True)
        ctx.exit(1)
        return

    # Parse context pairs
    context: dict[str, str] = {}
    for pair in ctx_pairs:
        if "=" in pair:
            k, v = pair.split("=", 1)
            context[k.strip()] = v.strip()

    assembler = BundleAssembler(repo)
    try:
        assembled_spell = assembler.assemble(bundle, context=context)
    except Exception as e:
        click.secho(f"Assembly failed: {e}", fg="red", err=True)
        ctx.exit(1)
        return

    if as_json:
        data = {
            "assembled_id": assembled_spell.id,
            "name": assembled_spell.name,
            "content_hash": assembled_spell.content_hash,
            "blocks": [
                {"role": b.role.value, "content": b.content} for b in assembled_spell.raw_blocks
            ],
        }
        click.echo(json.dumps(data, indent=2))
        return

    click.echo(f"\n  Assembled: {assembled_spell.name}")
    click.secho(f"  Hash: {assembled_spell.content_hash}", fg="cyan")
    click.echo(f"  Blocks: {len(assembled_spell.raw_blocks)}\n")
    for block in assembled_spell.raw_blocks:
        click.secho(f"# {block.role.value}", fg="blue")
        click.echo(block.content)
        click.echo()
