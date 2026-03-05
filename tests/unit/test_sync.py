# tests/unit/test_sync.py
"""
Tests for Phase 6: Sync & Drift Detection.
"""
from __future__ import annotations
import json
from pathlib import Path
import pytest
import yaml
from click.testing import CliRunner
from grimoire.cli import cli
from grimoire.sync import DriftReport, LLMCoreSyncer, SemantiscanSyncer, SyncResult, WairuSyncer
from grimoire.sync.base import BaseSyncer


def _make_wairu_manifest(tmp_path: Path) -> Path:
    exports = tmp_path / "exports" / "wairu"
    exports.mkdir(parents=True)
    tools = [
        {"id": "devtools/git_status", "name": "Git Status", "risk_level": "low", "tags": ["git"],
         "commands": {"status": {"description": "Get status", "risk_level": "low",
                                  "requires_approval": False,
                                  "params": {"path": {"type": "string", "required": True, "description": "Path"}}}}},
        {"id": "devtools/git_commit", "name": "Git Commit", "risk_level": "medium", "tags": ["git"],
         "commands": {"commit": {"description": "Commit", "risk_level": "medium",
                                  "requires_approval": True, "params": {}}}},
    ]
    (exports / "manifest.json").write_text(json.dumps({"activities": tools}))
    return tmp_path


def _make_llmcore_manifest(tmp_path: Path) -> Path:
    exports = tmp_path / "exports" / "llmcore"
    exports.mkdir(parents=True)
    activities = [{"id": "llmcore/chat", "name": "Chat", "risk_level": "low",
                   "tags": ["llm"], "commands": {}}]
    (exports / "manifest.json").write_text(json.dumps({"activities": activities}))
    return tmp_path


def _make_semantiscan_manifest(tmp_path: Path) -> Path:
    exports = tmp_path / "exports" / "semantiscan"
    exports.mkdir(parents=True)
    # SemantiscanSyncer reads *.toml files; filename stem becomes the id (with __ -> /)
    toml_content = 'name = "RAG Default"\nrisk_level = "low"\ntags = ["rag"]\n'
    (exports / "semantiscan__rag_default.toml").write_text(toml_content)
    return tmp_path


def _setup_repo(root: Path) -> None:
    if not (root / "grimoire.yaml").exists():
        manifest = {"name": "sync-test", "version": "0.1.0",
                    "spell_paths": ["spells/"], "rune_paths": ["runes/"],
                    "ritual_paths": ["rituals/"], "promptlet_paths": ["prompts/"],
                    "bundle_paths": ["bundles/"], "skilldoc_paths": ["skills/"]}
        (root / "grimoire.yaml").write_text(yaml.dump(manifest))
    for d in ["spells", "runes", "rituals", "prompts", "bundles", "skills", "vars"]:
        (root / d).mkdir(parents=True, exist_ok=True)
    defaults = root / "vars" / "defaults.yaml"
    if not defaults.exists():
        defaults.write_text("{}\n")


class TestSyncResult:
    def test_ok_no_errors(self):
        r = SyncResult(source="wairu")
        assert r.ok is True

    def test_ok_false_with_errors(self):
        r = SyncResult(source="wairu", errors=["fail"])
        assert r.ok is False

    def test_fields(self):
        r = SyncResult(source="llmcore", discovered=["a", "b"], imported=["a"], skipped=["b"])
        assert r.source == "llmcore"
        assert r.discovered == ["a", "b"]
        assert r.imported == ["a"]
        assert r.skipped == ["b"]


class TestDriftReport:
    def test_fields(self):
        d = DriftReport(artifact_id="tools/x", drift_type="missing_in_grimoire", detail="Not found")
        assert d.artifact_id == "tools/x"
        assert d.drift_type == "missing_in_grimoire"
        assert d.detail == "Not found"


