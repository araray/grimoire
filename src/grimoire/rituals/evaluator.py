# src/grimoire/rituals/evaluator.py
"""
Ritual evaluator.

Provides two execution modes:

``dry_run(ritual)``
    Produces a :class:`RitualAssemblyPlan` describing what each step
    *would* do (which spell, which variables, which condition) without
    executing anything.  Useful for inspecting rituals and detecting
    missing spell references.

``evaluate(ritual, variables)``
    Executes each step sequentially:
    1. Evaluates the optional ``when`` condition against the current context.
    2. Builds the effective variable map for the step (inherited context +
       explicit overrides).
    3. Calls :class:`~grimoire.conjure.engine.ConjureEngine` to conjure
       the step's spell.
    4. Captures the conjured output into the context under the variable
       name specified by ``output.capture``.

Subsequent steps can reference previously captured variables in their
``when`` conditions, enabling conditional branching based on prior outputs.

``when`` condition syntax (safe — no ``eval()``)::

    "{{ var }}"                          # truthy check
    "{{ var.contains('substring') }}"    # substring test
    "{{ var.startswith('prefix') }}"     # prefix test
    "{{ var.endswith('suffix') }}"       # suffix test
    "{{ var == 'value' }}"               # equality
    "{{ var != 'value' }}"               # inequality
    "True" / "False"                     # literal booleans
"""

from __future__ import annotations

import logging
import re
from typing import Any

from grimoire.conjure.engine import ConjureEngine
from grimoire.exceptions import ArtifactNotFoundError, RitualError
from grimoire.models import (
    ConjuredPrompt,
    ConjuredRitualStep,
    Ritual,
    RitualAssemblyPlan,
    RitualStep,
    RitualStepPlan,
)
from grimoire.store.repo import GrimoireRepo

logger = logging.getLogger(__name__)

# ── When-condition regex patterns (safe — no eval) ────────────────────────────

_WHEN_EXPR_RE = re.compile(r"^\s*\{\{\s*(.*?)\s*\}\}\s*$")
_CONTAINS_RE = re.compile(r"^([a-zA-Z_]\w*)\.contains\(\s*['\"]([^'\"]*)['\"]s*\)\s*$")
_STARTSWITH_RE = re.compile(r"^([a-zA-Z_]\w*)\.startswith\(\s*['\"]([^'\"]*)['\"]s*\)\s*$")
_ENDSWITH_RE = re.compile(r"^([a-zA-Z_]\w*)\.endswith\(\s*['\"]([^'\"]*)['\"]s*\)\s*$")
_EQ_RE = re.compile(r"^([a-zA-Z_]\w*)\s*==\s*['\"]([^'\"]*)['\"]$")
_NEQ_RE = re.compile(r"^([a-zA-Z_]\w*)\s*!=\s*['\"]([^'\"]*)['\"]$")
_IDENT_RE = re.compile(r"^[a-zA-Z_]\w*$")

# Slightly more permissive contains/startswith/endswith (allows spaces before paren)
_METHOD_RE = re.compile(
    r"^([a-zA-Z_]\w*)\.(contains|startswith|endswith)\(\s*['\"]([^'\"]*)['\"]s*\)\s*$"
)


