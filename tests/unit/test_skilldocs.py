# tests/unit/test_skilldocs.py
"""
Tests for Phase 7: SkillDocs.

Covers:
  - parse_skilldoc / parse_skilldoc_file
  - Section splitting from markdown headings
  - Frontmatter section metadata (tags per section)
  - SkillDocSelector: by_tags, by_heading, by_keyword, by_id, render
  - OpenAI tool schema export
  - GrimoireRepo discovery of *.skilldoc.md
  - validate_skilldoc()
  - CLI skill list|show|validate|docs|export
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from grimoire.cli import cli
from grimoire.exceptions import ArtifactNotFoundError, SkillDocParseError
from grimoire.models import SkillDoc
from grimoire.skilldocs.parser import parse_skilldoc, parse_skilldoc_file
from grimoire.skilldocs.selector import SkillDocSelector
from grimoire.store.repo import GrimoireRepo
from grimoire.validate.rules import validate_skilldoc


# ── Sample SkillDoc text ─────────────────────────────────────────────────────

_SAMPLE_SKILLDOC = """\
---
id: skills/git/workflow
name: Git Workflow Guide
version: 1.0.0
tags: [git, devtools]
sections:
  - id: branching
    tags: [branching, workflow]
  - id: rebase
    tags: [rebase, history]
---

## branching

Use short-lived feature branches off main.

## rebase

Prefer rebase over merge for feature branches.
"""

_SINGLE_SECTION = """\
---
id: skills/simple
name: Simple Doc
---

## overview

Single section content here.
"""

_NO_HEADINGS = """\
---
id: skills/nohd
name: No Headings
---

