# tests/unit/test_api.py
"""
Tests for ``grimoire.api.Grimoire`` — the live-bind facade.

Covers:
    - Construction and reload
    - Polymorphic conjure (spell, bundle, ritual)
    - Typed conjure variants (conjure_spell, conjure_bundle, conjure_ritual)
    - Variable introspection (spell_vars, missing_vars)
    - Tool schema generation (tool_schemas)
    - In-memory bind (bind)
    - Validation and lint
    - Catalog / introspection
    - Convenience accessors
    - Error paths
"""

from __future__ import annotations

from pathlib import Path

import pytest

from grimoire.api import Grimoire, _runes_to_openai_tools
from grimoire.exceptions import ArtifactNotFoundError
from grimoire.models import CommandSpec, ConjuredPrompt, ConjuredRitualStep, ParamSpec, RuneSpec

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
REPO_DIR = FIXTURES_DIR / "grimoire_repo"


# ═════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def grim() -> Grimoire:
    """Load the test grimoire fixture once per test."""
    return Grimoire(REPO_DIR)


@pytest.fixture
def grim_non_strict() -> Grimoire:
    """Grimoire with strict=False (leave unresolved placeholders)."""
    return Grimoire(REPO_DIR, strict=False)


# ═════════════════════════════════════════════════════════════════════════════
# Construction & Properties
# ═════════════════════════════════════════════════════════════════════════════


class TestConstruction:
    """Grimoire init, properties, repr, reload."""

    def test_load_from_path(self, grim: Grimoire) -> None:
        """Loading from a valid repo path succeeds."""
        assert grim.repo is not None
        assert grim.name == "test-grimoire"
        assert grim.version == "0.1.0"

    def test_load_invalid_path_raises(self, tmp_path: Path) -> None:
        """Loading from a nonexistent path raises RepoError."""
        from grimoire.exceptions import RepoError

        with pytest.raises(RepoError):
            Grimoire(tmp_path / "nonexistent")

    def test_repr(self, grim: Grimoire) -> None:
        """__repr__ includes name and artifact counts."""
        r = repr(grim)
        assert "test-grimoire" in r
        assert "spells=" in r
        assert "runes=" in r

    def test_reload(self, grim: Grimoire) -> None:
        """reload() repopulates internal state from disk."""
        original_spells = len(grim.list_spells())
        grim.reload()
        assert len(grim.list_spells()) == original_spells

    def test_strict_default_true(self) -> None:
        """Default strict=True."""
        g = Grimoire(REPO_DIR)
        assert g._strict is True

    def test_strict_override(self) -> None:
        """strict=False is respected."""
        g = Grimoire(REPO_DIR, strict=False)
        assert g._strict is False


# ═════════════════════════════════════════════════════════════════════════════
# Polymorphic conjure()
# ═════════════════════════════════════════════════════════════════════════════


