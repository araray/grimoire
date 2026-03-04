# tests/unit/test_conjure_engine.py
"""Unit tests for grimoire.conjure.engine."""

import pytest

from grimoire.conjure.engine import ConjureEngine
from grimoire.exceptions import (
    CircularIncludeError,
    IncludeError,
    MissingVariableError,
)
from grimoire.models import (
    MessageBlock,
    MessageRole,
    Promptlet,
    Spell,
    VariableSpec,
    VariableType,
)
from grimoire.runes.parser import parse_rune


def _make_spell(
    spell_id: str = "test/spell",
    blocks: list[tuple[str, str]] | None = None,
    variables: dict[str, VariableSpec] | None = None,
) -> Spell:
    """Helper to construct a Spell for testing."""
    if blocks is None:
        blocks = [("USER", "Hello {{ name }}")]
    if variables is None:
        variables = {}

    raw_blocks = [
        MessageBlock(role=MessageRole(role), content=content)
        for role, content in blocks
    ]
    return Spell(
        id=spell_id,
        name=spell_id,
        raw_blocks=raw_blocks,
        variables=variables,
    )


class TestVariableSubstitution:
    """Tests for {{ variable }} rendering."""

    def test_simple_variable(self) -> None:
        spell = _make_spell(variables={
            "name": VariableSpec(type=VariableType.STRING, required=True),
        })
        engine = ConjureEngine()
        result = engine.conjure(spell, variables={"name": "Alice"})
        assert result.blocks[0].content == "Hello Alice"

    def test_variable_with_default(self) -> None:
        spell = _make_spell(
            blocks=[("USER", 'Hello {{ name|default("World") }}')],
        )
        engine = ConjureEngine()
        result = engine.conjure(spell, variables={}, strict=False)
        assert result.blocks[0].content == "Hello World"

    def test_variable_default_overridden(self) -> None:
        spell = _make_spell(
            blocks=[("USER", 'Hello {{ name|default("World") }}')],
        )
        engine = ConjureEngine()
        result = engine.conjure(spell, variables={"name": "Alice"}, strict=False)
        assert result.blocks[0].content == "Hello Alice"

    def test_spell_default_used(self) -> None:
        spell = _make_spell(
            blocks=[("USER", "Detail: {{ detail }}")],
            variables={
                "detail": VariableSpec(type=VariableType.STRING, default="brief"),
            },
        )
        engine = ConjureEngine()
        result = engine.conjure(spell)
        assert result.blocks[0].content == "Detail: brief"

    def test_missing_required_raises_strict(self) -> None:
        spell = _make_spell(
            variables={
                "name": VariableSpec(type=VariableType.STRING, required=True),
            },
        )
        engine = ConjureEngine()
        with pytest.raises(MissingVariableError, match="name"):
            engine.conjure(spell, variables={}, strict=True)

    def test_missing_non_strict_preserves_placeholder(self) -> None:
        spell = _make_spell(
            variables={
                "name": VariableSpec(type=VariableType.STRING, required=True),
            },
        )
        engine = ConjureEngine()
        result = engine.conjure(spell, variables={}, strict=False)
        assert "{{ name }}" in result.blocks[0].content

    def test_builtin_variables(self) -> None:
        spell = _make_spell(
            blocks=[("USER", "Spell: {{ grimoire.spell.id }}")],
        )
        engine = ConjureEngine()
        result = engine.conjure(spell, strict=False)
        assert result.blocks[0].content == "Spell: test/spell"

    def test_grimoire_defaults_precedence(self) -> None:
        spell = _make_spell(
            blocks=[("USER", "{{ greeting }}")],
            variables={
                "greeting": VariableSpec(type=VariableType.STRING, default="Hi"),
            },
        )
        engine = ConjureEngine()
        # Grimoire default overrides spell default
        result = engine.conjure(spell, defaults={"greeting": "Hola"})
        assert result.blocks[0].content == "Hola"

    def test_explicit_overrides_all(self) -> None:
        spell = _make_spell(
            blocks=[("USER", "{{ greeting }}")],
            variables={
                "greeting": VariableSpec(type=VariableType.STRING, default="Hi"),
            },
        )
        engine = ConjureEngine()
        result = engine.conjure(
            spell,
            variables={"greeting": "Hey"},
            defaults={"greeting": "Hola"},
        )
        assert result.blocks[0].content == "Hey"


