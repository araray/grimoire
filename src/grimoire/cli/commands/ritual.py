# src/grimoire/cli/commands/ritual.py
"""``grimoire ritual`` — discover, inspect, and dry-run ritual flows."""

from __future__ import annotations

import json
import textwrap

import click

from grimoire.cli.helpers import format_table, load_repo
from grimoire.exceptions import ArtifactNotFoundError, RitualError
from grimoire.rituals.evaluator import RitualEvaluator
from grimoire.rituals.validator import validate_ritual
from grimoire.validate.rules import Severity


@click.group("ritual")
def ritual_group() -> None:
    """Discover, inspect, and dry-run ritual flows."""


# ── ritual list ────────────────────────────────────────────────────────────────


@ritual_group.command("list")
@click.option("--tag", "tags", multiple=True, help="Filter by tag (repeatable, AND logic).")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.pass_context
def ritual_list(ctx: click.Context, tags: tuple[str, ...], as_json: bool) -> None:
    """List all rituals in the grimoire."""
    repo = load_repo(ctx)
    rituals = repo.list_rituals(tags=list(tags) if tags else None)

    if as_json:
        data = [
            {
                "id": r.id,
                "name": r.name,
                "version": r.version,
                "tags": r.tags,
                "steps": len(r.steps),
            }
            for r in rituals
        ]
        click.echo(json.dumps(data, indent=2))
        return

    if not rituals:
        click.echo("No rituals found.")
        return

    rows = [[r.id, r.name, r.version, str(len(r.steps)), ", ".join(r.tags)] for r in rituals]
    click.echo(format_table(["ID", "Name", "Version", "Steps", "Tags"], rows))


# ── ritual show ────────────────────────────────────────────────────────────────


@ritual_group.command("show")
@click.argument("ritual_id")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.pass_context
def ritual_show(ctx: click.Context, ritual_id: str, as_json: bool) -> None:
    """Show details of a ritual."""
    repo = load_repo(ctx)
    try:
        ritual = repo.get_ritual(ritual_id)
    except ArtifactNotFoundError:
        click.secho(f"Ritual not found: {ritual_id!r}", fg="red", err=True)
        ctx.exit(1)
        return

    if as_json:
        data = {
            "id": ritual.id,
            "name": ritual.name,
            "version": ritual.version,
            "description": ritual.description,
            "tags": ritual.tags,
            "steps": [
                {
                    "id": s.id,
                    "spell": s.spell,
                    "when": s.when,
                    "description": s.description,
                    "conjure": s.conjure,
                    "output": s.output,
                }
                for s in ritual.steps
            ],
        }
        click.echo(json.dumps(data, indent=2))
        return

    # Human-readable
    click.echo(f"\n  Ritual: {ritual.name}")
    click.echo(f"  ID:      {ritual.id}")
    click.echo(f"  Version: {ritual.version}")
    if ritual.description:
        desc = textwrap.fill(
            ritual.description, width=72, initial_indent="  ", subsequent_indent="  "
        )
        click.echo(f"  Desc:    {desc.lstrip()}")
    if ritual.tags:
        click.echo(f"  Tags:    {', '.join(ritual.tags)}")
    click.echo(f"\n  Steps ({len(ritual.steps)}):")
    for i, step in enumerate(ritual.steps, 1):
        spell_str = step.spell or "(no spell)"
        when_str = f"  [when: {step.when}]" if step.when else ""
        capture = (step.output or {}).get("capture")
        capture_str = f"  → capture:{capture}" if capture else ""
        click.echo(f"    {i}. [{step.id}] {spell_str}{when_str}{capture_str}")
        if step.description:
            click.echo(f"       {step.description}")
    click.echo()


# ── ritual dry-run ─────────────────────────────────────────────────────────────


