# src/grimoire/cli/commands/rune.py
"""``grimoire rune`` — skills manager: discover and validate rune contracts."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

import click

from grimoire.cli.helpers import format_table, load_repo
from grimoire.models import CommandSpec, RiskLevel, RuneSpec
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


@rune_group.command("audit")
@click.option("--filter-owasp", help="Only show commands with this OWASP category.")
@click.option(
    "--require-owasp",
    is_flag=True,
    help="Exit non-zero if a high-risk command lacks OWASP categories.",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.pass_context
def rune_audit(
    ctx: click.Context,
    filter_owasp: str | None,
    require_owasp: bool,
    as_json: bool,
) -> None:
    """Audit rune OWASP LLM Top-10 metadata coverage."""
    repo = load_repo(ctx)
    report = _owasp_audit_report(repo.list_runes(), filter_owasp=filter_owasp)

    if as_json:
        click.echo(json.dumps(report, indent=2))
    else:
        _print_owasp_audit(report, filter_owasp=filter_owasp)

    if require_owasp and report["missing_high_risk"]:
        ctx.exit(1)


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


def _owasp_audit_report(
    runes: list[RuneSpec],
    *,
    filter_owasp: str | None = None,
) -> dict[str, Any]:
    """Build an OWASP metadata coverage report for rune commands."""
    commands: list[dict[str, Any]] = []
    missing_high_risk: list[dict[str, Any]] = []
    histogram: Counter[str] = Counter()

    for rune in runes:
        for command in rune.commands:
            categories = _effective_owasp_categories(rune, command)
            if filter_owasp and filter_owasp not in categories:
                continue

            effective_risk = command.risk_level or rune.risk_level
            entry = {
                "rune_id": rune.id,
                "command_name": command.name,
                "risk_level": effective_risk.value,
                "requires_approval": command.requires_approval or rune.requires_approval,
                "owasp_categories": categories,
            }
            commands.append(entry)
            histogram.update(categories)

            if effective_risk is RiskLevel.HIGH and not categories:
                missing_high_risk.append(entry)

    return {
        "schema": "grimoire.rune_owasp_audit.v1",
        "total_runes": len(runes),
        "total_commands": len(commands),
        "histogram": dict(sorted(histogram.items())),
        "missing_high_risk": missing_high_risk,
        "commands": commands,
    }


def _effective_owasp_categories(rune: RuneSpec, command: CommandSpec) -> list[str]:
    categories = command.owasp_categories or rune.owasp_categories
    return list(dict.fromkeys(str(category) for category in categories))


def _print_owasp_audit(report: dict[str, Any], *, filter_owasp: str | None = None) -> None:
    click.secho("OWASP Rune Audit", fg="cyan", bold=True)
    click.echo(f"  Runes:    {report['total_runes']}")
    click.echo(f"  Commands: {report['total_commands']}")
    if filter_owasp:
        click.echo(f"  Filter:   {filter_owasp}")

    click.echo("\nOWASP category histogram:")
    if report["histogram"]:
        for category, count in report["histogram"].items():
            click.echo(f"  {category}: {count}")
    else:
        click.echo("  (none)")

    if report["missing_high_risk"]:
        click.echo("\nHigh-risk commands lacking OWASP categories:")
        rows = [
            [entry["rune_id"], entry["command_name"], entry["risk_level"]]
            for entry in report["missing_high_risk"]
        ]
        click.echo(format_table(["Rune", "Command", "Risk"], rows))
    else:
        click.echo("\nHigh-risk OWASP coverage: complete")

    if filter_owasp and report["commands"]:
        rows = [
            [
                entry["rune_id"],
                entry["command_name"],
                entry["risk_level"],
                ", ".join(entry["owasp_categories"]),
            ]
            for entry in report["commands"]
        ]
        click.echo("\nMatching commands:")
        click.echo(format_table(["Rune", "Command", "Risk", "OWASP"], rows))
