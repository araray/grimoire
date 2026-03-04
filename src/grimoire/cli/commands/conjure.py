# src/grimoire/cli/commands/conjure.py
"""``grimoire conjure`` — render/assemble spells into provider messages."""

from __future__ import annotations

import json

import click

from grimoire.cli.helpers import load_repo, load_vars_from_files, write_output
from grimoire.conjure.engine import ConjureEngine
from grimoire.exceptions import ConjureError


@click.command("conjure")
@click.argument("spell_id")
@click.option("--ask-missing", is_flag=True, help="Interactively prompt for missing variables.")
@click.option("--no-ask-missing", is_flag=True, help="Fail on missing variables (non-interactive).")
@click.option("--strict/--no-strict", default=True, help="Strict variable checking (default: strict).")
@click.option("--provenance", is_flag=True, help="Include provenance report in output.")
@click.pass_context
def conjure_cmd(
    ctx: click.Context,
    spell_id: str,
    ask_missing: bool,
    no_ask_missing: bool,
    strict: bool,
    provenance: bool,
) -> None:
    """
    Conjure (render) a spell into provider messages.

    Examples:

        grimoire conjure engineering/bug_root_cause --vars incident.yaml

        grimoire conjure examples/hello --set name=Alice --format openai

        grimoire conjure engineering/rca --ask-missing --format json
    """
    repo = load_repo(ctx)
    output_format: str = ctx.obj["output_format"]

    # Load spell
    try:
        spell = repo.get_spell(spell_id)
    except Exception as e:
        click.secho(str(e), fg="red", err=True)
        ctx.exit(1)
        return

    # Build variable map
    vars_from_files = load_vars_from_files(ctx.obj["vars_files"])
    explicit_vars: dict[str, str] = ctx.obj["explicit_vars"]

    # Merge: file vars < explicit vars
    all_vars: dict[str, object] = {}
    all_vars.update(vars_from_files)
    all_vars.update(explicit_vars)

    # Interactive fill for missing required variables
    if ask_missing and not no_ask_missing:
        for name, spec in spell.required_variables().items():
            if name not in all_vars:
                prompt_text = spec.ask or f"Enter value for '{name}' ({spec.type.value})"
                value = click.prompt(prompt_text)
                all_vars[name] = value

    # Create conjure engine
    engine = ConjureEngine(
        promptlets={p.id: p for p in repo.list_promptlets()},
        runes={r.id: r for r in repo.list_runes()},
    )

    # Conjure
    try:
        result = engine.conjure(
            spell=spell,
            variables=all_vars,
            defaults=repo.default_vars,
            strict=strict,
        )
    except ConjureError as e:
        click.secho(f"Conjure failed: {e}", fg="red", err=True)
        ctx.exit(1)
        return

    # Format output
    if output_format == "json":
        output_data: dict = {
            "messages": result.to_messages(fmt="openai"),
        }
        if provenance and result.provenance:
            output_data["provenance"] = result.provenance.model_dump(mode="json")
        content = json.dumps(output_data, indent=2)

    elif output_format in ("openai", "anthropic"):
        messages = result.to_messages(fmt=output_format)
        content = json.dumps(messages, indent=2)

    else:  # text
        content = result.to_text()
        if provenance and result.provenance:
            p = result.provenance
            content += "\n\n---\n# PROVENANCE\n"
            content += f"Spell: {p.spell_id} (hash: {p.spell_hash})\n"
            content += f"Timestamp: {p.timestamp.isoformat()}\n"
            if p.variables_used:
                content += f"Variables: {json.dumps(p.variables_used)}\n"
            if p.includes_resolved:
                content += f"Includes: {', '.join(p.includes_resolved)}\n"
            if p.runes_referenced:
                content += f"Runes: {', '.join(p.runes_referenced)}\n"

    write_output(ctx, content)
