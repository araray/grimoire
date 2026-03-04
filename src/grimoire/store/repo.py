# src/grimoire/store/repo.py
"""
Grimoire repository loader.

Discovers and indexes all artifacts in a grimoire directory:
- Spells (``*.spell.md``)
- Runes (``*.rune.yaml``)
- Promptlets (plain ``.md`` files under promptlet paths)
- Rituals (``*.ritual.yaml``)
- Manifest (``grimoire.yaml``)
- Default variables (``vars/defaults.yaml``)

The repo provides look-up by ID, tag-based filtering, and a flat catalog
suitable for CLI listing and agent introspection.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from grimoire.exceptions import (
    ArtifactNotFoundError,
    ManifestError,
    RepoError,
)
from grimoire.models import (
    GrimoireManifest,
    Promptlet,
    Ritual,
    RuneSpec,
    Spell,
)
from grimoire.rituals.parser import parse_ritual_file
from grimoire.runes.parser import parse_rune_file
from grimoire.spells.parser import parse_spell_file

logger = logging.getLogger(__name__)


class GrimoireRepo:
    """
    In-memory index of a grimoire repository.

    Usage::

        repo = GrimoireRepo.load("/path/to/grimoire")
        spell = repo.get_spell("engineering/bug_root_cause")
        runes = repo.list_runes(tags=["devtools"])
    """

    def __init__(self, root: Path, manifest: GrimoireManifest) -> None:
        self.root = root
        self.manifest = manifest

        self._spells: dict[str, Spell] = {}
        self._runes: dict[str, RuneSpec] = {}
        self._promptlets: dict[str, Promptlet] = {}
        self._rituals: dict[str, Ritual] = {}
        self._default_vars: dict[str, object] = {}

    # ── Factory ─────────────────────────────────────────────────────────────

    @classmethod
    def load(cls, path: str | Path) -> "GrimoireRepo":
        """
        Load a grimoire repo from disk.

        Args:
            path: Path to the grimoire root directory.

        Returns:
            Populated GrimoireRepo instance.

        Raises:
            RepoError: If the path is invalid or loading fails.
        """
        root = Path(path).resolve()
        if not root.is_dir():
            raise RepoError(f"Not a directory: {root}")

        manifest = cls._load_manifest(root)
        repo = cls(root, manifest)

        repo._discover_promptlets()
        repo._discover_spells()
        repo._discover_runes()
        repo._discover_rituals()
        repo._load_default_vars()

        logger.info(
            f"Loaded grimoire '{manifest.name}' from {root}: "
            f"{len(repo._spells)} spells, {len(repo._runes)} runes, "
            f"{len(repo._promptlets)} promptlets, {len(repo._rituals)} rituals"
        )
        return repo

    # ── Manifest ────────────────────────────────────────────────────────────

    @staticmethod
    def _load_manifest(root: Path) -> GrimoireManifest:
        """Load and validate grimoire.yaml manifest."""
        manifest_path = root / "grimoire.yaml"
        if not manifest_path.exists():
            # Allow bare repos without manifest (use defaults)
            logger.debug(f"No grimoire.yaml in {root}, using defaults")
            return GrimoireManifest()

        try:
            data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ManifestError(f"grimoire.yaml must be a mapping, got {type(data)}")
            return GrimoireManifest(**data)
        except yaml.YAMLError as e:
            raise ManifestError(f"Invalid YAML in grimoire.yaml: {e}") from e
        except Exception as e:
            raise ManifestError(f"Failed to parse grimoire.yaml: {e}") from e

    # ── Discovery ───────────────────────────────────────────────────────────

    def _resolve_paths(self, path_list: list[str]) -> list[Path]:
        """Resolve path patterns relative to repo root, filtering to existing dirs."""
        resolved: list[Path] = []
        for p in path_list:
            full = self.root / p
            if full.is_dir():
                resolved.append(full)
            elif full.exists():
                resolved.append(full)
            else:
                logger.debug(f"Path not found, skipping: {full}")
        return resolved

    def _discover_spells(self) -> None:
        """Find and parse all *.spell.md files."""
        dirs = self._resolve_paths(self.manifest.spell_paths)
        for d in dirs:
            for spell_file in d.rglob("*.spell.md"):
                try:
                    spell = parse_spell_file(spell_file)
                    if spell.id in self._spells:
                        logger.warning(f"Duplicate spell id '{spell.id}', overwriting")
                    self._spells[spell.id] = spell
                except Exception as e:
                    logger.error(f"Failed to parse spell {spell_file}: {e}")

    def _discover_runes(self) -> None:
        """Find and parse all *.rune.yaml files."""
        dirs = self._resolve_paths(self.manifest.rune_paths)
        for d in dirs:
            for rune_file in d.rglob("*.rune.yaml"):
                try:
                    rune = parse_rune_file(rune_file)
                    if rune.id in self._runes:
                        logger.warning(f"Duplicate rune id '{rune.id}', overwriting")
                    self._runes[rune.id] = rune
                except Exception as e:
                    logger.error(f"Failed to parse rune {rune_file}: {e}")

    def _discover_promptlets(self) -> None:
        """Find and load promptlet .md files (plain markdown, no frontmatter)."""
        dirs = self._resolve_paths(self.manifest.promptlet_paths)
        for d in dirs:
            for md_file in d.rglob("*.md"):
                # Skip spell files
                if md_file.name.endswith(".spell.md"):
                    continue
                # Derive ID from relative path
                rel = md_file.relative_to(d)
                promptlet_id = str(rel.with_suffix("")).replace("\\", "/")
                try:
                    content = md_file.read_text(encoding="utf-8").strip()
                    self._promptlets[promptlet_id] = Promptlet(
                        id=promptlet_id,
                        content=content,
                        source_path=str(md_file),
                    )
                except Exception as e:
                    logger.error(f"Failed to load promptlet {md_file}: {e}")

    def _discover_rituals(self) -> None:
        """Find and parse all *.ritual.yaml files."""
        dirs = self._resolve_paths(self.manifest.ritual_paths)
        for d in dirs:
            for ritual_file in d.rglob("*.ritual.yaml"):
                try:
                    ritual = parse_ritual_file(ritual_file)
                    if ritual.id in self._rituals:
                        logger.warning(f"Duplicate ritual id '{ritual.id}', overwriting")
                    self._rituals[ritual.id] = ritual
                except Exception as e:
                    logger.error(f"Failed to parse ritual {ritual_file}: {e}")

    def _load_default_vars(self) -> None:
        """Load default variables from vars/defaults.yaml."""
        vars_path = self.root / self.manifest.vars_path
        if vars_path.exists():
            try:
                data = yaml.safe_load(vars_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._default_vars = data
            except Exception as e:
                logger.error(f"Failed to load default vars: {e}")

    # ── Accessors ───────────────────────────────────────────────────────────

    def get_spell(self, spell_id: str) -> Spell:
        """Get a spell by ID. Raises ArtifactNotFoundError if missing."""
        if spell_id not in self._spells:
            raise ArtifactNotFoundError(f"Spell not found: {spell_id}")
        return self._spells[spell_id]

    def get_rune(self, rune_id: str) -> RuneSpec:
        """Get a rune by ID. Raises ArtifactNotFoundError if missing."""
        if rune_id not in self._runes:
            raise ArtifactNotFoundError(f"Rune not found: {rune_id}")
        return self._runes[rune_id]

    def get_promptlet(self, promptlet_id: str) -> Promptlet:
        """Get a promptlet by ID. Raises ArtifactNotFoundError if missing."""
        if promptlet_id not in self._promptlets:
            raise ArtifactNotFoundError(f"Promptlet not found: {promptlet_id}")
        return self._promptlets[promptlet_id]

    def get_ritual(self, ritual_id: str) -> Ritual:
        """Get a ritual by ID. Raises ArtifactNotFoundError if missing."""
        if ritual_id not in self._rituals:
            raise ArtifactNotFoundError(f"Ritual not found: {ritual_id}")
        return self._rituals[ritual_id]

    @property
    def default_vars(self) -> dict[str, object]:
        """Default variable values from vars/defaults.yaml."""
        return dict(self._default_vars)

    # ── Listing / Filtering ─────────────────────────────────────────────────

    def list_spells(self, tags: list[str] | None = None) -> list[Spell]:
        """List all spells, optionally filtered by tags (AND logic)."""
        spells = list(self._spells.values())
        if tags:
            tag_set = set(tags)
            spells = [s for s in spells if tag_set.issubset(set(s.tags))]
        return sorted(spells, key=lambda s: s.id)

    def list_runes(self, tags: list[str] | None = None) -> list[RuneSpec]:
        """List all runes, optionally filtered by tags (AND logic)."""
        runes = list(self._runes.values())
        if tags:
            tag_set = set(tags)
            runes = [r for r in runes if tag_set.issubset(set(r.tags))]
        return sorted(runes, key=lambda r: r.id)

    def list_promptlets(self) -> list[Promptlet]:
        """List all promptlets."""
        return sorted(self._promptlets.values(), key=lambda p: p.id)

    def list_rituals(self, tags: list[str] | None = None) -> list[Ritual]:
        """List all rituals, optionally filtered by tags (AND logic)."""
        rituals = list(self._rituals.values())
        if tags:
            tag_set = set(tags)
            rituals = [r for r in rituals if tag_set.issubset(set(r.tags))]
        return sorted(rituals, key=lambda r: r.id)

    # ── Catalog (agent-friendly) ────────────────────────────────────────────

    def catalog(self) -> dict:
        """
        Return a JSON-serializable catalog of all artifacts.

        Suitable for agent introspection and CLI dump.
        """
        return {
            "grimoire": {
                "name": self.manifest.name,
                "version": self.manifest.version,
            },
            "spells": [
                {"id": s.id, "name": s.name, "version": s.version, "tags": s.tags}
                for s in self.list_spells()
            ],
            "runes": [
                {
                    "id": r.id,
                    "name": r.name,
                    "version": r.version,
                    "tags": r.tags,
                    "commands": [c.name for c in r.commands],
                }
                for r in self.list_runes()
            ],
            "promptlets": [{"id": p.id} for p in self.list_promptlets()],
            "rituals": [
                {"id": r.id, "name": r.name, "steps": len(r.steps)} for r in self.list_rituals()
            ],
        }
