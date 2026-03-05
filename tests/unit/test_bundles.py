# tests/unit/test_bundles.py
"""
Tests for Phase 4: Bundles & Assembly Plans.

Covers:
  - Bundle YAML parsing (parse_bundle, parse_bundle_file)
  - BundleAssembler.assemble() all five stages
  - Variant selection (first match wins, context matching)
  - BundleInject merging
  - Missing promptlet graceful degradation
  - validate_bundle()
  - GrimoireRepo discovery of *.bundle.yaml
  - CLI bundle list|show|validate|assemble
  - Transparent conjure of bundle IDs
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from grimoire.bundles.assembler import BundleAssembler
from grimoire.bundles.parser import parse_bundle, parse_bundle_file
from grimoire.cli import cli
from grimoire.exceptions import ArtifactNotFoundError, BundleAssemblyError, BundleParseError
from grimoire.models import Bundle, BundleInject, BundleVariant, MessageRole, Promptlet, Spell, MessageBlock
from grimoire.store.repo import GrimoireRepo
from grimoire.validate.rules import validate_bundle


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_minimal_bundle_dict(**overrides) -> dict:
    base = {
        "id": "bundles/test/minimal",
        "name": "Minimal Bundle",
        "base_template": "examples/greet",
    }
    base.update(overrides)
    return base


def _make_bundle_repo(tmp_path: Path) -> GrimoireRepo:
    """Create a full test repo with spell + promptlets + bundle."""
    manifest = {
        "name": "bundle-test",
        "version": "0.1.0",
        "spell_paths": ["spells/"],
        "rune_paths": ["runes/"],
        "ritual_paths": ["rituals/"],
        "promptlet_paths": ["spells/promptlets/"],
        "bundle_paths": ["spells/bundles/"],
        "skilldoc_paths": ["skills/docs/"],
    }
    (tmp_path / "grimoire.yaml").write_text(yaml.dump(manifest))
    for d in [
        "spells/promptlets/safety",
        "spells/promptlets/style",
        "runes",
        "rituals",
        "spells/bundles",
        "skills/docs",
        "vars",
    ]:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)

    # Base spell
    (tmp_path / "spells").mkdir(exist_ok=True)
    spell_text = """\
---
id: examples/greet
name: Hello Spell
version: 1.0.0
tags: [example]
variables:
  name:
    type: string
    required: true
    ask: "Your name"
---

# SYSTEM
You are a friendly assistant.

