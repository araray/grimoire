# tests/unit/test_cli.py
"""Unit tests for the Grimoire CLI using Click's CliRunner."""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from grimoire.cli import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def repo_args(grimoire_repo_dir: Path) -> list[str]:
    """Common args pointing to the fixture repo."""
    return ["--repo", str(grimoire_repo_dir)]


class TestInit:
    """Tests for ``grimoire init``."""

    def test_init_creates_skeleton(self, runner: CliRunner, tmp_path: Path) -> None:
        target = tmp_path / "new_grimoire"
        result = runner.invoke(cli, ["init", str(target), "--name", "test-grim"])
        assert result.exit_code == 0
        assert "Initialized grimoire" in result.output
        assert (target / "grimoire.yaml").exists()
        assert (target / "spells" / "promptlets").is_dir()
        assert (target / "runes" / "contracts").is_dir()
        assert (target / "vars" / "defaults.yaml").exists()

    def test_init_starter_spell_created(self, runner: CliRunner, tmp_path: Path) -> None:
        target = tmp_path / "grim2"
        runner.invoke(cli, ["init", str(target)])
        spell = target / "spells" / "templates" / "examples" / "hello.spell.md"
        assert spell.exists()

    def test_init_refuses_overwrite(self, runner: CliRunner, tmp_path: Path) -> None:
        target = tmp_path / "grim3"
        runner.invoke(cli, ["init", str(target)])
        result = runner.invoke(cli, ["init", str(target)])
        assert "already exists" in result.output

    def test_init_force_overwrites(self, runner: CliRunner, tmp_path: Path) -> None:
        target = tmp_path / "grim4"
        runner.invoke(cli, ["init", str(target)])
        result = runner.invoke(cli, ["init", str(target), "--force"])
        assert result.exit_code == 0


