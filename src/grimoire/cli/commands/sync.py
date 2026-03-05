# src/grimoire/cli/commands/sync.py
"""``grimoire sync`` — sync artifacts from runtimes + drift detection."""

from __future__ import annotations

import json
from pathlib import Path

import click

from grimoire.exceptions import SyncError


@click.group("sync")
def sync_group() -> None:
    """Sync artifacts from runtimes and detect drift."""


# ── from-wairu ────────────────────────────────────────────────────────────────


@sync_group.command("from-wairu")
@click.option(
    "--out",
    "out_dir",
    type=click.Path(),
    default=None,
    help="Output directory (default: runes/contracts/wairu/).",
)
@click.option("--overwrite", is_flag=True, help="Overwrite existing rune files.")
@click.option("--json", "as_json", is_flag=True, help="Output result as JSON.")
@click.pass_context
def sync_from_wairu(
    ctx: click.Context, out_dir: str | None, overwrite: bool, as_json: bool
) -> None:
    """Import tools from a running wairu instance as rune contracts."""
    from grimoire.sync.wairu import WairuSyncer

    repo_path = ctx.obj["repo_path"]
    repo_root = Path(repo_path).resolve()
    out = Path(out_dir) if out_dir else None

    syncer = WairuSyncer()
    try:
        result = syncer.import_artifacts(repo_root, out_dir=out, overwrite=overwrite)
    except SyncError as e:
        click.secho(f"Sync error: {e}", fg="red", err=True)
        ctx.exit(1)
        return

    _print_sync_result(result, as_json, ctx)


# ── from-llmcore ──────────────────────────────────────────────────────────────


@sync_group.command("from-llmcore")
@click.option("--out", "out_dir", type=click.Path(), default=None)
@click.option("--overwrite", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def sync_from_llmcore(
    ctx: click.Context, out_dir: str | None, overwrite: bool, as_json: bool
) -> None:
    """Import activities from llmcore exports as rune contracts."""
    from grimoire.sync.llmcore import LLMCoreSyncer

    repo_root = Path(ctx.obj["repo_path"]).resolve()
    out = Path(out_dir) if out_dir else None

    syncer = LLMCoreSyncer()
    try:
        result = syncer.import_artifacts(repo_root, out_dir=out, overwrite=overwrite)
    except SyncError as e:
        click.secho(f"Sync error: {e}", fg="red", err=True)
        ctx.exit(1)
        return

    _print_sync_result(result, as_json, ctx)


# ── from-semantiscan ──────────────────────────────────────────────────────────


@sync_group.command("from-semantiscan")
@click.option("--out", "out_dir", type=click.Path(), default=None)
@click.option("--overwrite", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def sync_from_semantiscan(
    ctx: click.Context, out_dir: str | None, overwrite: bool, as_json: bool
) -> None:
    """Import prompts from semantiscan as grimoire spells."""
    from grimoire.sync.semantiscan import SemantiscanSyncer

    repo_root = Path(ctx.obj["repo_path"]).resolve()
    out = Path(out_dir) if out_dir else None

    syncer = SemantiscanSyncer()
    try:
        result = syncer.import_artifacts(repo_root, out_dir=out, overwrite=overwrite)
    except SyncError as e:
        click.secho(f"Sync error: {e}", fg="red", err=True)
        ctx.exit(1)
        return

    _print_sync_result(result, as_json, ctx)


# ── drift ────────────────────────────────────────────────────────────────────


@sync_group.command("drift")
@click.option(
    "--target",
    type=click.Choice(["wairu", "llmcore", "semantiscan", "all"], case_sensitive=False),
    default="all",
    help="Target runtime to check drift against.",
)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def sync_drift(ctx: click.Context, target: str, as_json: bool) -> None:
    """Detect drift between grimoire artifacts and runtime surfaces."""
    from grimoire.sync.llmcore import LLMCoreSyncer
    from grimoire.sync.semantiscan import SemantiscanSyncer
    from grimoire.sync.wairu import WairuSyncer

    repo_root = Path(ctx.obj["repo_path"]).resolve()

    syncers = []
    if target in ("wairu", "all"):
        syncers.append(WairuSyncer())
    if target in ("llmcore", "all"):
        syncers.append(LLMCoreSyncer())
    if target in ("semantiscan", "all"):
        syncers.append(SemantiscanSyncer())

    all_reports = []
    for syncer in syncers:
        try:
            reports = syncer.detect_drift(repo_root)
            all_reports.extend(reports)
        except SyncError as e:
            click.secho(f"  [{syncer.source_name}] Drift detection failed: {e}", fg="yellow", err=True)

    if as_json:
        click.echo(
            json.dumps(
                [
                    {
                        "artifact_id": r.artifact_id,
                        "drift_type": r.drift_type,
                        "detail": r.detail,
                    }
                    for r in all_reports
                ],
                indent=2,
            )
        )
        return

    if not all_reports:
        click.secho("  ✓ No drift detected", fg="green")
        return

    click.secho(f"\n  {len(all_reports)} drift issue(s) found:\n", fg="yellow")
    for r in all_reports:
        icon = "⚠" if "missing" in r.drift_type else "≠"
        click.secho(f"  {icon} [{r.drift_type}] {r.artifact_id}", fg="yellow")
        click.echo(f"      {r.detail}")
    ctx.exit(1)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _print_sync_result(result, as_json: bool, ctx: click.Context) -> None:
    if as_json:
        click.echo(
            json.dumps(
                {
                    "source": result.source,
                    "discovered": result.discovered,
                    "imported": result.imported,
                    "skipped": result.skipped,
                    "errors": result.errors,
                    "ok": result.ok,
                },
                indent=2,
            )
        )
        return

    click.echo(f"\n  Source: {result.source}")
    click.echo(f"  Discovered: {len(result.discovered)}")
    click.secho(f"  Imported:   {len(result.imported)}", fg="green" if result.imported else "white")
    click.echo(f"  Skipped:    {len(result.skipped)}")

    if result.errors:
        click.secho(f"  Errors:     {len(result.errors)}", fg="red")
        for err in result.errors:
            click.secho(f"    ✗ {err}", fg="red")
        ctx.exit(1)
    else:
        click.secho("  ✓ Sync complete", fg="green")
