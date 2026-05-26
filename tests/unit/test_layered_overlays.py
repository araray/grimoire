# tests/unit/test_layered_overlays.py
"""
Unit tests for :class:`grimoire.layered.LayeredGrimoire` (WS-G2).

Covers:
    - Construction validation (empty / duplicate names).
    - ``from_roots`` scaffolding of writable layers.
    - Read precedence (highest layer wins) + ``resolve_layer``.
    - Overlay shadow + un-shadow on delete.
    - Merged ``list_spells`` / ``list_tags`` / ``search_spells``.
    - Writable-layer targeting (named + default highest-writable).
    - Read-only layer write/delete guards.
    - ``reload`` picks up on-disk changes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from grimoire.exceptions import ArtifactNotFoundError, RepoError
from grimoire.layered import GrimoireLayer, LayeredGrimoire
from grimoire.models import MessageBlock, MessageRole, Spell
from grimoire.store.repo import GrimoireRepo


def _spell(spell_id: str, *, name=None, tags=None, attributes=None, body="hi") -> Spell:
    return Spell(
        id=spell_id,
        name=name or spell_id.split("/")[-1].title(),
        tags=list(tags or []),
        attributes=dict(attributes or {}),
        raw_blocks=[MessageBlock(role=MessageRole.SYSTEM, content=body)],
    )


@pytest.fixture
def layered(tmp_path: Path) -> LayeredGrimoire:
    """A 3-layer stack: shipped(ro) < admin(rw) < user(rw), one shipped spell."""
    ship = tmp_path / "shipped"
    (ship / "spells").mkdir(parents=True)
    (ship / "grimoire.yaml").write_text("name: shipped\nversion: 0.1.0\n", encoding="utf-8")
    # Seed shipped via a writable load, then re-load read-only.
    seed = GrimoireRepo.load(ship, writable=True)
    seed.write_spell(
        _spell(
            "convergence/personas/skeptic",
            name="Skeptic",
            tags=["convergence", "pack:creative"],
            attributes={"color": "#333", "constraints": ["be terse"]},
            body="You are a skeptic.",
        )
    )
    return LayeredGrimoire.from_roots(
        [
            ("shipped", str(ship), False),
            ("admin", str(tmp_path / "admin"), True),
            ("user", str(tmp_path / "user"), True),
        ]
    )


class TestConstruction:
    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one"):
            LayeredGrimoire([])

    def test_duplicate_names_raise(self, tmp_path: Path) -> None:
        (tmp_path / "spells").mkdir()
        repo = GrimoireRepo.load(tmp_path)
        with pytest.raises(ValueError, match="unique"):
            LayeredGrimoire(
                [
                    GrimoireLayer("dup", repo, False),
                    GrimoireLayer("dup", repo, True),
                ]
            )

    def test_from_roots_scaffolds_writable(self, tmp_path: Path) -> None:
        ship = tmp_path / "ship"
        (ship / "spells").mkdir(parents=True)
        lg = LayeredGrimoire.from_roots(
            [("shipped", str(ship), False), ("user", str(tmp_path / "user"), True)]
        )
        # The user layer dir + manifest should have been scaffolded.
        assert (tmp_path / "user" / "grimoire.yaml").exists()
        assert (tmp_path / "user" / "spells").is_dir()
        assert {layer.name for layer in lg.layers} == {"shipped", "user"}

    def test_from_roots_missing_readonly_raises(self, tmp_path: Path) -> None:
        with pytest.raises(RepoError, match="does not exist"):
            LayeredGrimoire.from_roots([("shipped", str(tmp_path / "nope"), False)])


class TestPrecedence:
    def test_shipped_wins_when_alone(self, layered: LayeredGrimoire) -> None:
        assert layered.resolve_layer("convergence/personas/skeptic") == "shipped"
        spell = layered.get_spell("convergence/personas/skeptic")
        assert spell.name == "Skeptic"
        assert spell.attributes["color"] == "#333"

    def test_user_overlay_shadows_shipped(self, layered: LayeredGrimoire) -> None:
        layered.write_spell(
            _spell(
                "convergence/personas/skeptic",
                name="Skeptic (mine)",
                tags=["convergence", "custom"],
                attributes={"color": "#f00"},
            ),
            layer="user",
        )
        assert layered.resolve_layer("convergence/personas/skeptic") == "user"
        assert layered.get_spell("convergence/personas/skeptic").name == "Skeptic (mine)"
        # list_spells reflects the resolved (overlaid) view, deduped by id.
        ids = [s.id for s in layered.list_spells()]
        assert ids.count("convergence/personas/skeptic") == 1

    def test_default_write_targets_highest_writable(self, layered: LayeredGrimoire) -> None:
        layered.write_spell(_spell("convergence/personas/new", name="New"))
        assert layered.resolve_layer("convergence/personas/new") == "user"

    def test_admin_overlay_below_user(self, layered: LayeredGrimoire) -> None:
        layered.write_spell(_spell("convergence/personas/skeptic", name="Admin"), layer="admin")
        assert layered.resolve_layer("convergence/personas/skeptic") == "admin"
        layered.write_spell(_spell("convergence/personas/skeptic", name="User"), layer="user")
        assert layered.resolve_layer("convergence/personas/skeptic") == "user"

    def test_delete_overlay_unshadows(self, layered: LayeredGrimoire) -> None:
        layered.write_spell(_spell("convergence/personas/skeptic", name="Mine"), layer="user")
        assert layered.get_spell("convergence/personas/skeptic").name == "Mine"
        layered.delete_spell("convergence/personas/skeptic", layer="user")
        # Falls back to the shipped definition.
        assert layered.resolve_layer("convergence/personas/skeptic") == "shipped"
        assert layered.get_spell("convergence/personas/skeptic").name == "Skeptic"

    def test_delete_default_picks_highest_writable_holder(self, layered: LayeredGrimoire) -> None:
        layered.write_spell(_spell("convergence/personas/skeptic", name="A"), layer="admin")
        layered.write_spell(_spell("convergence/personas/skeptic", name="U"), layer="user")
        # No layer => delete from highest writable holder (user), revealing admin.
        layered.delete_spell("convergence/personas/skeptic")
        assert layered.resolve_layer("convergence/personas/skeptic") == "admin"


class TestMergedQueries:
    def test_list_tags_over_resolved_view(self, layered: LayeredGrimoire) -> None:
        layered.write_spell(
            _spell("convergence/personas/skeptic", tags=["convergence", "custom"]),
            layer="user",
        )
        tags = layered.list_tags()
        # The shipped 'pack:creative' tag is shadowed by the user overlay.
        assert "custom" in tags
        assert "pack:creative" not in tags

    def test_search_over_resolved_view(self, layered: LayeredGrimoire) -> None:
        layered.write_spell(_spell("convergence/personas/optimist", name="Optimist"), layer="user")
        ids = [s.id for s in layered.search_spells("optimist")]
        assert ids == ["convergence/personas/optimist"]

    def test_match_any(self, layered: LayeredGrimoire) -> None:
        layered.write_spell(_spell("convergence/personas/x", tags=["alpha"]), layer="user")
        ids = [s.id for s in layered.list_spells(["alpha", "nope"], match="any")]
        assert "convergence/personas/x" in ids


class TestGuards:
    def test_write_to_readonly_layer_rejected(self, layered: LayeredGrimoire) -> None:
        with pytest.raises(RepoError, match="read-only"):
            layered.write_spell(_spell("x"), layer="shipped")

    def test_delete_from_readonly_layer_rejected(self, layered: LayeredGrimoire) -> None:
        with pytest.raises(RepoError, match="read-only"):
            layered.delete_spell("convergence/personas/skeptic", layer="shipped")

    def test_unknown_layer_raises(self, layered: LayeredGrimoire) -> None:
        with pytest.raises(ValueError, match="Unknown grimoire layer"):
            layered.write_spell(_spell("x"), layer="ghost")

    def test_delete_absent_missing_ok(self, layered: LayeredGrimoire) -> None:
        assert layered.delete_spell("nope/none", missing_ok=True) is False
        with pytest.raises(ArtifactNotFoundError):
            layered.delete_spell("nope/none")

    def test_no_writable_layer(self, tmp_path: Path) -> None:
        ship = tmp_path / "s"
        (ship / "spells").mkdir(parents=True)
        lg = LayeredGrimoire.from_roots([("shipped", str(ship), False)])
        with pytest.raises(RepoError, match="No writable layer"):
            lg.write_spell(_spell("x"))


class TestReload:
    def test_reload_picks_up_external_change(self, layered: LayeredGrimoire) -> None:
        user_layer = next(layer for layer in layered.layers if layer.name == "user")
        # Write a spell directly to the user layer repo on disk (bypassing the stack).
        user_layer.repo.write_spell(_spell("convergence/personas/added", name="Added"))
        layered.reload()
        assert layered.get_spell("convergence/personas/added").name == "Added"
