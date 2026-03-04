# tests/unit/test_ritual_evaluator.py
"""
Unit and integration tests for ritual evaluation and validation.

Coverage:
- _evaluate_condition: all supported expression forms
- RitualEvaluator.dry_run: assembly plan accuracy, missing spell detection
- RitualEvaluator.evaluate: step execution, when branching, output capture, context flow
- validate_ritual: duplicate step IDs, missing spells, bad capture names, format
- CLI: grimoire ritual list|show|dry-run
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from grimoire.exceptions import RitualError
from grimoire.models import (
    ConjuredRitualStep,
    MessageBlock,
    MessageRole,
    Ritual,
    RitualAssemblyPlan,
    RitualStep,
    Spell,
)
from grimoire.rituals.evaluator import RitualEvaluator, _evaluate_condition
from grimoire.rituals.validator import validate_ritual
from grimoire.store.repo import GrimoireRepo
from grimoire.validate.rules import Severity

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_simple_spell(spell_id: str, var_name: str = "topic") -> Spell:
    """Build a minimal conjurable spell with one required variable."""
    from grimoire.models import VariableSpec

    block = MessageBlock(role=MessageRole.USER, content=f"Hello from {{{{ {var_name} }}}}")
    return Spell(
        id=spell_id,
        name=spell_id,
        variables={var_name: VariableSpec(type="string", required=True, ask="topic?")},
        raw_blocks=[block],
    )


def _make_repo_with_spells(tmp_path: Path, spells: list[Spell]) -> GrimoireRepo:
    """Create a minimal GrimoireRepo with given spells (no files needed beyond manifest)."""
    import yaml

    manifest = {
        "name": "test",
        "version": "0.1.0",
        "spell_paths": ["spells/"],
        "rune_paths": ["runes/"],
        "ritual_paths": ["rituals/"],
        "promptlet_paths": ["spells/promptlets/"],
    }
    (tmp_path / "grimoire.yaml").write_text(yaml.dump(manifest), encoding="utf-8")
    (tmp_path / "spells").mkdir(exist_ok=True)
    (tmp_path / "runes").mkdir(exist_ok=True)
    (tmp_path / "rituals").mkdir(exist_ok=True)
    (tmp_path / "spells" / "promptlets").mkdir(exist_ok=True)

    # Write each spell as a .spell.md file so the repo can load it
    for spell in spells:
        spell_dir = tmp_path / "spells" / Path(spell.id).parent
        spell_dir.mkdir(parents=True, exist_ok=True)
        var_section = ""
        for vname, _vspec in spell.variables.items():
            var_section += f'  {vname}:\n    type: string\n    required: true\n    ask: "?"\n'
        raw_blocks_text = ""
        for block in spell.raw_blocks:
            raw_blocks_text += f"\n# {block.role.value}\n{block.content}\n"
        content = f"---\nid: {spell.id}\nname: {spell.name}\nvariables:\n{var_section}---\n{raw_blocks_text}"
        (tmp_path / "spells" / f"{Path(spell.id).name}.spell.md").write_text(
            content, encoding="utf-8"
        )

    return GrimoireRepo.load(tmp_path)


# ── _evaluate_condition tests ─────────────────────────────────────────────────


class TestEvaluateCondition:
    """Tests for the when-condition safe evaluator."""

    def test_literal_true(self) -> None:
        assert _evaluate_condition("True", {}) is True

    def test_literal_false(self) -> None:
        assert _evaluate_condition("False", {}) is False

    def test_literal_true_lowercase(self) -> None:
        assert _evaluate_condition("true", {}) is True

    def test_literal_false_lowercase(self) -> None:
        assert _evaluate_condition("false", {}) is False

    def test_plain_identifier_truthy(self) -> None:
        assert _evaluate_condition("{{ result }}", {"result": "some content"}) is True

    def test_plain_identifier_falsy_empty(self) -> None:
        assert _evaluate_condition("{{ result }}", {"result": ""}) is False

    def test_plain_identifier_missing_key(self) -> None:
        assert _evaluate_condition("{{ result }}", {}) is False

    def test_contains_match(self) -> None:
        assert (
            _evaluate_condition("{{ report.contains('ERROR') }}", {"report": "An ERROR occurred"})
            is True
        )

    def test_contains_no_match(self) -> None:
        assert _evaluate_condition("{{ report.contains('ERROR') }}", {"report": "All OK"}) is False

    def test_contains_missing_var(self) -> None:
        # Missing var → empty string → substring not found → False
        assert _evaluate_condition("{{ report.contains('X') }}", {}) is False

    def test_startswith_match(self) -> None:
        assert (
            _evaluate_condition("{{ output.startswith('OK') }}", {"output": "OK: everything fine"})
            is True
        )

    def test_startswith_no_match(self) -> None:
        assert (
            _evaluate_condition("{{ output.startswith('FAIL') }}", {"output": "OK: all good"})
            is False
        )

    def test_endswith_match(self) -> None:
        assert _evaluate_condition("{{ text.endswith('done') }}", {"text": "task is done"}) is True

    def test_endswith_no_match(self) -> None:
        assert (
            _evaluate_condition("{{ text.endswith('done') }}", {"text": "task is pending"}) is False
        )

    def test_equality_match(self) -> None:
        assert _evaluate_condition('{{ status == "success" }}', {"status": "success"}) is True

    def test_equality_no_match(self) -> None:
        assert _evaluate_condition('{{ status == "success" }}', {"status": "failure"}) is False

    def test_inequality_match(self) -> None:
        assert _evaluate_condition('{{ status != "error" }}', {"status": "ok"}) is True

    def test_inequality_no_match(self) -> None:
        assert _evaluate_condition('{{ status != "error" }}', {"status": "error"}) is False

    def test_unknown_expression_returns_true(self, caplog) -> None:
        """Unknown expressions should be treated as True with a warning (don't silently skip)."""
        import logging

        with caplog.at_level(logging.WARNING):
            result = _evaluate_condition("{{ some.complex.expression() }}", {})
        assert result is True


# ── RitualEvaluator.dry_run tests ─────────────────────────────────────────────


class TestDryRun:
    """Tests for RitualEvaluator.dry_run()."""

    def test_dry_run_all_spells_found(self, grimoire_repo_dir: Path) -> None:
        repo = GrimoireRepo.load(grimoire_repo_dir)
        ritual = repo.get_ritual("rituals/greet_loop")
        evaluator = RitualEvaluator(repo)
        plan = evaluator.dry_run(ritual)

        assert isinstance(plan, RitualAssemblyPlan)
        assert plan.ritual_id == "rituals/greet_loop"
        assert plan.ok is True
        assert plan.missing_spells == []
        assert len(plan.steps) == 1

    def test_dry_run_step_plan_fields(self, grimoire_repo_dir: Path) -> None:
        repo = GrimoireRepo.load(grimoire_repo_dir)
        ritual = repo.get_ritual("rituals/greet_loop")
        evaluator = RitualEvaluator(repo)
        plan = evaluator.dry_run(ritual)

        sp = plan.steps[0]
        assert sp.step_id == "step_1"
        assert sp.spell_id == "examples/greet"
        assert sp.spell_found is True
        assert sp.condition is None
        assert sp.inherits_vars is True
        assert sp.output_capture == "greeting"
        assert sp.output_format == "text"

    def test_dry_run_rca_loop(self, grimoire_repo_dir: Path) -> None:
        repo = GrimoireRepo.load(grimoire_repo_dir)
        ritual = repo.get_ritual("rituals/rca_loop")
        evaluator = RitualEvaluator(repo)
        plan = evaluator.dry_run(ritual)

        assert len(plan.steps) == 2
        assert plan.steps[1].condition == "{{ greeting }}"
        assert plan.steps[1].explicit_vars == {"user_name": "follow-up"}
        assert plan.steps[1].output_capture == "followup"

    def test_dry_run_missing_spell_detected(self, tmp_path: Path) -> None:
        import yaml

        manifest = {
            "name": "t",
            "spell_paths": ["spells/"],
            "rune_paths": ["runes/"],
            "ritual_paths": ["rituals/"],
            "promptlet_paths": ["spells/promptlets/"],
        }
        (tmp_path / "grimoire.yaml").write_text(yaml.dump(manifest))
        for d in ["spells", "runes", "rituals", "spells/promptlets"]:
            (tmp_path / d).mkdir(parents=True, exist_ok=True)

        ritual_yaml = (
            "id: rituals/broken\nname: Broken\nsteps:\n  - id: s1\n    spell: does/not/exist\n"
        )
        (tmp_path / "rituals" / "broken.ritual.yaml").write_text(ritual_yaml)

        repo = GrimoireRepo.load(tmp_path)
        ritual = repo.get_ritual("rituals/broken")
        evaluator = RitualEvaluator(repo)
        plan = evaluator.dry_run(ritual)

        assert plan.ok is False
        assert "does/not/exist" in plan.missing_spells
        assert plan.steps[0].spell_found is False

    def test_dry_run_step_without_spell(self, tmp_path: Path) -> None:
        import yaml

        manifest = {
            "name": "t",
            "spell_paths": ["spells/"],
            "rune_paths": ["runes/"],
            "ritual_paths": ["rituals/"],
            "promptlet_paths": ["spells/promptlets/"],
        }
        (tmp_path / "grimoire.yaml").write_text(yaml.dump(manifest))
        for d in ["spells", "runes", "rituals", "spells/promptlets"]:
            (tmp_path / d).mkdir(parents=True, exist_ok=True)

        ritual_yaml = (
            "id: rituals/noop\nname: NoOp\nsteps:\n  - id: s1\n    description: A no-op step\n"
        )
        (tmp_path / "rituals" / "noop.ritual.yaml").write_text(ritual_yaml)

        repo = GrimoireRepo.load(tmp_path)
        ritual = repo.get_ritual("rituals/noop")
        evaluator = RitualEvaluator(repo)
        plan = evaluator.dry_run(ritual)

        assert plan.ok is True
        assert plan.steps[0].spell_id is None
        assert plan.steps[0].spell_found is True  # no spell declared → not a missing reference


# ── RitualEvaluator.evaluate tests ────────────────────────────────────────────


class TestEvaluate:
    """Tests for RitualEvaluator.evaluate()."""

    def test_evaluate_greet_loop(self, grimoire_repo_dir: Path) -> None:
        repo = GrimoireRepo.load(grimoire_repo_dir)
        ritual = repo.get_ritual("rituals/greet_loop")
        evaluator = RitualEvaluator(repo)
        results = evaluator.evaluate(ritual, variables={"user_name": "Alice"})

        assert len(results) == 1
        step_result = results[0]
        assert isinstance(step_result, ConjuredRitualStep)
        assert step_result.step_id == "step_1"
        assert step_result.skipped is False
        assert step_result.conjured is not None
        assert step_result.captured_var == "greeting"
        assert step_result.captured_value is not None
        # Captured text should contain Alice
        assert "Alice" in step_result.captured_value

    def test_evaluate_output_captured_into_context(self, grimoire_repo_dir: Path) -> None:
        """Captured output from step 1 should flow into step 2's when-check."""
        repo = GrimoireRepo.load(grimoire_repo_dir)
        ritual = repo.get_ritual("rituals/rca_loop")
        evaluator = RitualEvaluator(repo)
        results = evaluator.evaluate(ritual, variables={"user_name": "Bob"})

        assert len(results) == 2
        # step_1 should produce a greeting captured into "greeting"
        assert results[0].captured_var == "greeting"
        assert results[0].captured_value  # non-empty → step_2 when condition is True

        # step_2 should execute (greeting is non-empty)
        assert results[1].skipped is False
        assert results[1].conjured is not None

    def test_evaluate_step_skipped_when_false(self, tmp_path: Path) -> None:
        """A step with when='False' should be skipped."""
        import yaml

        manifest = {
            "name": "t",
            "spell_paths": ["spells/"],
            "rune_paths": ["runes/"],
            "ritual_paths": ["rituals/"],
            "promptlet_paths": ["spells/promptlets/"],
        }
        (tmp_path / "grimoire.yaml").write_text(yaml.dump(manifest))
        for d in ["spells", "runes", "rituals", "spells/promptlets"]:
            (tmp_path / d).mkdir(parents=True, exist_ok=True)

        # Write a simple spell
        spell_text = (
            "---\nid: test/hello\nname: Hello\n"
            'variables:\n  msg:\n    type: string\n    required: true\n    ask: "?"\n'
            "---\n\n# USER\n{{ msg }}\n"
        )
        (tmp_path / "spells" / "hello.spell.md").write_text(spell_text)

        ritual_yaml = (
            "id: rituals/conditional\nname: Conditional\nsteps:\n"
            "  - id: always\n    spell: test/hello\n    conjure:\n      vars:\n        msg: hi\n"
            "  - id: never\n    spell: test/hello\n    when: 'False'\n"
            "    conjure:\n      vars:\n        msg: skipped\n"
        )
        (tmp_path / "rituals" / "cond.ritual.yaml").write_text(ritual_yaml)

        repo = GrimoireRepo.load(tmp_path)
        ritual = repo.get_ritual("rituals/conditional")
        evaluator = RitualEvaluator(repo)
        results = evaluator.evaluate(ritual, variables={})

        assert len(results) == 2
        assert results[0].skipped is False
        assert results[1].skipped is True
        assert "when condition false" in results[1].skip_reason

    def test_evaluate_missing_spell_raises(self, grimoire_repo_dir: Path) -> None:
        repo = GrimoireRepo.load(grimoire_repo_dir)
        ritual = Ritual(
            id="rituals/bad",
            name="Bad",
            steps=[RitualStep(id="s1", spell="nonexistent/spell")],
        )
        evaluator = RitualEvaluator(repo)
        with pytest.raises(RitualError, match="missing spell"):
            evaluator.evaluate(ritual, variables={})

    def test_evaluate_context_accumulates(self, tmp_path: Path) -> None:
        """Variables captured by early steps are available in later steps."""
        import yaml

        manifest = {
            "name": "t",
            "spell_paths": ["spells/"],
            "rune_paths": ["runes/"],
            "ritual_paths": ["rituals/"],
            "promptlet_paths": ["spells/promptlets/"],
        }
        (tmp_path / "grimoire.yaml").write_text(yaml.dump(manifest))
        for d in ["spells", "runes", "rituals", "spells/promptlets"]:
            (tmp_path / d).mkdir(parents=True, exist_ok=True)

        spell_text = (
            "---\nid: test/echo\nname: Echo\n"
            'variables:\n  val:\n    type: string\n    required: true\n    ask: "?"\n'
            "---\n\n# USER\nECHO:{{ val }}\n"
        )
        (tmp_path / "spells" / "echo.spell.md").write_text(spell_text)

        ritual_yaml = (
            "id: rituals/chain\nname: Chain\nsteps:\n"
            "  - id: s1\n    spell: test/echo\n"
            "    conjure:\n      vars:\n        val: first\n"
            "    output:\n      capture: first_out\n"
            "  - id: s2\n    spell: test/echo\n"
            "    when: '{{ first_out }}'\n"
            "    conjure:\n      vars:\n        inherit: true\n        val: second\n"
            "    output:\n      capture: second_out\n"
        )
        (tmp_path / "rituals" / "chain.ritual.yaml").write_text(ritual_yaml)

        repo = GrimoireRepo.load(tmp_path)
        ritual = repo.get_ritual("rituals/chain")
        evaluator = RitualEvaluator(repo)
        results = evaluator.evaluate(ritual, variables={})

        assert results[0].captured_value is not None
        assert "ECHO:first" in results[0].captured_value
        assert results[1].skipped is False  # first_out is truthy

    def test_evaluate_no_spell_step_is_noop(self, tmp_path: Path) -> None:
        """A step with no spell should produce an un-skipped no-op result."""
        import yaml

        manifest = {
            "name": "t",
            "spell_paths": ["spells/"],
            "rune_paths": ["runes/"],
            "ritual_paths": ["rituals/"],
            "promptlet_paths": ["spells/promptlets/"],
        }
        (tmp_path / "grimoire.yaml").write_text(yaml.dump(manifest))
        for d in ["spells", "runes", "rituals", "spells/promptlets"]:
            (tmp_path / d).mkdir(parents=True, exist_ok=True)
        (tmp_path / "rituals" / "noop.ritual.yaml").write_text(
            "id: rituals/noop\nname: NoOp\nsteps:\n  - id: s1\n"
        )
        repo = GrimoireRepo.load(tmp_path)
        ritual = repo.get_ritual("rituals/noop")
        evaluator = RitualEvaluator(repo)
        results = evaluator.evaluate(ritual, variables={})

        assert len(results) == 1
        assert results[0].skipped is False
        assert results[0].conjured is None


# ── validate_ritual tests ─────────────────────────────────────────────────────


class TestValidateRitual:
    """Tests for validate_ritual()."""

    def test_valid_ritual_no_issues(self, grimoire_repo_dir: Path) -> None:
        repo = GrimoireRepo.load(grimoire_repo_dir)
        ritual = repo.get_ritual("rituals/greet_loop")
        diags = validate_ritual(ritual, repo=repo)
        errors = [d for d in diags if d.severity == Severity.ERROR]
        assert errors == []

    def test_missing_spell_error(self, grimoire_repo_dir: Path) -> None:
        repo = GrimoireRepo.load(grimoire_repo_dir)
        ritual = Ritual(
            id="rituals/broken",
            name="Broken",
            steps=[RitualStep(id="s1", spell="totally/missing")],
        )
        diags = validate_ritual(ritual, repo=repo)
        errors = [d for d in diags if d.severity == Severity.ERROR]
        assert any("totally/missing" in d.message for d in errors)

    def test_duplicate_step_id_error(self, grimoire_repo_dir: Path) -> None:
        repo = GrimoireRepo.load(grimoire_repo_dir)
        ritual = Ritual(
            id="rituals/dup",
            name="Dup",
            steps=[
                RitualStep(id="step_1"),
                RitualStep(id="step_1"),  # duplicate
            ],
        )
        diags = validate_ritual(ritual, repo=repo)
        errors = [d for d in diags if d.severity == Severity.ERROR]
        assert any("Duplicate step id" in d.message for d in errors)

    def test_non_namespaced_id_warning(self) -> None:
        ritual = Ritual(id="noids", name="No Namespace", steps=[])
        diags = validate_ritual(ritual)
        warnings = [d for d in diags if d.severity == Severity.WARNING]
        assert any("not namespaced" in d.message for d in warnings)

    def test_invalid_capture_name_error(self) -> None:
        ritual = Ritual(
            id="rituals/bad_capture",
            name="Bad Capture",
            steps=[
                RitualStep(id="s1", output={"capture": "123invalid"}),
            ],
        )
        diags = validate_ritual(ritual)
        errors = [d for d in diags if d.severity == Severity.ERROR]
        assert any("not a valid Python identifier" in d.message for d in errors)

    def test_valid_capture_name_ok(self) -> None:
        ritual = Ritual(
            id="rituals/good_capture",
            name="Good Capture",
            steps=[
                RitualStep(id="s1", output={"capture": "valid_name"}),
            ],
        )
        diags = validate_ritual(ritual)
        errors = [d for d in diags if d.severity == Severity.ERROR]
        assert not any("identifier" in d.message for d in errors)

    def test_unknown_output_format_warning(self) -> None:
        ritual = Ritual(
            id="rituals/bad_fmt",
            name="Bad Format",
            steps=[
                RitualStep(id="s1", output={"format": "xml"}),
            ],
        )
        diags = validate_ritual(ritual)
        warnings = [d for d in diags if d.severity == Severity.WARNING]
        assert any("output.format" in d.message for d in warnings)

    def test_validate_without_repo_skips_spell_check(self) -> None:
        ritual = Ritual(
            id="rituals/no_repo",
            name="No Repo",
            steps=[RitualStep(id="s1", spell="could/be/anything")],
        )
        # No repo passed — spell check should be skipped
        diags = validate_ritual(ritual, repo=None)
        errors = [d for d in diags if d.severity == Severity.ERROR]
        # The only potential error is non-namespaced id (but ritual/no_repo is namespaced)
        assert not any("not found" in d.message for d in errors)


# ── CLI tests ─────────────────────────────────────────────────────────────────


class TestRitualCLI:
    """CLI tests for grimoire ritual subcommands."""

    @pytest.fixture
    def repo_args(self, grimoire_repo_dir: Path) -> list[str]:
        return ["--repo", str(grimoire_repo_dir)]

    def test_ritual_list(self, repo_args: list[str]) -> None:
        from click.testing import CliRunner

        from grimoire.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, [*repo_args, "ritual", "list"])
        assert result.exit_code == 0
        assert "greet_loop" in result.output

    def test_ritual_list_json(self, repo_args: list[str]) -> None:
        from click.testing import CliRunner

        from grimoire.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, [*repo_args, "ritual", "list", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        ids = [d["id"] for d in data]
        assert "rituals/greet_loop" in ids

    def test_ritual_list_tag_filter(self, repo_args: list[str]) -> None:
        from click.testing import CliRunner

        from grimoire.cli import cli

        runner = CliRunner()
        # Tag that only rca_loop has
        result = runner.invoke(cli, [*repo_args, "ritual", "list", "--tag", "debugging"])
        assert result.exit_code == 0
        assert "rca_loop" in result.output
        # greet_loop doesn't have this tag
        assert "greet_loop" not in result.output

    def test_ritual_list_empty_on_unknown_tag(self, repo_args: list[str]) -> None:
        from click.testing import CliRunner

        from grimoire.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, [*repo_args, "ritual", "list", "--tag", "nonexistent_xyz"])
        assert result.exit_code == 0
        assert "No rituals found" in result.output

    def test_ritual_show(self, repo_args: list[str]) -> None:
        from click.testing import CliRunner

        from grimoire.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, [*repo_args, "ritual", "show", "rituals/greet_loop"])
        assert result.exit_code == 0
        assert "Greeting Loop" in result.output
        assert "step_1" in result.output

    def test_ritual_show_json(self, repo_args: list[str]) -> None:
        from click.testing import CliRunner

        from grimoire.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, [*repo_args, "ritual", "show", "--json", "rituals/greet_loop"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["id"] == "rituals/greet_loop"
        assert isinstance(data["steps"], list)

    def test_ritual_show_not_found(self, repo_args: list[str]) -> None:
        from click.testing import CliRunner

        from grimoire.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, [*repo_args, "ritual", "show", "does/not/exist"])
        assert result.exit_code != 0

    def test_ritual_dry_run(self, repo_args: list[str]) -> None:
        from click.testing import CliRunner

        from grimoire.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, [*repo_args, "ritual", "dry-run", "rituals/greet_loop"])
        assert result.exit_code == 0
        assert "Assembly Plan" in result.output
        assert "step_1" in result.output
        # The greet spell exists, so plan should be OK
        assert "OK" in result.output

    def test_ritual_dry_run_json(self, repo_args: list[str]) -> None:
        from click.testing import CliRunner

        from grimoire.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, [*repo_args, "ritual", "dry-run", "--json", "rituals/rca_loop"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["ritual_id"] == "rituals/rca_loop"
        assert data["ok"] is True
        assert len(data["steps"]) == 2
        assert data["steps"][1]["condition"] == "{{ greeting }}"

    def test_ritual_dry_run_not_found(self, repo_args: list[str]) -> None:
        from click.testing import CliRunner

        from grimoire.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, [*repo_args, "ritual", "dry-run", "no/such/ritual"])
        assert result.exit_code != 0
