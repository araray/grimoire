# src/grimoire/bind/__init__.py
"""
Binding/Casting — export grimoire artifacts to runtime-native formats.

Implements spec §10: transforms canonical spells, runes, and promptlets
into formats consumed by llmcore, semantiscan, and wairu.

Two operating modes:
    - Pre-bind (CI/offline): write to exports/<target>/
    - Live-bind (library): runtimes call grimoire to fetch+conjure on demand
"""

from grimoire.bind.base import Binder, BindResult, BindTarget
from grimoire.bind.llmcore import LLMCoreBinder
from grimoire.bind.semantiscan import SemantiscanBinder
from grimoire.bind.wairu import (
    WairuBinder,
    register_wairu_plugin_tools,
    wairu_tool_to_rune,
    wairu_tools_to_runes,
)

__all__ = [
    "BindResult",
    "BindTarget",
    "Binder",
    "LLMCoreBinder",
    "SemantiscanBinder",
    "WairuBinder",
    "register_wairu_plugin_tools",
    "wairu_tool_to_rune",
    "wairu_tools_to_runes",
]