def _evaluate_condition(condition: str, context: dict[str, Any]) -> bool:
    """
    Safely evaluate a ritual step ``when`` condition string.

    Supported expressions (all enclosed in ``{{ ... }}`` or bare literals):
    - ``True`` / ``False`` — literal booleans
    - ``{{ var }}`` — truthy check on context variable
    - ``{{ var.contains("text") }}`` — substring test
    - ``{{ var.startswith("text") }}`` — prefix test
    - ``{{ var.endswith("text") }}`` — suffix test
    - ``{{ var == "value" }}`` — equality check
    - ``{{ var != "value" }}`` — inequality check

    Args:
        condition: The ``when`` expression string.
        context: The current variable context (ritual state).

    Returns:
        True if the condition passes (step should execute), False otherwise.
        Unknown/unparseable expressions are treated as True with a warning.
    """
    stripped = condition.strip()

    # Bare boolean literals
    if stripped in ("True", "true", "yes"):
        return True
    if stripped in ("False", "false", "no"):
        return False

    # Extract inner expression from {{ ... }}
    outer_match = _WHEN_EXPR_RE.match(stripped)
    if not outer_match:
        # No braces — treat as a plain variable name (truthy check)
        if _IDENT_RE.match(stripped):
            return bool(context.get(stripped))
        logger.warning("Unrecognised when condition (no {{ }}): %r — treating as True", condition)
        return True

    expr = outer_match.group(1).strip()

    # method calls: var.contains(...), var.startswith(...), var.endswith(...)
    method_m = _METHOD_RE.match(expr)
    if method_m:
        var_name, method, operand = method_m.group(1), method_m.group(2), method_m.group(3)
        var_val = str(context.get(var_name, ""))
        if method == "contains":
            return operand in var_val
        if method == "startswith":
            return var_val.startswith(operand)
        if method == "endswith":
            return var_val.endswith(operand)

    # equality: var == "value"
    eq_m = _EQ_RE.match(expr)
    if eq_m:
        var_val = str(context.get(eq_m.group(1), ""))
        return var_val == eq_m.group(2)

    # inequality: var != "value"
    neq_m = _NEQ_RE.match(expr)
    if neq_m:
        var_val = str(context.get(neq_m.group(1), ""))
        return var_val != neq_m.group(2)

    # plain identifier — truthy check
    if _IDENT_RE.match(expr):
        return bool(context.get(expr))

    logger.warning("Unrecognised when expression: %r — treating as True", expr)
    return True


def _extract_step_conjure_config(step: RitualStep) -> tuple[bool, dict[str, str], bool]:
    """
    Extract structured values from ``step.conjure`` dict.

    Returns:
        Tuple of (inherit_vars, explicit_vars, ask_missing).
    """
    conjure_cfg = step.conjure or {}
    vars_cfg = conjure_cfg.get("vars", {})

    if isinstance(vars_cfg, dict):
        inherit = bool(vars_cfg.get("inherit", True))
        explicit_vars: dict[str, str] = {k: str(v) for k, v in vars_cfg.items() if k != "inherit"}
    else:
        inherit = True
        explicit_vars = {}

    ask_missing = bool(conjure_cfg.get("ask_missing", False))
    return inherit, explicit_vars, ask_missing


def _extract_step_output_config(step: RitualStep) -> tuple[str | None, str]:
    """
    Extract output capture config from ``step.output`` dict.

    Returns:
        Tuple of (capture_var_name, output_format).
    """
    output_cfg = step.output or {}
    capture = output_cfg.get("capture")
    fmt = str(output_cfg.get("format", "text"))
    return (str(capture) if capture is not None else None), fmt


# ── Main evaluator ────────────────────────────────────────────────────────────


