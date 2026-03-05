# src/grimoire/sync/semantiscan.py
"""
Semantiscan sync adapter.

Imports prompts from a running semantiscan instance (via its PromptManager
export file or ``semantiscan prompt list --json``) as grimoire spells.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from grimoire.exceptions import SyncError
from grimoire.sync.base import BaseSyncer, SyncResult, run_cli_json

logger = logging.getLogger(__name__)

_DEFAULT_OUT = "spells/templates/semantiscan"


class SemantiscanSyncer(BaseSyncer):
    """
    Sync prompts from a semantiscan PromptManager into grimoire spells.

    Discovery strategy:
    1. ``semantiscan prompt list --json`` subprocess.
    2. File-based fallback: reads ``exports/semantiscan/`` TOML files.
    """

    @property
    def source_name(self) -> str:
        return "semantiscan"

    def discover(self) -> list[dict[str, Any]]:
        """Query semantiscan for its registered prompts."""
        try:
            data = run_cli_json(
                ["semantiscan", "prompt", "list", "--json"],
                error_prefix="semantiscan: ",
            )
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and "prompts" in data:
                return data["prompts"]
            return []
        except SyncError as e:
            logger.warning("semantiscan CLI unavailable (%s); trying file fallback", e)
            return []

    def discover_from_exports(self, exports_dir: Path) -> list[dict[str, Any]]:
        """File-based fallback: enumerate TOML files in exports/semantiscan/."""
        toml_dir = exports_dir / "semantiscan"
        if not toml_dir.is_dir():
            return []
        results = []
        for f in toml_dir.glob("*.toml"):
            try:
                import tomllib  # type: ignore[import]
            except ImportError:
                try:
                    import tomli as tomllib  # type: ignore[import,no-redef]
                except ImportError:
                    logger.warning("tomllib/tomli not available; cannot parse TOML exports")
                    break
            try:
                data = tomllib.loads(f.read_text(encoding="utf-8"))
                spell_id = f.stem.replace("__", "/")
                results.append({"id": spell_id, "source": str(f), **data})
            except Exception as e:
                logger.warning("Failed to parse %s: %s", f, e)
        return results

    def import_artifacts(
        self,
        repo_root: Path,
        out_dir: Path | None = None,
        overwrite: bool = False,
    ) -> SyncResult:
        """Import semantiscan prompts as grimoire spell files."""
        out_dir = out_dir or (repo_root / _DEFAULT_OUT)
        result = SyncResult(source=self.source_name)

        prompts = self.discover()
        if not prompts:
            exports_dir = repo_root / "exports"
            prompts = self.discover_from_exports(exports_dir)

        if not prompts:
            result.errors.append(
                "No prompts found from semantiscan. "
                "Ensure semantiscan is installed or run 'grimoire bind semantiscan' first."
            )
            return result

        out_dir.mkdir(parents=True, exist_ok=True)

        for prompt in prompts:
            prompt_id: str = prompt.get("id", "")
            if not prompt_id:
                result.errors.append(f"Prompt missing 'id': {prompt}")
                continue

            result.discovered.append(prompt_id)
            safe_id = prompt_id.replace("/", "__")
            target_file = out_dir / f"{safe_id}.spell.md"

            if target_file.exists() and not overwrite:
                result.skipped.append(prompt_id)
                continue

            try:
                spell_text = _prompt_to_spell_md(prompt)
                target_file.write_text(spell_text, encoding="utf-8")
                result.imported.append(prompt_id)
                logger.info("Imported semantiscan prompt '%s' → %s", prompt_id, target_file)
            except Exception as e:
                result.errors.append(f"Failed to import '{prompt_id}': {e}")

        return result

    def _get_grimoire_ids(self, repo: Any) -> set[str]:
        return {
            s.id
            for s in repo.list_spells()
            if "semantiscan" in s.id or any("semantiscan" in t for t in s.tags)
        }


def _prompt_to_spell_md(prompt: dict[str, Any]) -> str:
    """Convert a semantiscan prompt descriptor to a .spell.md file."""
    import yaml as _yaml

    prompt_id = prompt.get("id", "unknown")
    name = prompt.get("name") or prompt_id
    system = prompt.get("system", "")
    user = prompt.get("user", "")
    description = prompt.get("description", "")

    # Build variable schema from placeholders detected in templates
    import re
    placeholders = set(re.findall(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", system + " " + user))
    variables: dict[str, Any] = {}
    for ph in sorted(placeholders):
        variables[ph] = {"type": "string", "required": True}

    frontmatter = {
        "id": prompt_id,
        "name": name,
        "version": "1.0.0",
        "description": description or None,
        "tags": ["semantiscan", *prompt.get("tags", [])],
    }
    if variables:
        # Convert from semantiscan {var} syntax to grimoire {{ var }} in content
        frontmatter["variables"] = variables  # type: ignore[assignment]

    fm_str = _yaml.dump(frontmatter, default_flow_style=False).strip()
    lines = [f"---\n{fm_str}\n---\n"]

    if system:
        # Convert {var} → {{ var }}
        system_grimoire = re.sub(r"\{([a-zA-Z_]\w*)\}", r"{{ \1 }}", system)
        lines.append(f"\n# SYSTEM\n{system_grimoire}\n")

    if user:
        user_grimoire = re.sub(r"\{([a-zA-Z_]\w*)\}", r"{{ \1 }}", user)
        lines.append(f"\n# USER\n{user_grimoire}\n")

    return "".join(lines)
