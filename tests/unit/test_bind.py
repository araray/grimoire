# tests/unit/test_bind.py
"""
Tests for the grimoire bind module (Phase 2).

Covers:
    - Base types (BindResult, BoundFile, BindTarget)
    - SemantiscanBinder (TOML + legacy .tmpl)
    - LLMCoreBinder (registry bundle + activities)
    - WairuBinder (tool packs + augmentations)
    - CLI bind command
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from grimoire.bind.base import BindFormat, BindResult, BindTarget, BoundFile
from grimoire.bind.llmcore import (
    LLMCoreBinder,
    _command_to_tool_schema,
    _rune_to_activity_definition,
    _spell_to_registry_entry,
)
from grimoire.bind.semantiscan import (
    SemantiscanBinder,
    _convert_vars_to_semantiscan,
    _spell_to_legacy_tmpl,
    _spell_to_toml,
)
from grimoire.bind.wairu import WairuBinder, _rune_to_tool_pack, _spell_to_augmentation
from grimoire.models import (
    CommandExample,
    CommandSpec,
    MessageBlock,
    MessageRole,
    ParamSpec,
    ReturnSpec,
    RiskLevel,
    RuneSpec,
    Spell,
    VariableSpec,
    VariableType,
)
from grimoire.store.repo import GrimoireRepo

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def simple_spell() -> Spell:
    """A minimal spell for testing binding."""
    return Spell(
        id="test/hello",
        name="Hello World",
        version="1.0.0",
        tags=["example"],
        variables={
            "name": VariableSpec(type=VariableType.STRING, required=True, ask="Your name?"),
            "style": VariableSpec(type=VariableType.STRING, required=False, default="friendly"),
        },
        raw_blocks=[
            MessageBlock(role=MessageRole.SYSTEM, content="You are a {{ style }} assistant."),
            MessageBlock(role=MessageRole.USER, content="Hello {{ name }}! How are you?"),
        ],
    )


@pytest.fixture
def engineering_spell() -> Spell:
    """An engineering spell with includes and rune refs."""
    return Spell(
        id="engineering/rca",
        name="Root Cause Analysis",
        version="2.0.0",
        tags=["engineering", "debugging"],
        requires_runes=["devtools/git"],
        variables={
            "issue": VariableSpec(type=VariableType.STRING, required=True),
            "env": VariableSpec(type=VariableType.MULTILINE, required=False, default="(unknown)"),
        },
        raw_blocks=[
            MessageBlock(
                role=MessageRole.SYSTEM,
                content='{{ include("safety/base") }}\nYou are a principal SWE.',
            ),
            MessageBlock(
                role=MessageRole.DEVELOPER,
                content="Use systematic analysis. List assumptions and failure modes.",
            ),
            MessageBlock(
                role=MessageRole.USER,
                content="Investigate: {{ issue }}\nEnvironment: {{ env }}",
            ),
        ],
    )


@pytest.fixture
def agentic_spell() -> Spell:
    """An agentic spell for wairu augmentation."""
    return Spell(
        id="agentic/tool_policy",
        name="Low-Risk Tool Policy",
        tags=["agentic", "tooling"],
        raw_blocks=[
            MessageBlock(
                role=MessageRole.SYSTEM,
                content="Only use tools tagged low-risk without explicit approval.",
            ),
        ],
    )


@pytest.fixture
def git_rune() -> RuneSpec:
    """A rune with multiple commands for testing."""
    return RuneSpec(
        id="devtools/git",
        name="Git (diagnostics)",
        version="1.0.0",
        description="Git commands for diagnostics.",
        tags=["devtools", "vcs"],
        risk_level=RiskLevel.LOW,
        permissions=["read_fs"],
        commands=[
            CommandSpec(
                name="status",
                summary="Show working tree status",
                params=[
                    ParamSpec(name="porcelain", type="bool", required=False, default=True),
                ],
                returns=ReturnSpec(
                    type="object",
                    properties={"stdout": {"type": "string"}},
                ),
                side_effects=[],
                examples=[
                    CommandExample(call={"porcelain": True}, expect="file list"),
                ],
            ),
            CommandSpec(
                name="diff",
                summary="Show changes",
                params=[
                    ParamSpec(name="pathspec", type="string", required=False),
                    ParamSpec(name="staged", type="bool", required=False, default=False),
                ],
                side_effects=[],
            ),
        ],
    )


@pytest.fixture
def test_repo(tmp_path: Path, simple_spell: Spell, git_rune: RuneSpec) -> GrimoireRepo:
    """Build a minimal on-disk grimoire repo for integration tests."""
    # Manifest
    (tmp_path / "grimoire.yaml").write_text(
        "name: test-bind\nversion: 0.1.0\nspell_paths: [spells/]\n"
        "rune_paths: [runes/]\npromptlet_paths: [spells/promptlets/]\n"
        "ritual_paths: [rituals/]\nprofile_paths: [profiles/]\n"
        "vars_path: vars/defaults.yaml\n"
    )

    # Dirs
    (tmp_path / "spells" / "templates").mkdir(parents=True)
    (tmp_path / "spells" / "promptlets" / "safety").mkdir(parents=True)
    (tmp_path / "runes").mkdir(parents=True)
    (tmp_path / "rituals").mkdir(parents=True)
    (tmp_path / "profiles" / "user").mkdir(parents=True)
    (tmp_path / "vars").mkdir(parents=True)

    # Spell file
    (tmp_path / "spells" / "templates" / "hello.spell.md").write_text(
        "---\nid: test/hello\nname: Hello World\nversion: 1.0.0\ntags: [example]\n"
        "variables:\n  name:\n    type: string\n    required: true\n"
        "  style:\n    type: string\n    required: false\n    default: friendly\n---\n\n"
        "# SYSTEM\nYou are a {{ style }} assistant.\n\n"
        "# USER\nHello {{ name }}! How are you?\n"
    )

    # Promptlet
    (tmp_path / "spells" / "promptlets" / "safety" / "base.md").write_text(
        "Always be helpful and safe."
    )

    # Rune file
    (tmp_path / "runes" / "git.rune.yaml").write_text(
        yaml.dump(
            {
                "id": "devtools/git",
                "name": "Git (diagnostics)",
                "version": "1.0.0",
                "description": "Git commands for diagnostics.",
                "tags": ["devtools", "vcs"],
                "risk_level": "low",
                "permissions": ["read_fs"],
                "commands": [
                    {
                        "name": "status",
                        "summary": "Show working tree status",
                        "params": [
                            {
                                "name": "porcelain",
                                "type": "bool",
                                "required": False,
                                "default": True,
                            }
                        ],
                        "side_effects": [],
                        "examples": [{"call": {"porcelain": True}, "expect": "file list"}],
                    },
                    {
                        "name": "diff",
                        "summary": "Show changes",
                        "params": [
                            {"name": "pathspec", "type": "string", "required": False},
                            {"name": "staged", "type": "bool", "required": False, "default": False},
                        ],
                        "side_effects": [],
                    },
                ],
            }
        )
    )

    # Defaults
    (tmp_path / "vars" / "defaults.yaml").write_text("default_greeting: Hello\n")

    # Profile
    (tmp_path / "profiles" / "user" / "testuser.yaml").write_text("name: TestUser\n")

    return GrimoireRepo.load(tmp_path)


# =============================================================================
# Base types tests
# =============================================================================


class TestBindResult:
    def test_ok_with_files(self):
        result = BindResult(
            target=BindTarget.SEMANTISCAN,
            format=BindFormat.TOML,
            files=[BoundFile(relative_path="test.toml", content="x")],
        )
        assert result.ok

    def test_not_ok_without_files(self):
        result = BindResult(target=BindTarget.SEMANTISCAN, format=BindFormat.TOML)
        assert not result.ok

    def test_write_creates_files(self, tmp_path: Path):
        result = BindResult(
            target=BindTarget.LLMCORE,
            format=BindFormat.REGISTRY_BUNDLE,
            files=[
                BoundFile(relative_path="prompts/test.json", content='{"id": "test"}'),
                BoundFile(relative_path="manifest.json", content="{}"),
            ],
        )
        written = result.write(tmp_path)
        assert len(written) == 2
        assert (tmp_path / "prompts" / "test.json").exists()
        assert (tmp_path / "manifest.json").exists()
        assert json.loads((tmp_path / "prompts" / "test.json").read_text()) == {"id": "test"}


# =============================================================================
# Semantiscan binder tests
# =============================================================================


class TestSemantiscanVarConversion:
    """Test variable syntax conversion: grimoire → semantiscan."""

    def test_plain_var(self):
        assert _convert_vars_to_semantiscan("{{ name }}") == "{name}"

    def test_var_with_default(self):
        assert _convert_vars_to_semantiscan('{{ env|default("prod") }}') == "{env}"

    def test_builtin_remapping(self):
        assert _convert_vars_to_semantiscan("{{ grimoire.now.date }}") == "{current_date}"

    def test_include_stripped(self):
        result = _convert_vars_to_semantiscan('{{ include("safety/base") }}\nHello')
        assert "include" not in result
        assert "Hello" in result

    def test_mixed_content(self):
        template = "Date: {{ grimoire.now.date }}\nUser: {{ name }}\nEnv: {{ env|default('dev') }}"
        result = _convert_vars_to_semantiscan(template)
        assert "{current_date}" in result
        assert "{name}" in result
        assert "{env}" in result


class TestSemantiscanToml:
    def test_basic_toml(self, simple_spell: Spell):
        toml_content = _spell_to_toml(simple_spell)
        assert "[metadata]" in toml_content
        assert "[prompts]" in toml_content
        assert 'name = "test/hello"' in toml_content
        assert "{style}" in toml_content
        assert "{name}" in toml_content

    def test_toml_has_defaults(self, simple_spell: Spell):
        toml_content = _spell_to_toml(simple_spell)
        assert "[defaults]" in toml_content
        assert 'style = "friendly"' in toml_content

    def test_toml_has_header_comment(self, simple_spell: Spell):
        toml_content = _spell_to_toml(simple_spell)
        assert "Auto-generated by grimoire" in toml_content
        assert "DO NOT EDIT" in toml_content


class TestSemantiscanLegacyTmpl:
    def test_basic_tmpl(self, simple_spell: Spell):
        tmpl = _spell_to_legacy_tmpl(simple_spell)
        assert "{name}" in tmpl
        # Legacy format requires {context} and {question}
        assert "{context}" in tmpl
        assert "{question}" in tmpl

    def test_tmpl_with_existing_context(self):
        """Spell already using context/question shouldn't get duplicates."""
        spell = Spell(
            id="test/rag",
            name="RAG",
            raw_blocks=[
                MessageBlock(
                    role=MessageRole.USER,
                    content="Given {{ context }}, answer {{ question }}",
                ),
            ],
        )
        tmpl = _spell_to_legacy_tmpl(spell)
        # Should have exactly one {context} and one {question}
        assert tmpl.count("{context}") == 1
        assert tmpl.count("{question}") == 1


