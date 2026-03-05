# src/grimoire/cli/commands/init.py
"""``grimoire init`` — create a new grimoire repository skeleton."""

from __future__ import annotations

from pathlib import Path

import click
import yaml

_SKELETON_DIRS = [
    "spells/promptlets/safety",
    "spells/promptlets/style",
    "spells/promptlets/output",
    "spells/promptlets/tool_policy",
    "spells/templates/engineering",
    "spells/templates/agentic",
    "spells/templates/semantiscan",
    "spells/bundles",
    "spells/graphs",
    "rituals",
    "runes/contracts",
    "runes/docs",
    "skills/docs",
    "profiles/user",
    "profiles/persona",
    "profiles/projects",
    "profiles/env",
    "vars",
    "schema",
    "tests/golden",
    "exports",
]

_DEFAULT_MANIFEST = {
    "name": "my-grimoire",
    "version": "0.1.0",
    "description": "A grimoire of spells, runes, and rituals.",
    "authors": [],
    "tags": [],
    "spell_paths": ["spells/"],
    "rune_paths": ["runes/contracts/"],
    "ritual_paths": ["rituals/"],
    "profile_paths": ["profiles/"],
    "promptlet_paths": ["spells/promptlets/"],
    "bundle_paths": ["spells/bundles/"],
    "skilldoc_paths": ["skills/docs/"],
    "vars_path": "vars/defaults.yaml",
}

_STARTER_SPELL = """\
---
id: examples/hello
name: Hello World Spell
version: 1.0.0
tags: [example]
variables:
  name:
    type: string
    required: true
    ask: "What is your name?"
  topic:
    type: string
    required: false
    default: "anything"
---

# SYSTEM
You are a helpful assistant.

# USER
Hello {{ name }}! Let's talk about {{ topic }}.
"""

_STARTER_PROMPTLET = """\
You are a careful, methodical engineer. Always consider:
- Assumptions and what is unknown
- Failure modes and edge cases
- Validation steps
"""


@click.command("init")
@click.argument("path", default=".", type=click.Path())
@click.option("--name", help="Grimoire name (default: directory name).")
@click.option("--force", is_flag=True, help="Overwrite existing files.")
def init_cmd(path: str, name: str | None, force: bool) -> None:
    """Create a new grimoire repository skeleton."""
    root = Path(path).resolve()

    if not name:
        name = root.name

    # Check for existing grimoire
    manifest_path = root / "grimoire.yaml"
    if manifest_path.exists() and not force:
        click.secho(
            f"grimoire.yaml already exists at {root}. Use --force to overwrite.",
            fg="yellow",
        )
        return

    # Create directories
    for d in _SKELETON_DIRS:
        (root / d).mkdir(parents=True, exist_ok=True)

    # Write manifest
    manifest = dict(_DEFAULT_MANIFEST)
    manifest["name"] = name
    manifest_path.write_text(yaml.dump(manifest, default_flow_style=False), encoding="utf-8")

    # Write default vars
    vars_path = root / "vars" / "defaults.yaml"
    if not vars_path.exists() or force:
        vars_path.write_text("# Default variable values\n{}\n", encoding="utf-8")

    # Write starter spell
    spell_path = root / "spells" / "templates" / "examples" / "hello.spell.md"
    spell_path.parent.mkdir(parents=True, exist_ok=True)
    if not spell_path.exists() or force:
        spell_path.write_text(_STARTER_SPELL, encoding="utf-8")

    # Write starter promptlet
    promptlet_path = root / "spells" / "promptlets" / "style" / "principal_swe.md"
    if not promptlet_path.exists() or force:
        promptlet_path.write_text(_STARTER_PROMPTLET, encoding="utf-8")

    # Write .gitignore for exports
    gitignore = root / "exports" / ".gitignore"
    if not gitignore.exists() or force:
        gitignore.write_text("*\n!.gitignore\n", encoding="utf-8")

    click.secho(f"✓ Initialized grimoire '{name}' at {root}", fg="green")
    click.echo(f"  {len(_SKELETON_DIRS)} directories created")
    click.echo("  Starter spell: spells/templates/examples/hello.spell.md")
    click.echo("  Run: grimoire spell list")
