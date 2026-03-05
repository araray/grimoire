# src/grimoire/cli/commands/skill.py
"""``grimoire skill`` — unified skill management (SkillDocs + SkillContracts)."""

from __future__ import annotations

import json

import click

from grimoire.cli.helpers import format_table, load_repo
from grimoire.validate.rules import validate_rune, validate_skilldoc


@click.group("skill")
def skill_group() -> None:
    """Manage skills: SkillDocs (knowledge) and SkillContracts (runes)."""


# ── List ─────────────────────────────────────────────────────────────────────


@skill_group.command("list")
@click.option(
    "--type",
    "skill_type",
    type=click.Choice(["docs", "contracts", "all"], case_sensitive=False),
    default="all",
    help="Filter by skill type.",
)
@click.option("--tag", "tags", multiple=True, help="Filter by tag (repeatable, AND logic).")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.pass_context
def skill_list(
    ctx: click.Context, skill_type: str, tags: tuple[str, ...], as_json: bool
) -> None:
    """List all skills (docs, contracts, or both)."""
    repo = load_repo(ctx)
    tag_list = list(tags) if tags else None

    items: list[dict] = []

    if skill_type in ("docs", "all"):
        for doc in repo.list_skilldocs(tags=tag_list):
            items.append(
                {
                    "type": "doc",
                    "id": doc.id,
                    "name": doc.name,
                    "tags": doc.tags,
                    "sections": len(doc.sections),
                }
            )

    if skill_type in ("contracts", "all"):
        for rune in repo.list_runes(tags=tag_list):
            items.append(
                {
                    "type": "contract",
                    "id": rune.id,
                    "name": rune.name,
                    "tags": rune.tags,
                    "commands": len(rune.commands),
                }
            )

    if as_json:
        click.echo(json.dumps(items, indent=2))
        return

    if not items:
        click.echo("No skills found.")
        return

    rows = [
        [
            item["type"],
            item["id"],
            item["name"],
            ", ".join(item["tags"]) if item["tags"] else "",
            str(item.get("sections", item.get("commands", ""))),
        ]
        for item in items
    ]
    click.echo(format_table(["TYPE", "ID", "NAME", "TAGS", "SECTIONS/CMDS"], rows))


# ── Show ─────────────────────────────────────────────────────────────────────


@skill_group.command("show")
@click.argument("skill_id")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.pass_context
def skill_show(ctx: click.Context, skill_id: str, as_json: bool) -> None:
    """Show details of a skill (doc or contract)."""
    repo = load_repo(ctx)

    # Try skilldoc first, then rune
    item = None
    item_type = None

    try:
        item = repo.get_skilldoc(skill_id)
        item_type = "doc"
    except Exception:
        pass

    if item is None:
        try:
            item = repo.get_rune(skill_id)
            item_type = "contract"
        except Exception:
            pass

    if item is None:
        click.secho(f"Skill '{skill_id}' not found (searched docs and contracts)", fg="red", err=True)
        ctx.exit(1)
        return

    if item_type == "doc":
        from grimoire.models import SkillDoc
        assert isinstance(item, SkillDoc)
        if as_json:
            click.echo(
                json.dumps(
                    {
                        "type": "doc",
                        "id": item.id,
                        "name": item.name,
                        "version": item.version,
                        "description": item.description,
                        "tags": item.tags,
                        "sections": [
                            {"id": s.id, "heading": s.heading, "tags": s.tags, "content": s.content}
                            for s in item.sections
                        ],
                        "content_hash": item.content_hash,
                    },
                    indent=2,
                )
            )
            return

        click.echo(f"\n  SkillDoc: {item.name} [{item.id}]")
        click.echo(f"  Version: {item.version}")
        if item.description:
            click.echo(f"  Description: {item.description}")
        click.echo(f"  Tags: {', '.join(item.tags) if item.tags else '(none)'}")
        click.secho(f"  Hash: {item.content_hash}", fg="cyan")
        click.echo(f"\n  Sections ({len(item.sections)}):")
        for sec in item.sections:
            tags_str = f"  [{', '.join(sec.tags)}]" if sec.tags else ""
            click.echo(f"    [{sec.id}] {sec.heading}{tags_str}")
            preview = sec.content[:80].replace("\n", " ")
            if len(sec.content) > 80:
                preview += "..."
            click.echo(f"      {preview}")
    else:
        # Rune contract
        from grimoire.models import RuneSpec
        assert isinstance(item, RuneSpec)
        if as_json:
            click.echo(json.dumps(item.model_dump(), indent=2))
            return

        click.echo(f"\n  SkillContract (Rune): {item.name} [{item.id}]")
        click.echo(f"  Risk: {item.risk_level.value}  Approval: {item.requires_approval}")
        if item.commands:
            click.echo(f"\n  Commands ({len(item.commands)}):")
            for cmd in item.commands:
                risk = cmd.risk_level.value if cmd.risk_level else item.risk_level.value
                click.echo(f"    {cmd.name}  [risk={risk}]")
                if cmd.summary:
                    click.echo(f"      {cmd.summary}")