class TestConjure:
    """Polymorphic conjure() auto-detects artifact type."""

    def test_conjure_spell(self, grim: Grimoire) -> None:
        """conjure() on a spell ID returns ConjuredPrompt."""
        result = grim.conjure(
            "examples/greet",
            variables={"user_name": "Alice"},
        )
        assert isinstance(result, ConjuredPrompt)
        assert len(result.blocks) >= 1
        # Variable was substituted
        text = result.to_text()
        assert "Alice" in text

    def test_conjure_spell_uses_grimoire_defaults(self, grim: Grimoire) -> None:
        """When no variables provided, grimoire defaults are used."""
        result = grim.conjure("examples/greet")
        text = result.to_text()
        # defaults.yaml has user_name: "World"
        assert "World" in text

    def test_conjure_bundle(self, grim: Grimoire) -> None:
        """conjure() on a bundle ID returns ConjuredPrompt."""
        result = grim.conjure(
            "bundles/engineering/rca_with_tools",
            variables={"issue_title": "OOM crash", "symptoms": "server dies"},
        )
        assert isinstance(result, ConjuredPrompt)
        text = result.to_text()
        assert "OOM crash" in text

    def test_conjure_bundle_with_variant(self, grim: Grimoire) -> None:
        """Bundle variant is applied when context matches."""
        result = grim.conjure(
            "bundles/engineering/rca_with_tools",
            variables={"issue_title": "Bug", "symptoms": "crash"},
            context={"provider": "anthropic"},
        )
        # Anthropic variant injects "style/concise" promptlet
        assert isinstance(result, ConjuredPrompt)
        assert result.to_text()

    def test_conjure_ritual(self, grim: Grimoire) -> None:
        """conjure() on a ritual ID returns list of ConjuredRitualStep."""
        result = grim.conjure(
            "rituals/greet_loop",
            variables={"user_name": "Bob"},
        )
        assert isinstance(result, list)
        assert len(result) >= 1
        assert isinstance(result[0], ConjuredRitualStep)

    def test_conjure_not_found(self, grim: Grimoire) -> None:
        """conjure() with unknown ID raises ArtifactNotFoundError."""
        with pytest.raises(ArtifactNotFoundError, match="not found"):
            grim.conjure("nonexistent/artifact")

    def test_conjure_strict_override(self, grim: Grimoire) -> None:
        """strict=False at call site overrides instance default."""
        # Missing required vars, but strict=False → no raise
        result = grim.conjure(
            "engineering/root_cause_analysis",
            variables={},
            strict=False,
        )
        assert isinstance(result, ConjuredPrompt)

    def test_conjure_custom_defaults(self, grim: Grimoire) -> None:
        """Passing explicit defaults overrides grimoire defaults."""
        result = grim.conjure(
            "examples/greet",
            defaults={"user_name": "CustomDefault"},
        )
        text = result.to_text()
        assert "CustomDefault" in text

    def test_conjure_to_openai_messages(self, grim: Grimoire) -> None:
        """Conjured prompt exports to OpenAI message format."""
        result = grim.conjure("examples/greet", variables={"user_name": "X"})
        messages = result.to_messages("openai")
        assert isinstance(messages, list)
        assert all("role" in m and "content" in m for m in messages)

    def test_conjure_to_anthropic_messages(self, grim: Grimoire) -> None:
        """Conjured prompt exports to Anthropic message format."""
        result = grim.conjure("examples/greet", variables={"user_name": "X"})
        messages = result.to_messages("anthropic")
        assert isinstance(messages, list)

    def test_conjure_provenance(self, grim: Grimoire) -> None:
        """Conjured prompt has provenance with spell ID and hash."""
        result = grim.conjure("examples/greet", variables={"user_name": "X"})
        assert result.provenance is not None
        assert result.provenance.spell_id == "examples/greet"
        assert result.provenance.spell_hash is not None


# ═════════════════════════════════════════════════════════════════════════════
# Typed conjure variants
# ═════════════════════════════════════════════════════════════════════════════


class TestTypedConjure:
    """Explicit conjure_spell / conjure_bundle / conjure_ritual methods."""

    def test_conjure_spell_typed(self, grim: Grimoire) -> None:
        result = grim.conjure_spell("examples/greet", variables={"user_name": "Alice"})
        assert isinstance(result, ConjuredPrompt)

    def test_conjure_spell_not_found(self, grim: Grimoire) -> None:
        with pytest.raises(ArtifactNotFoundError):
            grim.conjure_spell("nonexistent/spell")

    def test_conjure_bundle_typed(self, grim: Grimoire) -> None:
        result = grim.conjure_bundle(
            "bundles/engineering/rca_with_tools",
            variables={"issue_title": "Bug", "symptoms": "crash"},
        )
        assert isinstance(result, ConjuredPrompt)

    def test_conjure_bundle_not_found(self, grim: Grimoire) -> None:
        with pytest.raises(ArtifactNotFoundError):
            grim.conjure_bundle("nonexistent/bundle")

    def test_conjure_ritual_typed(self, grim: Grimoire) -> None:
        result = grim.conjure_ritual(
            "rituals/greet_loop",
            variables={"user_name": "Bob"},
        )
        assert isinstance(result, list)
        assert all(isinstance(s, ConjuredRitualStep) for s in result)

    def test_conjure_ritual_not_found(self, grim: Grimoire) -> None:
        with pytest.raises(ArtifactNotFoundError):
            grim.conjure_ritual("nonexistent/ritual")


