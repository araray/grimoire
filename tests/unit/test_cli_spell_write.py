# tests/unit/test_cli_spell_write.py
"""
CLI tests for the ``grimoire spell new|edit|rm`` write verbs (WS-G1).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from grimoire.cli import cli
from grimoire.spells.parser import parse_spell_file


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def repo_dir(tmp_path: Path) -> Path:
    (tmp_path / "spells").mkdir()
    (tmp_path / "grimoire.yaml").write_text("name: t\nversion: 0.1.0\n", encoding="utf-8")
    return tmp_path


def _args(repo_dir: Path, *rest: str) -> list[str]:
    return ["--repo", str(repo_dir), *rest]


class TestSpellNew:
    def test_new_writes_spell_file(self, runner: CliRunner, repo_dir: Path) -> None:
        result = runner.invoke(
            cli,
            _args(
                repo_dir,
                "spell",
                "new",
                "team/reviewer",
                "--name",
                "Reviewer",
                "--tags",
                "code,quality",
                "--description",
                "Reviews code",
                "--attributes",
                '{"color": "#0a0"}',
                "--system",
                "You are a reviewer.",
                "--user",
                "Review: {{ diff }}",
            ),
        )
        assert result.exit_code == 0, result.output
        path = repo_dir / "spells" / "team" / "reviewer.spell.md"
        assert path.exists()
        spell = parse_spell_file(path)
        assert spell.name == "Reviewer"
        assert spell.tags == ["code", "quality"]
        assert spell.attributes == {"color": "#0a0"}
        assert {b.role.value for b in spell.raw_blocks} == {"SYSTEM", "USER"}

    def test_new_requires_a_block(self, runner: CliRunner, repo_dir: Path) -> None:
        result = runner.invoke(
            cli, _args(repo_dir, "spell", "new", "x/y", "--name", "Y")
        )
        assert result.exit_code != 0
        assert "required" in result.output.lower()

    def test_new_refuses_clobber(self, runner: CliRunner, repo_dir: Path) -> None:
        base = ["spell", "new", "dup", "--system", "hi"]
        assert runner.invoke(cli, _args(repo_dir, *base)).exit_code == 0
        result = runner.invoke(cli, _args(repo_dir, *base))
        assert result.exit_code != 0
        assert "exists" in result.output.lower()

    def test_new_bad_attributes_json(self, runner: CliRunner, repo_dir: Path) -> None:
        result = runner.invoke(
            cli,
            _args(repo_dir, "spell", "new", "x/y", "--system", "hi", "--attributes", "[1,2]"),
        )
        assert result.exit_code != 0
        assert "json object" in result.output.lower()


class TestSpellEdit:
    def test_edit_updates_fields_preserves_body(self, runner: CliRunner, repo_dir: Path) -> None:
        runner.invoke(
            cli,
            _args(
                repo_dir,
                "spell",
                "new",
                "e/one",
                "--tags",
                "a",
                "--system",
                "Original system.",
            ),
        )
        result = runner.invoke(
            cli,
            _args(
                repo_dir,
                "spell",
                "edit",
                "e/one",
                "--tags",
                "a,b",
                "--description",
                "Now described",
            ),
        )
        assert result.exit_code == 0, result.output
        spell = parse_spell_file(repo_dir / "spells" / "e" / "one.spell.md")
        assert spell.tags == ["a", "b"]
        assert spell.description == "Now described"
        # Body preserved (only fields supplied were changed).
        assert any("Original system." in b.content for b in spell.raw_blocks)

    def test_edit_missing_spell(self, runner: CliRunner, repo_dir: Path) -> None:
        result = runner.invoke(cli, _args(repo_dir, "spell", "edit", "no/such", "--name", "X"))
        assert result.exit_code != 0


class TestSpellRm:
    def test_rm_with_yes(self, runner: CliRunner, repo_dir: Path) -> None:
        runner.invoke(cli, _args(repo_dir, "spell", "new", "r/one", "--system", "hi"))
        path = repo_dir / "spells" / "r" / "one.spell.md"
        assert path.exists()
        result = runner.invoke(cli, _args(repo_dir, "spell", "rm", "r/one", "--yes"))
        assert result.exit_code == 0, result.output
        assert not path.exists()

    def test_rm_missing(self, runner: CliRunner, repo_dir: Path) -> None:
        result = runner.invoke(cli, _args(repo_dir, "spell", "rm", "no/such", "--yes"))
        assert result.exit_code != 0