class TestSemantiscanBinder:
    def test_bind_toml(self, test_repo: GrimoireRepo):
        binder = SemantiscanBinder()
        assert binder.target == BindTarget.SEMANTISCAN
        assert binder.default_format == BindFormat.TOML

        result = binder.bind(test_repo, fmt=BindFormat.TOML)
        assert result.ok
        assert any(f.relative_path.endswith(".toml") for f in result.files)

    def test_bind_legacy_tmpl(self, test_repo: GrimoireRepo):
        result = SemantiscanBinder().bind(test_repo, fmt=BindFormat.LEGACY_TMPL)
        assert result.ok
        assert any(f.relative_path.endswith(".tmpl") for f in result.files)

    def test_bind_specific_spell(self, test_repo: GrimoireRepo):
        result = SemantiscanBinder().bind(test_repo, spell_ids=["test/hello"])
        assert result.ok
        assert len([f for f in result.files if f.relative_path.endswith(".toml")]) == 1

    def test_bind_missing_spell_warns(self, test_repo: GrimoireRepo):
        result = SemantiscanBinder().bind(test_repo, spell_ids=["nonexistent/spell"])
        assert not result.ok
        assert any("not found" in w for w in result.warnings)

    def test_bind_write_to_disk(self, test_repo: GrimoireRepo, tmp_path: Path):
        result = SemantiscanBinder().bind(test_repo)
        written = result.write(tmp_path)
        assert len(written) >= 1
        # File content should be valid
        for path in written:
            content = path.read_text()
            assert len(content) > 0