# ── Validate ─────────────────────────────────────────────────────────────────


@skill_group.command("validate")
@click.pass_context
def skill_validate(ctx: click.Context) -> None:
    """Validate all skills (docs and contracts)."""
    repo = load_repo(ctx)
    total_errors = 0
    total_warnings = 0

    for doc in repo.list_skilldocs():
        result = validate_skilldoc(doc)
        _print_diags(doc.id, "doc", result)
        total_errors += len(result.errors)
        total_warnings += len(result.warnings)

    for rune in repo.list_runes():
        result = validate_rune(rune)
        _print_diags(rune.id, "contract", result)
        total_errors += len(result.errors)
        total_warnings += len(result.warnings)

    click.echo()
    if total_errors:
        click.secho(f"  {total_errors} error(s), {total_warnings} warning(s)", fg="red")
        ctx.exit(1)
    else:
        click.secho(f"  All skills valid ({total_warnings} warning(s))", fg="green")


# ── Docs render ──────────────────────────────────────────────────────────────


@skill_group.command("docs")
@click.argument("skill_id")
@click.option("--sections", "section_tags", default=None, help="Comma-separated section tags to include.")
@click.pass_context
def skill_docs(ctx: click.Context, skill_id: str, section_tags: str | None) -> None:
    """Render a SkillDoc (optionally filtering sections by tags)."""
    from grimoire.skilldocs.selector import SkillDocSelector

    repo = load_repo(ctx)
    try:
        doc = repo.get_skilldoc(skill_id)
    except Exception as e:
        click.secho(str(e), fg="red", err=True)
        ctx.exit(1)
        return

    selector = SkillDocSelector(doc)
    if section_tags:
        tags = [t.strip() for t in section_tags.split(",") if t.strip()]
        sections = selector.by_tags(tags, require_all=False)
    else:
        sections = selector.all_sections()

    click.echo(selector.render(sections))


# ── Export ───────────────────────────────────────────────────────────────────


@skill_group.command("export")
@click.option(
    "--to",
    "target_format",
    type=click.Choice(
        ["openai-tool-schema", "llmcore-activities", "wairu-tools"],
        case_sensitive=False,
    ),
    required=True,
    help="Target export format.",
)
@click.option("--tag", "tags", multiple=True, help="Filter runes by tag.")
@click.option("--out", "out_path", type=click.Path(), help="Write output to file.")
@click.pass_context
def skill_export(
    ctx: click.Context,
    target_format: str,
    tags: tuple[str, ...],
    out_path: str | None,
) -> None:
    """Export skill contracts to a target format."""
    from grimoire.skilldocs.selector import SkillDocSelector

    repo = load_repo(ctx)
    runes = repo.list_runes(tags=list(tags) if tags else None)

    if target_format == "openai-tool-schema":
        tools = SkillDocSelector(None).render_to_openai_tool_schema(runes)  # type: ignore[arg-type]
        output = json.dumps(tools, indent=2)
    elif target_format == "llmcore-activities":
        activities = [
            {
                "id": r.id,
                "name": r.name,
                "version": r.version,
                "description": r.description,
                "tags": r.tags,
                "risk_level": r.risk_level.value,
                "commands": [
                    {
                        "name": c.name,
                        "summary": c.summary,
                        "params": [p.model_dump() for p in c.params],
                    }
                    for c in r.commands
                ],
                "mappings": r.mappings,
            }
            for r in runes
        ]
        output = json.dumps(activities, indent=2)
    elif target_format == "wairu-tools":
        tools_out = [
            {
                "id": r.id,
                "name": r.name,
                "description": r.description,
                "risk_level": r.risk_level.value,
                "requires_approval": r.requires_approval,
                "commands": {
                    c.name: {
                        "description": c.summary,
                        "risk_level": (c.risk_level.value if c.risk_level else r.risk_level.value),
                        "requires_approval": c.requires_approval,
                    }
                    for c in r.commands
                },
            }
            for r in runes
        ]
        output = json.dumps(tools_out, indent=2)
    else:
        click.secho(f"Unknown format: {target_format}", fg="red", err=True)
        ctx.exit(1)
        return

    if out_path:
        from pathlib import Path
        Path(out_path).write_text(output, encoding="utf-8")
        click.secho(f"Written to {out_path}", fg="green", err=True)
    else:
        click.echo(output)


# ── Private helpers ───────────────────────────────────────────────────────────


def _print_diags(artifact_id: str, skill_type: str, result) -> None:
    from grimoire.validate.rules import ValidationResult
    assert isinstance(result, ValidationResult)
    if not result.diagnostics:
        click.secho(f"  ✓ [{skill_type}] {artifact_id}", fg="green")
        return
    color = "red" if result.errors else "yellow"
    icon = "✗" if result.errors else "⚠"
    click.secho(f"  {icon} [{skill_type}] {artifact_id}", fg=color)
    for d in result.diagnostics:
        sev_color = {"error": "red", "warning": "yellow", "info": "cyan"}.get(
            d.severity.value, "white"
        )
        click.secho(f"      [{d.severity.value.upper()}] {d.message}", fg=sev_color)
