# tests/unit/test_rune_parser.py
"""Unit tests for grimoire.runes.parser."""

from pathlib import Path

import pytest

from grimoire.exceptions import RuneParseError, RuneValidationError
from grimoire.models import RiskLevel
from grimoire.runes.parser import parse_rune, parse_rune_file


class TestParseRune:
    """Tests for rune parsing from dicts."""

    def test_basic_rune(self, sample_rune_data: dict) -> None:
        rune = parse_rune(sample_rune_data)
        assert rune.id == "test/echo"
        assert rune.name == "Echo Tool"
        assert rune.version == "1.0.0"
        assert rune.risk_level == RiskLevel.NONE

    def test_commands_parsed(self, sample_rune_data: dict) -> None:
        rune = parse_rune(sample_rune_data)
        assert len(rune.commands) == 1
        cmd = rune.commands[0]
        assert cmd.name == "echo"
        assert cmd.summary == "Echo back input"
        assert len(cmd.params) == 1
        assert cmd.params[0].name == "message"
        assert cmd.params[0].required is True

    def test_get_command(self, sample_rune_data: dict) -> None:
        rune = parse_rune(sample_rune_data)
        cmd = rune.get_command("echo")
        assert cmd is not None
        assert cmd.name == "echo"
        assert rune.get_command("nonexistent") is None

    def test_missing_id_raises(self) -> None:
        with pytest.raises(RuneValidationError, match="must have an 'id'"):
            parse_rune({"name": "no_id", "commands": []})

    def test_invalid_data_type_raises(self) -> None:
        with pytest.raises(RuneParseError, match="must be a mapping"):
            parse_rune("not a dict")  # type: ignore[arg-type]

    def test_command_without_name_raises(self) -> None:
        data = {
            "id": "test/bad",
            "commands": [{"summary": "no name"}],
        }
        with pytest.raises(RuneValidationError, match="must have a 'name'"):
            parse_rune(data)

    def test_permissions_parsed(self) -> None:
        data = {
            "id": "test/perms",
            "permissions": ["read_fs", "network"],
            "commands": [],
        }
        rune = parse_rune(data)
        assert len(rune.permissions) == 2

    def test_content_hash_computed(self, sample_rune_data: dict) -> None:
        rune = parse_rune(sample_rune_data)
        assert rune.content_hash is not None
        assert len(rune.content_hash) == 16

    def test_deterministic_hash(self, sample_rune_data: dict) -> None:
        rune1 = parse_rune(sample_rune_data)
        rune2 = parse_rune(sample_rune_data)
        assert rune1.content_hash == rune2.content_hash

    def test_source_path_recorded(self, sample_rune_data: dict) -> None:
        rune = parse_rune(sample_rune_data, source_path="/test/echo.rune.yaml")
        assert rune.source_path == "/test/echo.rune.yaml"

    def test_return_spec(self) -> None:
        data = {
            "id": "test/ret",
            "commands": [
                {
                    "name": "get",
                    "returns": {
                        "type": "object",
                        "properties": {"value": {"type": "string"}},
                    },
                }
            ],
        }
        rune = parse_rune(data)
        assert rune.commands[0].returns is not None
        assert rune.commands[0].returns.type == "object"

    def test_examples_parsed(self) -> None:
        data = {
            "id": "test/ex",
            "commands": [
                {
                    "name": "test",
                    "examples": [
                        {"call": {"arg": "value"}, "expect": "some output"},
                    ],
                }
            ],
        }
        rune = parse_rune(data)
        assert len(rune.commands[0].examples) == 1
        assert rune.commands[0].examples[0].call == {"arg": "value"}

    def test_owasp_categories_parsed(self) -> None:
        data = {
            "id": "test/security",
            "owasp_categories": ["LLM06_excessive_agency"],
            "commands": [
                {
                    "name": "run",
                    "risk_level": "high",
                    "owasp_categories": ["LLM05_supply_chain"],
                }
            ],
        }

        rune = parse_rune(data)

        assert rune.owasp_categories == ["LLM06_excessive_agency"]
        assert rune.commands[0].owasp_categories == ["LLM05_supply_chain"]


class TestParseRuneFile:
    """Tests for file-based rune parsing."""

    def test_parse_fixture_file(self, fixtures_dir: Path) -> None:
        rune = parse_rune_file(fixtures_dir / "runes" / "git.rune.yaml")
        assert rune.id == "devtools/git"
        assert len(rune.commands) == 3
        assert rune.commands[0].name == "status"

    def test_missing_file_raises(self) -> None:
        with pytest.raises(RuneParseError, match="not found"):
            parse_rune_file("/nonexistent/rune.rune.yaml")