# =============================================================================
# LLMCore binder tests
# =============================================================================


class TestLLMCoreSpellEntry:
    def test_basic_entry(self, simple_spell: Spell):
        entry = _spell_to_registry_entry(simple_spell)
        assert entry["id"] == "test/hello"
        assert entry["name"] == "Hello World"
        assert entry["version"] == "1.0.0"
        assert len(entry["messages"]) == 2
        assert entry["messages"][0]["role"] == "system"
        assert entry["messages"][1]["role"] == "user"

    def test_variables_schema(self, simple_spell: Spell):
        entry = _spell_to_registry_entry(simple_spell)
        assert "name" in entry["variables"]
        assert entry["variables"]["name"]["type"] == "string"
        assert entry["variables"]["name"]["required"] is True
        assert entry["variables"]["style"]["default"] == "friendly"

    def test_content_hash(self, simple_spell: Spell):
        entry = _spell_to_registry_entry(simple_spell)
        assert "content_hash" in entry


class TestLLMCoreActivityDefinition:
    def test_basic_activity(self, git_rune: RuneSpec):
        activity = _rune_to_activity_definition(git_rune)
        assert activity["id"] == "devtools/git"
        assert activity["risk_level"] == "low"
        assert len(activity["commands"]) == 2

    def test_tool_schema(self, git_rune: RuneSpec):
        activity = _rune_to_activity_definition(git_rune)
        cmd = activity["commands"][0]
        assert "tool_schema" in cmd
        schema = cmd["tool_schema"]
        assert schema["type"] == "function"
        assert "porcelain" in schema["function"]["parameters"]["properties"]


