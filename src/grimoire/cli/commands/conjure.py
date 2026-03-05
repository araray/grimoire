# src/grimoire/cli/commands/conjure.py
"""``grimoire conjure`` — render/assemble spells into provider messages."""

from __future__ import annotations

import json

import click

from grimoire.cli.helpers import (
    load_profiles,
    load_repo,
    load_vars_from_files,
    prompt_for_variable,
    write_output,
)
from grimoire.conjure.engine import ConjureEngine
from grimoire.exceptions import ConjureError


@click.command("conjure")
@click.argument("spell_id")
@click.option("--ask-missing", is_flag=True, help="Interactively prompt for missing variables.")
@click.option("--no-ask-missing", is_flag=True, help="Fail on missing variables (non-interactive).")
@click.option("--ask-all", is_flag=True, help="Confirm all variables interactively.")
@click.option(
    "--strict/--no-strict", default=True, help="Strict variable checking (default: strict)."
)
@click.option("--provenance", is_flag=True, help="Include provenance report in output.")
@click.pass_context
def conjure_cmd(
    ctx: click.Context,
    spell_id: str,
    ask_missing: bool,
    no_ask_missing: bool,
    ask_all: bool,
    strict: bool,
    provenance: bool,
) -> None:
    """
    Conjure (render) a spell into provider messages.

    Variable resolution follows precedence (highest wins):
      1. --set key=value
      2. --vars file.yaml
      3. --profile overlays
      4. grimoire defaults (vars/defaults.yaml)
      5. spell defaults
      6. built-ins (grimoire.now.*, etc.)

    Examples:

        grimoire conjure engineering/bug_root_cause --vars incident.yaml

        grimoire conjure examples/hello --set name=Alice --format openai

        grimoire conjure engineering/rca --ask-missing --format json

        grimoire conjure examples/hello --profile user/aaiv --ask-all
    """
    repo = load_repo(ctx)
    output_format: str = ctx.obj["output_format"]

    # Load spell (or assemble a bundle transparently)
    try:
        spell = repo.get_spell(spell_id)
    except Exception:
        # Try as a bundle ID
        try:
            from grimoire.bundles.assembler import BundleAssembler
            bundle = repo.get_bundle(spell_id)
            assembler = BundleAssembler(repo)
            spell = assembler.assemble(bundle)
        except Exception as e:
            click.secho(
                f"'{spell_id}' not found as spell or bundle: {e}", fg="red", err=True
            )
            ctx.exit(1)
            return

    # Build variable map with precedence: profiles < file vars < explicit vars
    profile_vars = load_profiles(repo, ctx.obj["profiles"])
    vars_from_files = load_vars_from_files(ctx.obj["vars_files"])
    explicit_vars: dict[str, str] = ctx.obj["explicit_vars"]

    all_vars: dict[str, object] = {}
    all_vars.update(profile_vars)
    all_vars.update(vars_from_files)
    all_vars.update(explicit_vars)

    # Interactive fill: --ask-all confirms all variables; --ask-missing fills only missing
    if ask_all:
        for name, spec in spell.variables.items():
            current = all_vars.get(name, spec.default)
            if current is not None:
                confirm_text = spec.ask or f"Value for '{name}'"
                confirmed = click.prompt(
                    f"{confirm_text} [{current}]",
                    default=str(current),
                    show_default=False,
                )
                all_vars[name] = confirmed
            else:
                all_vars[name] = prompt_for_variable(name, spec)
    elif ask_missing and not no_ask_missing:
        for name, spec in spell.required_variables().items():
            if name not in all_vars:
                all_vars[name] = prompt_for_variable(name, spec)

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
