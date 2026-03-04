# src/grimoire/cli/commands/doctor.py
"""``grimoire doctor`` — diagnose repository issues."""

from __future__ import annotations

import click

from grimoire.cli.helpers import load_repo
from grimoire.validate.rules import validate_repo


@click.command("doctor")
@click.pass_context
def doctor_cmd(ctx: click.Context) -> None:
    """Diagnose grimoire repo: broken includes, schema issues, missing deps."""
    repo = load_repo(ctx)

    click.secho(f"Diagnosing grimoire '{repo.manifest.name}'...\n", fg="cyan")

    # Summary
    click.echo(f"  Spells:     {len(repo.list_spells())}")
    click.echo(f"  Runes:      {len(repo.list_runes())}")
    click.echo(f"  Promptlets: {len(repo.list_promptlets())}")
    click.echo(f"  Rituals:    {len(repo.list_rituals())}")
    click.echo()

    # Run validation
    result = validate_repo(repo)

    if not result.diagnostics:
        click.secho("✓ No issues found.", fg="green")
        return

    errors = result.errors
    warnings = result.warnings

    for d in result.diagnostics:
        color = {"error": "red", "warning": "yellow", "info": "blue"}
        prefix = d.severity.value.upper()
        loc = f" ({d.artifact_id})" if d.artifact_id else ""
        click.secho(f"  [{prefix}]{loc} {d.message}", fg=color.get(d.severity.value, "white"))

    click.echo()
    if errors:
        click.secho(f"✗ {len(errors)} error(s), {len(warnings)} warning(s)", fg="red")
        ctx.exit(1)
    else:
        click.secho(f"✓ {len(warnings)} warning(s), no errors", fg="yellow")
