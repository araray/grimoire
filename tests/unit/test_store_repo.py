# tests/unit/test_store_repo.py
"""Unit tests for grimoire.store.repo."""

from pathlib import Path

import pytest

from grimoire.exceptions import ArtifactNotFoundError, RepoError
from grimoire.store.repo import GrimoireRepo


class TestRepoLoading:
    """Tests for loading a grimoire repository."""

    def test_load_fixture_repo(self, grimoire_repo_dir: Path) -> None:
        repo = GrimoireRepo.load(grimoire_repo_dir)
        assert repo.manifest.name == "test-grimoire"
        assert repo.manifest.version == "0.1.0"

    def test_load_nonexistent_raises(self) -> None:
        with pytest.raises(RepoError, match="Not a directory"):
            GrimoireRepo.load("/nonexistent/path")

    def test_load_bare_repo_uses_defaults(self, tmp_path: Path) -> None:
        """A directory without grimoire.yaml should use default manifest."""
        (tmp_path / "spells").mkdir()
        repo = GrimoireRepo.load(tmp_path)
        assert repo.manifest.name == "default"


class TestSpellDiscovery:
    """Tests for spell discovery."""

    def test_spells_discovered(self, grimoire_repo_dir: Path) -> None:
        repo = GrimoireRepo.load(grimoire_repo_dir)
        spells = repo.list_spells()
        assert len(spells) >= 1
        ids = [s.id for s in spells]
        assert "examples/greet" in ids

    def test_get_spell(self, grimoire_repo_dir: Path) -> None:
        repo = GrimoireRepo.load(grimoire_repo_dir)
        spell = repo.get_spell("examples/greet")
        assert spell.name == "Greeting Spell"

    def test_get_missing_spell_raises(self, grimoire_repo_dir: Path) -> None:
        repo = GrimoireRepo.load(grimoire_repo_dir)
        with pytest.raises(ArtifactNotFoundError, match="Spell not found"):
            repo.get_spell("nonexistent/spell")

    def test_list_spells_by_tag(self, grimoire_repo_dir: Path) -> None:
        repo = GrimoireRepo.load(grimoire_repo_dir)
        spells = repo.list_spells(tags=["test"])
        assert all("test" in s.tags for s in spells)


class TestRuneDiscovery:
    """Tests for rune discovery."""

    def test_runes_discovered(self, grimoire_repo_dir: Path) -> None:
        repo = GrimoireRepo.load(grimoire_repo_dir)
        runes = repo.list_runes()
        assert len(runes) >= 1
        ids = [r.id for r in runes]
        assert "devtools/git" in ids

    def test_get_rune(self, grimoire_repo_dir: Path) -> None:
        repo = GrimoireRepo.load(grimoire_repo_dir)
        rune = repo.get_rune("devtools/git")
        assert rune.name == "Git (read-only diagnostics)"

    def test_get_missing_rune_raises(self, grimoire_repo_dir: Path) -> None:
        repo = GrimoireRepo.load(grimoire_repo_dir)
        with pytest.raises(ArtifactNotFoundError, match="Rune not found"):
            repo.get_rune("nonexistent/rune")

    def test_list_runes_by_tag(self, grimoire_repo_dir: Path) -> None:
        repo = GrimoireRepo.load(grimoire_repo_dir)
        runes = repo.list_runes(tags=["devtools"])
        assert len(runes) >= 1


class TestPromptletDiscovery:
    """Tests for promptlet discovery."""

    def test_promptlets_discovered(self, grimoire_repo_dir: Path) -> None:
        repo = GrimoireRepo.load(grimoire_repo_dir)
        promptlets = repo.list_promptlets()
        assert len(promptlets) >= 2
        ids = [p.id for p in promptlets]
        assert "safety/base_engineering" in ids
        assert "style/principal_swe" in ids

    def test_get_promptlet(self, grimoire_repo_dir: Path) -> None:
        repo = GrimoireRepo.load(grimoire_repo_dir)
        p = repo.get_promptlet("safety/base_engineering")
        assert "safety-conscious" in p.content

    def test_get_missing_promptlet_raises(self, grimoire_repo_dir: Path) -> None:
        repo = GrimoireRepo.load(grimoire_repo_dir)
        with pytest.raises(ArtifactNotFoundError, match="Promptlet not found"):
            repo.get_promptlet("nonexistent")


class TestRitualDiscovery:
    """Tests for ritual discovery."""

    def test_rituals_discovered(self, grimoire_repo_dir: Path) -> None:
        repo = GrimoireRepo.load(grimoire_repo_dir)
        rituals = repo.list_rituals()
        assert len(rituals) >= 1

    def test_get_ritual(self, grimoire_repo_dir: Path) -> None:
        repo = GrimoireRepo.load(grimoire_repo_dir)
        ritual = repo.get_ritual("rituals/greet_loop")
        assert ritual.name == "Greeting Loop"
        assert len(ritual.steps) == 1


class TestDefaultVars:
    """Tests for default variable loading."""

    def test_default_vars_loaded(self, grimoire_repo_dir: Path) -> None:
        repo = GrimoireRepo.load(grimoire_repo_dir)
        assert repo.default_vars.get("user_name") == "World"


class TestCatalog:
    """Tests for agent-friendly catalog."""

    def test_catalog_structure(self, grimoire_repo_dir: Path) -> None:
        repo = GrimoireRepo.load(grimoire_repo_dir)
        cat = repo.catalog()
        assert "grimoire" in cat
        assert "spells" in cat
        assert "runes" in cat
        assert "promptlets" in cat
        assert "rituals" in cat
        assert cat["grimoire"]["name"] == "test-grimoire"