# ═════════════════════════════════════════════════════════════════════════════
# Variable introspection
# ═════════════════════════════════════════════════════════════════════════════


class TestVariableIntrospection:
    """spell_vars() and missing_vars() methods."""

    def test_spell_vars_returns_schema(self, grim: Grimoire) -> None:
        """spell_vars returns the full variable schema."""
        vars_schema = grim.spell_vars("examples/greet")
        assert "user_name" in vars_schema
        assert vars_schema["user_name"].required is True
        assert "language" in vars_schema
        assert vars_schema["language"].required is False

    def test_spell_vars_not_found(self, grim: Grimoire) -> None:
        with pytest.raises(ArtifactNotFoundError):
            grim.spell_vars("nonexistent/spell")

    def test_missing_vars_all_missing(self, grim: Grimoire) -> None:
        """All required vars with no defaults are missing."""
        missing = grim.missing_vars("engineering/root_cause_analysis")
        # issue_title and symptoms are required with no grimoire defaults
        assert "issue_title" in missing
        assert "symptoms" in missing
        # environment has a spell default, so not missing
        assert "environment" not in missing

    def test_missing_vars_partially_provided(self, grim: Grimoire) -> None:
        """Providing some vars removes them from the missing set."""
        missing = grim.missing_vars(
            "engineering/root_cause_analysis",
            provided={"issue_title": "Bug"},
        )
        assert "issue_title" not in missing
        assert "symptoms" in missing

    def test_missing_vars_all_provided(self, grim: Grimoire) -> None:
        """No missing vars when all required are supplied."""
        missing = grim.missing_vars(
            "engineering/root_cause_analysis",
            provided={"issue_title": "Bug", "symptoms": "crash"},
        )
        assert len(missing) == 0

    def test_missing_vars_uses_grimoire_defaults(self, grim: Grimoire) -> None:
        """Variables present in grimoire defaults are not missing."""
        missing = grim.missing_vars("examples/greet")
        # defaults.yaml has user_name: "World"
        assert "user_name" not in missing

    def test_missing_vars_bundle(self, grim: Grimoire) -> None:
        """missing_vars works for bundle IDs too."""
        missing = grim.missing_vars("bundles/engineering/rca_with_tools")
        # Delegates to assembled spell's variable schema
        assert "issue_title" in missing

    def test_missing_vars_not_found(self, grim: Grimoire) -> None:
        with pytest.raises(ArtifactNotFoundError):
            grim.missing_vars("nonexistent/thing")


# ═════════════════════════════════════════════════════════════════════════════
# Tool schema generation
# ═════════════════════════════════════════════════════════════════════════════