@ritual_group.command("dry-run")
@click.argument("ritual_id")
@click.option("--json", "as_json", is_flag=True, help="Output plan as JSON.")
@click.option(
    "--validate/--no-validate",
    "do_validate",
    default=True,
    help="Run validation before dry-run (default: on).",
)
@click.pass_context
def ritual_dry_run(ctx: click.Context, ritual_id: str, as_json: bool, do_validate: bool) -> None:
    """
    Dry-run a ritual: show the assembly plan without conjuring.

    Prints each step with its spell reference, when condition,
    variable inheritance strategy, and output capture config.
    Reports any missing spell references.
    """
    repo = load_repo(ctx)
    try:
        ritual = repo.get_ritual(ritual_id)
    except ArtifactNotFoundError:
        click.secho(f"Ritual not found: {ritual_id!r}", fg="red", err=True)
        ctx.exit(1)
        return

    # Optional validation pass
    if do_validate:
        diags = validate_ritual(ritual, repo=repo)
        errors = [d for d in diags if d.severity == Severity.ERROR]
        warnings = [d for d in diags if d.severity == Severity.WARNING]
        if errors:
            click.secho(f"\n  ✗ {len(errors)} validation error(s):", fg="red", err=True)
            for d in errors:
                click.secho(f"    • {d.message}", fg="red", err=True)
        if warnings:
            click.secho(f"\n  ⚠ {len(warnings)} warning(s):", fg="yellow", err=True)
            for d in warnings:
                click.secho(f"    • {d.message}", fg="yellow", err=True)

    # Build assembly plan
    try:
        evaluator = RitualEvaluator(repo)
        plan = evaluator.dry_run(ritual)
    except RitualError as e:
        click.secho(f"Dry-run failed: {e}", fg="red", err=True)
        ctx.exit(1)
        return

    if as_json:
        data = {
            "ritual_id": plan.ritual_id,
            "ritual_name": plan.ritual_name,
            "ok": plan.ok,
            "missing_spells": plan.missing_spells,
            "steps": [
                {
                    "step_id": sp.step_id,
                    "spell_id": sp.spell_id,
                    "spell_found": sp.spell_found,
                    "condition": sp.condition,
                    "inherits_vars": sp.inherits_vars,
                    "explicit_vars": sp.explicit_vars,
                    "ask_missing": sp.ask_missing,
                    "output_capture": sp.output_capture,
                    "output_format": sp.output_format,
                    "description": sp.description,
                }
                for sp in plan.steps
            ],
        }
        click.echo(json.dumps(data, indent=2))
        return

    # Human-readable plan
    status_icon = "✓" if plan.ok else "✗"
    status_color = "green" if plan.ok else "red"
    click.secho(f"\n  Assembly Plan: {plan.ritual_name} [{plan.ritual_id}]")
    click.secho(f"  Status: {status_icon} {'OK' if plan.ok else 'ERRORS'}", fg=status_color)

    if plan.missing_spells:
        click.secho("\n  Missing spells:", fg="red")
        for s in plan.missing_spells:
            click.secho(f"    • {s}", fg="red")

    click.echo(f"\n  Steps ({len(plan.steps)}):")
    for sp in plan.steps:
        # Spell reference
        if sp.spell_id is None:
            spell_disp = "(no spell — no-op step)"
            spell_color = "yellow"
        elif sp.spell_found:
            spell_disp = sp.spell_id
            spell_color = "green"
        else:
            spell_disp = f"{sp.spell_id}  ✗ NOT FOUND"
            spell_color = "red"

        click.echo(f"    [{sp.step_id}]")
        click.secho(f"      spell:   {spell_disp}", fg=spell_color)

        if sp.condition:
            click.echo(f"      when:    {sp.condition}")
        if sp.description:
            click.echo(f"      desc:    {sp.description}")

        vars_info = "inherit=yes" if sp.inherits_vars else "inherit=no"
        if sp.explicit_vars:
            ovr = ", ".join(f"{k}={v!r}" for k, v in sp.explicit_vars.items())
            vars_info += f", overrides=[{ovr}]"
        click.echo(f"      vars:    {vars_info}")

        if sp.ask_missing:
            click.echo("      ask:     yes (will prompt for missing vars)")

        if sp.output_capture:
            click.echo(f"      capture: {sp.output_capture!r} (format={sp.output_format})")

    click.echo()


# ── ritual run ─────────────────────────────────────────────────────────────────