class TestLLMCoreToolSchema:
    def test_command_to_tool_schema(self, git_rune: RuneSpec):
        cmd = git_rune.commands[0]
        schema = _command_to_tool_schema(cmd, git_rune)
        assert schema["type"] == "function"
        func = schema["function"]
        assert "devtools_git_status" == func["name"]
        assert "porcelain" in func["parameters"]["properties"]


class TestLLMCoreBinder:
    def test_bind_produces_manifest(self, test_repo: GrimoireRepo):
        binder = LLMCoreBinder()
        assert binder.target == BindTarget.LLMCORE

        result = binder.bind(test_repo)
        assert result.ok
        # Should have manifest + prompts + activities
        assert any(f.relative_path == "manifest.json" for f in result.files)
        assert any("prompts/" in f.relative_path for f in result.files)
        assert any("activities/" in f.relative_path for f in result.files)

    def test_manifest_structure(self, test_repo: GrimoireRepo):
        result = LLMCoreBinder().bind(test_repo)
        manifest_file = next(f for f in result.files if f.relative_path == "manifest.json")
        manifest = json.loads(manifest_file.content)
        assert "prompts" in manifest
        assert "activities" in manifest
        assert manifest["grimoire"] == "test-bind"

    def test_prompt_file_valid_json(self, test_repo: GrimoireRepo):
        result = LLMCoreBinder().bind(test_repo)
        for f in result.files:
            if f.relative_path.startswith("prompts/"):
                entry = json.loads(f.content)
                assert "id" in entry
                assert "messages" in entry
                assert "variables" in entry

    def test_activity_file_valid_json(self, test_repo: GrimoireRepo):
        result = LLMCoreBinder().bind(test_repo)
        for f in result.files:
            if f.relative_path.startswith("activities/"):
                entry = json.loads(f.content)
                assert "id" in entry
                assert "commands" in entry
                assert "risk_level" in entry

    def test_write_to_disk(self, test_repo: GrimoireRepo, tmp_path: Path):
        result = LLMCoreBinder().bind(test_repo)
        written = result.write(tmp_path)
        assert len(written) >= 3  # manifest + 1 prompt + 1 activity
        assert (tmp_path / "manifest.json").exists()


# =============================================================================
# Wairu binder tests
# =============================================================================


class TestWairuToolPack:
    def test_basic_tool_pack(self, git_rune: RuneSpec):
        pack = _rune_to_tool_pack(git_rune)
        assert pack["id"] == "devtools/git"
        assert pack["risk_level"] == "low"
        assert len(pack["tools"]) == 2
        assert pack["_source"] == "grimoire"

    def test_tool_parameters(self, git_rune: RuneSpec):
        pack = _rune_to_tool_pack(git_rune)
        status_tool = pack["tools"][0]
        assert "parameters" in status_tool
        assert "porcelain" in status_tool["parameters"]["properties"]

    def test_tool_examples(self, git_rune: RuneSpec):
        pack = _rune_to_tool_pack(git_rune)
        status_tool = pack["tools"][0]
        assert "examples" in status_tool
        assert status_tool["examples"][0]["call"]["porcelain"] is True