class TestWairuSyncer:
    def test_source_name(self):
        assert WairuSyncer().source_name == "wairu"

    def test_discover_from_exports(self, tmp_path: Path):
        _make_wairu_manifest(tmp_path)
        syncer = WairuSyncer()
        raw = syncer.discover_from_exports(tmp_path / "exports")
        assert len(raw) == 2
        ids = [t["id"] for t in raw]
        assert "devtools/git_status" in ids
        assert "devtools/git_commit" in ids

    def test_discover_from_exports_missing_returns_empty(self, tmp_path: Path):
        syncer = WairuSyncer()
        result = syncer.discover_from_exports(tmp_path / "exports")
        assert result == []

    def test_import_writes_files(self, tmp_path: Path):
        _make_wairu_manifest(tmp_path)
        _setup_repo(tmp_path)
        syncer = WairuSyncer()
        out_dir = tmp_path / "runes" / "wairu_out"
        result = syncer.import_artifacts(repo_root=tmp_path, out_dir=out_dir)
        assert result.ok
        assert len(result.imported) == 2
        assert len(list(out_dir.glob("*.rune.yaml"))) == 2

    def test_import_source_is_wairu(self, tmp_path: Path):
        _make_wairu_manifest(tmp_path)
        _setup_repo(tmp_path)
        syncer = WairuSyncer()
        out_dir = tmp_path / "runes" / "wairu_out"
        result = syncer.import_artifacts(repo_root=tmp_path, out_dir=out_dir)
        assert result.source == "wairu"

    def test_import_skip_existing(self, tmp_path: Path):
        _make_wairu_manifest(tmp_path)
        _setup_repo(tmp_path)
        syncer = WairuSyncer()
        out_dir = tmp_path / "runes" / "wairu_out"
        syncer.import_artifacts(repo_root=tmp_path, out_dir=out_dir)
        r2 = syncer.import_artifacts(repo_root=tmp_path, out_dir=out_dir, overwrite=False)
        assert len(r2.imported) == 0
        assert len(r2.skipped) == 2

    def test_import_overwrite(self, tmp_path: Path):
        _make_wairu_manifest(tmp_path)
        _setup_repo(tmp_path)
        syncer = WairuSyncer()
        out_dir = tmp_path / "runes" / "wairu_out"
        syncer.import_artifacts(repo_root=tmp_path, out_dir=out_dir)
        r2 = syncer.import_artifacts(repo_root=tmp_path, out_dir=out_dir, overwrite=True)
        assert len(r2.imported) == 2
        assert len(r2.skipped) == 0

    def test_import_rune_yaml_valid(self, tmp_path: Path):
        _make_wairu_manifest(tmp_path)
        _setup_repo(tmp_path)
        syncer = WairuSyncer()
        out_dir = tmp_path / "runes" / "wairu_out"
        syncer.import_artifacts(repo_root=tmp_path, out_dir=out_dir)
        rune_file = out_dir / "devtools__git_status.rune.yaml"
        assert rune_file.exists()
        data = yaml.safe_load(rune_file.read_text())
        assert data["id"] == "devtools/git_status"

    def test_import_no_tools_reports_error(self, tmp_path: Path):
        _setup_repo(tmp_path)
        syncer = WairuSyncer()
        out_dir = tmp_path / "runes" / "wairu_out"
        result = syncer.import_artifacts(repo_root=tmp_path, out_dir=out_dir)
        assert not result.ok


class TestLLMCoreSyncer:
    def test_source_name(self):
        assert LLMCoreSyncer().source_name == "llmcore"

    def test_discover_from_exports(self, tmp_path: Path):
        _make_llmcore_manifest(tmp_path)
        syncer = LLMCoreSyncer()
        raw = syncer.discover_from_exports(tmp_path / "exports")
        assert len(raw) == 1
        assert raw[0]["id"] == "llmcore/chat"

    def test_import_artifacts(self, tmp_path: Path):
        _make_llmcore_manifest(tmp_path)
        _setup_repo(tmp_path)
        syncer = LLMCoreSyncer()
        out_dir = tmp_path / "runes" / "llmcore_out"
        result = syncer.import_artifacts(repo_root=tmp_path, out_dir=out_dir)
        assert result.source == "llmcore"
        assert len(result.imported) == 1

    def test_import_no_manifest_graceful(self, tmp_path: Path):
        _setup_repo(tmp_path)
        syncer = LLMCoreSyncer()
        out_dir = tmp_path / "runes" / "llmcore_out"
        result = syncer.import_artifacts(repo_root=tmp_path, out_dir=out_dir)
        assert isinstance(result, SyncResult)


