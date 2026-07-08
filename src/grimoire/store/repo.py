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
import os
import tempfile
from pathlib import Path

import yaml

from grimoire.bundles.parser import parse_bundle_file
from grimoire.exceptions import (
    ArtifactNotFoundError,
    ManifestError,
    RepoError,
)
from grimoire.models import (
    Bundle,
    GrimoireManifest,
    Promptlet,
    Ritual,
    RuneSpec,
    SkillDoc,
    Spell,
)
from grimoire.rituals.parser import parse_ritual_file
from grimoire.runes.parser import parse_rune_file
from grimoire.spells.parser import parse_spell_file, serialize_spell

logger = logging.getLogger(__name__)


def _tag_match(item_tags: set[str], wanted: set[str], match: str) -> bool:
    """
    Evaluate a tag filter against an item's tag set.

    Args:
        item_tags: The artifact's tags (as a set).
        wanted: The requested tags (as a set).
        match: ``"all"`` (AND — every requested tag must be present) or
               ``"any"`` (OR — at least one requested tag present).

    Returns:
        ``True`` if the item satisfies the filter.
    """
    if not wanted:
        return True
    if match == "any":
        return bool(item_tags & wanted)
    # default / "all"
    return wanted.issubset(item_tags)


def _validate_match(match: str) -> None:
    """Raise ``ValueError`` if ``match`` is not a recognized mode."""
    if match not in ("all", "any"):
        raise ValueError(f"Invalid tag match mode {match!r} (expected 'all' or 'any')")