class TestEscaping:
    """Tests for literal brace escaping."""

    def test_escaped_braces(self) -> None:
        spell = _make_spell(
            blocks=[("USER", "Use {{{{ and }}}} for literals")],
        )
        engine = ConjureEngine()
        result = engine.conjure(spell, strict=False)
        assert result.blocks[0].content == "Use {{ and }} for literals"


class TestIncludes:
    """Tests for {{ include("...") }} directives."""

    def test_simple_include(self) -> None:
        promptlets = {
            "safety/base": Promptlet(id="safety/base", content="Be safe."),
        }
        spell = _make_spell(
            blocks=[("SYSTEM", '{{ include("safety/base") }}\nBe helpful.')],
        )
        engine = ConjureEngine(promptlets=promptlets)
        result = engine.conjure(spell, strict=False)
        assert "Be safe." in result.blocks[0].content
        assert "Be helpful." in result.blocks[0].content

    def test_nested_include(self) -> None:
        promptlets = {
            "inner": Promptlet(id="inner", content="Inner content."),
            "outer": Promptlet(id="outer", content='Before. {{ include("inner") }} After.'),
        }
        spell = _make_spell(
            blocks=[("SYSTEM", '{{ include("outer") }}')],
        )
        engine = ConjureEngine(promptlets=promptlets)
        result = engine.conjure(spell, strict=False)
        assert "Inner content." in result.blocks[0].content

    def test_missing_include_raises(self) -> None:
        spell = _make_spell(
            blocks=[("SYSTEM", '{{ include("nonexistent") }}')],
        )
        engine = ConjureEngine()
        with pytest.raises(IncludeError, match="not found"):
            engine.conjure(spell, strict=False)

    def test_circular_include_raises(self) -> None:
        promptlets = {
            "a": Promptlet(id="a", content='{{ include("b") }}'),
            "b": Promptlet(id="b", content='{{ include("a") }}'),
        }
        spell = _make_spell(
            blocks=[("SYSTEM", '{{ include("a") }}')],
        )
        engine = ConjureEngine(promptlets=promptlets)
        with pytest.raises(CircularIncludeError):
            engine.conjure(spell, strict=False)

    def test_include_with_variables(self) -> None:
        promptlets = {
            "greet": Promptlet(id="greet", content="Hello {{ name }}!"),
        }
        spell = _make_spell(
            blocks=[("SYSTEM", '{{ include("greet") }}')],
            variables={"name": VariableSpec(type=VariableType.STRING, required=True)},
        )
        engine = ConjureEngine(promptlets=promptlets)
        result = engine.conjure(spell, variables={"name": "Alice"})
        assert result.blocks[0].content == "Hello Alice!"

    def test_include_tracked_in_provenance(self) -> None:
        promptlets = {
            "intro": Promptlet(id="intro", content="Welcome."),
        }
        spell = _make_spell(
            blocks=[("SYSTEM", '{{ include("intro") }}')],
        )
        engine = ConjureEngine(promptlets=promptlets)
        result = engine.conjure(spell, strict=False)
        assert "intro" in result.provenance.includes_resolved


