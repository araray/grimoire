# src/grimoire/api.py
"""
Grimoire Live-Bind API — single-entry-point facade for runtime consumption.

This module provides the ``Grimoire`` class, the primary interface for
runtimes (llmcore, semantiscan, wairu) that want to conjure prompts,
introspect variable schemas, generate tool definitions, and produce
in-memory bind results — all without disk-based export.

Spec references:
    - §10.2: Live-bind (library) operating mode
    - §12:   Library API specification
    - §12.3: Agent-friendly introspection

Architecture:
    ``Grimoire`` is a thin facade that wires together the existing lower-level
    components (``GrimoireRepo``, ``ConjureEngine``, ``BundleAssembler``,
    ``RitualEvaluator``, binders, validators).  It does not duplicate their
    logic — it orchestrates them behind a cohesive API that requires zero
    manual setup from the consumer.

Thread safety:
    A ``Grimoire`` instance is safe for concurrent reads (conjure, introspect,
    catalog).  It is *not* safe for concurrent mutation of the underlying repo.
    If the repo on disk changes, call ``Grimoire.reload()`` to pick up the
    new state.

Usage::

    from grimoire import Grimoire

    g = Grimoire("/path/to/repo")

    # Conjure a spell
    result = g.conjure("engineering/bug_root_cause", variables={"issue_title": "..."})
    messages = result.to_messages("openai")

    # Conjure a bundle with variant selection
    result = g.conjure("bundles/engineering/patch", context={"provider": "anthropic"})

    # Evaluate a ritual
    steps = g.conjure("rituals/rca_loop", variables={"issue_title": "..."})

    # Get tool schemas from runes
    tools = g.tool_schemas(tags=["devtools"])

    # In-memory bind
    bind_result = g.bind("llmcore", tags=["engineering"])

    # Introspection
    missing = g.missing_vars("engineering/bug_root_cause", provided={"issue_title": "x"})

    # Agent-friendly catalog
    catalog = g.catalog()

    # Procedural RAG / spell discovery
    matches = await g.find_by_intent("create a security threat model")
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from grimoire.bind.base import BindFormat, BindResult, BindTarget
from grimoire.bundles.assembler import BundleAssembler
from grimoire.conjure.engine import ConjureEngine
from grimoire.exceptions import ArtifactNotFoundError
from grimoire.models import (
    Bundle,
    ConjuredPrompt,
    ConjuredRitualStep,
    RiskLevel,
    Ritual,
    RuneSpec,
    SemanticRole,
    Spell,
    VariableSpec,
)
from grimoire.procedural import (
    IntentMatch,
    ProceduralSearchResult,
    ToolIntentMatch,
    find_spells_by_intent_linear,
    find_tools_by_intent_linear,
    normalize_procedural_results,
    spell_matches_filters,
    tool_matches_filters,
)
from grimoire.rituals.evaluator import RitualEvaluator
from grimoire.runes.schema import command_parameters_schema, command_to_openai_tool_schema
from grimoire.store.repo import GrimoireRepo
from grimoire.validate.rules import (
    LintConfig,
    ValidationResult,
    validate_repo,
    validate_spell_style,
)

logger = logging.getLogger(__name__)


# =============================================================================
# GRIMOIRE FACADE
# =============================================================================


class Grimoire:
    """
    High-level facade for programmatic grimoire access (live-bind mode).

    Loads a grimoire repository and provides a unified API for conjuring,
    introspection, tool-schema generation, in-memory binding, and validation.

    All heavy objects (repo, engine, assembler, evaluator) are lazily wired
    on first use after ``__init__``.

    Args:
        repo_path: Path to the grimoire root directory.  If ``None``,
                   defaults to the current working directory.
        strict: If ``True`` (default), conjuring raises on missing required
                variables.  If ``False``, leaves placeholders unreplaced.
        procedural_retriever: Optional Semantiscan-compatible retriever. If
                              absent, intent search uses an in-memory fallback.
        procedural_indexer: Optional Semantiscan-compatible indexer used by
                            ``rebuild_procedural_index``.
    """

    def __init__(
        self,
        repo_path: str | Path | None = None,
        *,
        strict: bool = True,
        procedural_retriever: Any | None = None,
        procedural_indexer: Any | None = None,
    ) -> None:
        path = Path(repo_path) if repo_path is not None else Path.cwd()
        self._layered: Any | None = None  # LayeredGrimoire when built via .layered()
        self._repo = GrimoireRepo.load(path)
        self._strict = strict
        self._procedural_retriever = procedural_retriever
        self._procedural_indexer = procedural_indexer
        self._engine = self._build_engine()
        self._assembler = BundleAssembler(self._repo)
        self._cache_generation = 0
        self._catalog_cache: tuple[int, dict[str, Any]] | None = None
        self._tool_schemas_cache: tuple[int, list[dict[str, Any]]] | None = None

    @classmethod
    def layered(
        cls,
        roots: Sequence[tuple[str, str | Path, bool]],
        *,
        strict: bool = True,
        load_strict: bool = True,
        scaffold_writable: bool = True,
        procedural_retriever: Any | None = None,
        procedural_indexer: Any | None = None,
    ) -> "Grimoire":
        """
        Build a Grimoire facade over ORDERED overlay layers (0.4.0).

        The composed view resolves every artifact type (spells, runes,
        promptlets, rituals, bundles, skilldocs, default vars) with
        deterministic precedence: **lowest → highest**, highest wins. This is
        the control-plane composition used by llmcore/wairu::

            g = Grimoire.layered([
                ("llmcore-builtin", llmcore_pack_path, False),
                ("wairu-core", wairu_pack_path, False),
                ("user", "~/.config/wairu/grimoire", True),
            ])

        Args:
            roots: Ordered ``(name, path, writable)`` triples, lowest →
                highest precedence.
            strict: Conjure strictness (missing required variables raise) —
                same meaning as the single-root constructor's ``strict``.
            load_strict: Load layers in strict repo mode — parse failures and
                duplicate ids inside a layer raise instead of log-and-skip
                (fail-loud; the default for control-plane use).
            scaffold_writable: Scaffold missing writable layer roots.
            procedural_retriever / procedural_indexer: As in ``__init__``.

        Returns:
            A layered ``Grimoire`` facade. Write APIs target the highest
            writable layer via the underlying :class:`LayeredGrimoire`.
        """
        from grimoire.layered import LayeredGrimoire

        layered = LayeredGrimoire.from_roots(
            roots, scaffold_writable=scaffold_writable, strict=load_strict
        )
        self = cls.__new__(cls)
        self._layered = layered
        self._repo = layered.composite_view()
        self._strict = strict
        self._procedural_retriever = procedural_retriever
        self._procedural_indexer = procedural_indexer
        self._engine = self._build_engine()
        self._assembler = BundleAssembler(self._repo)
        self._cache_generation = 0
        self._catalog_cache = None
        self._tool_schemas_cache = None
        return self

    # ── Internal wiring ─────────────────────────────────────────────────────

    def _build_engine(self) -> ConjureEngine:
        """Wire a ConjureEngine from the loaded repo's promptlets and runes."""
        return ConjureEngine(
            promptlets=dict(self._repo._promptlets),
            runes=dict(self._repo._runes),
        )

    # ── Reload ──────────────────────────────────────────────────────────────

    def reload(self) -> None:
        """
        Re-load the grimoire repo (or every layer) from disk.

        Call this after modifying files on disk to pick up changes.
        All internal caches (engine, assembler, catalog/tool-schema caches)
        are rebuilt. NOTE (layered mode): artifacts registered at runtime
        directly on the composed view (e.g. runtime runes) are dropped —
        callers own replaying them.
        """
        if self._layered is not None:
            self._layered.reload()
            self._repo = self._layered.composite_view()
        else:
            self._repo = GrimoireRepo.load(
                self._repo.root, writable=self._repo.writable, strict=self._repo.strict
            )
        self._engine = self._build_engine()
        self._assembler = BundleAssembler(self._repo)
        self.invalidate_caches()
        logger.info("Grimoire reloaded from %s", self._repo.root)

    def invalidate_caches(self) -> None:
        """Invalidate memoized catalog/tool-schema results (0.4.0).

        Called automatically by :meth:`reload`; call manually after mutating
        the repo in-memory (e.g. registering runtime runes) so cached
        catalog/tool listings never serve stale entries.
        """
        self._cache_generation += 1

    # ── Properties ──────────────────────────────────────────────────────────

    @property
    def repo(self) -> GrimoireRepo:
        """The underlying loaded repository (read-only access)."""
        return self._repo

    @property
    def name(self) -> str:
        """Grimoire manifest name."""
        return self._repo.manifest.name

    @property
    def version(self) -> str:
        """Grimoire manifest version."""
        return self._repo.manifest.version

    @property
    def layers(self) -> list[str] | None:
        """Layer names in ascending precedence, or ``None`` for single-root."""
        if self._layered is None:
            return None
        return [layer.name for layer in self._layered.layers]

    def resolve_layer(self, artifact_id: str, kind: str = "spell") -> str:
        """
        Name of the layer an artifact resolves from (layered mode).

        Args:
            artifact_id: The artifact id to locate.
            kind: ``spell`` (default) | ``rune`` | ``promptlet`` | ``ritual``
                | ``bundle`` | ``skilldoc``.

        Raises:
            RuntimeError: If this facade is not layered.
            ArtifactNotFoundError: If no layer defines the id.
        """
        if self._layered is None:
            raise RuntimeError("resolve_layer() requires a layered Grimoire (.layered(...))")
        return self._layered.resolve_layer(artifact_id, kind)

    # ── Conjure (polymorphic) ───────────────────────────────────────────────

    def conjure(
        self,
        artifact_id: str,
        *,
        variables: dict[str, Any] | None = None,
        defaults: dict[str, Any] | None = None,
        context: dict[str, str] | None = None,
        strict: bool | None = None,
    ) -> ConjuredPrompt | list[ConjuredRitualStep]:
        """
        Conjure (render) an artifact by ID.

        The method auto-detects the artifact type by looking up the ID across
        spells, bundles, and rituals (in that order).

        Args:
            artifact_id: A spell, bundle, or ritual ID.
            variables: Explicit variable values (highest precedence).
            defaults: Default variable values (lowest precedence).
                      If ``None``, uses the grimoire's ``vars/defaults.yaml``.
            context: Matching context for bundle variant selection
                     (e.g. ``{"provider": "anthropic"}``).
            strict: Override the instance-level strict setting for this call.

        Returns:
            ``ConjuredPrompt`` for spells and bundles.
            ``list[ConjuredRitualStep]`` for rituals.

        Raises:
            ArtifactNotFoundError: If the ID is not found in any artifact type.
            MissingVariableError: If strict and a required variable is missing.
            BundleAssemblyError: If bundle assembly fails.
            RitualError: If ritual evaluation fails.
        """
        effective_strict = strict if strict is not None else self._strict
        effective_defaults = defaults if defaults is not None else self._repo.default_vars

        # Try spell first (most common path)
        spell = self._repo._spells.get(artifact_id)
        if spell is not None:
            return self._conjure_spell(spell, variables, effective_defaults, effective_strict)

        # Try bundle
        bundle = self._repo._bundles.get(artifact_id)
        if bundle is not None:
            return self._conjure_bundle(
                bundle, variables, effective_defaults, context, effective_strict
            )

        # Try ritual
        ritual = self._repo._rituals.get(artifact_id)
        if ritual is not None:
            return self._conjure_ritual(ritual, variables, effective_defaults)

        raise ArtifactNotFoundError(
            f"Artifact not found: {artifact_id!r} (searched spells, bundles, rituals)"
        )

    def conjure_spell(
        self,
        spell_id: str,
        *,
        variables: dict[str, Any] | None = None,
        defaults: dict[str, Any] | None = None,
        strict: bool | None = None,
    ) -> ConjuredPrompt:
        """
        Conjure a specific spell by ID.

        Unlike the polymorphic ``conjure()``, this method is typed to always
        return a ``ConjuredPrompt`` and raises ``ArtifactNotFoundError`` if
        the ID is not a spell.

        Args:
            spell_id: The spell ID.
            variables: Explicit variable values.
            defaults: Default variable values (falls back to grimoire defaults).
            strict: Override instance-level strict setting.

        Returns:
            Rendered ConjuredPrompt.
        """
        spell = self._repo.get_spell(spell_id)
        effective_strict = strict if strict is not None else self._strict
        effective_defaults = defaults if defaults is not None else self._repo.default_vars
        return self._conjure_spell(spell, variables, effective_defaults, effective_strict)

    def conjure_bundle(
        self,
        bundle_id: str,
        *,
        variables: dict[str, Any] | None = None,
        defaults: dict[str, Any] | None = None,
        context: dict[str, str] | None = None,
        strict: bool | None = None,
    ) -> ConjuredPrompt:
        """
        Conjure a specific bundle by ID.

        Assembles the bundle into a synthetic spell (applying variant
        selection and promptlet injection), then conjures it.

        Args:
            bundle_id: The bundle ID.
            variables: Explicit variable values.
            defaults: Default variable values (falls back to grimoire defaults).
            context: Matching context for variant selection.
            strict: Override instance-level strict setting.

        Returns:
            Rendered ConjuredPrompt.
        """
        bundle = self._repo.get_bundle(bundle_id)
        effective_strict = strict if strict is not None else self._strict
        effective_defaults = defaults if defaults is not None else self._repo.default_vars
        return self._conjure_bundle(
            bundle, variables, effective_defaults, context, effective_strict
        )

    def conjure_ritual(
        self,
        ritual_id: str,
        *,
        variables: dict[str, Any] | None = None,
        defaults: dict[str, Any] | None = None,
    ) -> list[ConjuredRitualStep]:
        """
        Evaluate a ritual: conjure each step in sequence.

        Steps are executed sequentially; ``when`` conditions gate optional
        steps.  Output from each step flows into subsequent steps via
        context variable capture.

        Args:
            ritual_id: The ritual ID.
            variables: Explicit variable values.
            defaults: Default variable values (falls back to grimoire defaults).

        Returns:
            List of ConjuredRitualStep results.
        """
        ritual = self._repo.get_ritual(ritual_id)
        effective_defaults = defaults if defaults is not None else self._repo.default_vars
        return self._conjure_ritual(ritual, variables, effective_defaults)

    # ── Internal conjure helpers ────────────────────────────────────────────

    def _conjure_spell(
        self,
        spell: Spell,
        variables: dict[str, Any] | None,
        defaults: dict[str, Any],
        strict: bool,
    ) -> ConjuredPrompt:
        return self._engine.conjure(spell, variables=variables, defaults=defaults, strict=strict)

    def _conjure_bundle(
        self,
        bundle: Bundle,
        variables: dict[str, Any] | None,
        defaults: dict[str, Any],
        context: dict[str, str] | None,
        strict: bool,
    ) -> ConjuredPrompt:
        assembled_spell = self._assembler.assemble(bundle, context=context, variables=variables)
        return self._engine.conjure(
            assembled_spell, variables=variables, defaults=defaults, strict=strict
        )

    def _conjure_ritual(
        self,
        ritual: Ritual,
        variables: dict[str, Any] | None,
        defaults: dict[str, Any],
    ) -> list[ConjuredRitualStep]:
        evaluator = RitualEvaluator(self._repo, engine=self._engine)
        merged: dict[str, Any] = dict(defaults)
        if variables:
            merged.update(variables)
        return evaluator.evaluate(ritual, variables=merged)

    # ── Variable introspection ──────────────────────────────────────────────

    def spell_vars(self, spell_id: str) -> dict[str, VariableSpec]:
        """
        Return the full variable schema for a spell.

        Args:
            spell_id: The spell ID.

        Returns:
            Dict mapping variable name to its ``VariableSpec``.
        """
        spell = self._repo.get_spell(spell_id)
        return dict(spell.variables)

    def missing_vars(
        self,
        artifact_id: str,
        provided: dict[str, Any] | None = None,
    ) -> dict[str, VariableSpec]:
        """
        Identify which *required* variables are still missing.

        Checks spell defaults, grimoire defaults, and the ``provided`` dict.
        Returns only the variables that have no value from any source.

        Args:
            artifact_id: A spell or bundle ID.
            provided: Variables already supplied by the caller.

        Returns:
            Dict mapping each missing required variable name to its spec.

        Raises:
            ArtifactNotFoundError: If the artifact is not found.
        """
        provided = provided or {}
        repo_defaults = self._repo.default_vars

        # Resolve the variable schema
        spell = self._repo._spells.get(artifact_id)
        if spell is not None:
            var_schema = spell.variables
        else:
            bundle = self._repo._bundles.get(artifact_id)
            if bundle is not None:
                # Assemble to get merged variables
                assembled = self._assembler.assemble(bundle)
                var_schema = assembled.variables
            else:
                raise ArtifactNotFoundError(
                    f"Artifact not found for introspection: {artifact_id!r}"
                )

        missing: dict[str, VariableSpec] = {}
        for name, spec in var_schema.items():
            if not spec.required:
                continue
            # Check if any source provides a value
            if name in provided:
                continue
            if name in repo_defaults:
                continue
            if spec.default is not None:
                continue
            missing[name] = spec
        return missing

    # ── Tool schema generation ──────────────────────────────────────────────

    def tool_schemas(
        self,
        *,
        rune_ids: list[str] | None = None,
        tags: list[str] | None = None,
        schema_format: str = "openai",
    ) -> list[dict[str, Any]]:
        """
        Generate provider-compatible tool/function schemas from runes.

        Each rune command becomes one tool definition.

        Args:
            rune_ids: If given, only include these runes.
            tags: If given, filter runes by tags (AND logic).
            schema_format: Schema format — currently only ``"openai"`` is supported.

        Returns:
            List of tool definition dicts (OpenAI function-calling format).

        Raises:
            ValueError: If ``schema_format`` is unsupported.
        """
        if schema_format != "openai":
            raise ValueError(f"Unsupported tool schema format: {schema_format!r} (use 'openai')")

        # Fast path (0.4.0): memoize the unfiltered listing — the hot call for
        # tool inventories — keyed by the cache generation (reload/invalidate
        # bumps it). Filtered calls stay uncached (cheap + rarely hot).
        unfiltered = rune_ids is None and not tags
        if unfiltered and self._tool_schemas_cache is not None:
            gen, cached = self._tool_schemas_cache
            if gen == self._cache_generation:
                return cached

        # Select runes
        if rune_ids is not None:
            runes = []
            for rid in rune_ids:
                try:
                    runes.append(self._repo.get_rune(rid))
                except ArtifactNotFoundError:
                    logger.warning("tool_schemas: rune %r not found, skipping", rid)
        else:
            runes = self._repo.list_runes(tags=tags)

        result = _runes_to_openai_tools(runes)
        if unfiltered:
            self._tool_schemas_cache = (self._cache_generation, result)
        return result

    def to_mcp_tool_manifest(
        self,
        rune_id: str | None = None,
        *,
        rune_ids: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Return a JSON-safe MCP ``tools/list`` manifest for rune commands.

        Args:
            rune_id: Optional single rune ID to export.
            rune_ids: Optional list of rune IDs to export.
            tags: Optional tag filter used when no explicit rune IDs are given.

        Returns:
            Manifest with MCP ``tools`` entries and Grimoire metadata under
            ``_meta`` for later MCP server approval/routing decisions.

        Raises:
            ValueError: If both ``rune_id`` and ``rune_ids`` are supplied.
        """
        if rune_id is not None and rune_ids is not None:
            raise ValueError("Pass either rune_id or rune_ids, not both")

        selected_ids = [rune_id] if rune_id is not None else rune_ids
        if selected_ids is not None:
            runes = []
            for rid in selected_ids:
                try:
                    runes.append(self._repo.get_rune(rid))
                except ArtifactNotFoundError:
                    logger.warning("to_mcp_tool_manifest: rune %r not found, skipping", rid)
        else:
            runes = self._repo.list_runes(tags=tags)

        return _runes_to_mcp_tool_manifest(runes)

    # ── In-memory bind ──────────────────────────────────────────────────────

    def bind(
        self,
        target: str | BindTarget,
        *,
        fmt: str | BindFormat | None = None,
        spell_ids: list[str] | None = None,
        rune_ids: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> BindResult:
        """
        Produce in-memory bind artifacts for a runtime target.

        This is the live-bind equivalent of ``grimoire bind <target>``.
        Returns a ``BindResult`` with all produced files in memory —
        call ``result.write(path)`` to persist, or consume ``result.files``
        directly.

        Args:
            target: Runtime target — ``"llmcore"``, ``"semantiscan"``, or ``"wairu"``.
            fmt: Sub-format (e.g. ``"toml"``, ``"legacy_tmpl"``).
                 Uses the binder's default if ``None``.
            spell_ids: Bind only these spells.
            rune_ids: Bind only these runes.
            tags: Filter artifacts by tags.

        Returns:
            BindResult with files, metadata, and compiled_hash.
        """
        from grimoire.bind import LLMCoreBinder, SemantiscanBinder, WairuBinder

        if isinstance(target, str):
            target = BindTarget(target)

        binder_map = {
            BindTarget.LLMCORE: LLMCoreBinder,
            BindTarget.SEMANTISCAN: SemantiscanBinder,
            BindTarget.WAIRU: WairuBinder,
        }

        binder_cls = binder_map[target]
        binder = binder_cls()

        bind_fmt: BindFormat | None = None
        if fmt is not None:
            bind_fmt = BindFormat(fmt) if isinstance(fmt, str) else fmt

        result = binder.bind(
            self._repo,
            fmt=bind_fmt,
            spell_ids=spell_ids,
            rune_ids=rune_ids,
            tags=tags,
        )
        result.compute_hash()
        return result

    # ── Validation & lint ───────────────────────────────────────────────────

    def validate(self, *, layer: str | None = None) -> ValidationResult:
        """
        Run full structural validation on the grimoire repository.

        Checks all spells, runes, bundles, skilldocs, and cross-references.

        Args:
            layer: (Layered mode only) validate a SINGLE layer's repo in
                isolation — required for fail-loud startup checks, where a
                user overlay that merely shadows artifacts must still be
                validated on its own.

        Returns:
            ValidationResult with diagnostics.

        Raises:
            RuntimeError: If ``layer`` is given on a non-layered facade.
            ValueError: If ``layer`` names an unknown layer.
        """
        if layer is not None:
            if self._layered is None:
                raise RuntimeError("validate(layer=...) requires a layered Grimoire")
            return validate_repo(self._layered._layer(layer).repo)
        return validate_repo(self._repo)

    def lint(
        self,
        spell_id: str | None = None,
        *,
        config: LintConfig | None = None,
    ) -> ValidationResult:
        """
        Run style lint rules on spells.

        Args:
            spell_id: If given, lint only this spell.
                      If ``None``, lint all spells.
            config: Lint configuration overrides.

        Returns:
            Aggregated ValidationResult with all diagnostics.
        """
        if spell_id is not None:
            spell = self._repo.get_spell(spell_id)
            return validate_spell_style(spell, config)

        # Lint all spells
        all_diags: list = []
        for spell in self._repo.list_spells():
            result = validate_spell_style(spell, config)
            all_diags.extend(result.diagnostics)
        return ValidationResult(diagnostics=all_diags)

    # ── Catalog ─────────────────────────────────────────────────────────────

    def catalog(self) -> dict[str, Any]:
        """
        Return a JSON-serializable catalog of all artifacts.

        Suitable for agent introspection and LLM tool discovery.
        Delegates to ``GrimoireRepo.catalog()``; memoized per cache
        generation (see :meth:`invalidate_caches`).

        Returns:
            Dict with grimoire metadata, spells, runes, rituals, bundles,
            skilldocs, and promptlet listings.
        """
        if self._catalog_cache is not None:
            gen, cached = self._catalog_cache
            if gen == self._cache_generation:
                return cached
        result = self._repo.catalog()
        self._catalog_cache = (self._cache_generation, result)
        return result

    # ── Convenience accessors ───────────────────────────────────────────────

    def get_spell(self, spell_id: str) -> Spell:
        """Get a spell by ID."""
        return self._repo.get_spell(spell_id)

    def get_rune(self, rune_id: str) -> RuneSpec:
        """Get a rune by ID."""
        return self._repo.get_rune(rune_id)

    def get_bundle(self, bundle_id: str) -> Bundle:
        """Get a bundle by ID."""
        return self._repo.get_bundle(bundle_id)

    def get_ritual(self, ritual_id: str) -> Ritual:
        """Get a ritual by ID."""
        return self._repo.get_ritual(ritual_id)

    def list_spells(
        self, tags: list[str] | None = None, *, match: str = "all"
    ) -> list[Spell]:
        """List spells with optional tag filtering (``match`` = all|any)."""
        return self._repo.list_spells(tags=tags, match=match)

    def list_runes(
        self, tags: list[str] | None = None, *, match: str = "all"
    ) -> list[RuneSpec]:
        """List runes with optional tag filtering (``match`` = all|any)."""
        return self._repo.list_runes(tags=tags, match=match)

    def list_bundles(
        self, tags: list[str] | None = None, *, match: str = "all"
    ) -> list[Bundle]:
        """List bundles with optional tag filtering (``match`` = all|any)."""
        return self._repo.list_bundles(tags=tags, match=match)

    def list_rituals(
        self, tags: list[str] | None = None, *, match: str = "all"
    ) -> list[Ritual]:
        """List rituals with optional tag filtering (``match`` = all|any)."""
        return self._repo.list_rituals(tags=tags, match=match)

    # ── Tag vocabulary & search (WS-G3) ─────────────────────────────────────

    def list_tags(self, prefix: str | None = None) -> dict[str, int]:
        """Return the distinct spell-tag vocabulary with usage counts."""
        return self._repo.list_tags(prefix=prefix)

    def search_spells(
        self,
        query: str,
        *,
        fields: tuple[str, ...] = ("name", "description", "tags"),
    ) -> list[Spell]:
        """Case-insensitive substring search over spells."""
        return self._repo.search_spells(query, fields=fields)

    async def find_by_intent(
        self,
        query: str,
        *,
        top_k: int = 5,
        filter_domain: str | None = None,
        filter_semantic_role: SemanticRole | str | None = None,
        include_deprecated: bool = False,
    ) -> list[IntentMatch]:
        """Find spells by natural-language procedural intent.

        If a procedural retriever was supplied at construction time, Grimoire
        queries that retriever and resolves results back to loaded spells. If no
        retriever is configured, it uses a deterministic token-overlap fallback
        over the in-memory spell catalog.
        """
        if top_k <= 0:
            return []

        if self._procedural_retriever is None:
            return find_spells_by_intent_linear(
                query,
                self._repo.list_spells(),
                top_k=top_k,
                filter_domain=filter_domain,
                filter_semantic_role=filter_semantic_role,
                include_deprecated=include_deprecated,
            )

        raw_results = await _search_procedural_retriever(
            self._procedural_retriever,
            query,
            top_k=max(top_k * 4, top_k),
            filters=_intent_filters(
                filter_domain=filter_domain,
                filter_semantic_role=filter_semantic_role,
                include_deprecated=include_deprecated,
            ),
        )

        matches: list[IntentMatch] = []
        seen: set[str] = set()
        for result in raw_results:
            if result.spell_id in seen:
                continue
            spell = self._repo._spells.get(result.spell_id)
            if spell is None:
                continue
            if not spell_matches_filters(
                spell,
                filter_domain=filter_domain,
                filter_semantic_role=filter_semantic_role,
                include_deprecated=include_deprecated,
            ):
                continue
            seen.add(result.spell_id)
            matches.append(
                IntentMatch(
                    spell=spell,
                    score=result.score,
                    highlight=result.highlight or result.content[:240] or spell.effective_intent,
                )
            )

        return sorted(matches, key=lambda match: (-match.score, match.spell.id))[:top_k]

    async def rebuild_procedural_index(self) -> list[str]:
        """Re-index all loaded spells using the configured procedural indexer."""
        if self._procedural_indexer is None:
            raise RuntimeError(
                "rebuild_procedural_index requires procedural_indexer= at construction"
            )
        document_ids: list[str] = []
        if hasattr(self._procedural_indexer, "index_spells"):
            document_ids.extend(await self._procedural_indexer.index_spells(self._repo.list_spells()))
        else:
            for spell in self._repo.list_spells():
                document_ids.append(await self._procedural_indexer.index_spell(spell))

        if hasattr(self._procedural_indexer, "index_runes"):
            document_ids.extend(await self._procedural_indexer.index_runes(self._repo.list_runes()))
        return document_ids

    async def find_tools_by_intent(
        self,
        query: str,
        *,
        top_k: int = 5,
        tags: list[str] | None = None,
        max_risk: RiskLevel | str | None = None,
        include_requires_approval: bool = True,
    ) -> list[ToolIntentMatch]:
        """Find rune commands by natural-language capability intent."""
        if top_k <= 0:
            return []

        if self._procedural_retriever is None:
            return find_tools_by_intent_linear(
                query,
                self._repo.list_runes(),
                top_k=top_k,
                tags=tags,
                max_risk=max_risk,
                include_requires_approval=include_requires_approval,
            )

        raw_results = await _search_procedural_retriever(
            self._procedural_retriever,
            query,
            top_k=max(top_k * 4, top_k),
            filters=_tool_filters(tags=tags),
        )

        matches: list[ToolIntentMatch] = []
        seen: set[tuple[str, str]] = set()
        for result in raw_results:
            if result.artifact_type != "rune_command":
                continue
            key = (result.rune_id, result.command_name)
            if key in seen:
                continue
            rune = self._repo._runes.get(result.rune_id)
            if rune is None:
                continue
            command = rune.get_command(result.command_name)
            if command is None:
                continue
            if not tool_matches_filters(
                rune,
                command_name=command.name,
                tags=tags,
                max_risk=max_risk,
                include_requires_approval=include_requires_approval,
            ):
                continue
            seen.add(key)
            matches.append(
                ToolIntentMatch(
                    rune=rune,
                    command=command,
                    score=result.score,
                    highlight=result.highlight or result.content[:240] or command.summary or rune.name,
                )
            )

        return sorted(
            matches,
            key=lambda match: (-match.score, match.rune.id, match.command.name),
        )[:top_k]

    # ── Write API (WS-G1) ────────────────────────────────────────────────────

    def write_spell(self, spell: Spell, *, overwrite: bool = False) -> Path:
        """
        Persist a spell to the repo's primary spell directory and index it.

        Writing a spell does not affect the conjure engine (which is keyed on
        promptlets and runes), so no engine rebuild is required. See
        :meth:`GrimoireRepo.write_spell` for details.
        """
        return self._repo.write_spell(spell, overwrite=overwrite)

    def update_spell(self, spell: Spell) -> Path:
        """Persist a spell, overwriting any existing file with the same id."""
        return self._repo.update_spell(spell)

    def delete_spell(self, spell_id: str, *, missing_ok: bool = False) -> bool:
        """Delete a spell file and drop it from the index."""
        return self._repo.delete_spell(spell_id, missing_ok=missing_ok)

    # ── Repr ────────────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        s = len(self._repo._spells)
        r = len(self._repo._runes)
        b = len(self._repo._bundles)
        return (
            f"Grimoire({self._repo.root!s}, name={self.name!r}, spells={s}, runes={r}, bundles={b})"
        )


# =============================================================================
# HELPER: OpenAI tool schema generation
# =============================================================================


def _runes_to_openai_tools(runes: list[RuneSpec]) -> list[dict[str, Any]]:
    """
    Convert a list of runes to OpenAI-compatible tool/function schemas.

    Each rune command becomes one tool definition.  The function name is
    ``{rune_id}/{cmd_name}`` with ``/`` replaced by ``__`` for JSON
    compatibility.
    """
    tools: list[dict[str, Any]] = []
    for rune in runes:
        for cmd in rune.commands:
            tools.append(command_to_openai_tool_schema(cmd, rune))
    return tools


def _runes_to_mcp_tool_manifest(runes: list[RuneSpec]) -> dict[str, Any]:
    """Convert rune commands to an MCP ``tools/list`` compatible manifest."""
    tools: list[dict[str, Any]] = []
    for rune in runes:
        for command in rune.commands:
            tool_name = f"{rune.id.replace('/', '__')}__{command.name}"
            risk_level = command.risk_level or rune.risk_level
            requires_approval = command.requires_approval or rune.requires_approval
            permissions = [str(getattr(permission, "value", permission)) for permission in rune.permissions]
            execution_target = command.execution_target
            side_effects = [str(effect) for effect in command.side_effects]
            owasp_categories = command.owasp_categories or rune.owasp_categories

            tool: dict[str, Any] = {
                "name": tool_name,
                "description": command.summary or f"{rune.name}: {command.name}",
                "inputSchema": command_parameters_schema(command),
                "_meta": {
                    "grimoire.rune_id": rune.id,
                    "grimoire.rune_name": rune.name,
                    "grimoire.command_name": command.name,
                    "grimoire.risk_level": risk_level.value,
                    "grimoire.requires_approval": requires_approval,
                    "grimoire.owasp_categories": [str(category) for category in owasp_categories],
                    "grimoire.permissions": permissions,
                    "grimoire.tags": [str(tag) for tag in rune.tags],
                    "grimoire.side_effects": side_effects,
                    "grimoire.tool_name": tool_name,
                },
            }
            if execution_target:
                tool["_meta"]["grimoire.execution_target"] = str(execution_target)
            if rune.content_hash:
                tool["_meta"]["grimoire.content_hash"] = rune.content_hash

            destructive_permissions = {"write_fs", "exec"}
            if side_effects or destructive_permissions.intersection(permissions):
                tool["annotations"] = {
                    "readOnlyHint": False,
                    "destructiveHint": True,
                }
            else:
                tool["annotations"] = {
                    "readOnlyHint": True,
                    "destructiveHint": False,
                }

            tools.append(tool)

    return {
        "schema_version": "grimoire.mcp_tool_manifest.v1",
        "tools": tools,
    }


async def _search_procedural_retriever(
    retriever: Any,
    query: str,
    *,
    top_k: int,
    filters: dict[str, Any] | None,
) -> list[ProceduralSearchResult]:
    if hasattr(retriever, "search"):
        result = retriever.search(query, top_k=top_k, filters=filters)
    elif hasattr(retriever, "retrieve"):
        result = retriever.retrieve(query, top_k=top_k, filters=filters)
    elif callable(retriever):
        result = retriever(query, top_k=top_k, filters=filters)
    else:
        raise TypeError("procedural_retriever must expose search(), retrieve(), or be callable")

    if inspect.isawaitable(result):
        result = await result
    if isinstance(result, list) and all(isinstance(r, ProceduralSearchResult) for r in result):
        return result
    return normalize_procedural_results(result)


def _intent_filters(
    *,
    filter_domain: str | None,
    filter_semantic_role: SemanticRole | str | None,
    include_deprecated: bool,
) -> dict[str, Any]:
    filters: dict[str, Any] = {}
    if filter_domain:
        filters["domain"] = filter_domain
    # Status and semantic-role filters are applied after resolving spells.
    # Backend metadata operators vary, and role metadata may be comma-joined.
    _ = filter_semantic_role, include_deprecated
    return filters


def _tool_filters(*, tags: list[str] | None) -> dict[str, Any]:
    _ = tags
    filters = {"artifact_type": "rune_command"}
    return filters
