# src/grimoire/cli/__init__.py
"""
Grimoire CLI — prompt & tool control plane.

Built with Click + Rich, following the same patterns as confy and semantiscan CLIs.
"""

import logging
import sys

import click

from grimoire.cli.commands import conjure, doctor, init, rune, spell

logger = logging.getLogger(__name__)


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "--repo", "repo_path",
    type=click.Path(exists=False),
    default=".",
    help="Path to grimoire repository root (default: cwd).",
)
@click.option(
    "--profile", "profiles",
    multiple=True,
    help="Profile overlay(s) to apply (repeatable).",
)
@click.option(
    "--vars", "vars_files",
    multiple=True,
    type=click.Path(exists=True),
    help="YAML vars file(s) to load (repeatable).",
)
@click.option(
    "--set", "set_vars",
    multiple=True,
    help="Set a variable: key=value (repeatable).",
)
@click.option(
    "--format", "output_format",
    type=click.Choice(["text", "openai", "anthropic", "json"], case_sensitive=False),
    default="text",
    help="Output format for conjured prompts.",
)
@click.option(
    "--out", "output_path",
    type=click.Path(),
    help="Write output to file instead of stdout.",
)
@click.option(
    "--log-level",
    type=click.Choice(["trace", "debug", "info", "warn", "error"], case_sensitive=False),
    default="warn",
    help="Logging verbosity.",
)
@click.version_option(package_name="grimoire")
@click.pass_context
def cli(ctx, repo_path, profiles, vars_files, set_vars, output_format, output_path, log_level):
    """
    grimoire — prompt & tool control plane for the llmcore ecosystem.

    Manage spells (prompt templates), runes (skill contracts), and rituals
    (multi-step flows). Conjure prompts on-the-fly, bind to runtime targets.
    """
    # Configure logging
    level_map = {
        "trace": logging.DEBUG,
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warn": logging.WARNING,
        "error": logging.ERROR,
    }
    logging.basicConfig(
        level=level_map.get(log_level, logging.WARNING),
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    # Parse --set key=value pairs
    explicit_vars: dict[str, str] = {}
    for pair in set_vars:
        if "=" in pair:
            k, v = pair.split("=", 1)
            explicit_vars[k.strip()] = v.strip()
        else:
            click.secho(f"Warning: --set '{pair}' ignored (expected key=value)", fg="yellow", err=True)

    # Store context for subcommands
    ctx.ensure_object(dict)
    ctx.obj["repo_path"] = repo_path
    ctx.obj["profiles"] = list(profiles)
    ctx.obj["vars_files"] = list(vars_files)
    ctx.obj["explicit_vars"] = explicit_vars
    ctx.obj["output_format"] = output_format
    ctx.obj["output_path"] = output_path


# Register subcommands
cli.add_command(init.init_cmd, "init")
cli.add_command(spell.spell_group, "spell")
cli.add_command(rune.rune_group, "rune")
cli.add_command(conjure.conjure_cmd, "conjure")
cli.add_command(doctor.doctor_cmd, "doctor")
