# src/grimoire/cli/commands/bind.py
"""
``grimoire bind`` — export/compile artifacts to runtime targets.

Implements spec §11.2: transforms canonical grimoire artifacts into
formats consumable by semantiscan, llmcore, and wairu.

Examples::

    grimoire bind semantiscan --format toml --out exports/semantiscan/
    grimoire bind llmcore --out exports/llmcore/
    grimoire bind wairu --out exports/wairu/
    grimoire bind semantiscan --spells engineering/bug_root_cause --format legacy_tmpl
"""

from __future__ import annotations

import click

from grimoire.bind.base import BindFormat, BindTarget
from grimoire.bind.llmcore import LLMCoreBinder
from grimoire.bind.semantiscan import SemantiscanBinder
from grimoire.bind.wairu import WairuBinder
from grimoire.cli.helpers import load_repo

# Map target → binder class
_BINDERS = {
    BindTarget.SEMANTISCAN: SemantiscanBinder,
    BindTarget.LLMCORE: LLMCoreBinder,
    BindTarget.WAIRU: WairuBinder,
}

# Valid format strings per target
_FORMAT_MAP: dict[str, BindFormat] = {
    "toml": BindFormat.TOML,
    "legacy_tmpl": BindFormat.LEGACY_TMPL,
    "registry_bundle": BindFormat.REGISTRY_BUNDLE,
    "tool_pack": BindFormat.TOOL_PACK,
}


@click.command("bind")
@click.argument(
    "target",
    type=click.Choice(["semantiscan", "llmcore", "wairu"], case_sensitive=False),
)
@click.option(
    "--format",
    "bind_format",
    type=click.Choice(list(_FORMAT_MAP.keys()), case_sensitive=False),
    default=None,
    help="Output sub-format (default depends on target).",
)
@click.option(
    "--spells",
    help="Comma-separated spell IDs to bind (default: all).",
)
@click.option(
    "--runes",
    help="Comma-separated rune IDs to bind (default: all).",
)
@click.option(
    "--tags",
    help="Comma-separated tags to filter artifacts.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what would be generated without writing files.",
)
@click.pass_context
def bind_cmd(
    ctx: click.Context,
    target: str,
    bind_format: str | None,
    spells: str | None,
    runes: str | None,
    tags: str | None,
    dry_run: bool,
) -> None:
    """
    Bind (export/compile) grimoire artifacts to a runtime target.

    Transforms spells and runes into formats consumable by:
      - semantiscan: PromptManager TOML or legacy .tmpl
      - llmcore: prompt registry bundles + activity definitions
      - wairu: tool packs + augmentation prompts

    \b
    Examples:
      grimoire bind semantiscan --format toml --out exports/semantiscan/
      grimoire bind llmcore --out exports/llmcore/
      grimoire bind wairu --out exports/wairu/
      grimoire bind semantiscan --spells engineering/bug_root_cause
    """
    repo = load_repo(ctx)
    output_path = ctx.obj.get("output_path")

    # Resolve target
    bind_target = BindTarget(target.lower())
    binder = _BINDERS[bind_target]()

    # Resolve format
    fmt: BindFormat | None = None
    if bind_format:
        fmt = _FORMAT_MAP.get(bind_format)
        if fmt is None:
            click.secho(f"Unknown format: {bind_format}", fg="red", err=True)
            ctx.exit(1)
            return

    # Parse ID lists
    spell_ids = [s.strip() for s in spells.split(",")] if spells else None
    rune_ids = [r.strip() for r in runes.split(",")] if runes else None
    tag_list = [t.strip() for t in tags.split(",")] if tags else None

    # Bind
    result = binder.bind(
        repo,
        fmt=fmt,
        spell_ids=spell_ids,
        rune_ids=rune_ids,
        tags=tag_list,
    )

    # Show warnings
    for warning in result.warnings:
        click.secho(f"  ⚠ {warning}", fg="yellow", err=True)

    if not result.ok:
        click.secho("Binding produced no output files.", fg="red", err=True)
        ctx.exit(1)
        return

    # Dry-run: just list files
    if dry_run:
        click.secho(f"Bind target: {result.target.value} ({result.format.value})", fg="cyan")
        click.echo(f"Would generate {len(result.files)} file(s):")
        for bf in result.files:
            click.echo(f"  {bf.relative_path}  ({bf.description})")
        return

    # Write files
    if not output_path:
        # Default output dir: exports/<target>/
        output_path = f"exports/{target}/"

    written = result.write(output_path)

    click.secho(
        f"Bound {len(written)} file(s) to {output_path} "
        f"[{result.target.value}/{result.format.value}]",
        fg="green",
    )
    for path in written:
        click.echo(f"  {path}")
