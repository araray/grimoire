# src/grimoire/__init__.py
"""
Grimoire — prompt & tool control plane for the llmcore ecosystem.

Manage spells (prompt templates), runes (skill contracts), and rituals
(multi-step flows). Conjure prompts on-the-fly, bind to runtime targets.
"""

from importlib.metadata import PackageNotFoundError, version

from grimoire.api import Grimoire
from grimoire.bind import (
    Binder,
    BindResult,
    BindTarget,
    LLMCoreBinder,
    SemantiscanBinder,
    WairuBinder,
)
from grimoire.bundles import parse_bundle, parse_bundle_file
from grimoire.bundles.assembler import BundleAssembler
from grimoire.conjure.engine import ConjureEngine
from grimoire.exceptions import (
    AmbiguousArtifactError,
    ArtifactNotFoundError,
    BundleAssemblyError,
    BundleError,
    BundleParseError,
    BundleValidationError,
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
    SkillDocError,
    SkillDocParseError,
    SpellError,
    SpellParseError,
    SpellValidationError,
    SyncError,
    ValidationError,
)
from grimoire.layered import GrimoireLayer, LayeredGrimoire
from grimoire.models import (
    BlueprintParticipant,
    BlueprintStatus,
    Bundle,
    BundleInject,
    BundleVariant,
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
    SemanticBlueprint,
    SemanticRole,
    SkillDoc,
    SkillDocSection,
    Spell,
    VariableSensitivity,
    VariableSpec,
    VariableType,
)
from grimoire.procedural import (
    IntentMatch,
    ProceduralIndexer,
    ProceduralRetriever,
    build_spell_index_document,
    find_spells_by_intent_linear,
)
from grimoire.rituals import parse_ritual, parse_ritual_file
from grimoire.rituals.evaluator import RitualEvaluator
from grimoire.runes.parser import parse_rune, parse_rune_file
from grimoire.skilldocs import SkillDocSelector, parse_skilldoc, parse_skilldoc_file
from grimoire.spells.parser import parse_spell, parse_spell_file, serialize_spell
from grimoire.store.repo import GrimoireRepo
from grimoire.sync import DriftReport, LLMCoreSyncer, SemantiscanSyncer, SyncResult, WairuSyncer

try:
    __version__ = version("grimoire")
except PackageNotFoundError:
    from grimoire.get_version import _get_version_from_pyproject

    __version__ = _get_version_from_pyproject()

__all__ = [
    "AmbiguousArtifactError",
    "ArtifactNotFoundError",
    "BindResult",
    "BindTarget",
    "Binder",
    "BlueprintParticipant",
    "BlueprintStatus",
    "Bundle",
    "BundleAssembler",
    "BundleAssemblyError",
    "BundleError",
    "BundleInject",
    "BundleParseError",
    "BundleValidationError",
    "BundleVariant",
    "CircularIncludeError",
    "ConjureEngine",
    "ConjureError",
    "ConjuredPrompt",
    "ConjuredRitualStep",
    "DriftReport",
    "Grimoire",
    "GrimoireError",
    "GrimoireLayer",
    "GrimoireManifest",
    "GrimoireRepo",
    "IncludeError",
    "IntentMatch",
    "LLMCoreBinder",
    "LLMCoreSyncer",
    "LayeredGrimoire",
    "ManifestError",
    "MessageBlock",
    "MessageRole",
    "MissingVariableError",
    "ProceduralIndexer",
    "ProceduralRetriever",
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
    "SemanticBlueprint",
    "SemanticRole",
    "SemantiscanBinder",
    "SemantiscanSyncer",
    "SkillDoc",
    "SkillDocError",
    "SkillDocParseError",
    "SkillDocSection",
    "SkillDocSelector",
    "Spell",
    "SpellError",
    "SpellParseError",
    "SpellValidationError",
    "SyncError",
    "SyncResult",
    "ValidationError",
    "VariableSensitivity",
    "VariableSpec",
    "VariableType",
    "WairuBinder",
    "WairuSyncer",
    "__version__",
    "build_spell_index_document",
    "find_spells_by_intent_linear",
    "parse_bundle",
    "parse_bundle_file",
    "parse_ritual",
    "parse_ritual_file",
    "parse_rune",
    "parse_rune_file",
    "parse_skilldoc",
    "parse_skilldoc_file",
    "parse_spell",
    "parse_spell_file",
    "serialize_spell",
]