class TestSemantiscanSyncer:
    def test_source_name(self):
        assert SemantiscanSyncer().source_name == "semantiscan"

    def test_discover_from_exports(self, tmp_path: Path):
        _make_semantiscan_manifest(tmp_path)
        syncer = SemantiscanSyncer()
        raw = syncer.discover_from_exports(tmp_path / "exports")
        assert len(raw) == 1
        assert raw[0]["id"] == "semantiscan/rag_default"  # stem semantiscan__rag_default -> semantiscan/rag_default

    def test_import_artifacts(self, tmp_path: Path):
        _make_semantiscan_manifest(tmp_path)
        _setup_repo(tmp_path)
        syncer = SemantiscanSyncer()
        out_dir = tmp_path / "runes" / "sem_out"
        result = syncer.import_artifacts(repo_root=tmp_path, out_dir=out_dir)
        assert result.source == "semantiscan"
        assert len(result.imported) == 1


class TestDriftDetection:
    def _add_rune(self, root: Path, rune_id: str, risk: str = "low") -> None:
        rune = {"id": rune_id, "name": rune_id.split("/")[-1], "risk_level": risk,
                "tags": [], "commands": [{"name": "run", "summary": "Run"}]}
        fname = rune_id.replace("/", "__") + ".rune.yaml"
        (root / "runes" / fname).write_text(yaml.dump(rune))

    def _syncer_with_tools(self, tools: list) -> WairuSyncer:
        """Return a WairuSyncer whose discover() returns fixed tools (no CLI needed)."""
        syncer = WairuSyncer()
        syncer.discover = lambda: tools  # type: ignore[method-assign]
        return syncer

    def test_missing_in_grimoire(self, tmp_path: Path):
        """Runtime has a tool that grimoire doesn't → missing_in_grimoire."""
        _setup_repo(tmp_path)
        fake_tools = [{"id": "devtools/new_tool", "name": "New Tool"}]
        syncer = self._syncer_with_tools(fake_tools)
        reports = syncer.detect_drift(tmp_path)
        types = {r.drift_type for r in reports}
        assert "missing_in_grimoire" in types
        assert any("new_tool" in r.artifact_id for r in reports)

    def test_missing_in_runtime(self, tmp_path: Path):
        """Grimoire has a rune not in runtime → missing_in_runtime."""
        _setup_repo(tmp_path)
        self._add_rune(tmp_path, "devtools/extra_tool")
        syncer = self._syncer_with_tools([])  # empty runtime
        reports = syncer.detect_drift(tmp_path)
        # extra_tool is in grimoire but not runtime
        # Note: _get_grimoire_ids in WairuSyncer filters by wairu mappings;
        # base class uses empty set. Test against BaseSyncer logic directly.
        # Use BaseSyncer.detect_drift via monkeypatching _get_grimoire_ids
        from grimoire.store.repo import GrimoireRepo
        repo = GrimoireRepo.load(tmp_path)
        syncer._get_grimoire_ids = lambda r: {x.id for x in r.list_runes()}  # type: ignore[method-assign]
        reports = syncer.detect_drift(tmp_path)
        missing = [r for r in reports if r.drift_type == "missing_in_runtime"]
        assert any("extra_tool" in r.artifact_id for r in missing)

    def test_no_drift_when_ids_match(self, tmp_path: Path):
        """Same IDs in runtime and grimoire → no missing reports."""
        _setup_repo(tmp_path)
        self._add_rune(tmp_path, "devtools/git_status")
        self._add_rune(tmp_path, "devtools/git_commit")
        fake_tools = [{"id": "devtools/git_status"}, {"id": "devtools/git_commit"}]
        syncer = self._syncer_with_tools(fake_tools)
        from grimoire.store.repo import GrimoireRepo
        syncer._get_grimoire_ids = lambda r: {x.id for x in r.list_runes()}  # type: ignore[method-assign]
        reports = syncer.detect_drift(tmp_path)
        missing = [r for r in reports if "missing" in r.drift_type]
        assert missing == []

    def test_drift_reports_have_detail(self, tmp_path: Path):
        _setup_repo(tmp_path)
        fake_tools = [{"id": "devtools/new_tool"}]
        syncer = self._syncer_with_tools(fake_tools)
        reports = syncer.detect_drift(tmp_path)
        for r in reports:
            assert r.detail