class TestSpellCommands:
    """Tests for ``grimoire spell`` subcommands."""

    def test_spell_list(self, runner: CliRunner, repo_args: list[str]) -> None:
        result = runner.invoke(cli, [*repo_args, "spell", "list"])
        assert result.exit_code == 0
        assert "examples/greet" in result.output

    def test_spell_list_json(self, runner: CliRunner, repo_args: list[str]) -> None:
        result = runner.invoke(cli, [*repo_args, "spell", "list", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert any(s["id"] == "examples/greet" for s in data)

    def test_spell_list_tag_filter(self, runner: CliRunner, repo_args: list[str]) -> None:
        result = runner.invoke(cli, [*repo_args, "spell", "list", "--tags", "test"])
        assert result.exit_code == 0
        assert "examples/greet" in result.output

    def test_spell_show(self, runner: CliRunner, repo_args: list[str]) -> None:
        result = runner.invoke(cli, [*repo_args, "spell", "show", "examples/greet"])
        assert result.exit_code == 0
        assert "Greeting Spell" in result.output
        assert "user_name" in result.output

    def test_spell_show_json(self, runner: CliRunner, repo_args: list[str]) -> None:
        result = runner.invoke(cli, [*repo_args, "spell", "show", "examples/greet", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["id"] == "examples/greet"

    def test_spell_show_not_found(self, runner: CliRunner, repo_args: list[str]) -> None:
        result = runner.invoke(cli, [*repo_args, "spell", "show", "nonexistent"])
        assert result.exit_code != 0

    def test_spell_vars(self, runner: CliRunner, repo_args: list[str]) -> None:
        result = runner.invoke(cli, [*repo_args, "spell", "vars", "examples/greet"])
        assert result.exit_code == 0
        assert "user_name" in result.output
        assert "language" in result.output

    def test_spell_vars_json(self, runner: CliRunner, repo_args: list[str]) -> None:
        result = runner.invoke(cli, [*repo_args, "spell", "vars", "examples/greet", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "user_name" in data


class TestRuneCommands:
    """Tests for ``grimoire rune`` subcommands."""

    def test_rune_list(self, runner: CliRunner, repo_args: list[str]) -> None:
        result = runner.invoke(cli, [*repo_args, "rune", "list"])
        assert result.exit_code == 0
        assert "devtools/git" in result.output

    def test_rune_list_json(self, runner: CliRunner, repo_args: list[str]) -> None:
        result = runner.invoke(cli, [*repo_args, "rune", "list", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert any(r["id"] == "devtools/git" for r in data)

    def test_rune_show(self, runner: CliRunner, repo_args: list[str]) -> None:
        result = runner.invoke(cli, [*repo_args, "rune", "show", "devtools/git"])
        assert result.exit_code == 0
        assert "Git" in result.output
        assert "status" in result.output

    def test_rune_show_json(self, runner: CliRunner, repo_args: list[str]) -> None:
        result = runner.invoke(cli, [*repo_args, "rune", "show", "devtools/git", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["id"] == "devtools/git"

    def test_rune_validate(self, runner: CliRunner, repo_args: list[str]) -> None:
        result = runner.invoke(cli, [*repo_args, "rune", "validate"])
        assert result.exit_code == 0

    def test_rune_validate_specific(self, runner: CliRunner, repo_args: list[str]) -> None:
        result = runner.invoke(cli, [*repo_args, "rune", "validate", "devtools/git"])
        assert result.exit_code == 0


class TestConjureCommand:
    """Tests for ``grimoire conjure``."""

    def test_conjure_text(self, runner: CliRunner, repo_args: list[str]) -> None:
        result = runner.invoke(
            cli,
            [
                *repo_args,
                "--set",
                "user_name=TestUser",
                "conjure",
                "examples/greet",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "TestUser" in result.output
        assert "# SYSTEM" in result.output
        assert "# USER" in result.output

    def test_conjure_openai_format(self, runner: CliRunner, repo_args: list[str]) -> None:
        result = runner.invoke(
            cli,
            [
                *repo_args,
                "--format",
                "openai",
                "--set",
                "user_name=OAI",
                "conjure",
                "examples/greet",
            ],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert data[0]["role"] == "system"

    def test_conjure_json_format(self, runner: CliRunner, repo_args: list[str]) -> None:
        result = runner.invoke(
            cli,
            [
                *repo_args,
                "--format",
                "json",
                "--set",
                "user_name=JSON",
                "conjure",
                "examples/greet",
            ],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "messages" in data

    def test_conjure_with_provenance(self, runner: CliRunner, repo_args: list[str]) -> None:
        result = runner.invoke(
            cli,
            [
                *repo_args,
                "--set",
                "user_name=Prov",
                "conjure",
                "examples/greet",
                "--provenance",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "PROVENANCE" in result.output
        assert "examples/greet" in result.output

    def test_conjure_json_with_provenance(self, runner: CliRunner, repo_args: list[str]) -> None:
        result = runner.invoke(
            cli,
            [
                *repo_args,
                "--format",
                "json",
                "--set",
                "user_name=JP",
                "conjure",
                "examples/greet",
                "--provenance",
            ],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "provenance" in data
        assert data["provenance"]["spell_id"] == "examples/greet"

    def test_conjure_not_found(self, runner: CliRunner, repo_args: list[str]) -> None:
        result = runner.invoke(cli, [*repo_args, "conjure", "nonexistent"])
        assert result.exit_code != 0

    def test_conjure_to_file(self, runner: CliRunner, repo_args: list[str], tmp_path: Path) -> None:
        out_file = tmp_path / "output.txt"
        result = runner.invoke(
            cli,
            [
                *repo_args,
                "--out",
                str(out_file),
                "--set",
                "user_name=File",
                "conjure",
                "examples/greet",
            ],
        )
        assert result.exit_code == 0, result.output
        content = out_file.read_text()
        assert "File" in content

    def test_conjure_no_strict(self, runner: CliRunner, repo_args: list[str]) -> None:
        """Non-strict mode: user_name gets resolved from defaults, but we can
        verify the greet spell renders without error even with no explicit vars."""
        result = runner.invoke(
            cli,
            [
                *repo_args,
                "conjure",
                "examples/greet",
                "--no-strict",
            ],
        )
        assert result.exit_code == 0
        # user_name resolved from default_vars ("World"), language from spell default ("English")
        assert "World" in result.output
        assert "English" in result.output


class TestDoctorCommand:
    """Tests for ``grimoire doctor``."""

    def test_doctor(self, runner: CliRunner, repo_args: list[str]) -> None:
        result = runner.invoke(cli, [*repo_args, "doctor"])
        assert result.exit_code == 0 or result.exit_code == 1
        assert "Diagnosing" in result.output
        assert "Spells:" in result.output

    def test_doctor_bad_repo(self, runner: CliRunner, tmp_path: Path) -> None:
        result = runner.invoke(cli, ["--repo", str(tmp_path / "nope"), "doctor"])
        assert result.exit_code != 0


class TestGlobalOptions:
    """Tests for global CLI options."""

    def test_version(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output

    def test_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "grimoire" in result.output
        assert "conjure" in result.output

    def test_set_vars_parsing(self, runner: CliRunner, repo_args: list[str]) -> None:
        """Test that --set key=value works correctly."""
        result = runner.invoke(
            cli,
            [
                *repo_args,
                "--set",
                "user_name=SetTest",
                "conjure",
                "examples/greet",
            ],
        )
        assert result.exit_code == 0
        assert "SetTest" in result.output
