# src/grimoire/sync/llmcore.py
"""
llmcore sync adapter.

Discovers activities/prompts from the llmcore registry bundle export
(``exports/llmcore/manifest.json``) and imports them as grimoire artifacts.

Since llmcore is typically a library (no standalone CLI for activity listing),
the primary discovery strategy is file-based, reading the previously-exported
``exports/llmcore/`` directory produced by ``grimoire bind llmcore``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from grimoire.exceptions import SyncError
from grimoire.sync.base import BaseSyncer, SyncResult, load_exports_json

logger = logging.getLogger(__name__)

_DEFAULT_OUT = "runes/contracts/llmcore"


class LLMCoreSyncer(BaseSyncer):
    """
    Sync llmcore activities as grimoire rune contracts.

    Discovery reads ``exports/llmcore/manifest.json`` (file-based).
    """

    @property
    def source_name(self) -> str:
        return "llmcore"

    def discover(self) -> list[dict[str, Any]]:
        """Not applicable for llmcore (library, not CLI). Returns empty list."""
        logger.debug("llmcore: CLI discovery not supported; use discover_from_exports()")
        return []

    def discover_from_exports(self, exports_dir: Path) -> list[dict[str, Any]]:
        """Read activities from exports/llmcore/manifest.json."""
        try:
            data = load_exports_json(exports_dir / "llmcore", "manifest.json")
            if isinstance(data, dict):
                return data.get("activities", [])
            return []
        except SyncError as e:
            logger.warning("llmcore exports not found: %s", e)
            return []

    def import_artifacts(
        self,
        repo_root: Path,
        out_dir: Path | None = None,
        overwrite: bool = False,
    ) -> SyncResult:
        """Import llmcore activities as rune contract YAML files."""
        out_dir = out_dir or (repo_root / _DEFAULT_OUT)
        result = SyncResult(source=self.source_name)

        exports_dir = repo_root / "exports"
        activities = self.discover_from_exports(exports_dir)

        if not activities:
            result.errors.append(
                "No activities found in exports/llmcore/manifest.json. "
                "Run 'grimoire bind llmcore' first."
            )
            return result

        out_dir.mkdir(parents=True, exist_ok=True)

        for act in activities:
            act_id: str = act.get("id", "")
            if not act_id:
                result.errors.append(f"Activity missing 'id': {act}")
                continue

            result.discovered.append(act_id)
            safe_id = act_id.replace("/", "__")
            target_file = out_dir / f"{safe_id}.rune.yaml"

            if target_file.exists() and not overwrite:
                result.skipped.append(act_id)
                continue

            try:
                rune_doc = _activity_to_rune_yaml(act)
                target_file.write_text(
                    yaml.dump(rune_doc, default_flow_style=False), encoding="utf-8"
                )
                result.imported.append(act_id)
                logger.info("Imported llmcore activity '%s' → %s", act_id, target_file)
            except Exception as e:
                result.errors.append(f"Failed to import '{act_id}': {e}")

        return result

    def _get_grimoire_ids(self, repo: Any) -> set[str]:
        return {
            r.id
            for r in repo.list_runes()
            if r.mappings.get("llmcore.activity_name") or "llmcore" in r.id
        }


def _activity_to_rune_yaml(act: dict[str, Any]) -> dict[str, Any]:
    """Convert an llmcore activity descriptor to a rune contract dict."""
    act_id = act.get("id", "unknown")
    return {
        "id": act_id,
        "name": act.get("name") or act_id,
        "version": act.get("version", "1.0.0"),
        "description": act.get("description"),
        "tags": act.get("tags", ["llmcore"]),
        "risk_level": act.get("risk_level", "low"),
        "permissions": act.get("permissions", []),
        "requires_approval": False,
        "commands": [
            {
                "name": "run",
                "summary": act.get("description") or f"Execute llmcore activity {act_id}",
                "risk_level": act.get("risk_level", "low"),
                "requires_approval": False,
                "params": act.get("params", []),
            }
        ],
        "mappings": {"llmcore.activity_name": act_id},
    }
