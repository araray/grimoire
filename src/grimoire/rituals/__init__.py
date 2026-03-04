# src/grimoire/rituals/__init__.py
"""
Ritual parsing, evaluation, and validation.

Phase 3 implementation:
    - :func:`~grimoire.rituals.parser.parse_ritual` /
      :func:`~grimoire.rituals.parser.parse_ritual_file` — parse ``*.ritual.yaml``
    - :class:`~grimoire.rituals.evaluator.RitualEvaluator` — dry-run and evaluation
      (import directly: ``from grimoire.rituals.evaluator import RitualEvaluator``)
    - :func:`~grimoire.rituals.validator.validate_ritual` — structural + reference validation
      (import directly: ``from grimoire.rituals.validator import validate_ritual``)

Note:
    ``RitualEvaluator`` and ``validate_ritual`` are intentionally not re-exported here
    to avoid a circular import (evaluator → store.repo → rituals.parser → rituals.__init__).
    Import them by their full module path.
"""

from grimoire.rituals.parser import parse_ritual, parse_ritual_file

__all__ = [
    "parse_ritual",
    "parse_ritual_file",
]
