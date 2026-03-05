# src/grimoire/validate/rules.py
"""
Validation rules for grimoire artifacts.

Provides structural and semantic validation beyond what Pydantic handles.
Returns lists of diagnostic messages (warnings + errors) rather than
raising exceptions, so callers can display all issues at once.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from grimoire.models import Bundle, RuneSpec, SkillDoc, Spell, VariableSensitivity
from grimoire.store.repo import GrimoireRepo

logger = logging.getLogger(__name__)

# ── Sensitive variable name patterns ─────────────────────────────────────────
_SENSITIVE_NAME_PATTERNS = re.compile(
    r"(key|token|secret|password|passwd|api_key|access_key|private)", re.IGNORECASE
)

# Forbidden lint tokens (configurable; these are defaults)
_DEFAULT_FORBIDDEN_TOKENS = ["TODO", "FIXME", "PLACEHOLDER", "CHANGEME", "XXX"]


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

    # Validate each bundle (Phase 4)
    for bundle in repo.list_bundles():
        bundle_result = validate_bundle(bundle, repo)
        result.diagnostics.extend(bundle_result.diagnostics)

    # Validate each skilldoc (Phase 7)
    for skilldoc in repo.list_skilldocs():
        sd_result = validate_skilldoc(skilldoc)
        result.diagnostics.extend(sd_result.diagnostics)

    return result


# ── Bundle validation (Phase 4) ──────────────────────────────────────────────


def validate_bundle(bundle: Bundle, repo: GrimoireRepo | None = None) -> ValidationResult:
    """
    Validate a Bundle artifact.

    Rules:
        - Must have a non-empty ``base_template`` ID.
        - If ``repo`` is provided, the base_template spell must exist.
        - Variant IDs must be unique.
        - Inject promptlet IDs (if repo provided) should resolve.
    """
    result = ValidationResult()

    if not bundle.base_template:
        result.add(Severity.ERROR, "Bundle has no base_template", artifact_id=bundle.id)
        return result

    if repo is not None:
        try:
            repo.get_spell(bundle.base_template)
        except Exception:
            result.add(
                Severity.ERROR,
                f"Bundle '{bundle.id}': base_template '{bundle.base_template}' not found",
                artifact_id=bundle.id,
                field="base_template",
            )

    # Variant ID uniqueness
    variant_ids = [v.id for v in bundle.variants]
    if len(variant_ids) != len(set(variant_ids)):
        result.add(
            Severity.ERROR,
            "Bundle has duplicate variant IDs",
            artifact_id=bundle.id,
            field="variants",
        )

    # Check inject promptlet IDs
    if repo is not None and bundle.inject:
        all_inject_ids = (
            bundle.inject.system_prepend
            + bundle.inject.system_append
            + bundle.inject.user_prepend
            + bundle.inject.user_append
        )
        for pid in all_inject_ids:
            try:
                repo.get_promptlet(pid)
            except Exception:
                result.add(
                    Severity.WARNING,
                    f"Bundle '{bundle.id}': inject promptlet '{pid}' not found",
                    artifact_id=bundle.id,
                    field="inject",
                )

    return result


# ── SkillDoc validation (Phase 7) ─────────────────────────────────────────────


def validate_skilldoc(skilldoc: SkillDoc) -> ValidationResult:
    """
    Validate a SkillDoc artifact.

    Rules:
        - Must have at least one section.
        - Section IDs must be unique.
        - ID should follow slash-separated convention.
    """
    result = ValidationResult()

    if not skilldoc.sections:
        result.add(
            Severity.WARNING,
            "SkillDoc has no sections",
            artifact_id=skilldoc.id,
        )

    if "/" not in skilldoc.id:
        result.add(
            Severity.WARNING,
            f"SkillDoc id '{skilldoc.id}' should use slash-separated paths",
            artifact_id=skilldoc.id,
        )

    sec_ids = [s.id for s in skilldoc.sections]
    if len(sec_ids) != len(set(sec_ids)):
        result.add(
            Severity.ERROR,
            "SkillDoc has duplicate section IDs",
            artifact_id=skilldoc.id,
            field="sections",
        )

    return result


# ── Prompt lint (Phase 8) ─────────────────────────────────────────────────────


@dataclass
class LintConfig:
    """
    Configuration for prompt style linting rules.

    Loaded from ``grimoire.yaml`` under the ``lint:`` key, or used
    with default values.
    """

    # Maximum USER block length in characters (0 = no limit)
    max_user_block_chars: int = 0
    # Custom list of forbidden tokens (appended to defaults)
    forbidden_tokens: list[str] = field(default_factory=list)
    # Whether to check for engineering quality keywords
    check_engineering_quality: bool = True
    # Whether to warn on implicit secret variable names
    check_sensitivity: bool = True

    @classmethod
    def from_manifest_extra(cls, extra: dict[str, Any]) -> "LintConfig":
        """Parse lint config from the grimoire.yaml ``lint`` key."""
        lint_raw = extra.get("lint", {})
        if not isinstance(lint_raw, dict):
            return cls()
        return cls(
            max_user_block_chars=int(lint_raw.get("max_user_block_chars", 0)),
            forbidden_tokens=list(lint_raw.get("forbidden_tokens", [])),
            check_engineering_quality=bool(lint_raw.get("check_engineering_quality", True)),
            check_sensitivity=bool(lint_raw.get("check_sensitivity", True)),
        )


def validate_spell_style(spell: Spell, config: LintConfig | None = None) -> ValidationResult:
    """
    Lint a spell for style rule compliance (spec §8 Phase 8).

    Rules (configurable via ``LintConfig``):
        - No forbidden tokens (TODO, FIXME, PLACEHOLDER, …) in content.
        - Variable names must be snake_case (no camelCase).
        - Required variables should have ``ask`` text.
        - USER block must not exceed ``max_user_block_chars``.
        - Variables with secret-sounding names should have ``sensitivity=secret``.
        - Engineering spells should reference assumptions/failure-modes/validation.
    """
    config = config or LintConfig()
    result = ValidationResult()

    all_forbidden = _DEFAULT_FORBIDDEN_TOKENS + config.forbidden_tokens
    full_text = "\n".join(b.content for b in spell.raw_blocks)

    # Forbidden tokens
    for token in all_forbidden:
        if token in full_text:
            result.add(
                Severity.WARNING,
                f"Spell contains forbidden token '{token}'",
                artifact_id=spell.id,
            )

    # Variable naming: no camelCase
    _camel_re = re.compile(r"[a-z][A-Z]")
    for name in spell.variables:
        if _camel_re.search(name):
            result.add(
                Severity.WARNING,
                f"Variable '{name}' should use snake_case instead of camelCase",
                artifact_id=spell.id,
                field=f"variables.{name}",
            )

    # Required vars should have ask prompt
    for name, spec in spell.required_variables().items():
        if not spec.ask:
            result.add(
                Severity.INFO,
                f"Required variable '{name}' has no 'ask' prompt (needed for --ask-missing)",
                artifact_id=spell.id,
                field=f"variables.{name}",
            )

    # USER block length check
    if config.max_user_block_chars > 0:
        from grimoire.models import MessageRole
        for block in spell.raw_blocks:
            if block.role == MessageRole.USER and len(block.content) > config.max_user_block_chars:
                result.add(
                    Severity.WARNING,
                    f"USER block length ({len(block.content)}) exceeds max {config.max_user_block_chars}",
                    artifact_id=spell.id,
                )

    # Sensitivity check
    if config.check_sensitivity:
        for name, spec in spell.variables.items():
            if _SENSITIVE_NAME_PATTERNS.search(name):
                if spec.sensitivity == VariableSensitivity.PUBLIC:
                    result.add(
                        Severity.WARNING,
                        (
                            f"Variable '{name}' has a secret-sounding name but sensitivity=public; "
                            "consider setting sensitivity: secret"
                        ),
                        artifact_id=spell.id,
                        field=f"variables.{name}",
                    )

    # Engineering quality keywords
    if config.check_engineering_quality and "engineering" in spell.tags:
        lower_text = full_text.lower()
        for keyword in ("assumption", "failure mode", "validation", "edge case"):
            if keyword not in lower_text:
                result.add(
                    Severity.INFO,
                    f"Engineering spell should address '{keyword}'",
                    artifact_id=spell.id,
                )

    return result
