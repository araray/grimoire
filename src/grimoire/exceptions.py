# src/grimoire/exceptions.py
"""
Exception hierarchy for Grimoire.

Design: single module, flat hierarchy rooted at GrimoireError.
Each subsystem gets a specific subclass for targeted catching.
"""


class GrimoireError(Exception):
    """Base exception for all Grimoire errors."""


# ── Store / Repo ────────────────────────────────────────────────────────────


class RepoError(GrimoireError):
    """Error related to grimoire repository operations."""


class ManifestError(RepoError):
    """Error parsing or validating grimoire.yaml manifest."""


class ArtifactNotFoundError(RepoError):
    """A referenced spell, rune, ritual, or promptlet was not found."""


class AmbiguousArtifactError(RepoError):
    """An artifact ID matches multiple artifact types."""


# ── Spell parsing ───────────────────────────────────────────────────────────


class SpellError(GrimoireError):
    """Error parsing or validating a spell."""


class SpellParseError(SpellError):
    """Error parsing spell file format (frontmatter, blocks, etc.)."""


class SpellValidationError(SpellError):
    """Spell parsed but fails semantic validation."""


# ── Rune parsing ────────────────────────────────────────────────────────────


class RuneError(GrimoireError):
    """Error parsing or validating a rune."""


class RuneParseError(RuneError):
    """Error parsing rune YAML file."""


class RuneValidationError(RuneError):
    """Rune parsed but fails semantic validation."""


# ── Conjure (rendering) ────────────────────────────────────────────────────


class ConjureError(GrimoireError):
    """Error during spell/ritual conjuring (rendering)."""


class MissingVariableError(ConjureError):
    """A required variable was not provided and has no default."""


class IncludeError(ConjureError):
    """Error resolving an include() directive."""


class CircularIncludeError(IncludeError):
    """Include directives form a cycle."""


# ── Ritual ──────────────────────────────────────────────────────────────────


class RitualError(GrimoireError):
    """Error parsing or evaluating a ritual."""


class RitualParseError(RitualError):
    """Error parsing ritual YAML file."""


class RitualValidationError(RitualError):
    """Ritual parsed but fails semantic validation."""


# ── Validation ──────────────────────────────────────────────────────────────


class ValidationError(GrimoireError):
    """Schema or lint validation failure."""


# ── Bundle (Phase 4) ─────────────────────────────────────────────────────────


class BundleError(GrimoireError):
    """Error parsing or assembling a bundle."""


class BundleParseError(BundleError):
    """Error parsing bundle YAML file."""


class BundleValidationError(BundleError):
    """Bundle parsed but fails semantic validation."""


class BundleAssemblyError(BundleError):
    """Error during bundle assembly (missing spell, bad inject, etc.)."""


# ── SkillDoc (Phase 7) ───────────────────────────────────────────────────────


class SkillDocError(GrimoireError):
    """Error parsing or selecting from a SkillDoc."""


class SkillDocParseError(SkillDocError):
    """Error parsing SkillDoc markdown/frontmatter."""


# ── Sync (Phase 6) ───────────────────────────────────────────────────────────


class SyncError(GrimoireError):
    """Error during sync/drift detection operation."""
