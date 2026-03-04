# tests/unit/test_spell_parser.py
"""Unit tests for grimoire.spells.parser."""

from pathlib import Path

import pytest

from grimoire.exceptions import SpellParseError, SpellValidationError
from grimoire.models import MessageRole, VariableType
from grimoire.spells.parser import parse_spell, parse_spell_file


class TestSplitFrontmatter:
    """Tests for YAML front-matter extraction."""

    def test_valid_frontmatter(self, sample_spell_text: str) -> None:
        spell = parse_spell(sample_spell_text)
        assert spell.id == "test/simple"
        assert spell.name == "Simple Test Spell"
        assert spell.version == "1.0.0"

    def test_missing_opening_delimiter(self) -> None:
        with pytest.raises(SpellParseError, match="must start with YAML front-matter"):
            parse_spell("no frontmatter here\n# USER\nhello")

    def test_missing_closing_delimiter(self) -> None:
        with pytest.raises(SpellParseError, match="No closing"):
            parse_spell("---\nid: test\nname: test\n")

    def test_invalid_yaml(self) -> None:
        with pytest.raises(SpellParseError, match="Invalid YAML"):
            parse_spell("---\n: invalid: yaml: [[[broken\n---\n# USER\nhello")


class TestParseBlocks:
    """Tests for message block parsing."""

    def test_system_and_user_blocks(self, sample_spell_text: str) -> None:
        spell = parse_spell(sample_spell_text)
        assert len(spell.raw_blocks) == 2
        assert spell.raw_blocks[0].role == MessageRole.SYSTEM
        assert spell.raw_blocks[1].role == MessageRole.USER

    def test_all_block_types(self) -> None:
        text = """\
---
id: test/all_blocks
name: All Blocks
---

# SYSTEM
System content.

# DEVELOPER
Developer content.

# USER
User content.

# ASSISTANT_PREFILL
Prefill content.
"""
        spell = parse_spell(text)
        assert len(spell.raw_blocks) == 4
        roles = [b.role for b in spell.raw_blocks]
        assert roles == [
            MessageRole.SYSTEM,
            MessageRole.DEVELOPER,
            MessageRole.USER,
            MessageRole.ASSISTANT_PREFILL,
        ]

    def test_no_blocks_uses_user_fallback(self) -> None:
        text = """\
---
id: test/no_headers
name: No Headers
---

Just some content without role headers.
"""
        spell = parse_spell(text)
        assert len(spell.raw_blocks) == 1
        assert spell.raw_blocks[0].role == MessageRole.USER

    def test_empty_blocks_skipped(self) -> None:
        text = """\
---
id: test/empty
name: Empty
---

# SYSTEM

# USER
Actual content here.
"""
        spell = parse_spell(text)
        # SYSTEM block has no content, should be skipped
        assert len(spell.raw_blocks) == 1
        assert spell.raw_blocks[0].role == MessageRole.USER


class TestParseVariables:
    """Tests for variable schema parsing."""

    def test_typed_variables(self, sample_spell_text: str) -> None:
        spell = parse_spell(sample_spell_text)
        assert "topic" in spell.variables
        assert spell.variables["topic"].type == VariableType.STRING
        assert spell.variables["topic"].required is True

    def test_optional_with_default(self, sample_spell_text: str) -> None:
        spell = parse_spell(sample_spell_text)
        assert "detail" in spell.variables
        assert spell.variables["detail"].required is False
        assert spell.variables["detail"].default == "brief"

    def test_choice_variable(self) -> None:
        text = """\
---
id: test/choice
name: Choice
variables:
  color:
    type: choice
    choices: [red, green, blue]
---

# USER
Pick {{ color }}.
"""
        spell = parse_spell(text)
        assert spell.variables["color"].type == VariableType.CHOICE
        assert spell.variables["color"].choices == ["red", "green", "blue"]

    def test_choice_without_choices_raises(self) -> None:
        text = """\
---
id: test/bad_choice
name: Bad Choice
variables:
  color:
    type: choice
---

# USER
Pick {{ color }}.
"""
        with pytest.raises(SpellValidationError, match="must specify 'choices'"):
            parse_spell(text)

    def test_required_variables_helper(self, sample_spell_text: str) -> None:
        spell = parse_spell(sample_spell_text)
        req = spell.required_variables()
        assert "topic" in req
        assert "detail" not in req

    def test_optional_variables_helper(self, sample_spell_text: str) -> None:
        spell = parse_spell(sample_spell_text)
        opt = spell.optional_variables()
        assert "detail" in opt
        assert "topic" not in opt


class TestSpellMetadata:
    """Tests for spell metadata handling."""

    def test_missing_id_raises(self) -> None:
        with pytest.raises(SpellValidationError, match="must include 'id'"):
            parse_spell("---\nname: no_id\n---\n# USER\nhello")

    def test_content_hash_computed(self, sample_spell_text: str) -> None:
        spell = parse_spell(sample_spell_text)
        assert spell.content_hash is not None
        assert len(spell.content_hash) == 16

    def test_deterministic_hash(self, sample_spell_text: str) -> None:
        spell1 = parse_spell(sample_spell_text)
        spell2 = parse_spell(sample_spell_text)
        assert spell1.content_hash == spell2.content_hash

    def test_source_path_recorded(self) -> None:
        text = "---\nid: test/path\nname: Path\n---\n# USER\nhello"
        spell = parse_spell(text, source_path="/some/path.spell.md")
        assert spell.source_path == "/some/path.spell.md"

    def test_rune_dependencies(self) -> None:
        text = """\
---
id: test/deps
name: Deps
requires_runes: [devtools/git]
suggests_runes: [devtools/cmake]
---

# USER
hello
"""
        spell = parse_spell(text)
        assert spell.requires_runes == ["devtools/git"]
        assert spell.suggests_runes == ["devtools/cmake"]


class TestParseSpellFile:
    """Tests for file-based parsing."""

    def test_parse_fixture_file(self, fixtures_dir: Path) -> None:
        spell = parse_spell_file(fixtures_dir / "spells" / "hello.spell.md")
        assert spell.id == "examples/hello"
        assert spell.variables["name"].required is True

    def test_missing_file_raises(self) -> None:
        with pytest.raises(SpellParseError, match="not found"):
            parse_spell_file("/nonexistent/spell.spell.md")
