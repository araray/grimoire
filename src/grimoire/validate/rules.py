# src/grimoire/validate/rules.py
"""
Validation rules for grimoire artifacts.

Provides structural and semantic validation beyond what Pydantic handles.
Returns lists of diagnostic messages (warnings + errors) rather than
raising exceptions, so callers can display all issues at once.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

from grimoire.models import RuneSpec, Spell
from grimoire.store.repo import GrimoireRepo

logger = logging.getLogger(__name__)


class Severity(str, Enum):
    """Diagnostic severity levels."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class Diagnostic:
    """A single validation finding."""

    severity: Severity
    message: str
    artifact_id: str | None = None
    field: str | None = None


@dataclass
class ValidationResult:
    """Aggregated validation result."""

    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True if no errors (warnings are acceptable)."""
        return not any(d.severity == Severity.ERROR for d in self.diagnostics)

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == Severity.ERROR]

    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == Severity.WARNING]

    def add(self, severity: Severity, message: str, **kwargs: object) -> None:
        self.diagnostics.append(Diagnostic(severity=severity, message=message, **kwargs))


def validate_spell(spell: Spell) -> ValidationResult:
    """
    Validate a spell beyond Pydantic structural checks.

    Rules:
        - Must have at least one message block.
        - ID should follow slash-separated convention.
        - Required variables without defaults should have ``ask`` text.
        - Engineering spells should include assumption/failure-mode references.
    """
    result = ValidationResult()

    # Must have blocks
    if not spell.raw_blocks:
        result.add(Severity.ERROR, "Spell has no message blocks", artifact_id=spell.id)

    # ID convention
    if "/" not in spell.id:
        result.add(
            Severity.WARNING,
            f"Spell id '{spell.id}' should use slash-separated paths (e.g. 'category/name')",
            artifact_id=spell.id,
        )

    # Required variables should have interactive prompt text
    for name, spec in spell.required_variables().items():
        if not spec.ask:
            result.add(
                Severity.WARNING,
                f"Required variable '{name}' has no 'ask' prompt for interactive fill",
                artifact_id=spell.id,
                field=f"variables.{name}",
            )

    # Engineering spell lint (spec §13)
    if "engineering" in spell.tags:
        full_text = " ".join(b.content.lower() for b in spell.raw_blocks)
        if "assumption" not in full_text:
            result.add(
                Severity.WARNING,
                "Engineering spell should mention assumptions",
                artifact_id=spell.id,
            )
        if "failure" not in full_text and "edge case" not in full_text:
            result.add(
                Severity.WARNING,
                "Engineering spell should mention failure modes or edge cases",
                artifact_id=spell.id,
            )

    return result


def validate_rune(rune: RuneSpec) -> ValidationResult:
    """
    Validate a rune contract.

    Rules:
        - Must have at least one command.
        - Commands should have summaries.
        - High-risk commands should require approval.
    """
    result = ValidationResult()

    if not rune.commands:
        result.add(Severity.WARNING, "Rune has no commands", artifact_id=rune.id)

    for cmd in rune.commands:
        if not cmd.summary:
            result.add(
                Severity.WARNING,
                f"Command '{cmd.name}' has no summary",
                artifact_id=rune.id,
                field=f"commands.{cmd.name}",
            )

        # High-risk commands should require approval
        effective_risk = cmd.risk_level or rune.risk_level
        if (
            effective_risk in ("high", "medium")
            and not cmd.requires_approval
            and not rune.requires_approval
        ):
            result.add(
                Severity.WARNING,
                f"Command '{cmd.name}' has risk_level={effective_risk.value} but requires_approval is False",
                artifact_id=rune.id,
                field=f"commands.{cmd.name}",
            )

    return result


def validate_repo(repo: GrimoireRepo) -> ValidationResult:
    """
    Validate an entire grimoire repository.

    Checks:
        - All spells and runes pass individual validation.
        - Spell rune dependencies resolve.
        - No dangling include references (best-effort).
    """
    result = ValidationResult()

    # Validate each spell
    for spell in repo.list_spells():
        spell_result = validate_spell(spell)
        result.diagnostics.extend(spell_result.diagnostics)

        # Check rune dependencies
        for rune_id in spell.requires_runes:
            try:
                repo.get_rune(rune_id)
            except Exception:
                result.add(
                    Severity.ERROR,
                    f"Spell '{spell.id}' requires rune '{rune_id}' which is not found",
                    artifact_id=spell.id,
                )

        for rune_id in spell.suggests_runes:
            try:
                repo.get_rune(rune_id)
            except Exception:
                result.add(
                    Severity.WARNING,
                    f"Spell '{spell.id}' suggests rune '{rune_id}' which is not found",
                    artifact_id=spell.id,
                )

    # Validate each rune
    for rune in repo.list_runes():
        rune_result = validate_rune(rune)
        result.diagnostics.extend(rune_result.diagnostics)

    # Validate each ritual (Phase 3)
    from grimoire.rituals.validator import validate_ritual

    for ritual in repo.list_rituals():
        ritual_diags = validate_ritual(ritual, repo=repo)
        result.diagnostics.extend(ritual_diags)

    return result
