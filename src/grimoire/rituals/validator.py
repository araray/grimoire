# src/grimoire/rituals/validator.py
"""
Validation rules for ritual artifacts.

Validates ritual structure and semantic correctness beyond what Pydantic
handles.  Returns :class:`~grimoire.validate.rules.Diagnostic` lists rather
than raising exceptions so that all problems surface at once.

Checks performed:
- All referenced spell IDs exist in the repository.
- All step IDs are unique within the ritual.
- ``when`` conditions use recognised syntax.
- ``output.capture`` names are valid Python identifiers.
- ``output.format`` is a recognised value.
"""

from __future__ import annotations

import logging
import re

from grimoire.exceptions import ArtifactNotFoundError
from grimoire.models import Ritual
from grimoire.store.repo import GrimoireRepo
from grimoire.validate.rules import Diagnostic, Severity

logger = logging.getLogger(__name__)

# Valid output format values
_VALID_OUTPUT_FORMATS = {"text", "messages"}

# Valid Python identifier pattern (for capture variable names)
_IDENT_RE = re.compile(r"^[a-zA-Z_]\w*$")

# Recognised when condition patterns (for syntax warnings)
_WHEN_BARE_BOOL_RE = re.compile(r"^(True|False|true|false|yes|no)$")
_WHEN_BRACE_RE = re.compile(r"^\s*\{\{.*\}\}\s*$")


def validate_ritual(ritual: Ritual, repo: GrimoireRepo | None = None) -> list[Diagnostic]:
    """
    Validate a ritual's structure and, if a repo is provided, its references.

    Args:
        ritual: The ritual to validate.
        repo: Loaded grimoire repository used to check spell references.
              If None, reference checks are skipped.

    Returns:
        List of :class:`~grimoire.validate.rules.Diagnostic` findings.
        Empty list means the ritual is valid.
    """
    diags: list[Diagnostic] = []

    # ID convention: should be namespaced (contain a '/')
    if "/" not in ritual.id:
        diags.append(
            Diagnostic(
                severity=Severity.WARNING,
                message=(
                    f"Ritual id '{ritual.id}' is not namespaced (recommended: 'namespace/name')"
                ),
                artifact_id=ritual.id,
                field="id",
            )
        )

    # Step IDs must be unique
    seen_step_ids: set[str] = set()
    for step in ritual.steps:
        if step.id in seen_step_ids:
            diags.append(
                Diagnostic(
                    severity=Severity.ERROR,
                    message=f"Duplicate step id '{step.id}' in ritual '{ritual.id}'",
                    artifact_id=ritual.id,
                    field="steps",
                )
            )
        seen_step_ids.add(step.id)

    for step in ritual.steps:
        # Spell reference check
        if step.spell is not None and repo is not None:
            try:
                repo.get_spell(step.spell)
            except ArtifactNotFoundError:
                diags.append(
                    Diagnostic(
                        severity=Severity.ERROR,
                        message=(
                            f"Step '{step.id}' references unknown spell '{step.spell}' "
                            f"(ritual: '{ritual.id}')"
                        ),
                        artifact_id=ritual.id,
                        field=f"steps[{step.id}].spell",
                    )
                )

        # when condition syntax check
        if step.when is not None:
            stripped = step.when.strip()
            if (
                not _WHEN_BARE_BOOL_RE.match(stripped)
                and not _WHEN_BRACE_RE.match(stripped)
                and not _IDENT_RE.match(stripped)
            ):
                diags.append(
                    Diagnostic(
                        severity=Severity.WARNING,
                        message=(
                            f"Step '{step.id}' has an unrecognised 'when' syntax: "
                            f"{step.when!r}. "
                            "Expected: boolean literal, bare identifier, or "
                            "{{ expr }} (e.g. {{ var.contains('text') }})"
                        ),
                        artifact_id=ritual.id,
                        field=f"steps[{step.id}].when",
                    )
                )

        # output.capture must be a valid identifier
        output_cfg = step.output or {}
        capture = output_cfg.get("capture")
        if capture is not None and not _IDENT_RE.match(str(capture)):
            diags.append(
                Diagnostic(
                    severity=Severity.ERROR,
                    message=(
                        f"Step '{step.id}' output.capture '{capture}' is not a valid "
                        "Python identifier"
                    ),
                    artifact_id=ritual.id,
                    field=f"steps[{step.id}].output.capture",
                )
            )

        # output.format must be recognised
        fmt = output_cfg.get("format")
        if fmt is not None and str(fmt) not in _VALID_OUTPUT_FORMATS:
            diags.append(
                Diagnostic(
                    severity=Severity.WARNING,
                    message=(
                        f"Step '{step.id}' output.format '{fmt}' is not recognised. "
                        f"Known values: {sorted(_VALID_OUTPUT_FORMATS)}"
                    ),
                    artifact_id=ritual.id,
                    field=f"steps[{step.id}].output.format",
                )
            )

    return diags