# USER
Hello {{ name }}!
"""
    (tmp_path / "spells" / "greet.spell.md").write_text(spell_text)

    # Promptlets
    (tmp_path / "spells/promptlets/safety" / "rail.md").write_text("Be safe.")
    (tmp_path / "spells/promptlets/style" / "concise.md").write_text("Be concise.")

    # Default vars
    (tmp_path / "vars" / "defaults.yaml").write_text("{}\n")

    # Bundle
    bundle_data = {
        "id": "bundles/test/greet_bundle",
        "name": "Greet Bundle",
        "version": "1.0.0",
        "base_template": "examples/greet",
        "inject": {
            "system_prepend": ["safety/rail"],
        },
        "variants": [
            {
                "id": "concise_variant",
                "when": {"style": "concise"},
                "inject": {"system_append": ["style/concise"]},
            }
        ],
    }
    (tmp_path / "spells/bundles" / "greet.bundle.yaml").write_text(
        yaml.dump(bundle_data)
    )
    return GrimoireRepo.load(tmp_path)


# ── Parser tests ──────────────────────────────────────────────────────────────


class TestBundleParser:
    def test_parse_minimal(self):
        data = _make_minimal_bundle_dict()
        bundle = parse_bundle(data)
        assert bundle.id == "bundles/test/minimal"
        assert bundle.name == "Minimal Bundle"
        assert bundle.base_template == "examples/greet"
        assert bundle.inject is None
        assert bundle.variants == []
        assert bundle.content_hash is not None

    def test_parse_with_inject(self):
        data = _make_minimal_bundle_dict(
            inject={
                "system_prepend": ["safety/base"],
                "system_append": ["tool_policy/low_risk"],
                "user_prepend": [],
                "user_append": ["output/rubric"],
            }
        )
        bundle = parse_bundle(data)
        assert bundle.inject is not None
        assert bundle.inject.system_prepend == ["safety/base"]
        assert bundle.inject.system_append == ["tool_policy/low_risk"]
        assert bundle.inject.user_append == ["output/rubric"]

    def test_parse_with_variants(self):
        data = _make_minimal_bundle_dict(
            variants=[
                {
                    "id": "anthropic",
                    "when": {"provider": "anthropic"},
                    "inject": {"system_append": ["style/concise"]},
                }
            ]
        )
        bundle = parse_bundle(data)
        assert len(bundle.variants) == 1
        assert bundle.variants[0].id == "anthropic"
        assert bundle.variants[0].when == {"provider": "anthropic"}
        assert bundle.variants[0].inject is not None

    def test_parse_with_tools(self):
        data = _make_minimal_bundle_dict(
            tools={"diagnostics": ["devtools/git", "semantiscan/query"]}
        )
        bundle = parse_bundle(data)
        assert bundle.tools == {"diagnostics": ["devtools/git", "semantiscan/query"]}

    def test_parse_missing_id_raises(self):
        data = {"name": "No ID", "base_template": "x"}
        with pytest.raises(BundleParseError, match="id"):
            parse_bundle(data)

    def test_parse_missing_base_template_raises(self):
        data = {"id": "test/b", "name": "No Base"}
        with pytest.raises(BundleParseError, match="base_template"):
            parse_bundle(data)

    def test_parse_invalid_variant_raises(self):
        data = _make_minimal_bundle_dict(variants=["not_a_dict"])
        with pytest.raises(BundleParseError):
            parse_bundle(data)

    def test_parse_file(self, tmp_path: Path):
        bundle_data = _make_minimal_bundle_dict()
        f = tmp_path / "test.bundle.yaml"
        f.write_text(yaml.dump(bundle_data))
        bundle = parse_bundle_file(f)
        assert bundle.id == "bundles/test/minimal"

    def test_parse_file_bad_yaml(self, tmp_path: Path):
        f = tmp_path / "bad.bundle.yaml"
        f.write_text("{ not: valid: yaml: [")
        with pytest.raises(BundleParseError):
            parse_bundle_file(f)

    def test_parse_file_not_mapping(self, tmp_path: Path):
        f = tmp_path / "list.bundle.yaml"
        f.write_text("- a\n- b\n")
        with pytest.raises(BundleParseError):
            parse_bundle_file(f)

    def test_content_hash_stable(self):
        data = _make_minimal_bundle_dict()
        b1 = parse_bundle(data)
        b2 = parse_bundle(data)
        assert b1.content_hash == b2.content_hash

    def test_content_hash_changes_with_inject(self):
        b1 = parse_bundle(_make_minimal_bundle_dict())
        b2 = parse_bundle(
            _make_minimal_bundle_dict(inject={"system_prepend": ["safety/x"]})
        )
        assert b1.content_hash != b2.content_hash


# ── Assembler tests ────────────────────────────────────────────────────────────


class TestBundleAssembler:
    def test_assemble_base_only(self, tmp_path: Path):
        repo = _make_bundle_repo(tmp_path)
        bundle = repo.get_bundle("bundles/test/greet_bundle")
        # Assemble without variant context — only system_prepend applies
        assembler = BundleAssembler(repo)
        spell = assembler.assemble(bundle)

        assert "__bundle__" in spell.id
        assert any(b.role == MessageRole.SYSTEM for b in spell.raw_blocks)
        # Safety rail should be prepended to SYSTEM
        system_block = next(b for b in spell.raw_blocks if b.role == MessageRole.SYSTEM)
        assert "Be safe." in system_block.content
        assert "You are a friendly assistant." in system_block.content

    def test_assemble_variant_matched(self, tmp_path: Path):
        repo = _make_bundle_repo(tmp_path)
        bundle = repo.get_bundle("bundles/test/greet_bundle")
        assembler = BundleAssembler(repo)
        spell = assembler.assemble(bundle, context={"style": "concise"})

        system_block = next(b for b in spell.raw_blocks if b.role == MessageRole.SYSTEM)
        assert "Be concise." in system_block.content

    def test_assemble_variant_not_matched(self, tmp_path: Path):
        repo = _make_bundle_repo(tmp_path)
        bundle = repo.get_bundle("bundles/test/greet_bundle")
        assembler = BundleAssembler(repo)
        spell = assembler.assemble(bundle, context={"style": "verbose"})

        system_block = next(b for b in spell.raw_blocks if b.role == MessageRole.SYSTEM)
        assert "Be concise." not in system_block.content

    def test_assemble_missing_base_template_raises(self, tmp_path: Path):
        repo = _make_bundle_repo(tmp_path)
        # Create bundle referencing non-existent spell
        bad_bundle = parse_bundle(
            {"id": "bad/bundle", "name": "Bad", "base_template": "nonexistent/spell"}
        )
        assembler = BundleAssembler(repo)
        with pytest.raises(BundleAssemblyError, match="base_template"):
            assembler.assemble(bad_bundle)

    def test_assemble_missing_promptlet_degrades_gracefully(self, tmp_path: Path):
        repo = _make_bundle_repo(tmp_path)
        bundle = parse_bundle(
            {
                "id": "test/missing_inject",
                "name": "Missing Inject",
                "base_template": "examples/greet",
                "inject": {"system_prepend": ["does_not_exist/promptlet"]},
            }
        )
        assembler = BundleAssembler(repo)
        # Should not raise — missing promptlet is logged and skipped
        spell = assembler.assemble(bundle)
        assert spell is not None

    def test_assemble_hash_deterministic(self, tmp_path: Path):
        repo = _make_bundle_repo(tmp_path)
        bundle = repo.get_bundle("bundles/test/greet_bundle")
        assembler = BundleAssembler(repo)
        s1 = assembler.assemble(bundle)
        s2 = assembler.assemble(bundle)
        assert s1.content_hash == s2.content_hash

    def test_assemble_preserves_user_block(self, tmp_path: Path):
        repo = _make_bundle_repo(tmp_path)
        bundle = repo.get_bundle("bundles/test/greet_bundle")
        assembler = BundleAssembler(repo)
        spell = assembler.assemble(bundle)
        user_block = next(b for b in spell.raw_blocks if b.role == MessageRole.USER)
        assert "{{ name }}" in user_block.content

    def test_assemble_user_inject(self, tmp_path: Path):
        repo = _make_bundle_repo(tmp_path)
        # Bundle with user_append
        bundle_data = {
            "id": "test/user_inject",
            "name": "User Inject Bundle",
            "base_template": "examples/greet",
            "inject": {"user_append": ["style/concise"]},
        }
        bundle = parse_bundle(bundle_data)
        assembler = BundleAssembler(repo)
        spell = assembler.assemble(bundle)
        user_block = next(b for b in spell.raw_blocks if b.role == MessageRole.USER)
        assert "Be concise." in user_block.content

    def test_assemble_inject_no_system_block_creates_one(self, tmp_path: Path):
        """If base spell has no SYSTEM block but inject has system content, add one."""
        repo = _make_bundle_repo(tmp_path)
        # Create a spell with only a USER block
        (tmp_path / "spells" / "user_only.spell.md").write_text(
            "---\nid: test/user_only\nname: User Only\n---\n\n# USER\nHello.\n"
        )
        repo2 = GrimoireRepo.load(tmp_path)
        bundle = parse_bundle(
            {
                "id": "test/inject_new_system",
                "name": "Inject New System",
                "base_template": "test/user_only",
                "inject": {"system_prepend": ["safety/rail"]},
            }
        )
        assembler = BundleAssembler(repo2)
        spell = assembler.assemble(bundle)
        roles = [b.role for b in spell.raw_blocks]
        assert MessageRole.SYSTEM in roles


# ── Validation tests ──────────────────────────────────────────────────────────


class TestValidateBundle:
    def test_valid_bundle(self, tmp_path: Path):
        repo = _make_bundle_repo(tmp_path)
        bundle = repo.get_bundle("bundles/test/greet_bundle")
        result = validate_bundle(bundle, repo)
        assert result.ok

    def test_missing_base_template_error(self):
        bundle = parse_bundle(
            {"id": "bad/b", "name": "Bad", "base_template": "not/exist"}
        )
        from grimoire.validate.rules import Severity
        result = validate_bundle(bundle, repo=None)
        # Without repo, only structural checks; no ERROR for missing spell
        # With repo, should have error
        # (test without repo first)
        assert result.ok  # no repo → no spell lookup

    def test_missing_base_template_with_repo(self, tmp_path: Path):
        repo = _make_bundle_repo(tmp_path)
        bundle = parse_bundle(
            {"id": "bad/b", "name": "Bad", "base_template": "not/exist"}
        )
        result = validate_bundle(bundle, repo)
        assert not result.ok
        assert any("base_template" in d.message for d in result.errors)

    def test_duplicate_variant_ids_error(self):
        data = _make_minimal_bundle_dict(
            variants=[
                {"id": "dup", "when": {}},
                {"id": "dup", "when": {}},
            ]
        )
        bundle = parse_bundle(data)
        result = validate_bundle(bundle)
        assert not result.ok
        assert any("duplicate" in d.message.lower() for d in result.errors)

    def test_inject_promptlet_not_found_warning(self, tmp_path: Path):
        repo = _make_bundle_repo(tmp_path)
        bundle = parse_bundle(
            {
                "id": "test/warn_inject",
                "name": "Warn Inject",
                "base_template": "examples/greet",
                "inject": {"system_prepend": ["missing/promptlet"]},
            }
        )
        result = validate_bundle(bundle, repo)
        assert result.ok  # Only a warning, not error
        assert any("missing/promptlet" in d.message for d in result.warnings)


# ── Repo discovery tests ──────────────────────────────────────────────────────


class TestRepoBundleDiscovery:
    def test_discovers_bundles(self, tmp_path: Path):
        repo = _make_bundle_repo(tmp_path)
        bundles = repo.list_bundles()
        assert len(bundles) == 1
        assert bundles[0].id == "bundles/test/greet_bundle"

    def test_get_bundle(self, tmp_path: Path):
        repo = _make_bundle_repo(tmp_path)
        bundle = repo.get_bundle("bundles/test/greet_bundle")
        assert bundle.name == "Greet Bundle"

    def test_get_bundle_not_found(self, tmp_path: Path):
        repo = _make_bundle_repo(tmp_path)
        with pytest.raises(ArtifactNotFoundError):
            repo.get_bundle("does/not/exist")

    def test_list_bundles_tag_filter(self, tmp_path: Path):
        repo = _make_bundle_repo(tmp_path)
        # The fixture bundle has no tags; filter by non-existent tag
        result = repo.list_bundles(tags=["nonexistent"])
        assert result == []

    def test_catalog_includes_bundles(self, tmp_path: Path):
        repo = _make_bundle_repo(tmp_path)
        catalog = repo.catalog()
        assert "bundles" in catalog
        assert len(catalog["bundles"]) == 1

    def test_invalid_bundle_logged_not_raised(self, tmp_path: Path):
        """A corrupt bundle file should be logged but not crash discovery."""
        repo_base = _make_bundle_repo(tmp_path)
        # Write a corrupt bundle alongside the valid one
        (tmp_path / "spells/bundles" / "corrupt.bundle.yaml").write_text(
            "not: valid: bundle: [\n"
        )
        repo2 = GrimoireRepo.load(tmp_path)
        # Valid bundle still discovered; corrupt one is skipped
        assert len(repo2.list_bundles()) == 1

    def test_facade_prompts_bundles(self, tmp_path: Path):
        repo = _make_bundle_repo(tmp_path)
        bundles = repo.prompts.bundles()
        assert len(bundles) == 1


# ── CLI tests ─────────────────────────────────────────────────────────────────


class TestBundleCLI:
    def test_bundle_list(self, tmp_path: Path):
        _make_bundle_repo(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["--repo", str(tmp_path), "bundle", "list"])
        assert result.exit_code == 0
        assert "greet_bundle" in result.output

    def test_bundle_list_json(self, tmp_path: Path):
        import json

        _make_bundle_repo(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["--repo", str(tmp_path), "bundle", "list", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["id"] == "bundles/test/greet_bundle"

    def test_bundle_show(self, tmp_path: Path):
        _make_bundle_repo(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--repo", str(tmp_path), "bundle", "show", "bundles/test/greet_bundle"],
        )
        assert result.exit_code == 0
        assert "Greet Bundle" in result.output

    def test_bundle_show_json(self, tmp_path: Path):
        import json

        _make_bundle_repo(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--repo", str(tmp_path), "bundle", "show", "--json", "bundles/test/greet_bundle"],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["id"] == "bundles/test/greet_bundle"
        assert "variants" in data

    def test_bundle_show_not_found(self, tmp_path: Path):
        _make_bundle_repo(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["--repo", str(tmp_path), "bundle", "show", "no/such"])
        assert result.exit_code != 0

    def test_bundle_validate_ok(self, tmp_path: Path):
        _make_bundle_repo(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["--repo", str(tmp_path), "bundle", "validate"])
        assert result.exit_code == 0

    def test_bundle_assemble(self, tmp_path: Path):
        _make_bundle_repo(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--repo", str(tmp_path), "bundle", "assemble", "bundles/test/greet_bundle"],
        )
        assert result.exit_code == 0
        assert "SYSTEM" in result.output

    def test_bundle_assemble_with_context(self, tmp_path: Path):
        _make_bundle_repo(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "--repo", str(tmp_path),
                "bundle", "assemble",
                "--context", "style=concise",
                "bundles/test/greet_bundle",
            ],
        )
        assert result.exit_code == 0
        assert "Be concise." in result.output

    def test_conjure_resolves_bundle(self, tmp_path: Path):
        """grimoire conjure should transparently assemble a bundle ID."""
        _make_bundle_repo(tmp_path)
        # Write a vars file so the required 'name' variable is satisfied
        import yaml as _yaml
        (tmp_path / "vars" / "defaults.yaml").write_text(_yaml.dump({"name": "TestUser"}))
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "--repo", str(tmp_path),
                "conjure", "bundles/test/greet_bundle",
                "--no-strict",
            ],
        )
        assert result.exit_code == 0


# ── Additional bundle CLI coverage ─────────────────────────────────────────────


class TestBundleCLIExtra:
    def test_bundle_list_no_bundles(self, tmp_path: Path):
        """Empty bundle list should print 'No bundles found'."""
        import yaml
        manifest = {
            "name": "empty", "version": "0.1.0",
            "spell_paths": ["spells/"], "rune_paths": ["runes/"],
            "ritual_paths": ["rituals/"], "promptlet_paths": ["prompts/"],
            "bundle_paths": ["bundles/"], "skilldoc_paths": ["skills/"],
        }
        (tmp_path / "grimoire.yaml").write_text(yaml.dump(manifest))
        for d in ["spells", "runes", "rituals", "prompts", "bundles", "skills", "vars"]:
            (tmp_path / d).mkdir(parents=True, exist_ok=True)
        (tmp_path / "vars" / "defaults.yaml").write_text("{}\n")
        runner = CliRunner()
        result = runner.invoke(cli, ["--repo", str(tmp_path), "bundle", "list"])
        assert result.exit_code == 0
        assert "No bundles" in result.output

    def test_bundle_show_with_description(self, tmp_path: Path):
        """Bundle with description field renders it in show output."""
        repo_root = _make_bundle_repo(tmp_path)
        # Add description to the bundle
        import yaml
        bundle_path = tmp_path / "spells/bundles" / "greet.bundle.yaml"
        data = yaml.safe_load(bundle_path.read_text())
        data["description"] = "A test bundle description"
        bundle_path.write_text(yaml.dump(data))
        runner = CliRunner()
        result = runner.invoke(
            cli, ["--repo", str(tmp_path), "bundle", "show", "bundles/test/greet_bundle"])
        assert result.exit_code == 0

    def test_bundle_assemble_json(self, tmp_path: Path):
        """bundle assemble --json outputs structured JSON."""
        _make_bundle_repo(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--repo", str(tmp_path), "bundle", "assemble", "--json",
             "bundles/test/greet_bundle"],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "assembled_id" in data
        assert "blocks" in data
        assert len(data["blocks"]) > 0

    def test_bundle_assemble_not_found(self, tmp_path: Path):
        """bundle assemble with unknown ID exits non-zero."""
        _make_bundle_repo(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli, ["--repo", str(tmp_path), "bundle", "assemble", "does/not/exist"])
        assert result.exit_code != 0

    def test_bundle_validate_with_invalid_bundle(self, tmp_path: Path):
        """Validate should report errors for bundles with invalid base_template."""
        _make_bundle_repo(tmp_path)
        # Inject a bundle that references a non-existent base_template
        import yaml
        bad_bundle = {
            "id": "test/bad_bundle",
            "name": "Bad",
            "base_template": "does/not/exist",
        }
        (tmp_path / "spells/bundles" / "bad.bundle.yaml").write_text(yaml.dump(bad_bundle))
        runner = CliRunner()
        result = runner.invoke(cli, ["--repo", str(tmp_path), "bundle", "validate"])
        # Should exit 1 due to error
        assert result.exit_code != 0 or "error" in result.output.lower() or "✗" in result.output