class TestRuneIntrospection:
    """Tests for rune-aware rendering."""

    def _make_engine_with_git_rune(self) -> ConjureEngine:
        rune = parse_rune({
            "id": "devtools/git",
            "name": "Git",
            "tags": ["devtools", "engineering"],
            "risk_level": "low",
            "permissions": ["read_fs"],
            "commands": [
                {"name": "status", "summary": "Show status", "params": [
                    {"name": "porcelain", "type": "bool"},
                ]},
                {"name": "diff", "summary": "Show diff", "params": []},
            ],
        })
        return ConjureEngine(runes={rune.id: rune})

    def test_runes_list(self) -> None:
        engine = self._make_engine_with_git_rune()
        spell = _make_spell(
            blocks=[("SYSTEM", '{{ runes.list(tags=["devtools"]) }}')],
        )
        result = engine.conjure(spell, strict=False)
        assert "devtools/git" in result.blocks[0].content

    def test_runes_describe(self) -> None:
        engine = self._make_engine_with_git_rune()
        spell = _make_spell(
            blocks=[("SYSTEM", '{{ runes.describe("devtools/git") }}')],
        )
        result = engine.conjure(spell, strict=False)
        assert "Git" in result.blocks[0].content
        assert "status" in result.blocks[0].content

    def test_runes_command_signature(self) -> None:
        engine = self._make_engine_with_git_rune()
        spell = _make_spell(
            blocks=[("SYSTEM", '{{ runes.command("devtools/git", "status").signature }}')],
        )
        result = engine.conjure(spell, strict=False)
        assert "status(porcelain: bool)" in result.blocks[0].content

    def test_runes_tracked_in_provenance(self) -> None:
        engine = self._make_engine_with_git_rune()
        spell = _make_spell(
            blocks=[("SYSTEM", '{{ runes.describe("devtools/git") }}')],
        )
        result = engine.conjure(spell, strict=False)
        assert "devtools/git" in result.provenance.runes_referenced


class TestProvenance:
    """Tests for provenance tracking."""

    def test_provenance_spell_id(self) -> None:
        spell = _make_spell(spell_id="test/prov")
        engine = ConjureEngine()
        result = engine.conjure(spell, variables={}, strict=False)
        assert result.provenance.spell_id == "test/prov"

    def test_provenance_variables_recorded(self) -> None:
        spell = _make_spell(
            variables={"x": VariableSpec(type=VariableType.STRING, required=True)},
        )
        engine = ConjureEngine()
        result = engine.conjure(spell, variables={"x": "val"})
        assert result.provenance.variables_used["x"] == "val"

    def test_provenance_excludes_builtins(self) -> None:
        spell = _make_spell(
            blocks=[("USER", "{{ grimoire.spell.id }}")],
        )
        engine = ConjureEngine()
        result = engine.conjure(spell, strict=False)
        # Built-in vars should not appear in variables_used
        assert "grimoire.spell.id" not in result.provenance.variables_used


class TestOutputFormats:
    """Tests for ConjuredPrompt export methods."""

    def test_to_messages_openai(self) -> None:
        spell = _make_spell(
            blocks=[("SYSTEM", "Sys"), ("USER", "User msg")],
        )
        engine = ConjureEngine()
        result = engine.conjure(spell, strict=False)
        messages = result.to_messages(fmt="openai")
        assert len(messages) == 2
        assert messages[0] == {"role": "system", "content": "Sys"}
        assert messages[1] == {"role": "user", "content": "User msg"}

    def test_to_messages_anthropic_merges_system(self) -> None:
        spell = _make_spell(
            blocks=[("SYSTEM", "Part 1"), ("DEVELOPER", "Part 2"), ("USER", "User")],
        )
        engine = ConjureEngine()
        result = engine.conjure(spell, strict=False)
        messages = result.to_messages(fmt="anthropic")
        # SYSTEM + DEVELOPER should be merged (both map to "system")
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert "Part 1" in messages[0]["content"]
        assert "Part 2" in messages[0]["content"]

    def test_to_text(self) -> None:
        spell = _make_spell(
            blocks=[("SYSTEM", "Hello"), ("USER", "World")],
        )
        engine = ConjureEngine()
        result = engine.conjure(spell, strict=False)
        text = result.to_text()
        assert "# SYSTEM\nHello" in text
        assert "# USER\nWorld" in text


class TestDeterminism:
    """Tests verifying deterministic rendering (same inputs → same output)."""

    def test_same_inputs_same_output(self) -> None:
        spell = _make_spell(
            blocks=[("USER", "Topic: {{ topic }}")],
            variables={"topic": VariableSpec(type=VariableType.STRING, required=True)},
        )
        engine = ConjureEngine()
        r1 = engine.conjure(spell, variables={"topic": "AI"})
        r2 = engine.conjure(spell, variables={"topic": "AI"})
        assert r1.blocks[0].content == r2.blocks[0].content
        assert r1.provenance.spell_hash == r2.provenance.spell_hash
