# src/grimoire/bundles/__init__.py
"""
Bundle support for Grimoire.

A Bundle is a prompt composition recipe that selects a base spell,
applies profile overlays, injects promptlets at specific positions,
and optionally exposes a set of rune contracts.

**Circular-import warning**: This ``__init__`` exports only the parser
(``parse_bundle``, ``parse_bundle_file``) and the ``BundleAssembler`` class
(imported lazily). Do NOT import ``GrimoireRepo`` at module level here —
``store/repo.py`` imports ``bundles/parser.py``, so importing ``GrimoireRepo``
in ``bundles/__init__.py`` would create a cycle.

Anyone needing the assembler should import it directly::

    from grimoire.bundles.assembler import BundleAssembler
"""

from grimoire.bundles.parser import parse_bundle, parse_bundle_file

__all__ = ["parse_bundle", "parse_bundle_file"]
