# src/grimoire/cli/commands/prompt.py
"""
``grimoire prompt`` — prompt lint and golden test commands (Phase 8).
"""

from __future__ import annotations

import json
from pathlib import Path

import click

from grimoire.cli.helpers import load_repo


@click.group("prompt")
def prompt_group() -> None:
    """Prompt quality tooling (lint, test)."""


# ── Lint ─────────────────────────────────────────────────────────────────────


@prompt_group.command("lint")
@click.argument("spell_id", required=False)
@click.option("--tag", "tags", multiple=True, help="Filter spells by tag.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.option(
    "--fail-on-warnings",
    is_flag=True,
    help="Exit non-zero if any warnings are found.",
)
@click.pass_context
def prompt_lint(
    ctx: click.Context,
    spell_id: str | None,
    tags: tuple[str, ...],
    as_json: bool,
    fail_on_warnings: bool,
) -> None:
    """
    Lint one or all spells for style rule compliance.

    Checks: forbidden tokens, snake_case variable names, ask prompts,
    USER block length, sensitive variable naming, engineering keywords.

    Configuration is loaded from the ``lint:`` key in grimoire.yaml.
    """
    from grimoire.validate.rules import LintConfig, validate_spell_style

    repo = load_repo(ctx)

    # Load lint config from manifest extras
    lint_config = LintConfig.from_manifest_extra(
        dict(repo.manifest.model_extra or {})
    )

    spells = [repo.get_spell(spell_id)] if spell_id else repo.list_spells(
        tags=list(tags) if tags else None
    )

    total_errors = 0
    total_warnings = 0
    all_results = []

    for spell in spells:
        result = validate_spell_style(spell, lint_config)
        total_errors += len(result.errors)
        total_warnings += len(result.warnings)
        all_results.append((spell, result))

    if as_json:
        click.echo(
            json.dumps(
                [
                    {
                        "spell_id": spell.id,
                        "ok": result.ok,
                        "diagnostics": [
                            {
                                "severity": d.severity.value,
                                "message": d.message,
                                "field": d.field,
                            }
                            for d in result.diagnostics
                        ],
                    }
                    for spell, result in all_results
                ],
                indent=2,
            )
        )
    else:
        for spell, result in all_results:
            if not result.diagnostics:
                click.secho(f"  ✓ {spell.id}", fg="green")
                continue
            color = "red" if result.errors else "yellow"
            icon = "✗" if result.errors else "⚠"
            click.secho(f"  {icon} {spell.id}", fg=color)
            for d in result.diagnostics:
                sev_color = {"error": "red", "warning": "yellow", "info": "cyan"}.get(
                    d.severity.value, "white"
                )
                field_str = f" [{d.field}]" if d.field else ""
                click.secho(
                    f"      [{d.severity.value.upper()}]{field_str} {d.message}",
                    fg=sev_color,
                )

        click.echo()
        if total_errors:
            click.secho(f"  {total_errors} error(s), {total_warnings} warning(s)", fg="red")
        else:
            click.secho(
                f"  All clean ({total_warnings} warning(s))",
                fg="green" if not total_warnings else "yellow",
            )

    should_fail = total_errors > 0 or (fail_on_warnings and total_warnings > 0)
    if should_fail:
        ctx.exit(1)


# ── Test ──────────────────────────────────────────────────────────────────────


