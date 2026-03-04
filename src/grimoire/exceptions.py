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


# ── Validation ──────────────────────────────────────────────────────────────

class ValidationError(GrimoireError):
    """Schema or lint validation failure."""