class GrimoireRepo:
    """
    In-memory index of a grimoire repository.

    Usage::

        repo = GrimoireRepo.load("/path/to/grimoire")
        spell = repo.get_spell("engineering/bug_root_cause")
        runes = repo.list_runes(tags=["devtools"])
    """

    def __init__(
        self,
        root: Path,
        manifest: GrimoireManifest,
        *,
        writable: bool = True,
        strict: bool = False,
    ) -> None:
        self.root = root
        self.manifest = manifest
        # Whether write operations (write/update/delete spell) are permitted on
        # this repo. Standalone repos default to writable; the layered overlay
        # system (LayeredGrimoire) marks shipped layers read-only.
        self.writable = writable
        # Strict discovery: parse failures and duplicate ids RAISE instead of
        # being logged-and-skipped. Used for fail-loud control-plane layers
        # (llmcore/wairu load user overlays strict so a broken override aborts
        # startup instead of silently shadowing nothing).
        self.strict = strict

        self._spells: dict[str, Spell] = {}
        self._runes: dict[str, RuneSpec] = {}
        self._promptlets: dict[str, Promptlet] = {}
        self._rituals: dict[str, Ritual] = {}
        self._bundles: dict[str, Bundle] = {}
        self._skilldocs: dict[str, SkillDoc] = {}
        self._default_vars: dict[str, object] = {}

    # ── Factory ─────────────────────────────────────────────────────────────

    @classmethod
    def load(
        cls, path: str | Path, *, writable: bool = True, strict: bool = False
    ) -> "GrimoireRepo":
        """
        Load a grimoire repo from disk.

        Args:
            path: Path to the grimoire root directory.
            writable: If ``False``, the repo rejects write/update/delete
                operations (used for shipped/read-only overlay layers).
            strict: If ``True``, any artifact parse failure or duplicate id
                raises :class:`RepoError` (fail-loud) instead of the default
                log-and-skip / log-and-overwrite behavior.

        Returns:
            Populated GrimoireRepo instance.

        Raises:
            RepoError: If the path is invalid, loading fails, or (with
                ``strict=True``) any artifact fails to parse / collides.
        """
        root = Path(path).resolve()
        if not root.is_dir():
            raise RepoError(f"Not a directory: {root}")

        manifest = cls._load_manifest(root)
        repo = cls(root, manifest, writable=writable, strict=strict)

        repo._discover_promptlets()
        repo._discover_spells()
        repo._discover_runes()
        repo._discover_rituals()
        repo._discover_bundles()
        repo._discover_skilldocs()
        repo._load_default_vars()

        logger.info(
            f"Loaded grimoire '{manifest.name}' from {root}: "
            f"{len(repo._spells)} spells, {len(repo._runes)} runes, "
            f"{len(repo._promptlets)} promptlets, {len(repo._rituals)} rituals, "
            f"{len(repo._bundles)} bundles, {len(repo._skilldocs)} skilldocs"
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

    def _on_parse_error(self, kind: str, file: Path, exc: Exception) -> None:
        """Handle an artifact parse failure per the strictness policy.

        Default: log and skip (historical behavior). Strict: raise
        :class:`RepoError` naming the file and cause — the fail-loud mode
        control-plane layers rely on.
        """
        if self.strict:
            raise RepoError(f"Failed to parse {kind} {file}: {exc}") from exc
        logger.error(f"Failed to parse {kind} {file}: {exc}")

    def _on_duplicate(self, kind: str, artifact_id: str, file: Path) -> None:
        """Handle a duplicate artifact id per the strictness policy.

        Default: warn and let the later file win. With deterministic (sorted)
        discovery the winner is stable: last in (path-list order, then
        lexicographic file order). Strict: raise :class:`RepoError`.
        """
        if self.strict:
            raise RepoError(f"Duplicate {kind} id '{artifact_id}' (second file: {file})")
        logger.warning(f"Duplicate {kind} id '{artifact_id}', overwriting")

    def _discover_spells(self) -> None:
        """Find and parse all *.spell.md files (deterministic sorted order)."""
        dirs = self._resolve_paths(self.manifest.spell_paths)
        for d in dirs:
            for spell_file in sorted(d.rglob("*.spell.md")):
                try:
                    spell = parse_spell_file(spell_file)
                except Exception as e:
                    self._on_parse_error("spell", spell_file, e)
                    continue
                if spell.id in self._spells:
                    self._on_duplicate("spell", spell.id, spell_file)
                self._spells[spell.id] = spell

    def _discover_runes(self) -> None:
        """Find and parse all *.rune.yaml files (deterministic sorted order)."""
        dirs = self._resolve_paths(self.manifest.rune_paths)
        for d in dirs:
            for rune_file in sorted(d.rglob("*.rune.yaml")):
                try:
                    rune = parse_rune_file(rune_file)
                except Exception as e:
                    self._on_parse_error("rune", rune_file, e)
                    continue
                if rune.id in self._runes:
                    self._on_duplicate("rune", rune.id, rune_file)
                self._runes[rune.id] = rune

    def _discover_promptlets(self) -> None:
        """Find and load promptlet .md files (plain markdown, no frontmatter)."""
        dirs = self._resolve_paths(self.manifest.promptlet_paths)
        for d in dirs:
            for md_file in sorted(d.rglob("*.md")):
                # Skip spell files
                if md_file.name.endswith(".spell.md"):
                    continue
                # Derive ID from relative path
                rel = md_file.relative_to(d)
                promptlet_id = str(rel.with_suffix("")).replace("\\", "/")
                try:
                    content = md_file.read_text(encoding="utf-8").strip()
                except Exception as e:
                    self._on_parse_error("promptlet", md_file, e)
                    continue
                if promptlet_id in self._promptlets:
                    self._on_duplicate("promptlet", promptlet_id, md_file)
                self._promptlets[promptlet_id] = Promptlet(
                    id=promptlet_id,
                    content=content,
                    source_path=str(md_file),
                )

    def _discover_rituals(self) -> None:
        """Find and parse all *.ritual.yaml files (deterministic sorted order)."""
        dirs = self._resolve_paths(self.manifest.ritual_paths)
        for d in dirs:
            for ritual_file in sorted(d.rglob("*.ritual.yaml")):
                try:
                    ritual = parse_ritual_file(ritual_file)
                except Exception as e:
                    self._on_parse_error("ritual", ritual_file, e)
                    continue
                if ritual.id in self._rituals:
                    self._on_duplicate("ritual", ritual.id, ritual_file)
                self._rituals[ritual.id] = ritual

    def _discover_bundles(self) -> None:
        """Find and parse all *.bundle.yaml files (deterministic sorted order)."""
        dirs = self._resolve_paths(self.manifest.bundle_paths)
        for d in dirs:
            for bundle_file in sorted(d.rglob("*.bundle.yaml")):
                try:
                    bundle = parse_bundle_file(bundle_file)
                except Exception as e:
                    self._on_parse_error("bundle", bundle_file, e)
                    continue
                if bundle.id in self._bundles:
                    self._on_duplicate("bundle", bundle.id, bundle_file)
                self._bundles[bundle.id] = bundle

    def _discover_skilldocs(self) -> None:
        """Find and parse all *.skilldoc.md files (deterministic sorted order)."""
        from grimoire.skilldocs.parser import parse_skilldoc_file

        dirs = self._resolve_paths(self.manifest.skilldoc_paths)
        for d in dirs:
            for sd_file in sorted(d.rglob("*.skilldoc.md")):
                try:
                    skilldoc = parse_skilldoc_file(sd_file)
                except Exception as e:
                    self._on_parse_error("skilldoc", sd_file, e)
                    continue
                if skilldoc.id in self._skilldocs:
                    self._on_duplicate("skilldoc", skilldoc.id, sd_file)
                self._skilldocs[skilldoc.id] = skilldoc

    def _load_default_vars(self) -> None:
        """Load default variables from vars/defaults.yaml."""
        vars_path = self.root / self.manifest.vars_path
        if vars_path.exists():
            try:
                data = yaml.safe_load(vars_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._default_vars = data
            except Exception as e:
                self._on_parse_error("default vars", vars_path, e)

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

    def get_bundle(self, bundle_id: str) -> Bundle:
        """Get a bundle by ID. Raises ArtifactNotFoundError if missing."""
        if bundle_id not in self._bundles:
            raise ArtifactNotFoundError(f"Bundle not found: {bundle_id}")
        return self._bundles[bundle_id]

    def get_skilldoc(self, skilldoc_id: str) -> SkillDoc:
        """Get a SkillDoc by ID. Raises ArtifactNotFoundError if missing."""
        if skilldoc_id not in self._skilldocs:
            raise ArtifactNotFoundError(f"SkillDoc not found: {skilldoc_id}")
        return self._skilldocs[skilldoc_id]

    @property
    def default_vars(self) -> dict[str, object]:
        """Default variable values from vars/defaults.yaml."""
        return dict(self._default_vars)

    # ── Listing / Filtering ─────────────────────────────────────────────────

    def list_spells(
        self, tags: list[str] | None = None, *, match: str = "all"
    ) -> list[Spell]:
        """
        List all spells, optionally filtered by tags.

        Args:
            tags: Tags to filter by. ``None``/empty returns all spells.
            match: ``"all"`` (AND, default) or ``"any"`` (OR).
        """
        _validate_match(match)
        spells = list(self._spells.values())
        if tags:
            wanted = set(tags)
            spells = [s for s in spells if _tag_match(set(s.tags), wanted, match)]
        return sorted(spells, key=lambda s: s.id)

    def list_runes(
        self, tags: list[str] | None = None, *, match: str = "all"
    ) -> list[RuneSpec]:
        """List all runes, optionally filtered by tags (``match`` = all|any)."""
        _validate_match(match)
        runes = list(self._runes.values())
        if tags:
            wanted = set(tags)
            runes = [r for r in runes if _tag_match(set(r.tags), wanted, match)]
        return sorted(runes, key=lambda r: r.id)

    def list_promptlets(self) -> list[Promptlet]:
        """List all promptlets."""
        return sorted(self._promptlets.values(), key=lambda p: p.id)

    def list_rituals(
        self, tags: list[str] | None = None, *, match: str = "all"
    ) -> list[Ritual]:
        """List all rituals, optionally filtered by tags (``match`` = all|any)."""
        _validate_match(match)
        rituals = list(self._rituals.values())
        if tags:
            wanted = set(tags)
            rituals = [r for r in rituals if _tag_match(set(r.tags), wanted, match)]
        return sorted(rituals, key=lambda r: r.id)

    def list_bundles(
        self, tags: list[str] | None = None, *, match: str = "all"
    ) -> list[Bundle]:
        """List all bundles, optionally filtered by tags (``match`` = all|any)."""
        _validate_match(match)
        bundles = list(self._bundles.values())
        if tags:
            wanted = set(tags)
            bundles = [b for b in bundles if _tag_match(set(b.tags), wanted, match)]
        return sorted(bundles, key=lambda b: b.id)

    def list_skilldocs(
        self, tags: list[str] | None = None, *, match: str = "all"
    ) -> list[SkillDoc]:
        """List all SkillDocs, optionally filtered by tags (``match`` = all|any)."""
        _validate_match(match)
        docs = list(self._skilldocs.values())
        if tags:
            wanted = set(tags)
            docs = [d for d in docs if _tag_match(set(d.tags), wanted, match)]
        return sorted(docs, key=lambda d: d.id)

    # ── Tag vocabulary & text search (WS-G3) ────────────────────────────────

    def list_tags(self, prefix: str | None = None) -> dict[str, int]:
        """
        Return the distinct spell-tag vocabulary with usage counts.

        Counts the number of spells carrying each tag. Intended to power tag
        chip-bars and to bias wizard tag suggestions toward the existing
        vocabulary (Convergence WS-D).

        Args:
            prefix: If given, only tags starting with this (case-insensitive)
                prefix are returned.

        Returns:
            Mapping ``{tag: count}`` ordered by descending count then tag name.
        """
        counts: dict[str, int] = {}
        for spell in self._spells.values():
            for tag in spell.tags:
                counts[tag] = counts.get(tag, 0) + 1
        if prefix:
            pre = prefix.lower()
            counts = {t: c for t, c in counts.items() if t.lower().startswith(pre)}
        return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))

    def search_spells(
        self,
        query: str,
        *,
        fields: tuple[str, ...] = ("name", "description", "tags"),
    ) -> list[Spell]:
        """
        Case-insensitive substring search over spells.

        Args:
            query: Substring to match. Empty/blank query returns all spells.
            fields: Which spell fields to search. Supported:
                ``name``, ``description``, ``tags``, ``id``.

        Returns:
            Matching spells sorted by ``id``.
        """
        q = (query or "").strip().lower()
        if not q:
            return self.list_spells()

        def _hit(spell: Spell) -> bool:
            for f in fields:
                if f == "name" and q in (spell.name or "").lower():
                    return True
                if f == "description" and q in (spell.description or "").lower():
                    return True
                if f == "id" and q in spell.id.lower():
                    return True
                if f == "tags" and any(q in t.lower() for t in spell.tags):
                    return True
            return False

        return sorted((s for s in self._spells.values() if _hit(s)), key=lambda s: s.id)

    # ── Write API (WS-G1) ────────────────────────────────────────────────────

    def _spell_path(self, spell_id: str) -> Path:
        """Compute the on-disk path for a spell id within this repo's primary spell dir."""
        spell_dir = self.manifest.spell_paths[0] if self.manifest.spell_paths else "spells/"
        return self.root / spell_dir / f"{spell_id}.spell.md"

    def _ensure_writable(self) -> None:
        if not self.writable:
            raise RepoError(f"Grimoire repo at {self.root} is read-only; refusing to write")

    def write_spell(self, spell: Spell, *, overwrite: bool = False) -> Path:
        """
        Serialize and write a spell to disk, then hot-insert it into the index.

        The file is placed at ``<root>/<spell_paths[0]>/<spell.id>.spell.md`` and
        written atomically (temp file + ``os.replace``). After writing, the spell
        is re-parsed from disk so ``source_path``/``content_hash`` reflect the
        persisted form and the in-memory index stays consistent.

        Args:
            spell: The spell to persist (validated by the ``Spell`` model).
            overwrite: If ``False`` (default) and the target file already exists,
                a :class:`RepoError` is raised. ``update_spell`` passes ``True``.

        Returns:
            The path the spell was written to.

        Raises:
            RepoError: If the repo is read-only or the file exists and
                ``overwrite`` is ``False``.
        """
        self._ensure_writable()
        target = self._spell_path(spell.id)
        if target.exists() and not overwrite:
            raise RepoError(
                f"Spell file already exists: {target} (use overwrite=True / update_spell)"
            )

        target.parent.mkdir(parents=True, exist_ok=True)
        text = serialize_spell(spell)

        # Atomic write: temp file in the same directory, then os.replace.
        fd, tmp_name = tempfile.mkstemp(
            dir=str(target.parent), prefix=".grimoire-", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
            os.replace(tmp_name, target)
        except Exception:
            # Best-effort cleanup of the temp file on failure.
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

        # Re-parse from disk to capture source_path + recomputed hash, then index.
        parsed = parse_spell_file(target)
        self._spells[parsed.id] = parsed
        logger.info("Wrote spell '%s' -> %s", spell.id, target)
        return target

    def update_spell(self, spell: Spell) -> Path:
        """Write a spell, overwriting any existing file with the same id."""
        return self.write_spell(spell, overwrite=True)

    def delete_spell(self, spell_id: str, *, missing_ok: bool = False) -> bool:
        """
        Delete a spell file and drop it from the index.

        Args:
            spell_id: The spell id to delete.
            missing_ok: If ``True``, return ``False`` instead of raising when the
                spell is not present.

        Returns:
            ``True`` if a spell was deleted, ``False`` if missing and ``missing_ok``.

        Raises:
            RepoError: If the repo is read-only.
            ArtifactNotFoundError: If the spell is absent and ``missing_ok`` is False.
        """
        self._ensure_writable()
        spell = self._spells.get(spell_id)
        if spell is None:
            if missing_ok:
                return False
            raise ArtifactNotFoundError(f"Spell not found: {spell_id}")

        # Prefer the recorded source_path; fall back to the canonical location.
        path = Path(spell.source_path) if spell.source_path else self._spell_path(spell_id)
        if path.exists():
            path.unlink()
        self._spells.pop(spell_id, None)
        logger.info("Deleted spell '%s' (%s)", spell_id, path)
        return True

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
            "bundles": [
                {"id": b.id, "name": b.name, "version": b.version, "tags": b.tags}
                for b in self.list_bundles()
            ],
            "skilldocs": [
                {"id": d.id, "name": d.name, "tags": d.tags, "sections": len(d.sections)}
                for d in self.list_skilldocs()
            ],
        }

    # ── Facade accessors (spec §11) ─────────────────────────────────────────

    @property
    def prompts(self) -> "_PromptAccessor":
        """Facade for prompt operations (spec §11 ``repo.prompts.*``)."""
        return _PromptAccessor(self)

    @property
    def skills(self) -> "_SkillAccessor":
        """Facade for skill operations (spec §11 ``repo.skills.*``)."""
        return _SkillAccessor(self)