This document has no headings at all.
"""


# ── Parser tests ──────────────────────────────────────────────────────────────


class TestSkillDocParser:
    def test_parse_basic(self):
        fm = {"id": "skills/test", "name": "Test"}
        body = "## intro\n\nSome content.\n"
        doc = parse_skilldoc(fm, body)
        assert doc.id == "skills/test"
        assert doc.name == "Test"
        assert len(doc.sections) == 1
        assert doc.sections[0].id == "intro"
        assert "Some content." in doc.sections[0].content

    def test_parse_multiple_sections(self):
        fm = {"id": "skills/multi", "name": "Multi"}
        body = "## alpha\n\nAlpha content.\n\n## beta\n\nBeta content.\n"
        doc = parse_skilldoc(fm, body)
        assert len(doc.sections) == 2
        assert doc.sections[0].id == "alpha"
        assert doc.sections[1].id == "beta"

    def test_parse_section_tags_from_frontmatter(self):
        fm = {
            "id": "skills/tagged",
            "name": "Tagged",
            "sections": [
                {"id": "branching", "tags": ["git", "workflow"]}
            ],
        }
        body = "## branching\n\nContent here.\n"
        doc = parse_skilldoc(fm, body)
        assert doc.sections[0].tags == ["git", "workflow"]

    def test_parse_no_headings_creates_main_section(self):
        fm = {"id": "skills/nohd", "name": "No Headings"}
        body = "Plain text with no headings."
        doc = parse_skilldoc(fm, body)
        assert len(doc.sections) == 1
        assert doc.sections[0].id == "main"

    def test_parse_empty_body_no_sections(self):
        fm = {"id": "skills/empty", "name": "Empty"}
        doc = parse_skilldoc(fm, "")
        assert doc.sections == []

    def test_content_hash_computed(self):
        fm = {"id": "skills/hash", "name": "Hash"}
        body = "## sec\n\nContent.\n"
        doc = parse_skilldoc(fm, body)
        assert doc.content_hash is not None
        assert len(doc.content_hash) == 16

    def test_content_hash_stable(self):
        fm = {"id": "skills/hash", "name": "Hash"}
        body = "## sec\n\nContent.\n"
        d1 = parse_skilldoc(fm, body)
        d2 = parse_skilldoc(fm, body)
        assert d1.content_hash == d2.content_hash

    def test_missing_id_raises(self):
        fm = {"name": "No ID"}
        with pytest.raises(SkillDocParseError, match="id"):
            parse_skilldoc(fm, "")

    def test_missing_name_raises(self):
        fm = {"id": "skills/no_name"}
        with pytest.raises(SkillDocParseError, match="name"):
            parse_skilldoc(fm, "")

    def test_parse_file(self, tmp_path: Path):
        f = tmp_path / "git.skilldoc.md"
        f.write_text(_SAMPLE_SKILLDOC)
        doc = parse_skilldoc_file(f)
        assert doc.id == "skills/git/workflow"
        assert len(doc.sections) == 2

    def test_parse_file_missing_frontmatter(self, tmp_path: Path):
        f = tmp_path / "bad.skilldoc.md"
        f.write_text("# No frontmatter\n\nJust content.\n")
        with pytest.raises(SkillDocParseError, match="frontmatter"):
            parse_skilldoc_file(f)

    def test_parse_file_unclosed_frontmatter(self, tmp_path: Path):
        f = tmp_path / "unclosed.skilldoc.md"
        f.write_text("---\nid: test\nname: Test\n\nNo closing dashes.\n")
        with pytest.raises(SkillDocParseError, match="closing"):
            parse_skilldoc_file(f)

    def test_parse_file_bad_yaml_frontmatter(self, tmp_path: Path):
        f = tmp_path / "badfm.skilldoc.md"
        f.write_text("---\n{ not: valid: yaml: [\n---\n\n## sec\n\nContent.\n")
        with pytest.raises(SkillDocParseError, match="YAML"):
            parse_skilldoc_file(f)

    def test_section_id_derived_from_heading(self):
        fm = {"id": "skills/x", "name": "X"}
        body = "## My Section Heading\n\nContent.\n"
        doc = parse_skilldoc(fm, body)
        assert doc.sections[0].id == "my_section_heading"

    def test_heading_preserved(self):
        fm = {"id": "skills/x", "name": "X"}
        body = "## Branching Strategy\n\nContent.\n"
        doc = parse_skilldoc(fm, body)
        assert doc.sections[0].heading == "Branching Strategy"


# ── Selector tests ────────────────────────────────────────────────────────────


class TestSkillDocSelector:
    @pytest.fixture
    def doc(self, tmp_path: Path) -> SkillDoc:
        f = tmp_path / "test.skilldoc.md"
        f.write_text(_SAMPLE_SKILLDOC)
        return parse_skilldoc_file(f)

    def test_all_sections(self, doc: SkillDoc):
        sel = SkillDocSelector(doc)
        assert len(sel.all_sections()) == 2

    def test_by_tags_and(self, doc: SkillDoc):
        sel = SkillDocSelector(doc)
        result = sel.by_tags(["branching"], require_all=True)
        assert len(result) == 1
        assert result[0].id == "branching"

    def test_by_tags_or(self, doc: SkillDoc):
        sel = SkillDocSelector(doc)
        result = sel.by_tags(["branching", "rebase"], require_all=False)
        assert len(result) == 2

    def test_by_tags_no_match(self, doc: SkillDoc):
        sel = SkillDocSelector(doc)
        result = sel.by_tags(["nonexistent"])
        assert result == []

    def test_by_tags_empty_returns_all(self, doc: SkillDoc):
        sel = SkillDocSelector(doc)
        result = sel.by_tags([])
        assert len(result) == 2

    def test_by_heading(self, doc: SkillDoc):
        sel = SkillDocSelector(doc)
        result = sel.by_heading("branch")
        assert len(result) == 1
        assert result[0].id == "branching"

    def test_by_heading_case_insensitive(self, doc: SkillDoc):
        sel = SkillDocSelector(doc)
        result = sel.by_heading("BRANCH")
        assert len(result) == 1

    def test_by_id(self, doc: SkillDoc):
        sel = SkillDocSelector(doc)
        sec = sel.by_id("rebase")
        assert sec is not None
        assert sec.heading == "rebase"

    def test_by_id_not_found(self, doc: SkillDoc):
        sel = SkillDocSelector(doc)
        assert sel.by_id("does_not_exist") is None

    def test_by_keyword(self, doc: SkillDoc):
        sel = SkillDocSelector(doc)
        result = sel.by_keyword("short-lived")
        assert len(result) == 1
        assert result[0].id == "branching"

    def test_render_all(self, doc: SkillDoc):
        sel = SkillDocSelector(doc)
        text = sel.render()
        assert "## branching" in text
        assert "## rebase" in text
        assert "short-lived" in text

    def test_render_subset(self, doc: SkillDoc):
        sel = SkillDocSelector(doc)
        sections = sel.by_id_list = [doc.sections[0]]
        text = sel.render([doc.sections[0]])
        assert "## branching" in text
        assert "rebase" not in text

    def test_openai_tool_schema(self):
        """render_to_openai_tool_schema produces valid OpenAI function definitions."""
        from grimoire.models import CommandSpec, ParamSpec, RiskLevel, RuneSpec

        rune = RuneSpec(
            id="devtools/git",
            name="Git",
            commands=[
                CommandSpec(
                    name="status",
                    summary="Get repo status",
                    params=[
                        ParamSpec(name="path", type="string", required=True, description="Repo path")
                    ],
                )
            ],
        )
        sel = SkillDocSelector(None)  # type: ignore[arg-type]
        tools = sel.render_to_openai_tool_schema([rune])
        assert len(tools) == 1
        assert tools[0]["type"] == "function"
        assert "devtools__git" in tools[0]["function"]["name"]
        assert "path" in tools[0]["function"]["parameters"]["properties"]
        assert tools[0]["function"]["parameters"]["required"] == ["path"]


# ── Validation tests ──────────────────────────────────────────────────────────


class TestValidateSkillDoc:
    def test_valid_skilldoc(self, tmp_path: Path):
        f = tmp_path / "ok.skilldoc.md"
        f.write_text(_SAMPLE_SKILLDOC)
        doc = parse_skilldoc_file(f)
        result = validate_skilldoc(doc)
        assert result.ok

    def test_no_sections_warning(self, tmp_path: Path):
        f = tmp_path / "nosec.skilldoc.md"
        f.write_text(_NO_HEADINGS)
        # "No Headings" body has text but no ## headings → "main" section added
        # Actually it creates a main section from the body text
        doc = parse_skilldoc_file(f)
        result = validate_skilldoc(doc)
        # Should be fine since body creates a "main" section
        assert result.ok

    def test_missing_slash_in_id_warning(self):
        from grimoire.validate.rules import Severity
        fm = {"id": "noslash", "name": "No Slash"}
        body = "## sec\n\nContent.\n"
        doc = parse_skilldoc(fm, body)
        result = validate_skilldoc(doc)
        assert any(d.severity == Severity.WARNING for d in result.diagnostics)

    def test_duplicate_section_ids_error(self):
        fm = {"id": "skills/dup", "name": "Dup"}
        # parser can't create duplicate IDs from headings, so build manually
        from grimoire.models import SkillDocSection
        doc = SkillDoc(
            id="skills/dup",
            name="Dup",
            sections=[
                SkillDocSection(id="same", heading="Same", content="A"),
                SkillDocSection(id="same", heading="Same", content="B"),
            ],
        )
        result = validate_skilldoc(doc)
        assert not result.ok


# ── Repo discovery tests ──────────────────────────────────────────────────────


class TestRepoSkillDocDiscovery:
    def _make_repo(self, tmp_path: Path) -> GrimoireRepo:
        manifest = {
            "name": "sd-test",
            "version": "0.1.0",
            "spell_paths": ["spells/"],
            "rune_paths": ["runes/"],
            "ritual_paths": ["rituals/"],
            "promptlet_paths": ["prompts/"],
            "bundle_paths": ["bundles/"],
            "skilldoc_paths": ["skills/docs/"],
        }
        (tmp_path / "grimoire.yaml").write_text(yaml.dump(manifest))
        for d in ["spells", "runes", "rituals", "prompts", "bundles", "skills/docs", "vars"]:
            (tmp_path / d).mkdir(parents=True, exist_ok=True)
        (tmp_path / "vars" / "defaults.yaml").write_text("{}\n")
        f = tmp_path / "skills/docs" / "git.skilldoc.md"
        f.write_text(_SAMPLE_SKILLDOC)
        return GrimoireRepo.load(tmp_path)

    def test_discovers_skilldocs(self, tmp_path: Path):
        repo = self._make_repo(tmp_path)
        docs = repo.list_skilldocs()
        assert len(docs) == 1
        assert docs[0].id == "skills/git/workflow"

    def test_get_skilldoc(self, tmp_path: Path):
        repo = self._make_repo(tmp_path)
        doc = repo.get_skilldoc("skills/git/workflow")
        assert doc.name == "Git Workflow Guide"

    def test_get_skilldoc_not_found(self, tmp_path: Path):
        repo = self._make_repo(tmp_path)
        with pytest.raises(ArtifactNotFoundError):
            repo.get_skilldoc("does/not/exist")

    def test_list_skilldocs_tag_filter(self, tmp_path: Path):
        repo = self._make_repo(tmp_path)
        result = repo.list_skilldocs(tags=["git"])
        assert len(result) == 1
        result_none = repo.list_skilldocs(tags=["nonexistent"])
        assert result_none == []

    def test_catalog_includes_skilldocs(self, tmp_path: Path):
        repo = self._make_repo(tmp_path)
        catalog = repo.catalog()
        assert "skilldocs" in catalog
        assert catalog["skilldocs"][0]["id"] == "skills/git/workflow"

    def test_facade_skills_docs(self, tmp_path: Path):
        repo = self._make_repo(tmp_path)
        docs = repo.skills.docs()
        assert len(docs) == 1


# ── CLI tests ─────────────────────────────────────────────────────────────────


class TestSkillCLI:
    def _make_repo(self, tmp_path: Path) -> Path:
        manifest = {
            "name": "skill-cli-test",
            "version": "0.1.0",
            "spell_paths": ["spells/"],
            "rune_paths": ["runes/"],
            "ritual_paths": ["rituals/"],
            "promptlet_paths": ["prompts/"],
            "bundle_paths": ["bundles/"],
            "skilldoc_paths": ["skills/docs/"],
        }
        (tmp_path / "grimoire.yaml").write_text(yaml.dump(manifest))
        for d in ["spells", "runes", "rituals", "prompts", "bundles",
                  "skills/docs", "vars", "runes/contracts"]:
            (tmp_path / d).mkdir(parents=True, exist_ok=True)
        (tmp_path / "vars" / "defaults.yaml").write_text("{}\n")
        (tmp_path / "skills/docs" / "git.skilldoc.md").write_text(_SAMPLE_SKILLDOC)
        rune_data = {
            "id": "devtools/git",
            "name": "Git",
            "tags": ["git"],
            "risk_level": "low",
            "commands": [{"name": "status", "summary": "Git status"}],
        }
        (tmp_path / "runes" / "git.rune.yaml").write_text(yaml.dump(rune_data))
        return tmp_path

    def test_skill_list_all(self, tmp_path: Path):
        root = self._make_repo(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["--repo", str(root), "skill", "list"])
        assert result.exit_code == 0
        assert "git/workflow" in result.output or "git" in result.output

    def test_skill_list_docs_only(self, tmp_path: Path):
        root = self._make_repo(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["--repo", str(root), "skill", "list", "--type", "docs"])
        assert result.exit_code == 0
        assert "doc" in result.output.lower() or "git" in result.output

    def test_skill_list_json(self, tmp_path: Path):
        import json

        root = self._make_repo(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["--repo", str(root), "skill", "list", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        types = {item["type"] for item in data}
        assert "doc" in types
        assert "contract" in types

    def test_skill_show_doc(self, tmp_path: Path):
        root = self._make_repo(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["--repo", str(root), "skill", "show", "skills/git/workflow"])
        assert result.exit_code == 0
        assert "Git Workflow" in result.output

    def test_skill_show_contract(self, tmp_path: Path):
        root = self._make_repo(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["--repo", str(root), "skill", "show", "devtools/git"])
        assert result.exit_code == 0

    def test_skill_show_not_found(self, tmp_path: Path):
        root = self._make_repo(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["--repo", str(root), "skill", "show", "not/exist"])
        assert result.exit_code != 0

    def test_skill_validate(self, tmp_path: Path):
        root = self._make_repo(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["--repo", str(root), "skill", "validate"])
        assert result.exit_code == 0

    def test_skill_docs_render(self, tmp_path: Path):
        root = self._make_repo(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--repo", str(root), "skill", "docs", "skills/git/workflow"],
        )
        assert result.exit_code == 0
        assert "branching" in result.output.lower()

    def test_skill_docs_section_filter(self, tmp_path: Path):
        root = self._make_repo(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "--repo", str(root),
                "skill", "docs",
                "--sections", "branching",
                "skills/git/workflow",
            ],
        )
        assert result.exit_code == 0
        assert "branching" in result.output.lower()

    def test_skill_export_openai(self, tmp_path: Path):
        import json

        root = self._make_repo(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--repo", str(root), "skill", "export", "--to", "openai-tool-schema"],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert data[0]["type"] == "function"

    def test_skill_export_llmcore_activities(self, tmp_path: Path):
        import json

        root = self._make_repo(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--repo", str(root), "skill", "export", "--to", "llmcore-activities"],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert data[0]["id"] == "devtools/git"
