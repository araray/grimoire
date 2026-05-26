# src/grimoire/layered.py
"""
Layered grimoire overlays (WS-G2).

This module composes multiple :class:`~grimoire.store.repo.GrimoireRepo`
instances into a single resolver with deterministic precedence, so that a
*shipped* (read-only) spell library can be overridden by *admin* and *per-user*
overlays without ever mutating the shipped files on disk.

Precedence model
----------------
Layers are ordered **lowest → highest precedence**. By Convergence convention::

    [ shipped (read-only), global-admin (writable), per-user (writable) ]

When the same spell ``id`` exists in more than one layer, the **highest-precedence**
layer wins for reads (``get_spell``/``list_spells``). Writes target a named
writable layer (or, by default, the highest-precedence writable layer); deleting
an overlay spell *un-shadows* any lower-layer spell with the same id.

Design notes
------------
- This is the "option B" from the v0.8.0 plan: a thin resolver that holds
  ordered repos rather than physically merging them. Each layer keeps its own
  ``grimoire.yaml`` and its own on-disk tree.
- Grimoire never interprets spell ``attributes``; the resolver only composes and
  filters. Application semantics (personas/modes) live in the consumer.
- The resolver is safe for concurrent reads. It is *not* safe for concurrent
  mutation; serialize writes externally if needed.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

from grimoire.exceptions import ArtifactNotFoundError, RepoError
from grimoire.models import Spell
from grimoire.store.repo import GrimoireRepo, _tag_match, _validate_match

logger = logging.getLogger(__name__)


@dataclass
class GrimoireLayer:
    """
    One layer in a :class:`LayeredGrimoire`.

    Attributes:
        name: Stable identifier for the layer (e.g. ``"shipped"``, ``"admin"``,
            ``"user"``). Used to target writes and to report spell origin.
        repo: The loaded :class:`GrimoireRepo` backing this layer.
        writable: Whether writes may target this layer. Must agree with
            ``repo.writable``.
    """

    name: str
    repo: GrimoireRepo
    writable: bool = False


class LayeredGrimoire:
    """
    Compose ordered grimoire layers into a single precedence-aware resolver.

    Args:
        layers: Layers ordered **lowest → highest** precedence. Must be
            non-empty and have unique names.

    Raises:
        ValueError: If ``layers`` is empty or names are not unique.
    """

    def __init__(self, layers: Sequence[GrimoireLayer]) -> None:
        if not layers:
            raise ValueError("LayeredGrimoire requires at least one layer")
        names = [layer.name for layer in layers]
        if len(names) != len(set(names)):
            raise ValueError(f"Layer names must be unique, got {names}")
        # Keep insertion order = ascending precedence.
        self._layers: list[GrimoireLayer] = list(layers)
        self._by_name: dict[str, GrimoireLayer] = {layer.name: layer for layer in layers}

    # ── Construction helpers ─────────────────────────────────────────────────

    @staticmethod
    def ensure_layer_root(path: str | Path, *, name: str | None = None) -> Path:
        """
        Scaffold a writable grimoire layer root on demand.

        Creates the directory, a ``spells/`` subdir, and a minimal
        ``grimoire.yaml`` manifest if absent (idempotent). Used to create
        per-user / admin overlay roots lazily.

        Args:
            path: The layer root directory.
            name: Optional manifest name (defaults to the directory name).

        Returns:
            The resolved layer root path.
        """
        root = Path(path)
        root.mkdir(parents=True, exist_ok=True)
        (root / "spells").mkdir(parents=True, exist_ok=True)
        manifest = root / "grimoire.yaml"
        if not manifest.exists():
            manifest.write_text(
                yaml.safe_dump(
                    {"name": name or root.name, "version": "0.1.0"},
                    sort_keys=False,
                    default_flow_style=False,
                ),
                encoding="utf-8",
            )
        return root

    @classmethod
    def from_roots(
        cls,
        roots: Sequence[tuple[str, str | Path, bool]],
        *,
        scaffold_writable: bool = True,
    ) -> "LayeredGrimoire":
        """
        Build a :class:`LayeredGrimoire` from ``(name, path, writable)`` triples.

        Args:
            roots: Ordered ``(name, path, writable)`` triples, lowest →
                highest precedence.
            scaffold_writable: If ``True`` (default), writable roots that do not
                yet exist are scaffolded via :meth:`ensure_layer_root`. Read-only
                roots must already exist.

        Returns:
            A composed :class:`LayeredGrimoire`.

        Raises:
            RepoError: If a non-writable root does not exist.
        """
        layers: list[GrimoireLayer] = []
        for name, path, writable in roots:
            p = Path(path)
            if writable and scaffold_writable:
                cls.ensure_layer_root(p, name=name)
            if not p.is_dir():
                raise RepoError(f"Grimoire layer '{name}' root does not exist: {p}")
            repo = GrimoireRepo.load(p, writable=writable)
            layers.append(GrimoireLayer(name=name, repo=repo, writable=writable))
        return cls(layers)

    # ── Introspection ─────────────────────────────────────────────────────────

    @property
    def layers(self) -> list[GrimoireLayer]:
        """Layers in ascending precedence order (copy)."""
        return list(self._layers)

    @property
    def writable_layers(self) -> list[GrimoireLayer]:
        """Writable layers in ascending precedence order."""
        return [layer for layer in self._layers if layer.writable]

    def _highest_writable(self) -> GrimoireLayer:
        """Return the highest-precedence writable layer, or raise."""
        for layer in reversed(self._layers):
            if layer.writable:
                return layer
        raise RepoError("No writable layer available for write/delete operations")

    def _layer(self, name: str) -> GrimoireLayer:
        if name not in self._by_name:
            raise ValueError(f"Unknown grimoire layer: {name!r}")
        return self._by_name[name]

    # ── Resolution / reads ─────────────────────────────────────────────────────

    def _merged_spells(self) -> dict[str, Spell]:
        """
        Merge spells across layers by id, with higher precedence overriding.

        Returns:
            Mapping ``{id: Spell}`` reflecting the resolved view.
        """
        merged: dict[str, Spell] = {}
        for layer in self._layers:  # low → high; later overrides
            for spell in layer.repo._spells.values():
                merged[spell.id] = spell
        return merged

    def get_spell(self, spell_id: str) -> Spell:
        """
        Resolve a spell by id (highest-precedence layer wins).

        Raises:
            ArtifactNotFoundError: If no layer defines the id.
        """
        for layer in reversed(self._layers):  # high → low
            spell = layer.repo._spells.get(spell_id)
            if spell is not None:
                return spell
        raise ArtifactNotFoundError(f"Spell not found in any layer: {spell_id}")

    def resolve_layer(self, spell_id: str) -> str:
        """
        Return the name of the layer a spell resolves from.

        Raises:
            ArtifactNotFoundError: If no layer defines the id.
        """
        for layer in reversed(self._layers):
            if spell_id in layer.repo._spells:
                return layer.name
        raise ArtifactNotFoundError(f"Spell not found in any layer: {spell_id}")

    def list_spells(
        self, tags: list[str] | None = None, *, match: str = "all"
    ) -> list[Spell]:
        """List resolved spells, optionally filtered by tags (``match`` = all|any)."""
        _validate_match(match)
        spells = list(self._merged_spells().values())
        if tags:
            wanted = set(tags)
            spells = [s for s in spells if _tag_match(set(s.tags), wanted, match)]
        return sorted(spells, key=lambda s: s.id)

    def list_tags(self, prefix: str | None = None) -> dict[str, int]:
        """Distinct spell-tag vocabulary with counts, over the resolved view."""
        counts: dict[str, int] = {}
        for spell in self._merged_spells().values():
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
        """Case-insensitive substring search over the resolved spell view."""
        q = (query or "").strip().lower()
        spells = list(self._merged_spells().values())
        if not q:
            return sorted(spells, key=lambda s: s.id)

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

        return sorted((s for s in spells if _hit(s)), key=lambda s: s.id)

    # ── Writes ──────────────────────────────────────────────────────────────────

    def write_spell(
        self, spell: Spell, *, layer: str | None = None, overwrite: bool = False
    ) -> Path:
        """
        Write a spell to a writable layer.

        Args:
            spell: The spell to persist.
            layer: Target layer name. If ``None``, the highest-precedence
                writable layer is used.
            overwrite: Passed through to the layer repo's ``write_spell``.

        Returns:
            The path written.

        Raises:
            RepoError: If the target layer is not writable or none exists.
            ValueError: If a named layer is unknown.
        """
        target = self._layer(layer) if layer is not None else self._highest_writable()
        if not target.writable:
            raise RepoError(f"Layer {target.name!r} is read-only; cannot write spell")
        return target.repo.write_spell(spell, overwrite=overwrite)

    def update_spell(self, spell: Spell, *, layer: str | None = None) -> Path:
        """Write a spell to a writable layer, overwriting if present."""
        return self.write_spell(spell, layer=layer, overwrite=True)

    def delete_spell(
        self, spell_id: str, *, layer: str | None = None, missing_ok: bool = False
    ) -> bool:
        """
        Delete a spell from a writable layer (un-shadowing lower layers).

        Args:
            spell_id: The spell id to delete.
            layer: Target layer name. If ``None``, deletes from the
                highest-precedence writable layer that contains the spell.
            missing_ok: If ``True``, return ``False`` instead of raising when no
                writable layer holds the spell.

        Returns:
            ``True`` if a spell was deleted.

        Raises:
            RepoError: If a named layer is read-only or none is writable.
            ArtifactNotFoundError: If absent from writable layers and not ``missing_ok``.
            ValueError: If a named layer is unknown.
        """
        if layer is not None:
            target = self._layer(layer)
            if not target.writable:
                raise RepoError(f"Layer {target.name!r} is read-only; cannot delete spell")
            return target.repo.delete_spell(spell_id, missing_ok=missing_ok)

        # No layer specified: delete from the highest writable layer holding it.
        for cand in reversed(self._layers):
            if cand.writable and spell_id in cand.repo._spells:
                return cand.repo.delete_spell(spell_id)
        if missing_ok:
            return False
        raise ArtifactNotFoundError(
            f"Spell {spell_id!r} not present in any writable layer"
        )

    # ── Maintenance ──────────────────────────────────────────────────────────────

    def reload(self) -> None:
        """Reload every layer's repo from disk, preserving order/writability."""
        rebuilt: list[GrimoireLayer] = []
        for layer in self._layers:
            repo = GrimoireRepo.load(layer.repo.root, writable=layer.writable)
            rebuilt.append(GrimoireLayer(name=layer.name, repo=repo, writable=layer.writable))
        self._layers = rebuilt
        self._by_name = {layer.name: layer for layer in rebuilt}
        logger.info("LayeredGrimoire reloaded %d layers", len(rebuilt))

    def __repr__(self) -> str:
        descr = ", ".join(
            f"{layer.name}({'rw' if layer.writable else 'ro'}:{len(layer.repo._spells)})"
            for layer in self._layers
        )
        return f"LayeredGrimoire([{descr}])"