class TestSyncCLI:
    def test_from_wairu(self, tmp_path: Path):
        _make_wairu_manifest(tmp_path)
        _setup_repo(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["--repo", str(tmp_path), "sync", "from-wairu"])
        assert result.exit_code == 0

    def test_from_wairu_json(self, tmp_path: Path):
        _make_wairu_manifest(tmp_path)
        _setup_repo(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["--repo", str(tmp_path), "sync", "from-wairu", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["source"] == "wairu"

    def test_from_wairu_writes_files(self, tmp_path: Path):
        _make_wairu_manifest(tmp_path)
        _setup_repo(tmp_path)
        out_dir = tmp_path / "sync_out"
        runner = CliRunner()
        result = runner.invoke(
            cli, ["--repo", str(tmp_path), "sync", "from-wairu", "--out", str(out_dir)])
        assert result.exit_code == 0
        assert len(list(out_dir.glob("*.rune.yaml"))) == 2

    def test_from_llmcore(self, tmp_path: Path):
        _make_llmcore_manifest(tmp_path)
        _setup_repo(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["--repo", str(tmp_path), "sync", "from-llmcore"])
        assert result.exit_code == 0

    def test_from_semantiscan(self, tmp_path: Path):
        _make_semantiscan_manifest(tmp_path)
        _setup_repo(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["--repo", str(tmp_path), "sync", "from-semantiscan"])
        assert result.exit_code == 0

    def test_drift_wairu(self, tmp_path: Path):
        _make_wairu_manifest(tmp_path)
        _setup_repo(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli, ["--repo", str(tmp_path), "sync", "drift", "--target", "wairu"])
        assert result.exit_code == 0

    def test_drift_json(self, tmp_path: Path):
        _make_wairu_manifest(tmp_path)
        _setup_repo(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli, ["--repo", str(tmp_path), "sync", "drift", "--target", "wairu", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        if data:
            assert "artifact_id" in data[0]

    def test_drift_all_targets(self, tmp_path: Path):
        _make_wairu_manifest(tmp_path)
        _make_llmcore_manifest(tmp_path)
        _make_semantiscan_manifest(tmp_path)
        _setup_repo(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli, ["--repo", str(tmp_path), "sync", "drift", "--target", "all"])
        assert result.exit_code == 0

    def test_from_wairu_overwrite(self, tmp_path: Path):
        _make_wairu_manifest(tmp_path)
        _setup_repo(tmp_path)
        out_dir = tmp_path / "sync_out"
        runner = CliRunner()
        runner.invoke(cli, ["--repo", str(tmp_path), "sync", "from-wairu", "--out", str(out_dir)])
        result = runner.invoke(
            cli, ["--repo", str(tmp_path), "sync", "from-wairu",
                  "--out", str(out_dir), "--overwrite"])
        assert result.exit_code == 0


# ── run_cli_json / load_exports_json unit tests ───────────────────────────────


class TestSyncBaseHelpers:
    def test_load_exports_json_ok(self, tmp_path: Path):
        from grimoire.sync.base import load_exports_json
        d = tmp_path / "exports"
        d.mkdir()
        (d / "manifest.json").write_text('{"key": "val"}')
        data = load_exports_json(d, "manifest.json")
        assert data == {"key": "val"}

    def test_load_exports_json_missing_raises(self, tmp_path: Path):
        from grimoire.sync.base import load_exports_json
        from grimoire.exceptions import SyncError
        with pytest.raises(SyncError, match="Export file not found"):
            load_exports_json(tmp_path / "exports", "missing.json")

    def test_load_exports_json_bad_json_raises(self, tmp_path: Path):
        from grimoire.sync.base import load_exports_json
        from grimoire.exceptions import SyncError
        d = tmp_path / "exports"
        d.mkdir()
        (d / "bad.json").write_text("{not valid json")
        with pytest.raises(SyncError, match="Invalid JSON"):
            load_exports_json(d, "bad.json")

    def test_run_cli_json_command_not_found(self):
        from grimoire.sync.base import run_cli_json
        from grimoire.exceptions import SyncError
        with pytest.raises(SyncError, match="not found in PATH"):
            run_cli_json(["cmd_that_does_not_exist_xyzzy123"])

    def test_base_syncer_detect_drift_invalid_repo(self, tmp_path: Path):
        from grimoire.exceptions import SyncError
        syncer = WairuSyncer()
        syncer.discover = lambda: []  # type: ignore[method-assign]
        # non-existent path → SyncError
        with pytest.raises(SyncError):
            syncer.detect_drift(tmp_path / "nonexistent_repo_xyz")


class TestSemantiscanSyncerExtra:
    def test_import_skip_existing(self, tmp_path: Path):
        _make_semantiscan_manifest(tmp_path)
        _setup_repo(tmp_path)
        syncer = SemantiscanSyncer()
        out_dir = tmp_path / "runes" / "sem_out"
        syncer.import_artifacts(repo_root=tmp_path, out_dir=out_dir)
        r2 = syncer.import_artifacts(repo_root=tmp_path, out_dir=out_dir, overwrite=False)
        assert len(r2.imported) == 0
        assert len(r2.skipped) == 1

    def test_import_overwrite(self, tmp_path: Path):
        _make_semantiscan_manifest(tmp_path)
        _setup_repo(tmp_path)
        syncer = SemantiscanSyncer()
        out_dir = tmp_path / "runes" / "sem_out"
        syncer.import_artifacts(repo_root=tmp_path, out_dir=out_dir)
        r2 = syncer.import_artifacts(repo_root=tmp_path, out_dir=out_dir, overwrite=True)
        assert len(r2.imported) == 1

    def test_import_no_manifest_returns_error(self, tmp_path: Path):
        _setup_repo(tmp_path)
        syncer = SemantiscanSyncer()
        out_dir = tmp_path / "runes" / "sem_out"
        result = syncer.import_artifacts(repo_root=tmp_path, out_dir=out_dir)
        assert not result.ok

    def test_detect_drift(self, tmp_path: Path):
        _make_semantiscan_manifest(tmp_path)
        _setup_repo(tmp_path)
        syncer = SemantiscanSyncer()
        syncer.discover = lambda: [{"id": "semantiscan/rag_default"}]  # type: ignore[method-assign]
        reports = syncer.detect_drift(tmp_path)
        assert isinstance(reports, list)


# ── Additional coverage: LLMCore skip/overwrite + Semantiscan prompt template ─


class TestLLMCoreSyncerExtra:
    def test_import_skip_existing(self, tmp_path: Path):
        _make_llmcore_manifest(tmp_path)
        _setup_repo(tmp_path)
        syncer = LLMCoreSyncer()
        out_dir = tmp_path / "runes" / "llmcore_out"
        syncer.import_artifacts(repo_root=tmp_path, out_dir=out_dir)
        r2 = syncer.import_artifacts(repo_root=tmp_path, out_dir=out_dir, overwrite=False)
        assert len(r2.imported) == 0
        assert len(r2.skipped) == 1

    def test_import_overwrite(self, tmp_path: Path):
        _make_llmcore_manifest(tmp_path)
        _setup_repo(tmp_path)
        syncer = LLMCoreSyncer()
        out_dir = tmp_path / "runes" / "llmcore_out"
        syncer.import_artifacts(repo_root=tmp_path, out_dir=out_dir)
        r2 = syncer.import_artifacts(repo_root=tmp_path, out_dir=out_dir, overwrite=True)
        assert len(r2.imported) == 1
        assert len(r2.skipped) == 0

    def test_activity_missing_id_error(self, tmp_path: Path):
        _setup_repo(tmp_path)
        exports = tmp_path / "exports" / "llmcore"
        exports.mkdir(parents=True)
        (exports / "manifest.json").write_text('[{"activities": [{"name": "NoID"}]}]')
        # Actually, activities key needs to be at top level
        (exports / "manifest.json").write_text('{"activities": [{"name": "NoID"}]}')
        syncer = LLMCoreSyncer()
        out_dir = tmp_path / "runes" / "llmcore_out"
        result = syncer.import_artifacts(repo_root=tmp_path, out_dir=out_dir)
        # Should error: activity missing 'id'
        assert not result.ok


class TestSemantiscanPromptTemplate:
    def _make_toml_with_content(self, tmp_path: Path, content: str, stem: str) -> Path:
        exports = tmp_path / "exports" / "semantiscan"
        exports.mkdir(parents=True)
        (exports / f"{stem}.toml").write_text(content)
        return tmp_path

    def test_import_with_system_and_user(self, tmp_path: Path):
        """Prompt with system_template + user_template should produce valid spell md."""
        toml = 'system = "You are a helper."\nuser = "Answer: {query}"\n'
        self._make_toml_with_content(tmp_path, toml, "semantiscan__rag")
        _setup_repo(tmp_path)
        syncer = SemantiscanSyncer()
        out_dir = tmp_path / "spells_out"
        result = syncer.import_artifacts(repo_root=tmp_path, out_dir=out_dir)
        assert result.ok
        assert len(result.imported) == 1
        spell_file = out_dir / "semantiscan__rag.spell.md"
        content = spell_file.read_text()
        assert "SYSTEM" in content
        assert "USER" in content

    def test_import_spell_file_has_grimoire_syntax(self, tmp_path: Path):
        """Imported spell should convert {var} → {{ var }} syntax."""
        toml = 'user = "Hello {name}!"\n'
        self._make_toml_with_content(tmp_path, toml, "test__greet")
        _setup_repo(tmp_path)
        syncer = SemantiscanSyncer()
        out_dir = tmp_path / "spells_out"
        syncer.import_artifacts(repo_root=tmp_path, out_dir=out_dir)
        spell_file = out_dir / "test__greet.spell.md"
        content = spell_file.read_text()
        assert "{{ name }}" in content
        assert "{name}" not in content.replace("{{ name }}", "")


# ── run_cli_json error paths ──────────────────────────────────────────────────


class TestRunCliJson:
    def test_command_exits_nonzero(self):
        """Subprocess returning non-zero should raise SyncError."""
        import subprocess
        from unittest.mock import patch, MagicMock
        from grimoire.sync.base import run_cli_json
        from grimoire.exceptions import SyncError

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "some error"
        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(SyncError, match="exited"):
                run_cli_json(["fake_cmd", "arg"])

    def test_json_decode_error(self):
        """Subprocess returning invalid JSON should raise SyncError."""
        from unittest.mock import patch, MagicMock
        from grimoire.sync.base import run_cli_json
        from grimoire.exceptions import SyncError

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "not valid json {"
        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(SyncError, match="JSON parse error"):
                run_cli_json(["fake_cmd"])
