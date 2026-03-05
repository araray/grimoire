# tests/unit/test_spells.py
"""
Additional spell parser coverage: shorthand variables, runes_export, output_contract,
edge cases in block parsing.
"""
from __future__ import annotations
from pathlib import Path
import pytest


class TestSpellParserExtended:
    def test_shorthand_variable_string(self, tmp_path: Path):
        """Shorthand variable declaration: topic: string → VariableSpec(type=string)."""
        from grimoire.spells.parser import parse_spell_file
        text = "---\nid: test/shorthand\nname: Shorthand\nvariables:\n  topic: string\n---\n\n# USER\nTell me about {{ topic }}.\n"
        f = tmp_path / "sh.spell.md"
        f.write_text(text)
        spell = parse_spell_file(f)
        assert "topic" in spell.variables
        assert spell.variables["topic"].type.value == "string"

    def test_runes_export_parsed(self, tmp_path: Path):
        from grimoire.spells.parser import parse_spell_file
        text = "---\nid: test/runes_exp\nname: Runes Export\nrunes_export:\n  mode: reference\n  ids:\n    - devtools/git\n---\n\n# USER\nDo something.\n"
        f = tmp_path / "re.spell.md"
        f.write_text(text)
        spell = parse_spell_file(f)
        assert spell.runes_export is not None

    def test_output_contract_parsed(self, tmp_path: Path):
        from grimoire.spells.parser import parse_spell_file
        text = "---\nid: test/out_contract\nname: Output Contract\noutput_contract:\n  type: json\n---\n\n# USER\nReturn JSON.\n"
        f = tmp_path / "oc.spell.md"
        f.write_text(text)
        spell = parse_spell_file(f)
        assert spell.output_contract is not None

    def test_body_no_blocks_raises(self, tmp_path: Path):
        from grimoire.spells.parser import parse_spell_file
        from grimoire.exceptions import SpellParseError
        text = "---\nid: test/empty_body\nname: Empty\n---\n\n   \n"
        f = tmp_path / "eb.spell.md"
        f.write_text(text)
        with pytest.raises(SpellParseError):
            parse_spell_file(f)

    def test_invalid_variable_spec_raises(self, tmp_path: Path):
        from grimoire.spells.parser import parse_spell_file
        from grimoire.exceptions import SpellValidationError
        text = "---\nid: test/bad_var\nname: Bad Var\nvariables:\n  name:\n    - list\n    - not\n    - dict\n---\n\n# USER\nHello.\n"
        f = tmp_path / "bv.spell.md"
        f.write_text(text)
        with pytest.raises(SpellValidationError):
            parse_spell_file(f)

    def test_body_without_headers_is_user_block(self, tmp_path: Path):
        """Body with no # ROLE headers → treated as USER block."""
        from grimoire.spells.parser import parse_spell_file
        from grimoire.models import MessageRole
        text = "---\nid: test/noheader\nname: No Header\n---\n\nJust plain content.\n"
        f = tmp_path / "nh.spell.md"
        f.write_text(text)
        spell = parse_spell_file(f)
        assert len(spell.raw_blocks) == 1
        assert spell.raw_blocks[0].role == MessageRole.USER
        assert "plain content" in spell.raw_blocks[0].content


class TestRuneParserExtended:
    def test_command_missing_name_raises(self, tmp_path: Path):
        from grimoire.runes.parser import parse_rune
        from grimoire.exceptions import RuneValidationError
        data = {
            "id": "test/r",
            "name": "R",
            "commands": [{"summary": "No name"}],  # missing 'name'
        }
        with pytest.raises(RuneValidationError, match="name"):
            parse_rune(data)

    def test_invalid_param_raises(self, tmp_path: Path):
        from grimoire.runes.parser import parse_rune
        from grimoire.exceptions import RuneValidationError
        data = {
            "id": "test/r",
            "name": "R",
            "commands": [{"name": "run", "params": [{"name": "x", "type": "string", "extra_forbidden_field": True}]}],
        }
        # Pydantic extra=forbid should reject extra field
        with pytest.raises((RuneValidationError, Exception)):
            parse_rune(data)

    def test_rune_file_not_found_raises(self, tmp_path: Path):
        from grimoire.runes.parser import parse_rune_file
        from grimoire.exceptions import RuneParseError
        with pytest.raises(RuneParseError, match="not found"):
            parse_rune_file(tmp_path / "nonexistent.rune.yaml")

    def test_rune_file_empty_raises(self, tmp_path: Path):
        from grimoire.runes.parser import parse_rune_file
        from grimoire.exceptions import RuneParseError
        f = tmp_path / "empty.rune.yaml"
        f.write_text("")
        with pytest.raises(RuneParseError, match="Empty"):
            parse_rune_file(f)

    def test_rune_with_returns(self, tmp_path: Path):
        from grimoire.runes.parser import parse_rune
        data = {
            "id": "test/with_returns",
            "name": "With Returns",
            "commands": [{
                "name": "run",
                "summary": "Run",
                "returns": {"type": "json", "description": "The output"},
            }],
        }
        rune = parse_rune(data)
        assert rune.commands[0].returns is not None

    def test_rune_with_examples(self, tmp_path: Path):
        from grimoire.runes.parser import parse_rune
        data = {
            "id": "test/with_examples",
            "name": "With Examples",
            "commands": [{
                "name": "run",
                "summary": "Run",
                "examples": [{"call": {"path": "/tmp"}, "expect": "ok"}],
            }],
        }
        rune = parse_rune(data)
        assert len(rune.commands[0].examples) == 1
