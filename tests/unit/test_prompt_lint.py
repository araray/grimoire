# tests/unit/test_prompt_lint.py
"""
Tests for Phase 8: Prompt Lint & Golden Test.

Covers:
  - validate_spell_style() rules:
      - forbidden tokens (WARNING)
      - camelCase variable names (WARNING)
      - required vars without ask (INFO)
      - USER block length exceeded (WARNING)
      - sensitive variable naming (WARNING)
      - engineering quality keywords (INFO)
  - LintConfig dataclass (defaults + from_manifest_extra)
  - CLI: grimoire prompt lint [spell_id] [--tag] [--json] [--fail-on-warnings]
  - CLI: grimoire prompt test [--update-golden] [--golden-dir]
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from grimoire.cli import cli
from grimoire.models import (
    MessageBlock,
    MessageRole,
    Spell,
    VariableSpec,
    VariableSensitivity,
    VariableType,
)
from grimoire.validate.rules import LintConfig, Severity, validate_spell_style


# ── Helpers ───────────────────────────────────────────────────────────────────


def _simple_spell(
    content: str = "Hello world.",
    role: MessageRole = MessageRole.USER,
    tags: list[str] | None = None,
    variables: dict | None = None,
    spell_id: str = "test/simple",
) -> Spell:
    """Build a minimal Spell with one message block."""
    blocks = [MessageBlock(role=role, content=content)]
    return Spell(
        id=spell_id,
        name="Simple",
        raw_blocks=blocks,
        tags=tags or [],
        variables=variables or {},
    )


def _make_lint_repo(tmp_path: Path) -> Path:
    """Minimal repo with a clean spell + a dirty spell."""
    manifest = {
        "name": "lint-test",
        "version": "0.1.0",
        "spell_paths": ["spells/"],
        "rune_paths": ["runes/"],
        "ritual_paths": ["rituals/"],
        "promptlet_paths": ["prompts/"],
        "bundle_paths": ["bundles/"],
        "skilldoc_paths": ["skills/"],
    }
    (tmp_path / "grimoire.yaml").write_text(yaml.dump(manifest))
    for d in ["spells", "runes", "rituals", "prompts", "bundles", "skills", "vars"]:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    (tmp_path / "vars" / "defaults.yaml").write_text("{}\n")

    # Clean spell
    clean = """\
---
id: test/clean
name: Clean Spell
tags: [test]
variables:
  user_name:
    type: string
    required: true
    ask: "What is your name?"
---

# SYSTEM
You are helpful.

# USER
Hello {{ user_name }}.
"""
    (tmp_path / "spells" / "clean.spell.md").write_text(clean)

    # Dirty spell (forbidden token + camelCase var)
    dirty = """\
---
id: test/dirty
name: Dirty Spell
tags: [test]
variables:
  userName:
    type: string
    required: true
---

# SYSTEM
# TODO: fix this later