@prompt_group.command("test")
@click.argument("spell_id", required=False)
@click.option("--update-golden", is_flag=True, help="Overwrite golden files with current output.")
@click.option("--golden-dir", type=click.Path(), default=None, help="Golden file directory.")
@click.option("--format", "output_format", default="text", help="Render format (text/openai/anthropic).")
@click.option("--json", "as_json", is_flag=True, help="Output comparison as JSON.")
@click.pass_context
def prompt_test(
    ctx: click.Context,
    spell_id: str | None,
    update_golden: bool,
    golden_dir: str | None,
    output_format: str,
    as_json: bool,
) -> None:
    """
    Test spells against golden output files.

    Golden files live in ``tests/golden/<spell_id_as_path>.<format>.golden.txt``.
    Each spell is rendered with its default variable values and compared against
    the golden file. Use ``--update-golden`` to update golden files.

    Variables are filled from:
      1. Spell variable defaults.
      2. ``vars/defaults.yaml`` in the repo.

    Required variables with no default are not rendered in test mode
    (a placeholder ``{{ var }}`` is left unreplaced when ``--no-strict``).
    """
    from grimoire.conjure.engine import ConjureEngine

    repo = load_repo(ctx)
    golden_root = Path(golden_dir) if golden_dir else (Path(ctx.obj["repo_path"]) / "tests" / "golden")

    spells = [repo.get_spell(spell_id)] if spell_id else repo.list_spells()

    engine = ConjureEngine(
        promptlets={p.id: p for p in repo.list_promptlets()},
        runes={r.id: r for r in repo.list_runes()},
    )

    pass_count = fail_count = skip_count = 0
    results = []

    for spell in spells:
        golden_path = golden_root / _golden_filename(spell.id, output_format)

        # Render with defaults (non-strict so missing vars stay as placeholders)
        try:
            conjured = engine.conjure(
                spell,
                variables=None,
                defaults=repo.default_vars,
                strict=False,
            )
            if output_format == "text":
                rendered = conjured.to_text()
            else:
                rendered = json.dumps(conjured.to_messages(output_format), indent=2)
        except Exception as e:
            results.append({"spell_id": spell.id, "status": "error", "detail": str(e)})
            fail_count += 1
            continue

        if update_golden:
            golden_path.parent.mkdir(parents=True, exist_ok=True)
            golden_path.write_text(rendered, encoding="utf-8")
            results.append({"spell_id": spell.id, "status": "updated"})
            skip_count += 1
            continue

        if not golden_path.exists():
            results.append({"spell_id": spell.id, "status": "missing_golden"})
            skip_count += 1
            continue

        expected = golden_path.read_text(encoding="utf-8")
        if rendered == expected:
            results.append({"spell_id": spell.id, "status": "pass"})
            pass_count += 1
        else:
            results.append({
                "spell_id": spell.id,
                "status": "fail",
                "detail": _diff_summary(expected, rendered),
            })
            fail_count += 1

    if as_json:
        click.echo(json.dumps(results, indent=2))
        return

    for r in results:
        status = r["status"]
        if status == "pass":
            click.secho(f"  ✓ {r['spell_id']}", fg="green")
        elif status == "updated":
            click.secho(f"  ✎ {r['spell_id']} (golden updated)", fg="cyan")
        elif status == "missing_golden":
            click.secho(f"  ? {r['spell_id']} (no golden — run --update-golden)", fg="yellow")
        elif status == "error":
            click.secho(f"  ✗ {r['spell_id']} ERROR: {r.get('detail', '')}", fg="red")
        else:
            click.secho(f"  ✗ {r['spell_id']} FAIL", fg="red")
            if r.get("detail"):
                click.echo(f"      {r['detail']}")

    click.echo()
    click.echo(f"  {pass_count} passed, {fail_count} failed, {skip_count} skipped")

    if fail_count:
        ctx.exit(1)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _golden_filename(spell_id: str, fmt: str) -> str:
    """Convert spell ID to golden filename: 'a/b' → 'a__b.text.golden.txt'"""
    safe = spell_id.replace("/", "__")
    return f"{safe}.{fmt}.golden.txt"


def _diff_summary(expected: str, actual: str) -> str:
    """Return a compact first-difference summary for human-readable output."""
    exp_lines = expected.splitlines()
    act_lines = actual.splitlines()
    for i, (e, a) in enumerate(zip(exp_lines, act_lines, strict=False)):
        if e != a:
            return f"Line {i + 1} differs. Expected: {e[:60]!r}  Got: {a[:60]!r}"
    if len(exp_lines) != len(act_lines):
        return f"Length differs: expected {len(exp_lines)} lines, got {len(act_lines)}"
    return "Content differs"
