# tests/unit/test_repo_search_write.py
"""
Unit tests for GrimoireRepo tag-search/discovery (WS-G3) and the spell write
API (WS-G1).

WS-G3:
    - ``list_spells(match="all"|"any")`` AND/OR semantics + invalid mode guard.
    - ``list_tags(prefix=...)`` distinct-tag vocabulary with counts.
    - ``search_spells(query, fields=...)`` case-insensitive substring search.

WS-G1:
    - ``write_spell`` writes, hot-indexes, refuses to clobber without overwrite,
      and refuses writes on read-only repos.
    - ``update_spell`` overwrites.
    - ``delete_spell`` removes file + index entry, honors ``missing_ok``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from grimoire.exceptions import ArtifactNotFoundError, RepoError
from grimoire.models import MessageBlock, MessageRole, Spell
from grimoire.store.repo import GrimoireRepo


def _bare_repo(tmp_path: Path, *, writable: bool = True) -> GrimoireRepo:
    """Create an empty, loadable grimoire repo rooted at ``tmp_path``."""
    (tmp_path / "spells").mkdir(parents=True, exist_ok=True)
    return GrimoireRepo.load(tmp_path, writable=writable)


def _spell(spell_id: str, *, tags=None, name=None, description=None) -> Spell:
    return Spell(
        id=spell_id,
        name=name or spell_id.split("/")[-1].title(),
        tags=list(tags or []),
        description=description,
        raw_blocks=[MessageBlock(role=MessageRole.SYSTEM, content=f"You are {spell_id}.")],
    )


class TestTagMatch:
    def test_match_all_is_default(self, tmp_path: Path) -> None:
        repo = _bare_repo(tmp_path)
        repo.write_spell(_spell("a", tags=["x", "y"]))
        repo.write_spell(_spell("b", tags=["x"]))
        ids = [s.id for s in repo.list_spells(tags=["x", "y"])]
        assert ids == ["a"]

    def test_match_any(self, tmp_path: Path) -> None:
        repo = _bare_repo(tmp_path)
        repo.write_spell(_spell("a", tags=["x"]))
        repo.write_spell(_spell("b", tags=["y"]))
        repo.write_spell(_spell("c", tags=["z"]))
        ids = [s.id for s in repo.list_spells(tags=["x", "y"], match="any")]
        assert ids == ["a", "b"]

    def test_invalid_match_raises(self, tmp_path: Path) -> None:
        repo = _bare_repo(tmp_path)
        with pytest.raises(ValueError, match="match mode"):
            repo.list_spells(tags=["x"], match="bogus")


class TestListTags:
    def test_counts_and_ordering(self, tmp_path: Path) -> None:
        repo = _bare_repo(tmp_path)
        repo.write_spell(_spell("a", tags=["common", "alpha"]))
        repo.write_spell(_spell("b", tags=["common", "beta"]))
        repo.write_spell(_spell("c", tags=["common"]))
        tags = repo.list_tags()
        assert tags["common"] == 3
        # Ordered by descending count then name: common(3) first.
        assert next(iter(tags.keys())) == "common"

    def test_prefix_filter(self, tmp_path: Path) -> None:
        repo = _bare_repo(tmp_path)
        repo.write_spell(_spell("a", tags=["pack:creative", "pack:api", "other"]))
        tags = repo.list_tags(prefix="pack:")
        assert set(tags.keys()) == {"pack:creative", "pack:api"}


class TestSearchSpells:
    def test_search_name_and_description(self, tmp_path: Path) -> None:
        repo = _bare_repo(tmp_path)
        repo.write_spell(_spell("a", name="Skeptic", description="challenges ideas"))
        repo.write_spell(_spell("b", name="Optimist", description="supportive"))
        assert [s.id for s in repo.search_spells("skept")] == ["a"]
        assert [s.id for s in repo.search_spells("SUPPORT")] == ["b"]

    def test_search_tags_field(self, tmp_path: Path) -> None:
        repo = _bare_repo(tmp_path)
        repo.write_spell(_spell("a", tags=["analysis"]))
        repo.write_spell(_spell("b", tags=["creative"]))
        assert [s.id for s in repo.search_spells("analy", fields=("tags",))] == ["a"]

    def test_blank_query_returns_all(self, tmp_path: Path) -> None:
        repo = _bare_repo(tmp_path)
        repo.write_spell(_spell("a"))
        repo.write_spell(_spell("b"))
        assert [s.id for s in repo.search_spells("  ")] == ["a", "b"]


class TestWriteAPI:
    def test_write_then_get(self, tmp_path: Path) -> None:
        repo = _bare_repo(tmp_path)
        path = repo.write_spell(_spell("team/reviewer", tags=["code"]))
        assert Path(path).exists()
        got = repo.get_spell("team/reviewer")
        assert got.tags == ["code"]
        assert got.source_path == str(path)  # re-parsed from disk

    def test_write_refuses_clobber(self, tmp_path: Path) -> None:
        repo = _bare_repo(tmp_path)
        repo.write_spell(_spell("dup"))
        with pytest.raises(RepoError, match="already exists"):
            repo.write_spell(_spell("dup"))

    def test_update_overwrites(self, tmp_path: Path) -> None:
        repo = _bare_repo(tmp_path)
        repo.write_spell(_spell("u", tags=["v1"]))
        repo.update_spell(_spell("u", tags=["v2"]))
        assert repo.get_spell("u").tags == ["v2"]

    def test_readonly_repo_refuses_write(self, tmp_path: Path) -> None:
        repo = _bare_repo(tmp_path, writable=False)
        with pytest.raises(RepoError, match="read-only"):
            repo.write_spell(_spell("nope"))

    def test_delete_removes_file_and_index(self, tmp_path: Path) -> None:
        repo = _bare_repo(tmp_path)
        path = repo.write_spell(_spell("gone"))
        assert repo.delete_spell("gone") is True
        assert not Path(path).exists()
        with pytest.raises(ArtifactNotFoundError):
            repo.get_spell("gone")

    def test_delete_missing_ok(self, tmp_path: Path) -> None:
        repo = _bare_repo(tmp_path)
        assert repo.delete_spell("absent", missing_ok=True) is False
        with pytest.raises(ArtifactNotFoundError):
            repo.delete_spell("absent")

    def test_persisted_file_reloads(self, tmp_path: Path) -> None:
        repo = _bare_repo(tmp_path)
        repo.write_spell(_spell("persist/here", tags=["t"]))
        # A fresh load from disk should discover the written spell.
        repo2 = GrimoireRepo.load(tmp_path)
        assert repo2.get_spell("persist/here").tags == ["t"]