class TestWairuAugmentation:
    def test_spell_augmentation(self, agentic_spell: Spell):
        aug = _spell_to_augmentation(agentic_spell)
        assert aug["id"] == "agentic/tool_policy"
        assert "low-risk" in aug["content"]
        assert aug["tags"] == ["agentic", "tooling"]


class TestWairuBinder:
    def test_bind_produces_tools(self, test_repo: GrimoireRepo):
        binder = WairuBinder()
        assert binder.target == BindTarget.WAIRU

        result = binder.bind(test_repo)
        assert result.ok
        assert any("tools/" in f.relative_path for f in result.files)
        assert any(f.relative_path == "tool_manifest.json" for f in result.files)

    def test_tool_files_valid_yaml(self, test_repo: GrimoireRepo):
        result = WairuBinder().bind(test_repo)
        for f in result.files:
            if f.relative_path.startswith("tools/") and f.relative_path.endswith(".yaml"):
                pack = yaml.safe_load(f.content)
                assert "id" in pack
                assert "tools" in pack
                assert pack["_source"] == "grimoire"

    def test_manifest_structure(self, test_repo: GrimoireRepo):
        result = WairuBinder().bind(test_repo)
        manifest_file = next(f for f in result.files if f.relative_path == "tool_manifest.json")
        manifest = json.loads(manifest_file.content)
        assert "tools" in manifest
        assert "augmentations" in manifest

    def test_write_to_disk(self, test_repo: GrimoireRepo, tmp_path: Path):
        result = WairuBinder().bind(test_repo)
        written = result.write(tmp_path)
        assert any(str(p).endswith(".yaml") for p in written)
        assert (tmp_path / "tool_manifest.json").exists()


# =============================================================================
# CLI bind command tests
# =============================================================================


