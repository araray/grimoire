# src/grimoire/__init__.py
"""
Grimoire — prompt & tool control plane for the llmcore ecosystem.

Manage spells (prompt templates), runes (skill contracts), and rituals
(multi-step flows). Conjure prompts on-the-fly, bind to runtime targets.
"""

from importlib.metadata import PackageNotFoundError, version

from grimoire.bind import (
    Binder,
    BindResult,
    BindTarget,
    LLMCoreBinder,
    SemantiscanBinder,
    WairuBinder,
)
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
    RitualParseError,
    RitualValidationError,
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
    ConjuredRitualStep,
    GrimoireManifest,
    MessageBlock,
    MessageRole,
    Promptlet,
    Provenance,
    Ritual,
    RitualAssemblyPlan,
    RitualStep,
    RitualStepPlan,
    RuneSpec,
    Spell,
    VariableSensitivity,
    VariableSpec,
    VariableType,
)
from grimoire.rituals import parse_ritual, parse_ritual_file
from grimoire.rituals.evaluator import RitualEvaluator
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
    # Bind
    "BindResult",
    "BindTarget",
    "Binder",
    "CircularIncludeError",
    "ConjureEngine",
    "ConjureError",
    # Core types
    "ConjuredPrompt",
    "ConjuredRitualStep",
    # Exceptions
    "GrimoireError",
    "GrimoireManifest",
    "GrimoireRepo",
    "IncludeError",
    "LLMCoreBinder",
    "ManifestError",
    "MessageBlock",
    "MessageRole",
    "MissingVariableError",
    "Promptlet",
    "Provenance",
    "RepoError",
    "Ritual",
    "RitualAssemblyPlan",
    "RitualError",
    "RitualEvaluator",
    "RitualParseError",
    "RitualStep",
    "RitualStepPlan",
    "RitualValidationError",
    "RuneError",
    "RuneParseError",
    "RuneSpec",
    "RuneValidationError",
    "SemantiscanBinder",
    "Spell",
    "SpellError",
    "SpellParseError",
    "SpellValidationError",
    "ValidationError",
    "VariableSensitivity",
    "VariableSpec",
    "VariableType",
    "WairuBinder",
    # Version
    "__version__",
    "parse_ritual",
    "parse_ritual_file",
    "parse_rune",
    "parse_rune_file",
    # Parsers
    "parse_spell",
    "parse_spell_file",
]
