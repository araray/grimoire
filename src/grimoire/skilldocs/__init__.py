# src/grimoire/skilldocs/__init__.py
"""
SkillDoc support for Grimoire (Phase 7).

SkillDocs are markdown files with YAML frontmatter describing domain knowledge.
They are analogous to llmcore's ``SkillLoader`` format and support section
filtering by tag, heading, or keyword.
"""

from grimoire.skilldocs.parser import parse_skilldoc, parse_skilldoc_file
from grimoire.skilldocs.selector import SkillDocSelector

__all__ = ["SkillDocSelector", "parse_skilldoc", "parse_skilldoc_file"]