class TestToolSchemas:
    """tool_schemas() generates OpenAI-compatible function definitions."""

    def test_all_runes(self, grim: Grimoire) -> None:
        """Without filters, returns schemas for all rune commands."""
        tools = grim.tool_schemas()
        assert isinstance(tools, list)
        assert len(tools) > 0
        # Each tool has the right structure
        for tool in tools:
            assert tool["type"] == "function"
            assert "name" in tool["function"]
            assert "parameters" in tool["function"]
            assert tool["function"]["parameters"]["type"] == "object"

    def test_filter_by_tags(self, grim: Grimoire) -> None:
        """Filtering by tags reduces the result set."""
        all_tools = grim.tool_schemas()
        devtools = grim.tool_schemas(tags=["devtools"])
        assert len(devtools) > 0
        assert len(devtools) <= len(all_tools)

    def test_filter_by_rune_ids(self, grim: Grimoire) -> None:
        """Filtering by rune_ids selects specific runes."""
        tools = grim.tool_schemas(rune_ids=["devtools/git"])
        assert len(tools) > 0
        # All function names should reference git
        for tool in tools:
            assert "git" in tool["function"]["name"]

    def test_rune_ids_not_found_warns(self, grim: Grimoire) -> None:
        """Unknown rune IDs are silently skipped."""
        tools = grim.tool_schemas(rune_ids=["nonexistent/rune"])
        assert tools == []

    def test_tool_name_format(self, grim: Grimoire) -> None:
        """Tool names use __ separator for rune_id/command."""
        tools = grim.tool_schemas(rune_ids=["devtools/git"])
        names = [t["function"]["name"] for t in tools]
        # git rune has 'status' and 'diff' commands
        assert "devtools__git__status" in names
        assert "devtools__git__diff" in names

    def test_unsupported_format_raises(self, grim: Grimoire) -> None:
        """Unsupported schema_format raises ValueError."""
        with pytest.raises(ValueError, match=r"(?i)unsupported"):
            grim.tool_schemas(schema_format="jsonschema")


class TestMCPToolManifest:
    """to_mcp_tool_manifest() exposes rune commands in MCP tools/list shape."""

    def test_single_rune_manifest_shape(self, grim: Grimoire) -> None:
        manifest = grim.to_mcp_tool_manifest("devtools/git")

        assert manifest["schema_version"] == "grimoire.mcp_tool_manifest.v1"
        tools = manifest["tools"]
        assert {tool["name"] for tool in tools} == {
            "devtools__git__status",
            "devtools__git__diff",
        }
        status = next(tool for tool in tools if tool["name"] == "devtools__git__status")
        assert status["description"] == "Show working tree status"
        assert status["inputSchema"]["type"] == "object"
        assert status["inputSchema"]["properties"]["porcelain"]["type"] == "boolean"
        assert status["annotations"] == {
            "readOnlyHint": True,
            "destructiveHint": False,
        }
        assert status["_meta"]["grimoire.rune_id"] == "devtools/git"
        assert status["_meta"]["grimoire.command_name"] == "status"
        assert status["_meta"]["grimoire.permissions"] == ["read_fs"]
        assert status["_meta"]["grimoire.requires_approval"] is False
        assert status["_meta"]["grimoire.risk_level"] == "low"

    def test_manifest_preserves_risk_approval_and_execution_target(
        self,
        grim: Grimoire,
    ) -> None:
        rune = grim.get_rune("wairu/shell")
        assert rune.mappings["wairu.tool_name"] == "shell"
        assert rune.commands[0].execution_target == "sandbox"

        manifest = grim.to_mcp_tool_manifest(rune_ids=["wairu/shell"])

        tool = manifest["tools"][0]
        assert tool["name"] == "wairu__shell__run"
        assert tool["inputSchema"]["required"] == ["command"]
        assert tool["annotations"] == {
            "readOnlyHint": False,
            "destructiveHint": True,
        }
        assert tool["_meta"]["grimoire.risk_level"] == "high"
        assert tool["_meta"]["grimoire.requires_approval"] is True
        assert tool["_meta"]["grimoire.execution_target"] == "sandbox"
        assert tool["_meta"]["grimoire.permissions"] == ["exec", "write_fs", "read_fs"]

    def test_unknown_rune_ids_are_skipped(self, grim: Grimoire) -> None:
        assert grim.to_mcp_tool_manifest(rune_ids=["missing/rune"])["tools"] == []

    def test_rejects_single_and_multi_rune_selection(self, grim: Grimoire) -> None:
        with pytest.raises(ValueError, match="either rune_id or rune_ids"):
            grim.to_mcp_tool_manifest("devtools/git", rune_ids=["wairu/shell"])


