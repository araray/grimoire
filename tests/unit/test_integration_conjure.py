# tests/unit/test_integration_conjure.py
"""
Integration test: full conjure workflow.

Loads the fixture grimoire repo, conjures a spell with includes,
variables, and rune introspection, and verifies the full output.
"""

from pathlib import Path

from grimoire.conjure.engine import ConjureEngine
from grimoire.store.repo import GrimoireRepo


class TestFullConjureWorkflow:
    """End-to-end conjure tests using the fixture repository."""

    def test_conjure_greet_spell(self, grimoire_repo_dir: Path) -> None:
        """Conjure the greeting spell with all layers."""
        repo = GrimoireRepo.load(grimoire_repo_dir)
        spell = repo.get_spell("examples/greet")

        engine = ConjureEngine(
            promptlets={p.id: p for p in repo.list_promptlets()},
            runes={r.id: r for r in repo.list_runes()},
        )

        result = engine.conjure(
            spell,
            variables={"user_name": "Arara"},
            defaults=repo.default_vars,
        )

        # Should have SYSTEM and USER blocks
        assert len(result.blocks) == 2

        # SYSTEM block should contain included promptlet content
        system_content = result.blocks[0].content
        assert "safety-conscious" in system_content
        assert "multilingual" in system_content

        # USER block should have variable substituted
        user_content = result.blocks[1].content
        assert "Arara" in user_content
        assert "English" in user_content  # default value

    def test_conjure_with_override(self, grimoire_repo_dir: Path) -> None:
        """Explicit variable overrides grimoire defaults."""
        repo = GrimoireRepo.load(grimoire_repo_dir)
        spell = repo.get_spell("examples/greet")

        engine = ConjureEngine(
            promptlets={p.id: p for p in repo.list_promptlets()},
        )

        result = engine.conjure(
            spell,
            variables={"user_name": "Test", "language": "Spanish"},
            defaults=repo.default_vars,
        )

        user_content = result.blocks[1].content
        assert "Test" in user_content
        assert "Spanish" in user_content

    def test_conjure_provenance_complete(self, grimoire_repo_dir: Path) -> None:
        """Verify provenance tracks variables, includes, and timestamps."""
        repo = GrimoireRepo.load(grimoire_repo_dir)
        spell = repo.get_spell("examples/greet")

        engine = ConjureEngine(
            promptlets={p.id: p for p in repo.list_promptlets()},
        )

        result = engine.conjure(
            spell,
            variables={"user_name": "Prov"},
            defaults=repo.default_vars,
        )

        prov = result.provenance
        assert prov.spell_id == "examples/greet"
        assert prov.spell_hash is not None
        assert "user_name" in prov.variables_used
        assert prov.variables_used["user_name"] == "Prov"
        assert "safety/base_engineering" in prov.includes_resolved
        assert prov.timestamp is not None

    def test_conjure_to_openai_format(self, grimoire_repo_dir: Path) -> None:
        """Export as OpenAI message format."""
        repo = GrimoireRepo.load(grimoire_repo_dir)
        spell = repo.get_spell("examples/greet")

        engine = ConjureEngine(
            promptlets={p.id: p for p in repo.list_promptlets()},
        )

        result = engine.conjure(
            spell,
            variables={"user_name": "OAI"},
            defaults=repo.default_vars,
        )

        messages = result.to_messages(fmt="openai")
        assert isinstance(messages, list)
        assert all("role" in m and "content" in m for m in messages)
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    def test_conjure_to_anthropic_format(self, grimoire_repo_dir: Path) -> None:
        """Export as Anthropic message format (merges system blocks)."""
        repo = GrimoireRepo.load(grimoire_repo_dir)
        spell = repo.get_spell("examples/greet")

        engine = ConjureEngine(
            promptlets={p.id: p for p in repo.list_promptlets()},
        )

        result = engine.conjure(
            spell,
            variables={"user_name": "Anth"},
            defaults=repo.default_vars,
        )

        messages = result.to_messages(fmt="anthropic")
        assert isinstance(messages, list)
        # Should have system and user
        roles = [m["role"] for m in messages]
        assert "system" in roles
        assert "user" in roles

    def test_conjure_deterministic(self, grimoire_repo_dir: Path) -> None:
        """Same inputs produce identical outputs."""
        repo = GrimoireRepo.load(grimoire_repo_dir)
        spell = repo.get_spell("examples/greet")

        engine = ConjureEngine(
            promptlets={p.id: p for p in repo.list_promptlets()},
        )

        vars_dict = {"user_name": "Det"}
        r1 = engine.conjure(spell, variables=vars_dict, defaults=repo.default_vars)
        r2 = engine.conjure(spell, variables=vars_dict, defaults=repo.default_vars)

        assert r1.blocks[0].content == r2.blocks[0].content
        assert r1.blocks[1].content == r2.blocks[1].content
        assert r1.provenance.spell_hash == r2.provenance.spell_hash
