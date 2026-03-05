# src/grimoire/bind/base.py
"""
Base binder types and protocol.

All binding targets implement the ``Binder`` abstract class, producing
``BindResult`` artifacts that can be written to disk or consumed in-memory.
"""

from __future__ import annotations

import hashlib
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from grimoire.store.repo import GrimoireRepo

logger = logging.getLogger(__name__)


class BindTarget(str, Enum):
    """Supported binding targets (spec §10.1)."""

    SEMANTISCAN = "semantiscan"
    LLMCORE = "llmcore"
    WAIRU = "wairu"


class BindFormat(str, Enum):
    """Sub-format selection within a target."""

    # Semantiscan
    TOML = "toml"
    LEGACY_TMPL = "legacy_tmpl"
    # llmcore
    REGISTRY_BUNDLE = "registry_bundle"
    # wairu
    TOOL_PACK = "tool_pack"


@dataclass
class BoundFile:
    """A single file produced by a binder."""

    relative_path: str
    content: str
    description: str = ""


@dataclass
class BindResult:
    """
    Aggregated output of a binding operation.

    Contains all files produced, plus metadata for reporting.
    ``compiled_hash`` is a SHA-256 (truncated 16 chars) of all produced
    file contents concatenated in order — used for drift detection (spec §12).
    """

    target: BindTarget
    format: BindFormat
    files: list[BoundFile] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    compiled_hash: str | None = None

    @property
    def ok(self) -> bool:
        """True if files were produced without fatal errors."""
        return len(self.files) > 0

    def compute_hash(self) -> "BindResult":
        """Compute and set compiled_hash from all BoundFile contents."""
        hasher = hashlib.sha256()
        for bf in self.files:
            hasher.update(bf.content.encode())
        self.compiled_hash = hasher.hexdigest()[:16]
        return self

    def write(self, out_dir: str | Path) -> list[Path]:
        """
        Write all bound files to disk under ``out_dir``.

        Creates directories as needed. Returns list of written paths.
        """
        out = Path(out_dir)
        written: list[Path] = []
        for bf in self.files:
            target = out / bf.relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(bf.content, encoding="utf-8")
            written.append(target)
            logger.debug("Wrote %s", target)
        return written


class Binder(ABC):
    """
    Abstract base for all binding targets.

    Subclasses implement ``bind()`` to produce ``BindResult`` from a
    grimoire repository. The binder is stateless; all context comes
    from the repo and options.
    """

    @property
    @abstractmethod
    def target(self) -> BindTarget:
        """The binding target this binder produces."""
        ...

    @property
    @abstractmethod
    def default_format(self) -> BindFormat:
        """Default format if none specified."""
        ...

    @abstractmethod
    def bind(
        self,
        repo: GrimoireRepo,
        *,
        fmt: BindFormat | None = None,
        spell_ids: list[str] | None = None,
        rune_ids: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> BindResult:
        """
        Produce bound artifacts from a grimoire repository.

        Args:
            repo: Loaded grimoire repository.
            fmt: Output sub-format (uses default if None).
            spell_ids: If given, only bind these spells.
            rune_ids: If given, only bind these runes.
            tags: If given, filter artifacts by tags.

        Returns:
            BindResult with all produced files.
        """
        ...