# USER
Hello {{ userName }}. PLACEHOLDER
"""
    (tmp_path / "spells" / "dirty.spell.md").write_text(dirty)

    return tmp_path


# ── LintConfig tests ──────────────────────────────────────────────────────────


class TestLintConfig:
    def test_defaults(self):
        cfg = LintConfig()
        assert cfg.max_user_block_chars == 0  # 0 = no limit
        assert cfg.forbidden_tokens == []
        assert cfg.check_engineering_quality is True
        assert cfg.check_sensitivity is True

    def test_from_manifest_extra_empty(self):
        cfg = LintConfig.from_manifest_extra({})
        assert cfg.max_user_block_chars == 0

    def test_from_manifest_extra_with_values(self):
        cfg = LintConfig.from_manifest_extra({
            "lint": {
                "max_user_block_chars": 500,
                "forbidden_tokens": ["HACK"],
                "check_engineering_quality": False,
                "check_sensitivity": False,
            }
        })
        assert cfg.max_user_block_chars == 500
        assert "HACK" in cfg.forbidden_tokens
        assert cfg.check_engineering_quality is False
        assert cfg.check_sensitivity is False

    def test_from_manifest_extra_no_lint_key(self):
        cfg = LintConfig.from_manifest_extra({"other_key": "value"})
        assert cfg.max_user_block_chars == 0


# ── validate_spell_style() unit tests ────────────────────────────────────────


class TestValidateSpellStyle:
    def test_clean_spell_passes(self):
        spell = _simple_spell("Clean content, no problems.")
        result = validate_spell_style(spell)
        assert result.ok
        assert result.diagnostics == []

    # Forbidden tokens
    def test_forbidden_token_todo(self):
        spell = _simple_spell("Do this. TODO: finish later.")
        result = validate_spell_style(spell)
        assert any("TODO" in d.message for d in result.diagnostics)

    def test_forbidden_token_fixme(self):
        spell = _simple_spell("FIXME: broken logic here.")
        result = validate_spell_style(spell)
        assert any("FIXME" in d.message for d in result.diagnostics)

    def test_forbidden_token_placeholder(self):
        spell = _simple_spell("Insert PLACEHOLDER here.")
        result = validate_spell_style(spell)
        assert any("PLACEHOLDER" in d.message for d in result.diagnostics)

    def test_forbidden_token_severity_is_warning(self):
        spell = _simple_spell("TODO fix")
        result = validate_spell_style(spell)
        todo_diags = [d for d in result.diagnostics if "TODO" in d.message]
        assert all(d.severity == Severity.WARNING for d in todo_diags)

    def test_custom_forbidden_token(self):
        cfg = LintConfig(forbidden_tokens=["CUSTOM_BAD"])
        spell = _simple_spell("Do not put CUSTOM_BAD here.")
        result = validate_spell_style(spell, config=cfg)
        assert any("CUSTOM_BAD" in d.message for d in result.diagnostics)

    def test_no_forbidden_tokens_clean(self):
        spell = _simple_spell("Regular content here.")
        result = validate_spell_style(spell)
        forbidden_diags = [d for d in result.diagnostics if "forbidden token" in d.message]
        assert forbidden_diags == []

    # camelCase variable names
    def test_camel_case_variable_warning(self):
        vars_ = {"userName": VariableSpec(type=VariableType.STRING)}
        spell = _simple_spell(variables=vars_)
        result = validate_spell_style(spell)
        assert any("userName" in d.message and "snake_case" in d.message for d in result.diagnostics)

    def test_snake_case_variable_clean(self):
        vars_ = {"user_name": VariableSpec(type=VariableType.STRING)}
        spell = _simple_spell(variables=vars_)
        result = validate_spell_style(spell)
        camel_diags = [d for d in result.diagnostics if "snake_case" in d.message]
        assert camel_diags == []

    def test_camel_case_severity_is_warning(self):
        vars_ = {"apiKey": VariableSpec(type=VariableType.STRING)}
        spell = _simple_spell(variables=vars_)
        result = validate_spell_style(spell)
        camel_diags = [d for d in result.diagnostics if "snake_case" in d.message]
        assert all(d.severity == Severity.WARNING for d in camel_diags)

    # Required vars without ask
    def test_required_var_no_ask_info(self):
        vars_ = {"name": VariableSpec(type=VariableType.STRING, required=True)}
        spell = _simple_spell(variables=vars_)
        result = validate_spell_style(spell)
        ask_diags = [d for d in result.diagnostics if "ask" in d.message.lower() and "name" in d.message]
        assert len(ask_diags) == 1
        assert ask_diags[0].severity == Severity.INFO

    def test_required_var_with_ask_clean(self):
        vars_ = {"name": VariableSpec(type=VariableType.STRING, required=True, ask="Your name?")}
        spell = _simple_spell(variables=vars_)
        result = validate_spell_style(spell)
        ask_diags = [d for d in result.diagnostics if "ask" in d.message.lower()]
        assert ask_diags == []

    def test_optional_var_no_ask_ok(self):
        """Optional vars don't need ask prompts."""
        vars_ = {"opt": VariableSpec(type=VariableType.STRING, required=False)}
        spell = _simple_spell(variables=vars_)
        result = validate_spell_style(spell)
        ask_diags = [d for d in result.diagnostics if "'opt'" in d.message and "ask" in d.message.lower()]
        assert ask_diags == []

    # USER block length
    def test_user_block_too_long(self):
        cfg = LintConfig(max_user_block_chars=10)
        spell = _simple_spell("This content is longer than 10 chars.")
        result = validate_spell_style(spell, config=cfg)
        length_diags = [d for d in result.diagnostics if "USER block length" in d.message]
        assert len(length_diags) == 1
        assert length_diags[0].severity == Severity.WARNING

    def test_user_block_within_limit(self):
        cfg = LintConfig(max_user_block_chars=1000)
        spell = _simple_spell("Short.")
        result = validate_spell_style(spell, config=cfg)
        length_diags = [d for d in result.diagnostics if "USER block length" in d.message]
        assert length_diags == []

    def test_user_block_no_limit_zero(self):
        cfg = LintConfig(max_user_block_chars=0)  # 0 = disabled
        spell = _simple_spell("x" * 100_000)
        result = validate_spell_style(spell, config=cfg)
        length_diags = [d for d in result.diagnostics if "USER block length" in d.message]
        assert length_diags == []

    # Sensitive variable names
    def test_secret_name_public_sensitivity_warning(self):
        vars_ = {"api_key": VariableSpec(
            type=VariableType.STRING,
            sensitivity=VariableSensitivity.PUBLIC,
        )}
        spell = _simple_spell(variables=vars_)
        result = validate_spell_style(spell)
        sens_diags = [d for d in result.diagnostics if "api_key" in d.message and "secret" in d.message.lower()]
        assert len(sens_diags) == 1
        assert sens_diags[0].severity == Severity.WARNING

    def test_secret_name_already_secret_clean(self):
        vars_ = {"api_key": VariableSpec(
            type=VariableType.STRING,
            sensitivity=VariableSensitivity.SECRET,
        )}
        spell = _simple_spell(variables=vars_)
        result = validate_spell_style(spell)
        sens_diags = [d for d in result.diagnostics if "api_key" in d.message and "sensitivity" in d.message.lower()]
        assert sens_diags == []

    def test_sensitive_patterns(self):
        """All sensitive name patterns should trigger the warning."""
        for name in ["password", "secret_key", "access_token", "private_key"]:
            vars_ = {name: VariableSpec(type=VariableType.STRING, sensitivity=VariableSensitivity.PUBLIC)}
            spell = _simple_spell(variables=vars_)
            result = validate_spell_style(spell)
            diags = [d for d in result.diagnostics if name in d.message]
            assert diags, f"Expected warning for sensitive name '{name}'"

    def test_sensitivity_check_disabled(self):
        cfg = LintConfig(check_sensitivity=False)
        vars_ = {"api_key": VariableSpec(type=VariableType.STRING, sensitivity=VariableSensitivity.PUBLIC)}
        spell = _simple_spell(variables=vars_)
        result = validate_spell_style(spell, config=cfg)
        sens_diags = [d for d in result.diagnostics if "sensitivity" in d.message.lower()]
        assert sens_diags == []

    # Engineering quality
    def test_engineering_tag_missing_keywords(self):
        spell = _simple_spell("Just some content.", tags=["engineering"])
        result = validate_spell_style(spell)
        eng_diags = [d for d in result.diagnostics
                     if d.severity == Severity.INFO and ("assumption" in d.message or "failure" in d.message.lower())]
        assert len(eng_diags) > 0

    def test_engineering_tag_with_keywords_clean(self):
        content = "Assumption: X. Failure mode: Y. Validation: Z. Edge case: W."
        spell = _simple_spell(content, tags=["engineering"])
        result = validate_spell_style(spell)
        eng_diags = [d for d in result.diagnostics
                     if "assumption" in d.message.lower() or "failure" in d.message.lower()]
        assert eng_diags == []

    def test_non_engineering_tag_no_quality_check(self):
        spell = _simple_spell("No keywords here.", tags=["other"])
        result = validate_spell_style(spell)
        eng_diags = [d for d in result.diagnostics
                     if "Engineering spell" in d.message]
        assert eng_diags == []

    def test_engineering_check_disabled(self):
        cfg = LintConfig(check_engineering_quality=False)
        spell = _simple_spell("No keywords.", tags=["engineering"])
        result = validate_spell_style(spell, config=cfg)
        eng_diags = [d for d in result.diagnostics if "Engineering" in d.message]
        assert eng_diags == []

    # ValidationResult helpers
    def test_result_ok_no_errors(self):
        spell = _simple_spell("Clean.")
        result = validate_spell_style(spell)
        assert result.ok  # only warnings/infos possible from style check

    def test_result_errors_only_error_severity(self):
        """result.errors returns only ERROR-severity diagnostics."""
        spell = _simple_spell("TODO fix")
        result = validate_spell_style(spell)
        # Style lint only emits WARNING/INFO, not ERROR
        assert result.errors == []

    def test_result_warnings_list(self):
        spell = _simple_spell("TODO and FIXME here.")
        result = validate_spell_style(spell)
        assert len(result.warnings) >= 2