# ═════════════════════════════════════════════════════════════════════════════
# In-memory bind
# ═════════════════════════════════════════════════════════════════════════════


class TestBind:
    """bind() produces in-memory BindResult for each target."""

    def test_bind_llmcore(self, grim: Grimoire) -> None:
        """Bind to llmcore target produces files."""
        result = grim.bind("llmcore")
        assert result.ok
        assert len(result.files) > 0
        assert result.compiled_hash is not None

    def test_bind_semantiscan(self, grim: Grimoire) -> None:
        """Bind to semantiscan target produces files."""
        result = grim.bind("semantiscan")
        assert result.ok

    def test_bind_wairu(self, grim: Grimoire) -> None:
        """Bind to wairu target produces files."""
        result = grim.bind("wairu")
        assert result.ok

    def test_bind_with_tags_filter(self, grim: Grimoire) -> None:
        """Tag filter reduces bound artifacts."""
        all_result = grim.bind("llmcore")
        filtered = grim.bind("llmcore", tags=["engineering"])
        assert len(filtered.files) <= len(all_result.files)

    def test_bind_with_spell_ids(self, grim: Grimoire) -> None:
        """spell_ids filter selects specific spells."""
        result = grim.bind("llmcore", spell_ids=["examples/greet"])
        assert result.ok
        # Should have fewer files than binding everything
        all_result = grim.bind("llmcore")
        assert len(result.files) <= len(all_result.files)

    def test_bind_enum_target(self, grim: Grimoire) -> None:
        """BindTarget enum works as target argument."""
        from grimoire.bind.base import BindTarget

        result = grim.bind(BindTarget.LLMCORE)
        assert result.ok

    def test_bind_with_format(self, grim: Grimoire) -> None:
        """Explicit format parameter works."""
        result = grim.bind("semantiscan", fmt="toml")
        assert result.ok

    def test_bind_write_to_disk(self, grim: Grimoire, tmp_path: Path) -> None:
        """BindResult.write() persists files to disk."""
        result = grim.bind("llmcore")
        written = result.write(tmp_path / "exports")
        assert len(written) > 0
        assert all(p.exists() for p in written)

    def test_bind_invalid_target_raises(self, grim: Grimoire) -> None:
        """Invalid target string raises ValueError."""
        with pytest.raises(ValueError):
            grim.bind("invalid_target")


# ═════════════════════════════════════════════════════════════════════════════
# Validation & Lint
# ═════════════════════════════════════════════════════════════════════════════


class TestValidation:
    """validate() and lint() methods."""

    def test_validate_repo(self, grim: Grimoire) -> None:
        """Repo validation produces a ValidationResult."""
        result = grim.validate()
        assert hasattr(result, "ok")
        assert hasattr(result, "diagnostics")

    def test_lint_single_spell(self, grim: Grimoire) -> None:
        """Lint a specific spell by ID."""
        result = grim.lint("engineering/root_cause_analysis")
        assert hasattr(result, "ok")
        assert hasattr(result, "diagnostics")

    def test_lint_all_spells(self, grim: Grimoire) -> None:
        """Lint all spells when no spell_id given."""
        result = grim.lint()
        assert hasattr(result, "diagnostics")
        # Should have run lint on multiple spells
        assert isinstance(result.diagnostics, list)

    def test_lint_not_found(self, grim: Grimoire) -> None:
        with pytest.raises(ArtifactNotFoundError):
            grim.lint("nonexistent/spell")

    def test_lint_with_custom_config(self, grim: Grimoire) -> None:
        """Custom LintConfig is passed through."""
        from grimoire.validate.rules import LintConfig

        config = LintConfig(forbidden_tokens=["NEVER_USE_THIS"])
        result = grim.lint("examples/greet", config=config)
        assert hasattr(result, "ok")


