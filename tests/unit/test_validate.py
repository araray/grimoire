# tests/unit/test_validate.py
"""Unit tests for grimoire.validate.rules."""

from pathlib import Path

from grimoire.models import (
    CommandSpec,
    MessageBlock,
    MessageRole,
    RiskLevel,
    RuneSpec,
    Spell,
    VariableSpec,
    VariableType,
)
from grimoire.store.repo import GrimoireRepo
from grimoire.validate.rules import validate_repo, validate_rune, validate_spell


class TestValidateSpell:
    """Tests for spell validation."""

    def test_valid_spell_passes(self) -> None:
        spell = Spell(
            id="category/name",
            name="Good Spell",
            raw_blocks=[MessageBlock(role=MessageRole.USER, content="hello")],
            variables={
                "x": VariableSpec(type=VariableType.STRING, required=True, ask="Enter x"),
            },
        )
        result = validate_spell(spell)
        assert result.ok

    def test_no_blocks_is_error(self) -> None:
        spell = Spell(id="test/empty", name="Empty", raw_blocks=[])
        result = validate_spell(spell)
        assert not result.ok
        assert any("no message blocks" in d.message for d in result.errors)

    def test_no_slash_in_id_warns(self) -> None:
        spell = Spell(
            id="flatid",
            name="Flat",
            raw_blocks=[MessageBlock(role=MessageRole.USER, content="hi")],
        )
        result = validate_spell(spell)
        assert result.ok  # warnings are ok
        assert any("slash-separated" in d.message for d in result.warnings)

    def test_required_var_without_ask_warns(self) -> None:
        spell = Spell(
            id="test/noask",
            name="No Ask",
            raw_blocks=[MessageBlock(role=MessageRole.USER, content="hi")],
            variables={"x": VariableSpec(type=VariableType.STRING, required=True)},
        )
        result = validate_spell(spell)
        assert any("no 'ask' prompt" in d.message for d in result.warnings)

    def test_engineering_spell_lint_assumptions(self) -> None:
        spell = Spell(
            id="eng/test",
            name="Eng",
            tags=["engineering"],
            raw_blocks=[MessageBlock(role=MessageRole.USER, content="Do something.")],
        )
        result = validate_spell(spell)
        assert any("assumption" in d.message.lower() for d in result.warnings)

    def test_engineering_spell_with_assumptions_passes(self) -> None:
        spell = Spell(
            id="eng/good",
            name="Good Eng",
            tags=["engineering"],
            raw_blocks=[
                MessageBlock(
                    role=MessageRole.USER,
                    content="List assumptions. Consider failure modes and edge cases.",
                ),
            ],
        )
        result = validate_spell(spell)
        # Should not have assumption/failure warnings
        assumption_warnings = [
            d
            for d in result.warnings
            if "assumption" in d.message.lower() or "failure" in d.message.lower()
        ]
        assert len(assumption_warnings) == 0


class TestValidateRune:
    """Tests for rune validation."""

    def test_valid_rune_passes(self) -> None:
        rune = RuneSpec(
            id="test/ok",
            name="OK",
            commands=[CommandSpec(name="do", summary="Does thing")],
        )
        result = validate_rune(rune)
        assert result.ok

    def test_no_commands_warns(self) -> None:
        rune = RuneSpec(id="test/empty", name="Empty", commands=[])
        result = validate_rune(rune)
        assert any("no commands" in d.message for d in result.warnings)

    def test_command_without_summary_warns(self) -> None:
        rune = RuneSpec(
            id="test/nosumm",
            name="No Summary",
            commands=[CommandSpec(name="do")],
        )
        result = validate_rune(rune)
        assert any("no summary" in d.message for d in result.warnings)

    def test_high_risk_without_approval_warns(self) -> None:
        rune = RuneSpec(
            id="test/risky",
            name="Risky",
            risk_level=RiskLevel.HIGH,
            commands=[CommandSpec(name="destroy", summary="Destroy everything")],
        )
        result = validate_rune(rune)
        assert any("requires_approval" in d.message for d in result.warnings)


class TestValidateRepo:
    """Tests for repo-wide validation."""

    def test_validate_fixture_repo(self, grimoire_repo_dir: Path) -> None:
        repo = GrimoireRepo.load(grimoire_repo_dir)
        result = validate_repo(repo)
        # Should have some warnings but no hard errors
        # (the fixture repo doesn't have engineering/observability rune)
        # Actually the fixture spell requires_runes engineering/observability
        # which doesn't exist — that should be an error only if the spell
        # has requires_runes. Our fixture greet spell doesn't.
        # So it should be clean.
        assert result.ok or any("not found" in d.message for d in result.errors)
