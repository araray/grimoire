# src/grimoire/skilldocs/selector.py
"""
SkillDoc section selector.

Provides tag/heading/keyword filtering over a ``SkillDoc``'s sections,
compatible with the llmcore ``SkillLoader`` section-filtering interface.
"""

from __future__ import annotations

from grimoire.models import SkillDoc, SkillDocSection
from grimoire.runes.schema import command_to_openai_tool_schema


class SkillDocSelector:
    """
    Filter sections from a ``SkillDoc`` by tags, headings, or keywords.

    Usage::

        selector = SkillDocSelector(skilldoc)
        sections = selector.by_tags(["branching", "workflow"])
        text = selector.render(sections)
    """

    def __init__(self, skilldoc: SkillDoc) -> None:
        self._doc = skilldoc

    # ── Filtering ────────────────────────────────────────────────────────────

    def all_sections(self) -> list[SkillDocSection]:
        """Return all sections in document order."""
        return list(self._doc.sections)

    def by_tags(self, tags: list[str], require_all: bool = True) -> list[SkillDocSection]:
        """
        Filter sections by tags.

        Args:
            tags: Tag list to match against.
            require_all: If True (default), section must have ALL tags (AND).
                         If False, section must have ANY tag (OR).

        Returns:
            Filtered list of sections in document order.
        """
        if not tags:
            return self.all_sections()

        tag_set = set(tags)
        result = []
        for sec in self._doc.sections:
            sec_tags = set(sec.tags)
            if require_all:
                if tag_set.issubset(sec_tags):
                    result.append(sec)
            else:
                if tag_set & sec_tags:
                    result.append(sec)
        return result

    def by_heading(self, heading_pattern: str) -> list[SkillDocSection]:
        """
        Filter sections whose heading contains ``heading_pattern`` (case-insensitive).

        Args:
            heading_pattern: Substring to search in headings.

        Returns:
            Filtered list of sections in document order.
        """
        pattern = heading_pattern.lower()
        return [sec for sec in self._doc.sections if pattern in sec.heading.lower()]

    def by_id(self, section_id: str) -> SkillDocSection | None:
        """Return the section with the given ID, or None if not found."""
        for sec in self._doc.sections:
            if sec.id == section_id:
                return sec
        return None

    def by_keyword(self, keyword: str) -> list[SkillDocSection]:
        """
        Filter sections whose content or heading contains ``keyword`` (case-insensitive).

        Args:
            keyword: Substring to search in heading + content.

        Returns:
            Filtered list of sections in document order.
        """
        kw = keyword.lower()
        return [
            sec
            for sec in self._doc.sections
            if kw in sec.heading.lower() or kw in sec.content.lower()
        ]

    # ── Rendering ────────────────────────────────────────────────────────────

    def render(self, sections: list[SkillDocSection] | None = None) -> str:
        """
        Render selected sections to a markdown string.

        Args:
            sections: Sections to render.  If None, renders all sections.

        Returns:
            Markdown text with headings and content.
        """
        if sections is None:
            sections = self.all_sections()
        parts = []
        for sec in sections:
            parts.append(f"## {sec.heading}\n\n{sec.content}")
        return "\n\n".join(parts)

    def render_to_openai_tool_schema(self, runes: list) -> list[dict]:
        """
        Export a list of RuneSpec objects as OpenAI-compatible tool definitions.

        This is a convenience adapter used by ``grimoire skill export --to openai-tool-schema``.

        Args:
            runes: List of ``RuneSpec`` instances.

        Returns:
            List of OpenAI function-calling tool dicts.
        """
        tools = []
        for rune in runes:
            for cmd in rune.commands:
                tools.append(command_to_openai_tool_schema(cmd, rune))
        return tools
