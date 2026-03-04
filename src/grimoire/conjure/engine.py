# src/grimoire/conjure/engine.py
"""
Conjure engine — deterministic spell rendering.

Implements the Jinja-like subset specified in spec §6.2:
    - ``{{ var_name }}`` — variable substitution
    - ``{{ var|default("...") }}`` — variable with fallback
    - ``{{ include("path/or/id") }}`` — promptlet inclusion
    - ``{{{{`` / ``}}}}`` — literal brace escapes

Variable resolution follows the precedence in spec §9.1:
    1. Explicit overrides (CLI --set)
    2. vars file (--vars)
    3. profile overlays
    4. grimoire defaults (vars/defaults.yaml)
    5. spell defaults
    6. built-ins (grimoire.now.*, etc.)

The engine is stateless per-call: all context is passed in, ensuring
deterministic output (same inputs → same output).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from grimoire.exceptions import (
    CircularIncludeError,
    IncludeError,
    MissingVariableError,
)
from grimoire.models import (
    ConjuredPrompt,
    MessageBlock,
    Promptlet,
    Provenance,
    RuneSpec,
    Spell,
)

logger = logging.getLogger(__name__)

# Maximum include depth to prevent infinite recursion
_MAX_INCLUDE_DEPTH = 16

# ── Regex patterns ──────────────────────────────────────────────────────────

# Escaped braces: {{{{ → {{ (literal)
_ESCAPE_OPEN = re.compile(r"\{\{\{\{")
_ESCAPE_CLOSE = re.compile(r"\}\}\}\}")

# Include directive: {{ include("path/to/promptlet") }}
_INCLUDE_RE = re.compile(
    r"\{\{\s*include\(\s*[\"']([^\"']+)[\"']\s*\)\s*\}\}"
)

# Variable with default: {{ var|default("value") }} or {{ var|default(value) }}
_VAR_DEFAULT_RE = re.compile(
    r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_.]*)\s*\|\s*default\(\s*[\"']?([^\"')]*)[\"']?\s*\)\s*\}\}"
)

# Plain variable: {{ var_name }}
_VAR_RE = re.compile(
    r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_.]*)\s*\}\}"
)

# Rune introspection calls (Phase 0: rendered as text descriptions)
_RUNE_LIST_RE = re.compile(
    r"\{\{\s*runes\.list\(\s*tags\s*=\s*\[([^\]]*)\]\s*\)\s*\}\}"
)
_RUNE_DESCRIBE_RE = re.compile(
    r"\{\{\s*runes\.describe\(\s*[\"']([^\"']+)[\"']\s*\)\s*\}\}"
)
_RUNE_CMD_SIG_RE = re.compile(
    r"\{\{\s*runes\.command\(\s*[\"']([^\"']+)[\"']\s*,\s*[\"']([^\"']+)[\"']\s*\)\.signature\s*\}\}"
)


class ConjureEngine:
    """
    Deterministic spell rendering engine.

    Usage::

        engine = ConjureEngine(
            promptlets={"safety/base": Promptlet(...)},
            runes={"devtools/git": RuneSpec(...)},
        )
        result = engine.conjure(spell, variables={"issue_title": "Bug"})
    """

    def __init__(
        self,
        promptlets: dict[str, Promptlet] | None = None,
        runes: dict[str, RuneSpec] | None = None,
    ) -> None:
        self._promptlets: dict[str, Promptlet] = promptlets or {}
        self._runes: dict[str, RuneSpec] = runes or {}

    # ── Public API ──────────────────────────────────────────────────────────

    def conjure(
        self,
        spell: Spell,
        variables: dict[str, Any] | None = None,
        defaults: dict[str, Any] | None = None,
        strict: bool = True,
    ) -> ConjuredPrompt:
        """
        Render a spell into a ConjuredPrompt.

        Args:
            spell: The spell to conjure.
            variables: Explicit variable values (highest precedence).
            defaults: Default variable values (lowest precedence, from grimoire defaults).
            strict: If True, raise on missing required variables.
                    If False, leave placeholders unreplaced.

        Returns:
            ConjuredPrompt with rendered blocks and provenance.

        Raises:
            MissingVariableError: If strict and a required variable is missing.
            IncludeError: If an include() cannot be resolved.
            CircularIncludeError: If includes form a cycle.
        """
        # Build effective variable map (precedence: explicit > defaults > spell defaults > builtins)
        effective_vars = self._build_var_map(spell, variables, defaults)

        # Track provenance
        includes_resolved: list[str] = []
        runes_referenced: list[str] = []

        # Render each block
        rendered_blocks: list[MessageBlock] = []
        for block in spell.raw_blocks:
            content = self._render_template(
                template=block.content,
                variables=effective_vars,
                spell=spell,
                strict=strict,
                includes_resolved=includes_resolved,
                runes_referenced=runes_referenced,
            )
            rendered_blocks.append(MessageBlock(role=block.role, content=content))

        provenance = Provenance(
            spell_id=spell.id,
            spell_hash=spell.content_hash,
            variables_used={k: str(v) for k, v in effective_vars.items()
                           if not k.startswith("grimoire.")},
            includes_resolved=includes_resolved,
            runes_referenced=runes_referenced,
        )

        return ConjuredPrompt(blocks=rendered_blocks, provenance=provenance)

    # ── Variable resolution ─────────────────────────────────────────────────

    def _build_var_map(
        self,
        spell: Spell,
        variables: dict[str, Any] | None,
        defaults: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """
        Build the effective variable map with precedence:
            explicit > defaults_arg > spell_defaults > builtins
        """
        effective: dict[str, Any] = {}

        # Layer 1: Built-ins
        now = datetime.now(timezone.utc)
        effective["grimoire.now.iso"] = now.isoformat()
        effective["grimoire.now.date"] = now.strftime("%Y-%m-%d")
        effective["grimoire.now.time"] = now.strftime("%H:%M:%S")
        effective["grimoire.spell.id"] = spell.id
        effective["grimoire.spell.name"] = spell.name
        effective["grimoire.spell.version"] = spell.version

        # Layer 2: Spell defaults
        for name, spec in spell.variables.items():
            if spec.default is not None:
                effective[name] = spec.default

        # Layer 3: Grimoire defaults
        if defaults:
            effective.update(defaults)

        # Layer 4: Explicit variables (highest precedence)
        if variables:
            effective.update(variables)

        return effective

    # ── Template rendering ──────────────────────────────────────────────────

    def _render_template(
        self,
        template: str,
        variables: dict[str, Any],
        spell: Spell,
        strict: bool,
        includes_resolved: list[str],
        runes_referenced: list[str],
        _depth: int = 0,
        _include_stack: frozenset[str] | None = None,
    ) -> str:
        """
        Render a single template string.

        Processes in order:
            1. Escape sequences
            2. Include directives (recursive)
            3. Rune introspection
            4. Variable substitution
            5. Unescape
        """
        if _depth > _MAX_INCLUDE_DEPTH:
            raise CircularIncludeError(
                f"Include depth exceeded {_MAX_INCLUDE_DEPTH} — probable cycle"
            )

        if _include_stack is None:
            _include_stack = frozenset()

        result = template

        # Step 1: Replace escaped braces with placeholders
        result = _ESCAPE_OPEN.sub("\x00LBRACE\x00", result)
        result = _ESCAPE_CLOSE.sub("\x00RBRACE\x00", result)

        # Step 2: Resolve includes
        result = self._resolve_includes(
            result, variables, spell, strict,
            includes_resolved, runes_referenced,
            _depth, _include_stack,
        )

        # Step 3: Resolve rune introspection
        result = self._resolve_runes(result, runes_referenced)

        # Step 4: Resolve variables with defaults
        result = self._resolve_var_defaults(result, variables)

        # Step 5: Resolve plain variables
        result = self._resolve_vars(result, variables, spell, strict)

        # Step 6: Restore escaped braces
        result = result.replace("\x00LBRACE\x00", "{{")
        result = result.replace("\x00RBRACE\x00", "}}")

        return result

    def _resolve_includes(
        self,
        text: str,
        variables: dict[str, Any],
        spell: Spell,
        strict: bool,
        includes_resolved: list[str],
        runes_referenced: list[str],
        depth: int,
        include_stack: frozenset[str],
    ) -> str:
        """Resolve all include() directives in the text."""

        def _replace_include(match: re.Match) -> str:
            path = match.group(1)

            # Cycle detection
            if path in include_stack:
                raise CircularIncludeError(
                    f"Circular include detected: {path} (stack: {include_stack})"
                )

            # Look up promptlet
            promptlet = self._promptlets.get(path)
            if promptlet is None:
                # Try with "spells/promptlets/" prefix stripped if present
                stripped = path.removeprefix("spells/promptlets/")
                promptlet = self._promptlets.get(stripped)

            if promptlet is None:
                raise IncludeError(f"Promptlet not found: '{path}'")

            includes_resolved.append(path)

            # Recursively render the included content
            return self._render_template(
                template=promptlet.content,
                variables=variables,
                spell=spell,
                strict=strict,
                includes_resolved=includes_resolved,
                runes_referenced=runes_referenced,
                _depth=depth + 1,
                _include_stack=include_stack | {path},
            )

        return _INCLUDE_RE.sub(_replace_include, text)

    def _resolve_runes(
        self,
        text: str,
        runes_referenced: list[str],
    ) -> str:
        """Resolve rune introspection directives."""

        # runes.list(tags=[...])
        def _replace_rune_list(match: re.Match) -> str:
            tags_str = match.group(1)
            tags = [t.strip().strip("\"'") for t in tags_str.split(",") if t.strip()]
            tag_set = set(tags)

            matching = [
                r for r in self._runes.values()
                if tag_set.issubset(set(r.tags))
            ]
            if not matching:
                return "(no matching runes)"

            lines: list[str] = []
            for rune in sorted(matching, key=lambda r: r.id):
                runes_referenced.append(rune.id)
                cmds = ", ".join(c.name for c in rune.commands)
                lines.append(f"- **{rune.id}** ({rune.name}): {cmds}")
            return "\n".join(lines)

        text = _RUNE_LIST_RE.sub(_replace_rune_list, text)

        # runes.describe("id")
        def _replace_rune_describe(match: re.Match) -> str:
            rune_id = match.group(1)
            rune = self._runes.get(rune_id)
            if rune is None:
                return f"(rune '{rune_id}' not found)"
            runes_referenced.append(rune_id)
            lines = [f"**{rune.name}** (v{rune.version})"]
            if rune.description:
                lines.append(rune.description)
            lines.append(f"Risk: {rune.risk_level.value} | Permissions: {', '.join(p.value for p in rune.permissions)}")
            for cmd in rune.commands:
                params_str = ", ".join(f"{p.name}: {p.type}" for p in cmd.params)
                lines.append(f"  - `{cmd.name}({params_str})` — {cmd.summary or ''}")
            return "\n".join(lines)

        text = _RUNE_DESCRIBE_RE.sub(_replace_rune_describe, text)

        # runes.command("id", "cmd").signature
        def _replace_rune_cmd_sig(match: re.Match) -> str:
            rune_id = match.group(1)
            cmd_name = match.group(2)
            rune = self._runes.get(rune_id)
            if rune is None:
                return f"(rune '{rune_id}' not found)"
            cmd = rune.get_command(cmd_name)
            if cmd is None:
                return f"(command '{cmd_name}' not found in '{rune_id}')"
            runes_referenced.append(rune_id)
            params_str = ", ".join(f"{p.name}: {p.type}" for p in cmd.params)
            return f"{cmd.name}({params_str})"

        text = _RUNE_CMD_SIG_RE.sub(_replace_rune_cmd_sig, text)

        return text

    def _resolve_var_defaults(
        self,
        text: str,
        variables: dict[str, Any],
    ) -> str:
        """Resolve {{ var|default("fallback") }} patterns."""

        def _replace(match: re.Match) -> str:
            var_name = match.group(1)
            fallback = match.group(2)
            value = variables.get(var_name)
            if value is not None:
                return str(value)
            return fallback

        return _VAR_DEFAULT_RE.sub(_replace, text)

    def _resolve_vars(
        self,
        text: str,
        variables: dict[str, Any],
        spell: Spell,
        strict: bool,
    ) -> str:
        """Resolve {{ var_name }} patterns."""

        def _replace(match: re.Match) -> str:
            var_name = match.group(1)
            value = variables.get(var_name)
            if value is not None:
                return str(value)

            # Check if this is a required variable
            if strict and var_name in spell.variables:
                spec = spell.variables[var_name]
                if spec.required:
                    raise MissingVariableError(
                        f"Required variable '{var_name}' not provided "
                        f"(spell: {spell.id})"
                    )

            # Non-strict: leave placeholder as-is
            if not strict:
                return match.group(0)

            # Not in spell schema — might be a promptlet var, leave as-is
            if var_name not in spell.variables:
                logger.debug(f"Unknown variable '{var_name}' in spell '{spell.id}', leaving as-is")
                return match.group(0)

            return match.group(0)

        return _VAR_RE.sub(_replace, text)