# ── CLI prompt lint tests ─────────────────────────────────────────────────────


class TestPromptLintCLI:
    def test_lint_all_spells(self, tmp_path: Path):
        _make_lint_repo(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["--repo", str(tmp_path), "prompt", "lint"])
        assert result.exit_code == 0

    def test_lint_clean_spell_exit_zero(self, tmp_path: Path):
        _make_lint_repo(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["--repo", str(tmp_path), "prompt", "lint", "test/clean"])
        assert result.exit_code == 0

    def test_lint_dirty_spell_exit_zero_without_fail_on_warnings(self, tmp_path: Path):
        """Warnings alone don't cause non-zero exit unless --fail-on-warnings."""
        _make_lint_repo(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["--repo", str(tmp_path), "prompt", "lint", "test/dirty"])
        assert result.exit_code == 0

    def test_lint_dirty_spell_fail_on_warnings(self, tmp_path: Path):
        _make_lint_repo(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--repo", str(tmp_path), "prompt", "lint", "test/dirty", "--fail-on-warnings"],
        )
        # dirty spell has warnings → exit non-zero
        assert result.exit_code != 0

    def test_lint_json_output(self, tmp_path: Path):
        _make_lint_repo(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli, ["--repo", str(tmp_path), "prompt", "lint", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) == 2
        # Each entry has spell_id, ok, diagnostics
        for entry in data:
            assert "spell_id" in entry
            assert "ok" in entry
            assert "diagnostics" in entry

    def test_lint_json_diagnostics_format(self, tmp_path: Path):
        _make_lint_repo(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli, ["--repo", str(tmp_path), "prompt", "lint", "test/dirty", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        dirty = next(e for e in data if e["spell_id"] == "test/dirty")
        assert len(dirty["diagnostics"]) > 0
        for d in dirty["diagnostics"]:
            assert "severity" in d
            assert "message" in d

    def test_lint_by_tag(self, tmp_path: Path):
        _make_lint_repo(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli, ["--repo", str(tmp_path), "prompt", "lint", "--tag", "test"])
        assert result.exit_code == 0

    def test_lint_nonexistent_spell(self, tmp_path: Path):
        _make_lint_repo(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli, ["--repo", str(tmp_path), "prompt", "lint", "does/not/exist"])
        assert result.exit_code != 0

    def test_lint_output_shows_spell_id(self, tmp_path: Path):
        _make_lint_repo(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["--repo", str(tmp_path), "prompt", "lint"])
        assert "test/clean" in result.output
        assert "test/dirty" in result.output


# ── CLI prompt test (golden) tests ────────────────────────────────────────────


class TestPromptTestCLI:
    def test_prompt_test_no_golden(self, tmp_path: Path):
        """Without golden files, all spells report missing_golden."""
        _make_lint_repo(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["--repo", str(tmp_path), "prompt", "test"])
        assert result.exit_code == 0
        # Should mention missing golden
        assert "golden" in result.output.lower() or "missing" in result.output.lower()

    def test_prompt_test_update_golden(self, tmp_path: Path):
        """--update-golden should create golden files."""
        _make_lint_repo(tmp_path)
        golden_dir = tmp_path / "tests" / "golden"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "--repo", str(tmp_path),
                "prompt", "test",
                "test/clean",
                "--update-golden",
                "--golden-dir", str(golden_dir),
            ],
        )
        assert result.exit_code == 0
        golden_files = list(golden_dir.glob("*.golden.txt"))
        assert len(golden_files) == 1

    def test_prompt_test_passes_after_update(self, tmp_path: Path):
        """After --update-golden, running prompt test should PASS."""
        _make_lint_repo(tmp_path)
        golden_dir = tmp_path / "tests" / "golden"
        runner = CliRunner()
        # First: create golden
        runner.invoke(
            cli,
            ["--repo", str(tmp_path), "prompt", "test", "test/clean",
             "--update-golden", "--golden-dir", str(golden_dir)],
        )
        # Second: verify against golden
        result = runner.invoke(
            cli,
            ["--repo", str(tmp_path), "prompt", "test", "test/clean",
             "--golden-dir", str(golden_dir)],
        )
        assert result.exit_code == 0
        assert "pass" in result.output.lower()

    def test_prompt_test_fails_on_mismatch(self, tmp_path: Path):
        """If golden content doesn't match current render, should report failure."""
        _make_lint_repo(tmp_path)
        golden_dir = tmp_path / "tests" / "golden"
        golden_dir.mkdir(parents=True)
        # Write wrong golden content
        (golden_dir / "test__clean.text.golden.txt").write_text("WRONG CONTENT HERE")
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--repo", str(tmp_path), "prompt", "test", "test/clean",
             "--golden-dir", str(golden_dir)],
        )
        # Exit non-zero on mismatch
        assert result.exit_code != 0 or "fail" in result.output.lower()

    def test_prompt_test_json_output(self, tmp_path: Path):
        """--json flag outputs structured results."""
        _make_lint_repo(tmp_path)
        golden_dir = tmp_path / "tests" / "golden"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--repo", str(tmp_path), "prompt", "test",
             "--golden-dir", str(golden_dir), "--json"],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        for entry in data:
            assert "spell_id" in entry
            assert "status" in entry

    def test_prompt_test_custom_golden_dir(self, tmp_path: Path):
        """--golden-dir should be respected."""
        _make_lint_repo(tmp_path)
        custom_dir = tmp_path / "my_goldens"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--repo", str(tmp_path), "prompt", "test", "test/clean",
             "--update-golden", "--golden-dir", str(custom_dir)],
        )
        assert result.exit_code == 0
        assert (custom_dir / "test__clean.text.golden.txt").exists()

    def test_prompt_test_format_openai(self, tmp_path: Path):
        """--format openai produces different golden files."""
        _make_lint_repo(tmp_path)
        custom_dir = tmp_path / "goldens"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--repo", str(tmp_path), "prompt", "test", "test/clean",
             "--update-golden", "--golden-dir", str(custom_dir), "--format", "openai"],
        )
        assert result.exit_code == 0
        openai_files = list(custom_dir.glob("*.openai.golden.txt"))
        assert len(openai_files) == 1