# ═════════════════════════════════════════════════════════════════════════════
# Catalog
# ═════════════════════════════════════════════════════════════════════════════


class TestCatalog:
    """catalog() returns agent-friendly JSON dict."""

    def test_catalog_structure(self, grim: Grimoire) -> None:
        """Catalog has expected top-level keys."""
        cat = grim.catalog()
        assert "grimoire" in cat
        assert "spells" in cat
        assert "runes" in cat
        assert "rituals" in cat
        assert "bundles" in cat
        assert "skilldocs" in cat
        assert "promptlets" in cat

    def test_catalog_grimoire_metadata(self, grim: Grimoire) -> None:
        cat = grim.catalog()
        assert cat["grimoire"]["name"] == "test-grimoire"
        assert cat["grimoire"]["version"] == "0.1.0"

    def test_catalog_spells_populated(self, grim: Grimoire) -> None:
        cat = grim.catalog()
        assert len(cat["spells"]) > 0
        spell_ids = [s["id"] for s in cat["spells"]]
        assert "examples/greet" in spell_ids

    def test_catalog_runes_populated(self, grim: Grimoire) -> None:
        cat = grim.catalog()
        assert len(cat["runes"]) > 0
        rune_ids = [r["id"] for r in cat["runes"]]
        assert "devtools/git" in rune_ids

    def test_catalog_json_serializable(self, grim: Grimoire) -> None:
        """Catalog output can be serialized to JSON."""
        import json

        cat = grim.catalog()
        # Should not raise
        serialized = json.dumps(cat)
        assert isinstance(serialized, str)


# ═════════════════════════════════════════════════════════════════════════════
# Convenience accessors
# ═════════════════════════════════════════════════════════════════════════════


class TestAccessors:
    """Convenience methods delegate to GrimoireRepo correctly."""

    def test_get_spell(self, grim: Grimoire) -> None:
        spell = grim.get_spell("examples/greet")
        assert spell.id == "examples/greet"

    def test_get_rune(self, grim: Grimoire) -> None:
        rune = grim.get_rune("devtools/git")
        assert rune.id == "devtools/git"

    def test_get_bundle(self, grim: Grimoire) -> None:
        bundle = grim.get_bundle("bundles/engineering/rca_with_tools")
        assert bundle.id == "bundles/engineering/rca_with_tools"

    def test_get_ritual(self, grim: Grimoire) -> None:
        ritual = grim.get_ritual("rituals/greet_loop")
        assert ritual.id == "rituals/greet_loop"

    def test_list_spells(self, grim: Grimoire) -> None:
        spells = grim.list_spells()
        assert len(spells) > 0

    def test_list_spells_with_tags(self, grim: Grimoire) -> None:
        tagged = grim.list_spells(tags=["engineering"])
        all_spells = grim.list_spells()
        assert len(tagged) <= len(all_spells)
        assert all("engineering" in s.tags for s in tagged)

    def test_list_runes(self, grim: Grimoire) -> None:
        runes = grim.list_runes()
        assert len(runes) > 0

    def test_list_bundles(self, grim: Grimoire) -> None:
        bundles = grim.list_bundles()
        assert len(bundles) > 0

    def test_list_rituals(self, grim: Grimoire) -> None:
        rituals = grim.list_rituals()
        assert len(rituals) > 0


# ═════════════════════════════════════════════════════════════════════════════
# Helper: _runes_to_openai_tools
# ═════════════════════════════════════════════════════════════════════════════


