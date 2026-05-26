# tests/unit/test_spell_attributes.py
"""
Unit tests for the opaque ``Spell.attributes`` field and the spell serializer
(WS-G4 + WS-G1 serializer).

Covers:
    - ``attributes`` defaults to an empty dict and is a declared field
      (``extra="forbid"`` is preserved on the model).
    - The parser reads an ``attributes:`` front-matter mapping.
    - Non-mapping ``attributes`` raises a validation error.
    - ``serialize_spell`` round-trips: parse -> serialize -> parse yields an
      equivalent spell, and the ``content_hash`` is unchanged (attributes are
      metadata, not prompt body).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from grimoire.exceptions import SpellValidationError
from grimoire.models import MessageBlock, MessageRole, Spell, VariableSpec
from grimoire.spells.parser import parse_spell, serialize_spell

SPELL_WITH_ATTRS = """\
---
id: convergence/personas/skeptic
name: Skeptic
version: 1.2.0
tags: [convergence, "pack:creative"]
attributes:
  color: "#cc3333"
  constraints:
    - challenge assumptions
    - cite evidence
description: A relentless skeptic persona.
---

# SYSTEM
You are a relentless skeptic. Question every claim.

# USER
Topic: {{ topic }}
"""


class TestAttributesParsing:
    def test_attributes_default_empty(self) -> None:
        spell = Spell(
            id="x/y",
            name="Y",
            raw_blocks=[MessageBlock(role=MessageRole.USER, content="hi")],
        )
        assert spell.attributes == {}

    def test_model_still_forbids_extra(self) -> None:
        # Adding `attributes` must not relax extra="forbid".
        with pytest.raises(ValidationError):
            Spell(
                id="x/y",
                name="Y",
                bogus_field=123,  # type: ignore[call-arg]
                raw_blocks=[MessageBlock(role=MessageRole.USER, content="hi")],
            )

    def test_parse_reads_attributes(self) -> None:
        spell = parse_spell(SPELL_WITH_ATTRS, source_path="s")
        assert spell.attributes["color"] == "#cc3333"
        assert spell.attributes["constraints"] == ["challenge assumptions", "cite evidence"]
        assert spell.tags == ["convergence", "pack:creative"]

    def test_parse_rejects_non_mapping_attributes(self) -> None:
        bad = SPELL_WITH_ATTRS.replace(
            "attributes:\n  color: \"#cc3333\"\n  constraints:\n"
            "    - challenge assumptions\n    - cite evidence",
            "attributes: not-a-mapping",
        )
        with pytest.raises(SpellValidationError, match="attributes"):
            parse_spell(bad, source_path="s")


class TestSerializerRoundTrip:
    def test_round_trip_preserves_content_and_hash(self) -> None:
        original = parse_spell(SPELL_WITH_ATTRS, source_path="orig")
        text = serialize_spell(original)
        reparsed = parse_spell(text, source_path="reparsed")

        assert reparsed.id == original.id
        assert reparsed.name == original.name
        assert reparsed.version == original.version
        assert reparsed.tags == original.tags
        assert reparsed.attributes == original.attributes
        assert reparsed.description == original.description
        assert [b.role for b in reparsed.raw_blocks] == [b.role for b in original.raw_blocks]
        assert [b.content for b in reparsed.raw_blocks] == [
            b.content for b in original.raw_blocks
        ]
        # Hash is over raw_blocks only and must be stable across round-trips.
        assert reparsed.content_hash == original.content_hash

    def test_round_trip_with_variables(self) -> None:
        spell = Spell(
            id="t/vars",
            name="Vars",
            variables={
                "topic": VariableSpec(type="string", required=True, ask="Topic?"),
                "detail": VariableSpec(type="string", required=False, default="brief"),
            },
            raw_blocks=[
                MessageBlock(role=MessageRole.USER, content="Tell me about {{ topic }}."),
            ],
        )
        reparsed = parse_spell(serialize_spell(spell))
        assert set(reparsed.variables.keys()) == {"topic", "detail"}
        assert reparsed.variables["topic"].required is True
        assert reparsed.variables["topic"].ask == "Topic?"
        assert reparsed.variables["detail"].required is False
        assert reparsed.variables["detail"].default == "brief"

    def test_serialized_omits_empty_collections(self) -> None:
        spell = Spell(
            id="t/min",
            name="Min",
            raw_blocks=[MessageBlock(role=MessageRole.SYSTEM, content="hi")],
        )
        text = serialize_spell(spell)
        assert "tags:" not in text
        assert "attributes:" not in text
        assert "variables:" not in text
