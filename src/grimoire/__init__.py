# src/grimoire/__init__.py
"""
Grimoire — prompt & tool control plane for the llmcore ecosystem.

Manage spells (prompt templates), runes (skill contracts), and rituals
(multi-step flows). Conjure prompts on-the-fly, bind to runtime targets.
"""

from importlib.metadata import PackageNotFoundError, version

from grimoire.conjure.engine import ConjureEngine
from grimoire.exceptions import (
    ArtifactNotFoundError,
    CircularIncludeError,
    ConjureError,
    GrimoireError,
    IncludeError,
    ManifestError,
    MissingVariableError,
    RepoError,
    RitualError,
    RuneError,
    RuneParseError,
    RuneValidationError,
    SpellError,
    SpellParseError,
    SpellValidationError,
    ValidationError,
)
from grimoire.models import (
    ConjuredPrompt,
    GrimoireManifest,
    MessageBlock,
    MessageRole,
    Promptlet,
    Provenance,
    Ritual,
    RuneSpec,
    Spell,
    VariableSpec,
)
from grimoire.runes.parser import parse_rune, parse_rune_file
from grimoire.spells.parser import parse_spell, parse_spell_file
from grimoire.store.repo import GrimoireRepo

try:
    __version__ = version("grimoire")
except PackageNotFoundError:
    from grimoire.get_version import _get_version_from_pyproject
    __version__ = _get_version_from_pyproject()

__all__ = [
    "ArtifactNotFoundError",
    "CircularIncludeError",
    "ConjureEngine",
    "ConjureError",
    # Core types
    "ConjuredPrompt",
    # Exceptions
    "GrimoireError",
    "GrimoireManifest",
    "GrimoireRepo",
    "IncludeError",
    "ManifestError",
    "MessageBlock",
    "MessageRole",
    "MissingVariableError",
    "Promptlet",
    "Provenance",
    "RepoError",
    "Ritual",
    "RitualError",
    "RuneError",
    "RuneParseError",
    "RuneSpec",
    "RuneValidationError",
    "Spell",
    "SpellError",
    "SpellParseError",
    "SpellValidationError",
    "ValidationError",
    "VariableSpec",
    # Version
    "__version__",
    "parse_rune",
    "parse_rune_file",
    # Parsers
    "parse_spell",
    "parse_spell_file",
]
