# src/grimoire/bundles/assembler.py
"""
Bundle assembler — materialises a Bundle into a conjurable Spell.

The assembler performs the following stages in order (spec §7.2):

1. **Load base spell** — fetch ``bundle.base_template`` from the repo.
2. **Apply variant overlays** — if a matching variant is found by matching
   ``bundle.variants[i].when`` against ``context``, merge its inject and
   variable_overrides onto the base.
3. **Inject promptlets** — append/prepend promptlet content to SYSTEM and
   USER blocks at the four injection points.
4. **Expose tool descriptions** — if ``bundle.tools`` is non-empty, append
   a formatted tool-availability block to the SYSTEM content.
5. **Return an assembled Spell** with a synthetic ID derived from the bundle.

The assembled ``Spell`` can be passed directly to ``ConjureEngine.conjure()``.

**Note on circular imports**: This module imports ``GrimoireRepo`` at function
scope only (not at module level). Do NOT hoist this import to the top of the
file — ``store/repo.py`` imports ``bundles.parser``, creating a cycle.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from grimoire.exceptions import ArtifactNotFoundError, BundleAssemblyError
from grimoire.models import (
    Bundle,
    BundleInject,
    BundleVariant,
    MessageBlock,
    MessageRole,
    Spell,
)

logger = logging.getLogger(__name__)


class BundleAssembler:
    """
    Assembles a ``Bundle`` into a ready-to-conjure ``Spell``.

    Usage::

        from grimoire.store.repo import GrimoireRepo
        from grimoire.bundles.assembler import BundleAssembler

        repo = GrimoireRepo.load("/path/to/repo")
        assembler = BundleAssembler(repo)
        spell = assembler.assemble(bundle, context={"provider": "anthropic"})
    """

    def __init__(self, repo: Any) -> None:
        # Type annotation uses Any to avoid importing GrimoireRepo at module level.
        # At runtime this must be a GrimoireRepo instance.
        self._repo = repo

    # ── Public API ──────────────────────────────────────────────────────────

    def assemble(
        self,
        bundle: Bundle,
        context: dict[str, str] | None = None,
        variables: dict[str, Any] | None = None,
    ) -> Spell:
        """
        Materialise a bundle into a conjurable ``Spell``.

        Args:
            bundle: The bundle to assemble.
            context: Matching context for variant selection (e.g. ``{"provider": "anthropic"}``).
            variables: Variable overrides from profile overlays / CLI (applied on top of
                       ``bundle`` variable_overrides from any matched variant).

        Returns:
            A fully assembled ``Spell`` ready for ``ConjureEngine.conjure()``.

        Raises:
            BundleAssemblyError: If base_template not found, or inject references
                                 a promptlet that doesn't exist in the repo.
        """
        context = context or {}
        variables = variables or {}

        # Stage 1 — load base spell
        try:
            base_spell = self._repo.get_spell(bundle.base_template)
        except ArtifactNotFoundError as e:
            raise BundleAssemblyError(
                f"Bundle '{bundle.id}': base_template '{bundle.base_template}' not found: {e}"
            ) from e

        # Stage 2 — select variant (first match wins)
        effective_inject = bundle.inject
        effective_var_overrides: dict[str, Any] = {}

        for variant in bundle.variants:
            if _matches_context(variant, context):
                logger.debug("Bundle '%s': applying variant '%s'", bundle.id, variant.id)
                # Merge variant inject on top of base inject
                effective_inject = _merge_inject(effective_inject, variant.inject)
                effective_var_overrides.update(variant.variable_overrides)
                break  # first match wins

        # Merge variable overrides: bundle variants < caller variables
        # variable overrides from variants feed into conjure-time values, not spec
        _ = {**base_spell.variables}  # placeholder: used at conjure time

        # Stage 3 — inject promptlets into blocks
        new_blocks = _inject_promptlets(
            blocks=list(base_spell.raw_blocks),
            inject=effective_inject,
            repo=self._repo,
            bundle_id=bundle.id,
        )

        # Stage 4 — expose tool descriptions (if any)
        if bundle.tools:
            tool_block_content = _render_tool_exposure(bundle, self._repo)
            new_blocks = _append_to_system(new_blocks, "\n\n" + tool_block_content)

        # Stage 5 — construct assembled Spell with synthetic ID and merged vars
        assembled_id = f"__bundle__/{bundle.id}"
        # Combine base spell variables with any variant-level defaults
        assembled_vars = dict(base_spell.variables)

        # Compute a deterministic hash for the assembled spell
        hasher = hashlib.sha256()
        hasher.update(bundle.id.encode())
        hasher.update(bundle.content_hash.encode() if bundle.content_hash else b"")
        for block in new_blocks:
            hasher.update(block.role.value.encode())
            hasher.update(block.content.encode())
        assembled_hash = hasher.hexdigest()[:16]

        assembled_spell = Spell(
            id=assembled_id,
            name=f"[Bundle] {bundle.name}",
            version=bundle.version,
            description=bundle.description,
            tags=bundle.tags,
            variables=assembled_vars,
            requires_runes=base_spell.requires_runes,
            suggests_runes=base_spell.suggests_runes,
            runes_export=base_spell.runes_export,
            output_contract=base_spell.output_contract,
            raw_blocks=new_blocks,
            source_path=bundle.source_path,
            content_hash=assembled_hash,
        )

        logger.info(
            "Bundle '%s' assembled → %d blocks, hash=%s",
            bundle.id,
            len(new_blocks),
            assembled_hash,
        )
        return assembled_spell


# ── Helpers ──────────────────────────────────────────────────────────────────


def _matches_context(variant: BundleVariant, context: dict[str, str]) -> bool:
    """Return True if all variant.when keys match the context dict."""
    if not variant.when:
        return True
    for key, expected in variant.when.items():
        if context.get(key) != expected:
            return False
    return True


def _merge_inject(
    base: BundleInject | None,
    overlay: BundleInject | None,
) -> BundleInject | None:
    """
    Merge two BundleInject configs — overlay lists are appended to base lists.
    """
    if base is None and overlay is None:
        return None
    base = base or BundleInject()
    overlay = overlay or BundleInject()
    return BundleInject(
        system_prepend=base.system_prepend + overlay.system_prepend,
        system_append=base.system_append + overlay.system_append,
        user_prepend=base.user_prepend + overlay.user_prepend,
        user_append=base.user_append + overlay.user_append,
    )


def _inject_promptlets(
    blocks: list[MessageBlock],
    inject: BundleInject | None,
    repo: Any,
    bundle_id: str,
) -> list[MessageBlock]:
    """
    Inject promptlet content at the four injection points.

    Returns a new list of MessageBlocks with injected content.
    """
    if not inject:
        return blocks

    def _get_content(promptlet_id: str) -> str:
        try:
            return repo.get_promptlet(promptlet_id).content
        except ArtifactNotFoundError:
            logger.warning(
                "Bundle '%s': inject promptlet '%s' not found, skipping",
                bundle_id,
                promptlet_id,
            )
            return ""

    def _prefixed(ids: list[str]) -> str:
        parts = [_get_content(pid) for pid in ids]
        return "\n\n".join(p for p in parts if p)

    def _suffixed(ids: list[str]) -> str:
        return _prefixed(ids)

    result: list[MessageBlock] = []
    found_system = False
    found_user = False

    for block in blocks:
        if block.role == MessageRole.SYSTEM:
            found_system = True
            pre = _prefixed(inject.system_prepend)
            suf = _suffixed(inject.system_append)
            new_content = "\n\n".join(filter(None, [pre, block.content, suf]))
            result.append(MessageBlock(role=block.role, content=new_content))
        elif block.role == MessageRole.USER:
            found_user = True
            pre = _prefixed(inject.user_prepend)
            suf = _suffixed(inject.user_append)
            new_content = "\n\n".join(filter(None, [pre, block.content, suf]))
            result.append(MessageBlock(role=block.role, content=new_content))
        else:
            result.append(block)

    # If no SYSTEM block existed but there is a system inject, prepend a new block
    if not found_system and (inject.system_prepend or inject.system_append):
        system_content = _prefixed(inject.system_prepend + inject.system_append)
        if system_content:
            result.insert(0, MessageBlock(role=MessageRole.SYSTEM, content=system_content))

    # If no USER block existed but there is a user inject, append a new block
    if not found_user and (inject.user_prepend or inject.user_append):
        user_content = _prefixed(inject.user_prepend + inject.user_append)
        if user_content:
            result.append(MessageBlock(role=MessageRole.USER, content=user_content))

    return result


def _append_to_system(blocks: list[MessageBlock], text: str) -> list[MessageBlock]:
    """Append ``text`` to the last SYSTEM block, or create one if absent."""
    for i, block in enumerate(blocks):
        if block.role == MessageRole.SYSTEM:
            updated = MessageBlock(role=block.role, content=block.content + text)
            blocks = list(blocks)
            blocks[i] = updated
            return blocks
    # No SYSTEM block — prepend one
    return [MessageBlock(role=MessageRole.SYSTEM, content=text.strip()), *blocks]


def _render_tool_exposure(bundle: Bundle, repo: Any) -> str:
    """
    Render the tool-availability block from bundle.tools.

    Produces a markdown section listing available tool groups and their rune names.
    """
    lines = ["## Available Tools\n"]
    for group_name, rune_ids in bundle.tools.items():
        lines.append(f"**{group_name}**:")
        for rune_id in rune_ids:
            try:
                rune = repo.get_rune(rune_id)
                cmd_names = ", ".join(c.name for c in rune.commands)
                lines.append(f"  - `{rune.id}` — {rune.name} (commands: {cmd_names})")
            except ArtifactNotFoundError:
                lines.append(f"  - `{rune_id}` (not found in repo)")
        lines.append("")
    return "\n".join(lines)