class RitualEvaluator:
    """
    Evaluates ritual flows: dry-run inspection and step-by-step conjuring.

    Args:
        repo: Loaded grimoire repository (used to look up spells).
        engine: Conjure engine instance.  If not provided, one is created
            from the repo's promptlets and runes.
    """

    def __init__(
        self,
        repo: GrimoireRepo,
        engine: ConjureEngine | None = None,
    ) -> None:
        self._repo = repo
        self._engine = engine or ConjureEngine(
            promptlets={p.id: p for p in repo.list_promptlets()},
            runes={r.id: r for r in repo.list_runes()},
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def dry_run(self, ritual: Ritual) -> RitualAssemblyPlan:
        """
        Produce an assembly plan without conjuring anything.

        Inspects each step to describe what would happen: which spell would
        be used, which variables are available, which condition gates it, and
        where the output would be captured.  Also reports any missing spell
        references so problems surface before execution.

        Args:
            ritual: The ritual to inspect.

        Returns:
            :class:`RitualAssemblyPlan` with one
            :class:`RitualStepPlan` per step.
        """
        step_plans: list[RitualStepPlan] = []
        missing_spells: list[str] = []

        for step in ritual.steps:
            inherit, explicit_vars, ask_missing = _extract_step_conjure_config(step)
            capture_var, output_fmt = _extract_step_output_config(step)

            spell_found = True
            if step.spell is not None:
                try:
                    self._repo.get_spell(step.spell)
                except ArtifactNotFoundError:
                    spell_found = False
                    missing_spells.append(step.spell)

            step_plans.append(
                RitualStepPlan(
                    step_id=step.id,
                    spell_id=step.spell,
                    spell_found=spell_found,
                    condition=step.when,
                    inherits_vars=inherit,
                    explicit_vars=explicit_vars,
                    ask_missing=ask_missing,
                    output_capture=capture_var,
                    output_format=output_fmt,
                    description=step.description,
                )
            )

        return RitualAssemblyPlan(
            ritual_id=ritual.id,
            ritual_name=ritual.name,
            steps=step_plans,
            missing_spells=missing_spells,
        )

    def evaluate(
        self,
        ritual: Ritual,
        variables: dict[str, Any] | None = None,
        defaults: dict[str, Any] | None = None,
    ) -> list[ConjuredRitualStep]:
        """
        Execute all ritual steps sequentially, conjuring each spell.

        Steps with a ``when`` condition are skipped when the condition
        evaluates to False.  Output from each step can be captured into the
        shared context under a named variable, making it available to
        subsequent steps' ``when`` conditions and variable expansions.

        Args:
            ritual: The ritual to evaluate.
            variables: Initial variable context (typically from CLI or caller).
            defaults: Default variable values from the repo.

        Returns:
            List of :class:`ConjuredRitualStep` — one per step (including
            skipped steps).

        Raises:
            RitualError: If a non-optional step references a missing spell.
        """
        # Initialise the mutable context that accumulates across steps
        context: dict[str, Any] = {}
        if defaults:
            context.update(defaults)
        if variables:
            context.update(variables)

        results: list[ConjuredRitualStep] = []

        for step in ritual.steps:
            result = self._evaluate_step(step, context)
            results.append(result)

            # Update context with captured output
            if result.captured_var is not None and result.captured_value is not None:
                context[result.captured_var] = result.captured_value

        return results

    # ── Private step execution ────────────────────────────────────────────────

    def _evaluate_step(
        self,
        step: RitualStep,
        context: dict[str, Any],
    ) -> ConjuredRitualStep:
        """Evaluate a single ritual step against the current context."""
        capture_var, output_fmt = _extract_step_output_config(step)
        inherit, explicit_vars, _ask_missing = _extract_step_conjure_config(step)

        # Check when condition
        if step.when is not None:
            if not _evaluate_condition(step.when, context):
                logger.debug("Step '%s' skipped: when=%r evaluated to False", step.id, step.when)
                return ConjuredRitualStep(
                    step_id=step.id,
                    spell_id=step.spell,
                    skipped=True,
                    skip_reason=f"when condition false: {step.when!r}",
                    conjured=None,
                    captured_var=capture_var,
                    captured_value=None,
                )

        # No spell declared — step is a no-op (e.g., a condition check only)
        if step.spell is None:
            logger.debug("Step '%s' has no spell — skipping conjure", step.id)
            return ConjuredRitualStep(
                step_id=step.id,
                spell_id=None,
                skipped=False,
                skip_reason=None,
                conjured=None,
                captured_var=capture_var,
                captured_value=None,
            )

        # Look up the spell
        try:
            spell = self._repo.get_spell(step.spell)
        except ArtifactNotFoundError as e:
            raise RitualError(
                f"Ritual step '{step.id}' references missing spell '{step.spell}': {e}"
            ) from e

        # Build effective variables for this step
        step_vars: dict[str, Any] = {}
        if inherit:
            step_vars.update(context)
        step_vars.update(explicit_vars)

        # Conjure the spell
        conjured: ConjuredPrompt = self._engine.conjure(
            spell=spell,
            variables=step_vars,
            strict=True,
        )

        # Determine captured output
        captured_value: str | None = None
        if capture_var is not None:
            if output_fmt == "messages":
                import json

                captured_value = json.dumps(conjured.to_messages("openai"))
            else:
                captured_value = conjured.to_text()

        logger.debug(
            "Step '%s' conjured spell '%s'%s",
            step.id,
            step.spell,
            f"; captured → {capture_var!r}" if capture_var else "",
        )

        return ConjuredRitualStep(
            step_id=step.id,
            spell_id=step.spell,
            skipped=False,
            skip_reason=None,
            conjured=conjured,
            captured_var=capture_var,
            captured_value=captured_value,
        )
