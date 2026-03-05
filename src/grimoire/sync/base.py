# src/grimoire/sync/base.py
"""
Base types for grimoire sync & drift detection (Phase 6).

``BaseSyncer`` is a protocol/ABC that each runtime adapter implements.
``SyncResult`` captures what was discovered / imported / skipped.
``DriftReport`` records a single artifact mismatch between grimoire and runtime.
"""

from __future__ import annotations

import json
import logging
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from grimoire.exceptions import SyncError

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    """
    Outcome of a sync-from-runtime operation.

    Attributes:
        source:     Runtime name ("wairu", "llmcore", "semantiscan").
        discovered: Artifact IDs found in the runtime.
        imported:   IDs actually written to the grimoire repo.
        skipped:    IDs that already existed (``--overwrite`` not set).
        errors:     Human-readable error messages for failed imports.
    """

    source: str
    discovered: list[str] = field(default_factory=list)
    imported: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True if no errors occurred."""
        return not self.errors


@dataclass
class DriftReport:
    """
    A single detected mismatch between a grimoire artifact and the runtime.

    Attributes:
        artifact_id:  Grimoire artifact ID (spell/rune ID).
        drift_type:   Classification of the mismatch.
        detail:       Human-readable explanation.
    """

    artifact_id: str
    drift_type: str  # "missing_in_runtime" | "missing_in_grimoire" | "schema_mismatch" | "risk_mismatch"
    detail: str


class BaseSyncer(ABC):
    """
    Abstract base for runtime sync adapters.

    Each concrete syncer implements ``discover()`` (query the runtime for its
    current artifact surface) and ``import_artifacts()`` (write them to grimoire).
    """

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Human-readable runtime name."""
        ...

    @abstractmethod
    def discover(self) -> list[dict[str, Any]]:
        """
        Query the runtime and return raw artifact descriptors.

        Returns:
            List of dicts with at minimum ``{"id": ..., "type": ...}``.
        """
        ...

    @abstractmethod
    def import_artifacts(
        self,
        repo_root: Path,
        out_dir: Path,
        overwrite: bool = False,
    ) -> SyncResult:
        """
        Discover and write new artifacts into the grimoire repo.

        Args:
            repo_root: Path to grimoire repo root.
            out_dir:   Directory under repo root where artifacts should be written.
            overwrite: If True, overwrite existing files.

        Returns:
            SyncResult describing what was imported/skipped/failed.
        """
        ...

    def detect_drift(self, repo_root: Path) -> list[DriftReport]:
        """
        Compare runtime surface against grimoire canonical artifacts.

        Default implementation does a symmetric difference:
        - Artifacts in grimoire but not in runtime → ``missing_in_runtime``.
        - Artifacts in runtime but not in grimoire → ``missing_in_grimoire``.

        Subclasses can override to add ``schema_mismatch`` / ``risk_mismatch``
        checks.

        Returns:
            List of DriftReport instances.
        """
        from grimoire.store.repo import GrimoireRepo

        try:
            repo = GrimoireRepo.load(repo_root)
        except Exception as e:
            raise SyncError(f"Cannot load grimoire repo from {repo_root}: {e}") from e

        runtime_ids = {a.get("id", "") for a in self.discover()}
        grimoire_ids = self._get_grimoire_ids(repo)

        reports: list[DriftReport] = []
        for gid in grimoire_ids - runtime_ids:
            reports.append(
                DriftReport(
                    artifact_id=gid,
                    drift_type="missing_in_runtime",
                    detail=f"'{gid}' is in grimoire but not found in {self.source_name}",
                )
            )
        for rid in runtime_ids - grimoire_ids:
            reports.append(
                DriftReport(
                    artifact_id=rid,
                    drift_type="missing_in_grimoire",
                    detail=f"'{rid}' exists in {self.source_name} but not in grimoire",
                )
            )
        return reports

    def _get_grimoire_ids(self, repo: Any) -> set[str]:
        """Return the grimoire-side IDs relevant to this syncer. Override per target."""
        return set()


# ── CLI subprocess helpers ────────────────────────────────────────────────────


def run_cli_json(
    args: list[str],
    timeout: int = 15,
    error_prefix: str = "",
) -> list[Any] | dict[str, Any]:
    """
    Run a subprocess expecting JSON stdout.

    Args:
        args: Command + arguments list.
        timeout: Timeout in seconds.
        error_prefix: Prefix for error messages.

    Returns:
        Parsed JSON (list or dict).

    Raises:
        SyncError: If the command fails or output is not valid JSON.
    """
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            raise SyncError(
                f"{error_prefix}Command {args[0]} exited {result.returncode}: {result.stderr[:200]}"
            )
        return json.loads(result.stdout)
    except FileNotFoundError:
        raise SyncError(f"{error_prefix}'{args[0]}' not found in PATH") from None
    except subprocess.TimeoutExpired:
        raise SyncError(f"{error_prefix}'{args[0]}' timed out after {timeout}s") from None
    except json.JSONDecodeError as e:
        raise SyncError(f"{error_prefix}JSON parse error from '{args[0]}': {e}") from e


def load_exports_json(exports_dir: Path, filename: str) -> Any:
    """
    Fallback: load a pre-existing export JSON file (file-based sync).

    Args:
        exports_dir: Path to grimoire exports directory.
        filename: JSON filename within exports_dir.

    Returns:
        Parsed JSON content.

    Raises:
        SyncError: If the file is absent or invalid.
    """
    target = exports_dir / filename
    if not target.exists():
        raise SyncError(f"Export file not found: {target}")
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SyncError(f"Invalid JSON in {target}: {e}") from e
