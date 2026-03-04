# tests/unit/test_ritual_parser.py
"""
Unit tests for grimoire.rituals.parser.

Tests cover:
- Valid ritual parsing from dict and file
- Step parsing with all supported fields
- Error handling: missing id, invalid structure, bad YAML
- Extended model fields (description, tags)
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from grimoire.exceptions import RitualParseError
from grimoire.models import Ritual, RitualStep
from grimoire.rituals.parser import parse_ritual, parse_ritual_file

# ── Fixtures ──────────────────────────────────────────────────────────────────


MINIMAL_RITUAL_DATA: dict = {
    "id": "rituals/test_minimal",
    "name": "Minimal Ritual",
    "steps": [],
}

FULL_RITUAL_DATA: dict = {
    "id": "rituals/test_full",
    "name": "Full Ritual",
    "version": "2.0.0",
    "description": "A complete ritual for testing",
    "tags": ["engineering", "test"],
    "steps": [
        {
            "id": "step_1",
            "spell": "examples/greet",
            "description": "First step",
            "conjure": {"vars": {"inherit": True}},
            "output": {"capture": "greeting", "format": "text"},
        },
        {
            "id": "step_2",
            "when": "{{ greeting.contains('Hello') }}",
            "spell": "examples/greet",
            "conjure": {"ask_missing": True},
        },
        {
            "id": "step_3",
            "description": "No-op step",
            # No spell — should be accepted
        },
    ],
}


# ── parse_ritual (from dict) ───────────────────────────────────────────────────


class TestParseRitual:
    """Tests for parse_ritual() accepting a pre-loaded dict."""

    def test_minimal_ritual(self) -> None:
        ritual = parse_ritual(MINIMAL_RITUAL_DATA)
        assert isinstance(ritual, Ritual)
        assert ritual.id == "rituals/test_minimal"
        assert ritual.name == "Minimal Ritual"
        assert ritual.version == "1.0.0"  # default
        assert ritual.steps == []

    def test_full_ritual_fields(self) -> None:
        ritual = parse_ritual(FULL_RITUAL_DATA)
        assert ritual.id == "rituals/test_full"
        assert ritual.version == "2.0.0"
        assert ritual.description == "A complete ritual for testing"
        assert ritual.tags == ["engineering", "test"]
        assert len(ritual.steps) == 3

    def test_step_fields_step1(self) -> None:
        ritual = parse_ritual(FULL_RITUAL_DATA)
        s1 = ritual.steps[0]
        assert isinstance(s1, RitualStep)
        assert s1.id == "step_1"
        assert s1.spell == "examples/greet"
        assert s1.description == "First step"
        assert s1.when is None
        assert s1.conjure == {"vars": {"inherit": True}}
        assert s1.output == {"capture": "greeting", "format": "text"}

    def test_step_fields_step2(self) -> None:
        ritual = parse_ritual(FULL_RITUAL_DATA)
        s2 = ritual.steps[1]
        assert s2.id == "step_2"
        assert s2.when == "{{ greeting.contains('Hello') }}"
        assert s2.conjure == {"ask_missing": True}

    def test_step_without_spell(self) -> None:
        ritual = parse_ritual(FULL_RITUAL_DATA)
        s3 = ritual.steps[2]
        assert s3.spell is None

    def test_source_path_stored(self, tmp_path: Path) -> None:
        p = tmp_path / "test.ritual.yaml"
        ritual = parse_ritual(MINIMAL_RITUAL_DATA, source_path=p)
        assert ritual.source_path == str(p)

    def test_source_path_none(self) -> None:
        ritual = parse_ritual(MINIMAL_RITUAL_DATA)
        assert ritual.source_path is None

    def test_default_name_from_id(self) -> None:
        data = {"id": "rituals/no_name", "steps": []}
        ritual = parse_ritual(data)
        assert ritual.name == "rituals/no_name"

    def test_tags_default_empty(self) -> None:
        ritual = parse_ritual(MINIMAL_RITUAL_DATA)
        assert ritual.tags == []


# ── Error handling ────────────────────────────────────────────────────────────


class TestParseRitualErrors:
    """Tests for parse_ritual() error handling."""

    def test_missing_id_raises(self) -> None:
        with pytest.raises(RitualParseError, match="missing required 'id'"):
            parse_ritual({"name": "No ID", "steps": []})

    def test_non_dict_input_raises(self) -> None:
        with pytest.raises(RitualParseError, match="must be a mapping"):
            parse_ritual("not a dict")  # type: ignore[arg-type]

    def test_steps_not_list_raises(self) -> None:
        with pytest.raises(RitualParseError, match="must be a list"):
            parse_ritual({"id": "x", "name": "X", "steps": "not a list"})

    def test_step_not_dict_raises(self) -> None:
        with pytest.raises(RitualParseError, match="must be a mapping"):
            parse_ritual({"id": "x", "name": "X", "steps": ["string_step"]})

    def test_step_missing_id_raises(self) -> None:
        with pytest.raises(RitualParseError, match="missing required 'id'"):
            parse_ritual({"id": "x", "name": "X", "steps": [{"spell": "foo"}]})


# ── parse_ritual_file ─────────────────────────────────────────────────────────


class TestParseRitualFile:
    """Tests for parse_ritual_file() loading from disk."""

    def test_parse_greet_loop_fixture(self, grimoire_repo_dir: Path) -> None:
        fixture = grimoire_repo_dir / "rituals" / "greet_loop.ritual.yaml"
        ritual = parse_ritual_file(fixture)
        assert ritual.id == "rituals/greet_loop"
        assert ritual.name == "Greeting Loop"
        assert len(ritual.steps) >= 1
        assert ritual.steps[0].spell == "examples/greet"

    def test_parse_rca_loop_fixture(self, grimoire_repo_dir: Path) -> None:
        fixture = grimoire_repo_dir / "rituals" / "rca_loop.ritual.yaml"
        ritual = parse_ritual_file(fixture)
        assert ritual.id == "rituals/rca_loop"
        assert len(ritual.steps) == 2
        assert ritual.tags == ["engineering", "debugging"]
        # step_2 should have a when condition
        assert ritual.steps[1].when is not None

    def test_parse_roundtrip(self, tmp_path: Path) -> None:
        """Write a ritual to YAML and parse it back."""
        data = {
            "id": "rituals/roundtrip",
            "name": "Roundtrip Test",
            "steps": [{"id": "s1", "spell": "foo/bar", "output": {"capture": "result"}}],
        }
        p = tmp_path / "roundtrip.ritual.yaml"
        p.write_text(yaml.dump(data), encoding="utf-8")
        ritual = parse_ritual_file(p)
        assert ritual.id == "rituals/roundtrip"
        assert ritual.steps[0].output == {"capture": "result"}

    def test_file_not_found_raises(self, tmp_path: Path) -> None:
        with pytest.raises(RitualParseError, match="not found"):
            parse_ritual_file(tmp_path / "nonexistent.ritual.yaml")

    def test_invalid_yaml_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.ritual.yaml"
        bad.write_text(": bad: yaml: [", encoding="utf-8")
        with pytest.raises(RitualParseError, match="Invalid YAML"):
            parse_ritual_file(bad)

    def test_non_mapping_yaml_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "list.ritual.yaml"
        bad.write_text("- item1\n- item2\n", encoding="utf-8")
        with pytest.raises(RitualParseError, match="must be a mapping"):
            parse_ritual_file(bad)