class TestBindCLI:
    """Test the ``grimoire bind`` CLI command via Click's test runner."""

    @pytest.fixture
    def runner(self):
        from click.testing import CliRunner

        return CliRunner()

    @pytest.fixture
    def cli(self):
        from grimoire.cli import cli

        return cli

    @pytest.fixture
    def repo_dir(self, test_repo: GrimoireRepo) -> Path:
        return test_repo.root

    def test_bind_semantiscan_toml(self, runner, cli, repo_dir: Path, tmp_path: Path):
        out_dir = str(tmp_path / "out")
        result = runner.invoke(
            cli,
            [
                "--repo",
                str(repo_dir),
                "--out",
                out_dir,
                "bind",
                "semantiscan",
                "--format",
                "toml",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "Bound" in result.output

    def test_bind_semantiscan_legacy(self, runner, cli, repo_dir: Path, tmp_path: Path):
        out_dir = str(tmp_path / "out")
        result = runner.invoke(
            cli,
            [
                "--repo",
                str(repo_dir),
                "--out",
                out_dir,
                "bind",
                "semantiscan",
                "--format",
                "legacy_tmpl",
            ],
        )
        assert result.exit_code == 0, result.output

    def test_bind_llmcore(self, runner, cli, repo_dir: Path, tmp_path: Path):
        out_dir = str(tmp_path / "out")
        result = runner.invoke(
            cli,
            [
                "--repo",
                str(repo_dir),
                "--out",
                out_dir,
                "bind",
                "llmcore",
            ],
        )
        assert result.exit_code == 0, result.output
        assert (Path(out_dir) / "manifest.json").exists()

    def test_bind_wairu(self, runner, cli, repo_dir: Path, tmp_path: Path):
        out_dir = str(tmp_path / "out")
        result = runner.invoke(
            cli,
            [
                "--repo",
                str(repo_dir),
                "--out",
                out_dir,
                "bind",
                "wairu",
            ],
        )
        assert result.exit_code == 0, result.output
        assert (Path(out_dir) / "tool_manifest.json").exists()

    def test_bind_dry_run(self, runner, cli, repo_dir: Path):
        result = runner.invoke(
            cli,
            [
                "--repo",
                str(repo_dir),
                "bind",
                "semantiscan",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        assert "Would generate" in result.output

    def test_bind_with_spell_filter(self, runner, cli, repo_dir: Path, tmp_path: Path):
        out_dir = str(tmp_path / "out")
        result = runner.invoke(
            cli,
            [
                "--repo",
                str(repo_dir),
                "--out",
                out_dir,
                "bind",
                "semantiscan",
                "--spells",
                "test/hello",
            ],
        )
        assert result.exit_code == 0, result.output

    def test_bind_help(self, runner, cli):
        result = runner.invoke(cli, ["bind", "--help"])
        assert result.exit_code == 0
        assert "semantiscan" in result.output
        assert "llmcore" in result.output
        assert "wairu" in result.output


# =============================================================================
# Profile overlay tests (Phase 1 completion)
# =============================================================================


class TestProfileOverlay:
    """Test profile loading in CLI helpers."""

    def test_load_profile(self, test_repo: GrimoireRepo):
        from grimoire.cli.helpers import load_profiles

        profile_vars = load_profiles(test_repo, ["user/testuser"])
        assert profile_vars.get("name") == "TestUser"

    def test_load_missing_profile_warns(self, test_repo: GrimoireRepo, capsys):
        """Missing profiles emit a warning but don't crash."""
        from grimoire.cli.helpers import load_profiles

        profile_vars = load_profiles(test_repo, ["nonexistent/profile"])
        assert profile_vars == {}

    def test_profile_merge_order(self, test_repo: GrimoireRepo, tmp_path: Path):
        """Later profiles override earlier ones."""
        # Create a second profile
        profile_dir = test_repo.root / "profiles" / "user"
        (profile_dir / "override.yaml").write_text("name: Overridden\nextra: value\n")

        from grimoire.cli.helpers import load_profiles

        profile_vars = load_profiles(test_repo, ["user/testuser", "user/override"])
        assert profile_vars["name"] == "Overridden"
        assert profile_vars["extra"] == "value"


# =============================================================================
# Additional coverage tests
# =============================================================================


class TestLLMCoreVariableSchemaEdgeCases:
    """Cover more variable schema branches in llmcore binding."""

    def test_variable_with_description(self):
        spell = Spell(
            id="test/desc",
            name="Desc Test",
            variables={
                "x": VariableSpec(
                    type=VariableType.INTEGER,
                    required=True,
                    description="A number",
                    min_value=1,
                    max_value=100,
                ),
                "choice": VariableSpec(
                    type=VariableType.CHOICE,
                    required=False,
                    choices=["a", "b", "c"],
                    default="a",
                ),
            },
            raw_blocks=[
                MessageBlock(role=MessageRole.USER, content="Value: {{ x }}, choice: {{ choice }}"),
            ],
        )
        entry = _spell_to_registry_entry(spell)
        assert entry["variables"]["x"]["description"] == "A number"
        assert entry["variables"]["x"]["min"] == 1
        assert entry["variables"]["x"]["max"] == 100
        assert entry["variables"]["choice"]["choices"] == ["a", "b", "c"]

    def test_spell_with_output_contract_json_schema(self):
        from grimoire.models import OutputContract

        spell = Spell(
            id="test/schema",
            name="Schema Test",
            description="A test spell with JSON output contract.",
            output_contract=OutputContract.model_validate(
                {
                    "type": "json",
                    "schema": {"type": "object", "properties": {"result": {"type": "string"}}},
                }
            ),
            raw_blocks=[
                MessageBlock(role=MessageRole.USER, content="Respond with JSON."),
            ],
        )
        entry = _spell_to_registry_entry(spell)
        assert entry["description"] == "A test spell with JSON output contract."
        assert entry["output_contract"]["type"] == "json"
        assert "schema" in entry["output_contract"]

    def test_spell_with_rune_refs(self):
        spell = Spell(
            id="test/refs",
            name="Refs Test",
            requires_runes=["devtools/git"],
            suggests_runes=["devtools/npm"],
            raw_blocks=[
                MessageBlock(role=MessageRole.USER, content="Hi"),
            ],
        )
        entry = _spell_to_registry_entry(spell)
        assert entry["requires_runes"] == ["devtools/git"]
        assert entry["suggests_runes"] == ["devtools/npm"]


class TestWairuToolPackEdgeCases:
    """Cover more branches in wairu binding."""

    def test_tool_with_constraints(self):
        rune = RuneSpec(
            id="test/constrained",
            name="Constrained Tool",
            risk_level=RiskLevel.MEDIUM,
            requires_approval=True,
            commands=[
                CommandSpec(
                    name="run",
                    summary="Run with constraints",
                    params=[
                        ParamSpec(
                            name="timeout",
                            type="integer",
                            required=True,
                            description="Timeout in seconds",
                            minimum=1,
                            maximum=300,
                        ),
                        ParamSpec(
                            name="mode",
                            type="string",
                            required=False,
                            default="safe",
                            enum=["safe", "fast", "debug"],
                        ),
                    ],
                    side_effects=["writes_fs"],
                ),
            ],
        )
        pack = _rune_to_tool_pack(rune)
        tool = pack["tools"][0]
        assert tool["requires_approval"] is True
        assert tool["risk_level"] == "medium"
        props = tool["parameters"]["properties"]
        assert props["timeout"]["minimum"] == 1
        assert props["timeout"]["maximum"] == 300
        assert props["mode"]["enum"] == ["safe", "fast", "debug"]
        assert props["mode"]["default"] == "safe"
        assert "required" in tool["parameters"]
        assert "timeout" in tool["parameters"]["required"]

    def test_augmentation_with_variables(self, agentic_spell: Spell):
        aug = _spell_to_augmentation(agentic_spell)
        assert "variables" in aug
        assert isinstance(aug["variables"], dict)


class TestSemantiscanEdgeCases:
    """Cover more branches in semantiscan binding."""

    def test_toml_boolean_default(self):
        spell = Spell(
            id="test/bool",
            name="Bool Test",
            variables={
                "verbose": VariableSpec(type=VariableType.BOOLEAN, required=False, default=True),
            },
            raw_blocks=[
                MessageBlock(role=MessageRole.USER, content="Verbose: {{ verbose }}"),
            ],
        )
        toml_content = _spell_to_toml(spell)
        assert "verbose = true" in toml_content

    def test_toml_numeric_default(self):
        spell = Spell(
            id="test/num",
            name="Num Test",
            variables={
                "count": VariableSpec(type=VariableType.INTEGER, required=False, default=42),
            },
            raw_blocks=[
                MessageBlock(role=MessageRole.USER, content="Count: {{ count }}"),
            ],
        )
        toml_content = _spell_to_toml(spell)
        assert "count = 42" in toml_content

    def test_toml_developer_block_in_system(self):
        """DEVELOPER blocks should merge into system section in TOML."""
        spell = Spell(
            id="test/dev",
            name="Dev Test",
            raw_blocks=[
                MessageBlock(role=MessageRole.SYSTEM, content="System instruction."),
                MessageBlock(role=MessageRole.DEVELOPER, content="Developer context."),
                MessageBlock(role=MessageRole.USER, content="User question."),
            ],
        )
        toml_content = _spell_to_toml(spell)
        # Both system and developer blocks should be in the system prompt
        assert "System instruction." in toml_content
        assert "Developer context." in toml_content

    def test_bind_with_tag_filter(self, test_repo: GrimoireRepo):
        result = SemantiscanBinder().bind(test_repo, tags=["nonexistent"])
        assert not result.ok
        assert any("No spells" in w for w in result.warnings)


class TestLLMCoreBinderEdgeCases:
    """Cover error path branches in llmcore binder."""

    def test_bind_with_tag_filter_no_match(self, test_repo: GrimoireRepo):
        result = LLMCoreBinder().bind(test_repo, tags=["nonexistent"])
        # Should still produce manifest, just empty
        assert result.ok  # manifest is always produced
        manifest_file = next(f for f in result.files if f.relative_path == "manifest.json")
        manifest = json.loads(manifest_file.content)
        assert manifest["prompts"] == []
        assert manifest["activities"] == []

    def test_bind_missing_rune(self, test_repo: GrimoireRepo):
        result = LLMCoreBinder().bind(test_repo, rune_ids=["nonexistent/rune"])
        assert any("not found" in w for w in result.warnings)


class TestWairuBinderEdgeCases:
    def test_bind_missing_rune(self, test_repo: GrimoireRepo):
        result = WairuBinder().bind(test_repo, rune_ids=["nonexistent/rune"])
        assert any("not found" in w for w in result.warnings)

    def test_bind_by_tags(self, test_repo: GrimoireRepo):
        result = WairuBinder().bind(test_repo, tags=["devtools"])
        assert result.ok
        # Should find the devtools/git rune
        tool_files = [f for f in result.files if f.relative_path.startswith("tools/")]
        assert len(tool_files) >= 1


# =============================================================================
# Interactive fill tests (prompt_for_variable via mock)
# =============================================================================


class TestPromptForVariable:
    """Test interactive variable prompting with mocked click.prompt."""

    def test_string_prompt(self, monkeypatch):
        from grimoire.cli.helpers import prompt_for_variable

        monkeypatch.setattr("click.prompt", lambda *a, **kw: "Alice")
        spec = VariableSpec(type=VariableType.STRING, required=True, ask="Name?")
        assert prompt_for_variable("name", spec) == "Alice"

    def test_integer_prompt(self, monkeypatch):
        from grimoire.cli.helpers import prompt_for_variable

        monkeypatch.setattr("click.prompt", lambda *a, **kw: 42)
        spec = VariableSpec(type=VariableType.INTEGER, required=True)
        assert prompt_for_variable("count", spec) == 42

    def test_float_prompt(self, monkeypatch):
        from grimoire.cli.helpers import prompt_for_variable

        monkeypatch.setattr("click.prompt", lambda *a, **kw: 3.14)
        spec = VariableSpec(type=VariableType.FLOAT, required=True)
        assert prompt_for_variable("rate", spec) == 3.14

    def test_boolean_prompt(self, monkeypatch):
        from grimoire.cli.helpers import prompt_for_variable

        monkeypatch.setattr("click.confirm", lambda *a, **kw: True)
        spec = VariableSpec(type=VariableType.BOOLEAN, required=True)
        assert prompt_for_variable("flag", spec) is True

    def test_multiline_prompt(self, monkeypatch):
        from grimoire.cli.helpers import prompt_for_variable

        lines = iter(["line 1", "line 2", ""])
        monkeypatch.setattr("click.prompt", lambda *a, **kw: next(lines))
        monkeypatch.setattr("click.echo", lambda *a, **kw: None)
        spec = VariableSpec(type=VariableType.MULTILINE, required=True)
        result = prompt_for_variable("text", spec)
        assert result == "line 1\nline 2"

    def test_choice_prompt(self, monkeypatch):
        from grimoire.cli.helpers import prompt_for_variable

        monkeypatch.setattr("click.prompt", lambda *a, **kw: 2)
        monkeypatch.setattr("click.echo", lambda *a, **kw: None)
        spec = VariableSpec(
            type=VariableType.CHOICE, required=True, choices=["red", "green", "blue"]
        )
        assert prompt_for_variable("color", spec) == "green"

    def test_list_prompt(self, monkeypatch):
        from grimoire.cli.helpers import prompt_for_variable

        monkeypatch.setattr("click.prompt", lambda *a, **kw: "a, b, c")
        monkeypatch.setattr("click.echo", lambda *a, **kw: None)
        spec = VariableSpec(type=VariableType.LIST, required=True)
        result = prompt_for_variable("items", spec)
        assert result == ["a", "b", "c"]


class TestLoadVarsFromFiles:
    """Test YAML vars loading."""

    def test_load_single_file(self, tmp_path: Path):
        from grimoire.cli.helpers import load_vars_from_files

        f = tmp_path / "vars.yaml"
        f.write_text("name: Alice\ncount: 5\n")
        result = load_vars_from_files([str(f)])
        assert result == {"name": "Alice", "count": 5}

    def test_load_multiple_files_merge(self, tmp_path: Path):
        from grimoire.cli.helpers import load_vars_from_files

        f1 = tmp_path / "a.yaml"
        f1.write_text("name: Alice\n")
        f2 = tmp_path / "b.yaml"
        f2.write_text("name: Bob\nextra: 1\n")
        result = load_vars_from_files([str(f1), str(f2)])
        assert result["name"] == "Bob"  # Last wins
        assert result["extra"] == 1

    def test_load_invalid_file_warns(self, tmp_path: Path):
        from grimoire.cli.helpers import load_vars_from_files

        f = tmp_path / "bad.yaml"
        f.write_text(":\n  invalid yaml {{{")
        result = load_vars_from_files([str(f)])
        assert result == {}