@ritual_group.command("run")
@click.argument("ritual_id")
@click.option("--ask-missing", is_flag=True, help="Interactively prompt for missing variables.")
@click.option("--no-validate", is_flag=True, help="Skip pre-run validation.")
@click.option("--json", "as_json", is_flag=True, help="Output step results as JSON.")
@click.option("--format", "output_format", default="text", help="Output format per step (text/openai/anthropic).")
@click.pass_context
def ritual_run(
    ctx: click.Context,
    ritual_id: str,
    ask_missing: bool,
    no_validate: bool,
    as_json: bool,
    output_format: str,
) -> None:
    """
    Execute a ritual: conjure each step in sequence.

    Steps are executed sequentially; ``when`` conditions gate optional steps.
    Output from each step is printed and can flow into subsequent steps via
    context variable capture.

    Variable resolution per step:
      1. --set key=value (from global CLI)
      2. --vars file(s) (from global CLI)
      3. --profile overlay(s) (from global CLI)
      4. grimoire defaults (vars/defaults.yaml)
      5. Spell defaults
      6. Built-ins (grimoire.now.*, etc.)
    """
    from grimoire.cli.helpers import load_profiles, load_vars_from_files

    repo = load_repo(ctx)

    try:
        ritual = repo.get_ritual(ritual_id)
    except ArtifactNotFoundError as e:
        click.secho(str(e), fg="red", err=True)
        ctx.exit(1)
        return

    # Optional pre-run validation
    if not no_validate:
        issues = validate_ritual(ritual, repo=repo)
        errors = [d for d in issues if d.severity == Severity.ERROR]
        if errors:
            click.secho("\n  Pre-run validation failed:", fg="red", err=True)
            for d in errors:
                click.secho(f"    ✗ {d.message}", fg="red", err=True)
            ctx.exit(1)
            return

    # Build base variables from CLI context
    profile_vars = load_profiles(repo, ctx.obj["profiles"])
    vars_from_files = load_vars_from_files(ctx.obj["vars_files"])
    explicit_vars: dict = ctx.obj["explicit_vars"]

    base_vars: dict = {}
    base_vars.update(profile_vars)
    base_vars.update(vars_from_files)
    base_vars.update(explicit_vars)

    evaluator = RitualEvaluator(repo)

    # Inject ask_missing option into evaluator context
    ctx_vars: dict = dict(base_vars)

    # Execute
    try:
        steps = evaluator.evaluate(ritual, variables=ctx_vars)
    except RitualError as e:
        click.secho(f"\n  Ritual execution failed: {e}", fg="red", err=True)
        ctx.exit(1)
        return

    if as_json:
        output = []
        for step in steps:
            entry: dict = {
                "step_id": step.step_id,
                "spell_id": step.spell_id,
                "skipped": step.skipped,
                "skip_reason": step.skip_reason,
                "captured_var": step.captured_var,
            }
            if step.conjured:
                if output_format == "text":
                    entry["output"] = step.conjured.to_text()
                else:
                    entry["output"] = step.conjured.to_messages(output_format)
            output.append(entry)
        click.echo(json.dumps(output, indent=2))
        return

    # Human-readable step-by-step output
    click.echo(f"\n  Running ritual: {ritual.name} [{ritual.id}]\n")
    click.echo(f"  {'─' * 60}")

    any_failure = False
    for step in steps:
        if step.skipped:
            reason = step.skip_reason or "when condition evaluated to False"
            click.secho(f"\n  ⊘ [{step.step_id}] SKIPPED — {reason}", fg="yellow")
            continue

        click.secho(f"\n  ▶ [{step.step_id}]", fg="blue", bold=True)

        if step.spell_id:
            click.echo(f"    spell: {step.spell_id}")

        if step.conjured is None:
            click.echo("    (no-op step — no spell declared)")
            continue

        click.echo()
        if output_format == "text":
            click.echo(step.conjured.to_text())
        else:
            messages = step.conjured.to_messages(output_format)
            click.echo(json.dumps(messages, indent=2))

        if step.captured_var:
            click.secho(
                f"\n    → captured into '{step.captured_var}'",
                fg="cyan",
            )

        click.echo(f"  {'─' * 60}")

    if any_failure:
        ctx.exit(1)
    else:
        click.secho(f"\n  ✓ Ritual complete ({len(steps)} steps)", fg="green")