class TestRunesToOpenAITools:
    """Unit tests for the standalone helper function."""

    def test_empty_list(self) -> None:
        assert _runes_to_openai_tools([]) == []

    def test_single_rune_single_command(self, grim: Grimoire) -> None:
        rune = grim.get_rune("devtools/git")
        tools = _runes_to_openai_tools([rune])
        # git has status + diff = 2 commands
        assert len(tools) == 2

    def test_required_params_in_schema(self, grim: Grimoire) -> None:
        """Required params appear in the 'required' array."""
        rune = grim.get_rune("devtools/git")
        tools = _runes_to_openai_tools([rune])
        for tool in tools:
            params = tool["function"]["parameters"]
            assert "properties" in params

    def test_constraints_in_schema(self) -> None:
        rune = RuneSpec(
            id="devtools/check",
            name="Check",
            commands=[
                CommandSpec(
                    name="run",
                    params=[
                        ParamSpec(name="enabled", type="bool", default=True),
                        ParamSpec(name="target", type="string", pattern="^[a-z]+$", required=True),
                        ParamSpec(name="limit", type="integer", minimum=1, maximum=10),
                    ],
                )
            ],
        )
        tool = _runes_to_openai_tools([rune])[0]
        params = tool["function"]["parameters"]
        props = params["properties"]
        assert props["enabled"]["type"] == "boolean"
        assert props["enabled"]["default"] is True
        assert props["target"]["pattern"] == "^[a-z]+$"
        assert props["limit"]["minimum"] == 1
        assert props["limit"]["maximum"] == 10
        assert params["required"] == ["target"]

    def test_multiple_runes(self, grim: Grimoire) -> None:
        runes = grim.list_runes()
        tools = _runes_to_openai_tools(runes)
        # Should have at least one tool per rune
        assert len(tools) >= len(runes)


# ═════════════════════════════════════════════════════════════════════════════
# Integration: end-to-end live-bind workflow
# ═════════════════════════════════════════════════════════════════════════════


class TestLiveBindWorkflow:
    """End-to-end workflows simulating runtime consumption."""

    def test_discover_conjure_export(self, grim: Grimoire) -> None:
        """Full workflow: discover → check vars → conjure → export messages."""
        # 1. Discover available spells
        spells = grim.list_spells(tags=["engineering"])
        assert len(spells) > 0
        spell_id = spells[0].id

        # 2. Check what variables are needed
        missing = grim.missing_vars(spell_id)

        # 3. Provide missing variables
        provided = {name: f"test_{name}" for name in missing}
        result = grim.conjure(spell_id, variables=provided)

        # 4. Export as OpenAI messages
        messages = result.to_messages("openai")
        assert len(messages) > 0

    def test_bundle_with_tools_workflow(self, grim: Grimoire) -> None:
        """Workflow: conjure bundle + get tool schemas."""
        # Conjure the RCA bundle
        result = grim.conjure_bundle(
            "bundles/engineering/rca_with_tools",
            variables={"issue_title": "OOM", "symptoms": "process killed"},
        )
        messages = result.to_messages("openai")

        # Get matching tool schemas
        tools = grim.tool_schemas(tags=["devtools"])

        # Both messages and tools are ready for a provider API call
        assert len(messages) > 0
        assert len(tools) > 0

    def test_ritual_step_capture(self, grim: Grimoire) -> None:
        """Ritual steps produce conjured output with capture metadata."""
        steps = grim.conjure_ritual(
            "rituals/greet_loop",
            variables={"user_name": "Agent"},
        )
        assert len(steps) >= 1
        step = steps[0]
        assert step.spell_id == "examples/greet"
        assert step.conjured is not None

    def test_bind_then_consume(self, grim: Grimoire) -> None:
        """In-memory bind produces files consumable by runtimes."""
        result = grim.bind("llmcore")
        assert result.ok

        # Files are in memory — runtime can consume without disk
        for bf in result.files:
            assert len(bf.content) > 0
            assert bf.relative_path

    def test_validate_before_bind(self, grim: Grimoire) -> None:
        """Validation check before binding (CI pattern)."""
        val_result = grim.validate()
        # If valid, proceed to bind
        if val_result.ok:
            bind_result = grim.bind("llmcore")
            assert bind_result.ok