# ── Facade classes (spec §11) ────────────────────────────────────────────────


class _PromptAccessor:
    """Thin facade over GrimoireRepo for prompt operations."""

    def __init__(self, repo: GrimoireRepo) -> None:
        self._repo = repo

    def list(self, tags: list[str] | None = None) -> list[Spell]:
        """List spells with optional tag filtering."""
        return self._repo.list_spells(tags=tags)

    def get(self, spell_id: str) -> Spell:
        """Retrieve a spell by ID."""
        return self._repo.get_spell(spell_id)

    def bundles(self, tags: list[str] | None = None) -> list[Bundle]:
        """List bundles with optional tag filtering."""
        return self._repo.list_bundles(tags=tags)


class _SkillAccessor:
    """Thin facade over GrimoireRepo for skill operations."""

    def __init__(self, repo: GrimoireRepo) -> None:
        self._repo = repo

    def contracts(self, tags: list[str] | None = None) -> list[RuneSpec]:
        """List rune contracts with optional tag filtering."""
        return self._repo.list_runes(tags=tags)

    def docs(self, tags: list[str] | None = None) -> list[SkillDoc]:
        """List SkillDocs with optional tag filtering."""
        return self._repo.list_skilldocs(tags=tags)

    def get_contract(self, rune_id: str) -> RuneSpec:
        """Retrieve a rune contract by ID."""
        return self._repo.get_rune(rune_id)

    def get_doc(self, skilldoc_id: str) -> SkillDoc:
        """Retrieve a SkillDoc by ID."""
        return self._repo.get_skilldoc(skilldoc_id)
