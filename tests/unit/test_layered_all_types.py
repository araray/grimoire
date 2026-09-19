# tests/unit/test_layered_all_types.py
"""
0.4.0 layered-composition tests (WS-G2b).

Covers the control-plane enablement work:
- LayeredGrimoire resolution for ALL artifact types (not just spells)
- CompositeRepoView satisfying the GrimoireRepo duck type
- Grimoire.layered() facade parity (conjure/tool_schemas/catalog/validate/
  resolve_layer/reload) + write rejection on the composite
- wairu-compat: runtime rune registration against a layered facade, cache
  invalidation, and drop-on-reload semantics
- Deterministic + strict repo loading
- Lazy federation import (no llmcore at import time)
- Facade catalog/tool_schemas caches + engine static-builtin cache
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from grimoire import Grimoire
from grimoire.exceptions import ArtifactNotFoundError, RepoError
from grimoire.layered import CompositeRepoView, LayeredGrimoire
from grimoire.store.repo import GrimoireRepo

FIXTURE_REPO = Path(__file__).parent.parent / "fixtures" / "grimoire_repo"


# ---------------------------------------------------------------------------
# Overlay fixture: a higher-precedence layer overriding base artifacts
# ---------------------------------------------------------------------------


@pytest.fixture()
def overlay_root(tmp_path: Path) -> Path:
    """A small overlay repo that overrides one artifact of several types."""
    root = tmp_path / "overlay"
    (root / "spells").mkdir(parents=True)
    (root / "runes" / "contracts").mkdir(parents=True)
    (root / "rituals").mkdir(parents=True)
    (root / "spells" / "promptlets").mkdir(parents=True)
    (root / "vars").mkdir(parents=True)

    (root / "grimoire.yaml").write_text(
        textwrap.dedent(
            """\
            name: overlay
            version: 9.9.9
            spell_paths: [spells/]
            rune_paths: [runes/contracts/]
            ritual_paths: [rituals/]
            promptlet_paths: [spells/promptlets/]
            vars_path: vars/defaults.yaml
            """
        )
    )

    # Overrides the base repo's agentic/iterative_debug_loop spell id.
    (root / "spells" / "debug_loop_override.spell.md").write_text(
        textwrap.dedent(
            """\
            ---
            id: agentic/iterative_debug_loop
            name: Overridden Debug Loop
            version: 2.0.0
            tags: [agentic, override]
            variables:
              problem_statement:
                type: multiline
                required: true
            ---

            # SYSTEM
            OVERLAY WINS: {{ problem_statement }}
            """
        )
    )

    # Overrides the base repo's devtools/git rune id.
    (root / "runes" / "contracts" / "git_override.rune.yaml").write_text(
        textwrap.dedent(
            """\
            ---
            id: devtools/git
            name: Git (overlay)
            version: 2.0.0
            description: Overridden git rune.
            tags: [devtools, override]
            risk_level: medium
            commands:
              - name: status
                summary: Overridden status
                params: []
                side_effects: []
            """
        )
    )

    # Overrides the base repo's rituals/greet_loop ritual id.
    (root / "rituals" / "greet_override.ritual.yaml").write_text(
        textwrap.dedent(
            """\
            id: rituals/greet_loop
            name: Overridden Greeting Loop
            version: 2.0.0
            steps:
              - id: step_1
                spell: examples/greet
                conjure:
                  vars:
                    inherit: true
            """
        )
    )

    # A NEW promptlet only the overlay has.
    (root / "spells" / "promptlets" / "overlay_note.md").write_text("overlay promptlet")

    # Override one default var + add a new one.
    (root / "vars" / "defaults.yaml").write_text("user_name: Overlay\noverlay_only: yes\n")

    return root


@pytest.fixture()
def layered(overlay_root: Path) -> LayeredGrimoire:
    return LayeredGrimoire.from_roots(
        [("base", FIXTURE_REPO, False), ("overlay", overlay_root, False)],
        scaffold_writable=False,
    )


# ---------------------------------------------------------------------------
# LayeredGrimoire: all-artifact-type resolution
# ---------------------------------------------------------------------------


class TestLayeredAllTypes:
    def test_spell_override_wins(self, layered: LayeredGrimoire):
        spell = layered.get_spell("agentic/iterative_debug_loop")
        assert spell.name == "Overridden Debug Loop"
        assert layered.resolve_layer("agentic/iterative_debug_loop", "spell") == "overlay"

    def test_rune_override_wins(self, layered: LayeredGrimoire):
        rune = layered.get_rune("devtools/git")
        assert rune.name == "Git (overlay)"
        assert str(rune.risk_level) in ("RiskLevel.MEDIUM", "medium")
        assert layered.resolve_layer("devtools/git", "rune") == "overlay"

    def test_rune_from_base_still_resolves(self, layered: LayeredGrimoire):
        rune = layered.get_rune("wairu/shell")
        assert rune is not None
        assert layered.resolve_layer("wairu/shell", "rune") == "base"

    def test_ritual_override_wins(self, layered: LayeredGrimoire):
        ritual = layered.get_ritual("rituals/greet_loop")
        assert ritual.name == "Overridden Greeting Loop"
        assert layered.resolve_layer("rituals/greet_loop", "ritual") == "overlay"

    def test_promptlet_merge(self, layered: LayeredGrimoire):
        assert layered.get_promptlet("overlay_note").content == "overlay promptlet"
        # Base promptlets still visible.
        assert layered.get_promptlet("safety/base_engineering") is not None

    def test_bundle_and_skilldoc_passthrough(self, layered: LayeredGrimoire):
        base = GrimoireRepo.load(FIXTURE_REPO)
        assert {b.id for b in layered.list_bundles()} == set(base._bundles)
        assert {d.id for d in layered.list_skilldocs()} == set(base._skilldocs)

    def test_default_vars_merge_per_key(self, layered: LayeredGrimoire):
        merged = layered.default_vars
        assert merged["user_name"] == "Overlay"  # overlay key wins
        assert merged["overlay_only"] is True or merged["overlay_only"] == "yes"

    def test_unknown_kind_raises(self, layered: LayeredGrimoire):
        with pytest.raises(ValueError, match="Unknown artifact kind"):
            layered.resolve_layer("x", "wand")

    def test_missing_artifact_raises(self, layered: LayeredGrimoire):
        with pytest.raises(ArtifactNotFoundError):
            layered.get_rune("no/such_rune")


# ---------------------------------------------------------------------------
# CompositeRepoView + Grimoire.layered() facade parity
# ---------------------------------------------------------------------------


class TestLayeredFacade:
    def test_composite_view_duck_type(self, layered: LayeredGrimoire):
        view = layered.composite_view()
        assert isinstance(view, CompositeRepoView)
        assert isinstance(view, GrimoireRepo)  # the load-bearing property
        assert view.writable is False
        assert view.get_rune("devtools/git").name == "Git (overlay)"
        assert "agentic/iterative_debug_loop" in view._spells
        assert view.default_vars["user_name"] == "Overlay"
        assert view.resolve_layer("devtools/git", "rune") == "overlay"

    def test_composite_rejects_writes(self, layered: LayeredGrimoire):
        view = layered.composite_view()
        spell = view.get_spell("agentic/iterative_debug_loop")
        with pytest.raises(RepoError, match="read-only"):
            view.write_spell(spell, overwrite=True)

    def test_facade_layered_reads_and_conjure(self, overlay_root: Path):
        g = Grimoire.layered(
            [("base", FIXTURE_REPO, False), ("overlay", overlay_root, False)]
        )
        assert g.layers == ["base", "overlay"]
        assert g.resolve_layer("devtools/git", "rune") == "overlay"
        # Conjure resolves the OVERLAY spell body.
        result = g.conjure_spell(
            "agentic/iterative_debug_loop", variables={"problem_statement": "X"}
        )
        text = "\n".join(block.content for block in result.blocks)
        assert "OVERLAY WINS: X" in text

    def test_facade_tool_schemas_reflect_overlay(self, overlay_root: Path):
        g = Grimoire.layered(
            [("base", FIXTURE_REPO, False), ("overlay", overlay_root, False)]
        )
        schemas = g.tool_schemas()
        names = [s["function"]["name"] for s in schemas]
        # Overlay git rune has exactly ONE command (status): the base rune's
        # other commands must NOT leak through.
        git_tools = [n for n in names if n.startswith("devtools__git__")]
        assert git_tools == ["devtools__git__status"]

    def test_facade_validate_layer(self, overlay_root: Path):
        g = Grimoire.layered(
            [("base", FIXTURE_REPO, False), ("overlay", overlay_root, False)]
        )
        result = g.validate(layer="overlay")
        assert result is not None
        with pytest.raises(ValueError):
            g.validate(layer="nope")

    def test_single_root_facade_rejects_layer_apis(self):
        g = Grimoire(FIXTURE_REPO)
        assert g.layers is None
        with pytest.raises(RuntimeError):
            g.resolve_layer("devtools/git", "rune")
        with pytest.raises(RuntimeError):
            g.validate(layer="base")

    def test_wairu_runtime_rune_registration_and_reload(self, overlay_root: Path):
        """wairu-compat: runtime runes land in the composite view, are served
        through (cache-invalidated) tool_schemas, and drop on reload()."""
        from grimoire.bind.wairu import register_wairu_plugin_tools

        g = Grimoire.layered(
            [("base", FIXTURE_REPO, False), ("overlay", overlay_root, False)]
        )
        _ = g.tool_schemas()  # prime the cache

        class FakeTool:
            name = "frobnicate"
            description = "Frobnicates things"
            parameters: dict = {"type": "object", "properties": {}}  # noqa: RUF012
            requires_approval = False
            risk_level = "low"

        runes = register_wairu_plugin_tools(g, [FakeTool()], plugin_name="testplug")
        assert len(runes) == 1
        names = [s["function"]["name"] for s in g.tool_schemas()]
        assert any("frobnicate" in n for n in names), names  # cache invalidated

        g.reload()  # runtime runes are documented to drop on reload
        names_after = [s["function"]["name"] for s in g.tool_schemas()]
        assert not any("frobnicate" in n for n in names_after)
        # Layered state survives the reload.
        assert g.resolve_layer("devtools/git", "rune") == "overlay"


# ---------------------------------------------------------------------------
# Deterministic + strict loading
# ---------------------------------------------------------------------------


def _write_min_repo(root: Path, spell_bodies: dict[str, str]) -> None:
    (root / "spells").mkdir(parents=True)
    (root / "grimoire.yaml").write_text("name: t\nspell_paths: [spells/]\n")
    for fname, body in spell_bodies.items():
        (root / "spells" / fname).write_text(body)


def _spell(spell_id: str, name: str) -> str:
    return textwrap.dedent(
        f"""\
        ---
        id: {spell_id}
        name: {name}
        ---

        # USER
        hello
        """
    )


class TestDeterministicStrictLoad:
    def test_duplicate_last_lexicographic_wins(self, tmp_path: Path):
        _write_min_repo(
            tmp_path,
            {
                "a_first.spell.md": _spell("dup/id", "First"),
                "z_last.spell.md": _spell("dup/id", "Last"),
            },
        )
        repo = GrimoireRepo.load(tmp_path)  # non-strict: warn + overwrite
        assert repo.get_spell("dup/id").name == "Last"

    def test_strict_duplicate_raises(self, tmp_path: Path):
        _write_min_repo(
            tmp_path,
            {
                "a_first.spell.md": _spell("dup/id", "First"),
                "z_last.spell.md": _spell("dup/id", "Last"),
            },
        )
        with pytest.raises(RepoError, match="Duplicate spell id"):
            GrimoireRepo.load(tmp_path, strict=True)

    def test_strict_parse_failure_raises(self, tmp_path: Path):
        _write_min_repo(tmp_path, {"broken.spell.md": "not: [valid frontmatter"})
        with pytest.raises(RepoError, match="Failed to parse spell"):
            GrimoireRepo.load(tmp_path, strict=True)
        # Non-strict: skipped with a logged error.
        repo = GrimoireRepo.load(tmp_path)
        assert repo._spells == {}

    def test_from_roots_strict_names_layer(self, tmp_path: Path):
        _write_min_repo(tmp_path / "bad", {"broken.spell.md": "not: [valid"})
        with pytest.raises(RepoError, match="layer 'user' failed to load"):
            LayeredGrimoire.from_roots(
                [("base", FIXTURE_REPO, False), ("user", tmp_path / "bad", False)],
                scaffold_writable=False,
                strict=True,
            )


# ---------------------------------------------------------------------------
# Lazy federation import (cycle hazard)
# ---------------------------------------------------------------------------


class TestLazyFederation:
    def test_import_federation_does_not_import_llmcore(self):
        """grimoire.federation must not pull llmcore at import time — llmcore
        depends on grimoire (0.4.0+), so this edge must stay lazy."""
        code = (
            "import sys\n"
            "import grimoire.federation\n"
            "bad = [m for m in sys.modules if m.split('.')[0] == 'llmcore']\n"
            "assert not bad, f'llmcore imported eagerly: {bad}'\n"
            "print('lazy OK')\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, timeout=60
        )
        assert proc.returncode == 0, proc.stderr
        assert "lazy OK" in proc.stdout

    def test_reexport_still_works(self):
        # llmcore IS installed in this venv; the lazy re-export must serve it.
        from grimoire.federation import EcosystemEvent, SourceSystem

        assert EcosystemEvent is not None
        assert SourceSystem is not None


# ---------------------------------------------------------------------------
# Caches
# ---------------------------------------------------------------------------


class TestCaches:
    def test_catalog_memoized_and_invalidated(self):
        g = Grimoire(FIXTURE_REPO)
        first = g.catalog()
        assert g.catalog() is first  # memoized
        g.invalidate_caches()
        assert g.catalog() is not first

    def test_tool_schemas_unfiltered_memoized(self):
        g = Grimoire(FIXTURE_REPO)
        first = g.tool_schemas()
        assert g.tool_schemas() is first
        # Filtered calls bypass the cache.
        filtered = g.tool_schemas(tags=["devtools"])
        assert filtered is not first
        g.reload()
        assert g.tool_schemas() is not first

    def test_engine_static_builtins_cached(self):
        g = Grimoire(FIXTURE_REPO)
        engine = g._engine
        snapshot = engine._static_builtins
        # Conjuring must not recompute the static builtin dict.
        spell = g.get_spell("agentic/iterative_debug_loop")
        engine.conjure(spell, variables={"problem_statement": "x"}, strict=False)
        assert engine._static_builtins is snapshot
        engine.refresh_builtins()
        assert engine._static_builtins is not snapshot
