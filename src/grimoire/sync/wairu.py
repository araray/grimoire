# src/grimoire/sync/wairu.py
"""
Wairu sync adapter.

Discovers tools from ``wairu tool list --json`` (or falls back to the exported
``exports/wairu/`` directory) and imports them as ``*.rune.yaml`` contracts.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from grimoire.exceptions import SyncError
from grimoire.sync.base import BaseSyncer, DriftReport, SyncResult, load_exports_json, run_cli_json

logger = logging.getLogger(__name__)

# Default output path relative to repo root
_DEFAULT_OUT = "runes/contracts/wairu"


class WairuSyncer(BaseSyncer):
    """
    Sync tools from a running wairu instance into grimoire rune contracts.

    Discovery strategy (in order):
    1. ``wairu tool list --json`` subprocess (Option A — live).
    2. File-based fallback: reads ``exports/wairu/manifest.json`` if wairu CLI
       is not available.
    """

    @property
    def source_name(self) -> str:
        return "wairu"

    def discover(self) -> list[dict[str, Any]]:
        """Query wairu for its current tool surface."""
        try:
            data = run_cli_json(
                ["wairu", "tool", "list", "--json"],
                error_prefix="wairu: ",
            )
            if isinstance(data, list):
                return data
            # Some wairu versions wrap under "tools"
            if isinstance(data, dict) and "tools" in data:
                return data["tools"]
            return []
        except SyncError as e:
            logger.warning("wairu CLI unavailable (%s); trying file fallback", e)
            return []

    def discover_from_exports(self, exports_dir: Path) -> list[dict[str, Any]]:
        """File-based fallback: read exports/wairu/manifest.json."""
        try:
            data = load_exports_json(exports_dir / "wairu", "manifest.json")
            if isinstance(data, dict):
                return data.get("activities", [])
            return []
        except SyncError as e:
            logger.warning("File fallback also failed: %s", e)
            return []

    def import_artifacts(
        self,
        repo_root: Path,
        out_dir: Path | None = None,
        overwrite: bool = False,
    ) -> SyncResult:
        """Import wairu tools as rune contract YAML files."""
        out_dir = out_dir or (repo_root / _DEFAULT_OUT)
        result = SyncResult(source=self.source_name)

        tools = self.discover()
        if not tools:
            exports_dir = repo_root / "exports"
            tools = self.discover_from_exports(exports_dir)

        if not tools:
            result.errors.append("No tools discovered from wairu (CLI and file fallback both failed)")
            return result

        out_dir.mkdir(parents=True, exist_ok=True)

        for tool in tools:
            tool_id: str = tool.get("id") or tool.get("name") or ""
            if not tool_id:
                result.errors.append(f"Tool missing 'id' field: {tool}")
                continue

            result.discovered.append(tool_id)
            safe_id = tool_id.replace("/", "__")
            target_file = out_dir / f"{safe_id}.rune.yaml"

            if target_file.exists() and not overwrite:
                result.skipped.append(tool_id)
                continue

            try:
                rune_doc = _tool_to_rune_yaml(tool)
                target_file.write_text(yaml.dump(rune_doc, default_flow_style=False), encoding="utf-8")
                result.imported.append(tool_id)
                logger.info("Imported wairu tool '%s' → %s", tool_id, target_file)
            except Exception as e:
                result.errors.append(f"Failed to import '{tool_id}': {e}")

        return result

    def _get_grimoire_ids(self, repo: Any) -> set[str]:
        """Return rune IDs that map to wairu tools."""
        return {
            r.id
            for r in repo.list_runes()
            if r.mappings.get("wairu.tool_name") or "wairu" in r.id
        }

    def detect_drift(self, repo_root: Path) -> list[DriftReport]:
        """Drift detection: compare wairu tools vs grimoire rune contracts."""
        from grimoire.store.repo import GrimoireRepo

        try:
            repo = GrimoireRepo.load(repo_root)
        except Exception as e:
            raise SyncError(f"Cannot load grimoire repo: {e}") from e

        runtime_tools = self.discover()
        runtime_ids = {t.get("id") or t.get("name", "") for t in runtime_tools}
        grimoire_ids = self._get_grimoire_ids(repo)

        reports: list[DriftReport] = []
        for gid in grimoire_ids - runtime_ids:
            reports.append(DriftReport(
                artifact_id=gid,
                drift_type="missing_in_runtime",
                detail=f"Rune '{gid}' is in grimoire but not exposed by wairu",
            ))
        for rid in runtime_ids - grimoire_ids:
            reports.append(DriftReport(
                artifact_id=rid,
                drift_type="missing_in_grimoire",
                detail=f"Wairu tool '{rid}' has no grimoire rune contract",
            ))

        # Schema mismatch: check risk_level consistency
        for tool in runtime_tools:
            tool_id = tool.get("id") or tool.get("name", "")
            try:
                rune = repo.get_rune(tool_id)
                tool_risk = tool.get("risk_level", "low")
                if rune.risk_level.value != tool_risk:
                    reports.append(DriftReport(
                        artifact_id=tool_id,
                        drift_type="risk_mismatch",
                        detail=(
                            f"Grimoire risk={rune.risk_level.value!r} "
                            f"but wairu reports risk={tool_risk!r}"
                        ),
                    ))
            except Exception:
                pass

        return reports


def _tool_to_rune_yaml(tool: dict[str, Any]) -> dict[str, Any]:
    """Convert a wairu tool descriptor dict into a rune contract dict."""
    tool_id = tool.get("id") or tool.get("name", "unknown")
    name = tool.get("name") or tool_id
    commands = []

    for cmd_name, cmd_info in tool.get("commands", {}).items():
        if isinstance(cmd_info, dict):
            cmd: dict[str, Any] = {
                "name": cmd_name,
                "summary": cmd_info.get("description"),
                "risk_level": cmd_info.get("risk_level", "low"),
                "requires_approval": cmd_info.get("requires_approval", False),
            }
            params = []
            for p_name, p_info in cmd_info.get("params", {}).items():
                if isinstance(p_info, dict):
                    params.append({
                        "name": p_name,
                        "type": p_info.get("type", "string"),
                        "required": p_info.get("required", False),
                        "description": p_info.get("description"),
                    })
            if params:
                cmd["params"] = params
            commands.append(cmd)

    return {
        "id": tool_id,
        "name": name,
        "version": tool.get("version", "1.0.0"),
        "description": tool.get("description"),
        "tags": tool.get("tags", ["wairu"]),
        "risk_level": tool.get("risk_level", "low"),
        "permissions": tool.get("permissions", []),
        "requires_approval": tool.get("requires_approval", False),
        "commands": commands,
        "mappings": {"wairu.tool_name": tool_id},
    }
