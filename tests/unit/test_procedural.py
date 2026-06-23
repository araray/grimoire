"""Tests for procedural spell discovery."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from grimoire import Grimoire
from grimoire.models import BlueprintStatus, SemanticRole
from grimoire.procedural import (
    IntentMatch,
    ProceduralIndexer,
    ProceduralSearchResult,
    ToolIntentMatch,
    build_rune_command_index_documents,
    build_spell_index_document,
    find_spells_by_intent_linear,
    find_tools_by_intent_linear,
)
from grimoire.runes.parser import parse_rune
from grimoire.spells.parser import parse_spell

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
REPO_DIR = FIXTURES_DIR / "grimoire_repo"


def _blueprint_spell_text(status: str = "active") -> str:
    return f"""\
---
id: test/security_summary
name: Security Summary
description: Summarize a technical document preserving security details.
intent_description: summarize a technical document for a security reviewer
semantic_blueprint:
  scene_goal: summarize a technical document for a security reviewer
  participants:
    - role: summarizer
      semantic_role: Agent
    - role: document
      semantic_role: Patient
      description: code, specs, or RFCs
    - role: reviewer
      semantic_role: Recipient
      description: security-focused reviewer
  action_to_complete: produce a concise security-focused summary
  domain: summarization
  keywords: [security, audit, risk]
  status: {status}
---

# USER
Summarize {{ document }}.
"""


def _git_rune_data() -> dict[str, Any]:
    return {
        "id": "devtools/git",
        "name": "Git diagnostics",
        "description": "Git commands for repository diagnostics.",
        "tags": ["devtools", "vcs", "engineering"],
        "risk_level": "low",
        "permissions": ["read_fs"],
        "commands": [
            {
                "name": "status",
                "summary": "Show working tree status",
                "params": [{"name": "porcelain", "type": "bool", "default": True}],
            },
            {
                "name": "diff",
                "summary": "Show changes in the working tree",
                "params": [{"name": "staged", "type": "bool", "default": False}],
            },
        ],
    }


def test_build_spell_index_document_from_blueprint() -> None:
    spell = parse_spell(_blueprint_spell_text())

    document = build_spell_index_document(spell)

    assert document.document_id == "test/security_summary@1.0.0"
    assert "Goal: summarize a technical document" in document.content
    assert document.metadata["spell_id"] == "test/security_summary"
    assert document.metadata["domain"] == "summarization"
    assert document.metadata["status"] == BlueprintStatus.ACTIVE.value
    assert document.metadata["participant_semantic_roles"] == "Agent,Patient,Recipient"
    assert document.metadata["keywords"] == "security,audit,risk"
    assert document.metadata["has_blueprint"] is True


def test_build_rune_command_index_documents() -> None:
    rune = parse_rune(_git_rune_data())

    documents = build_rune_command_index_documents(rune)

    assert [document.document_id for document in documents] == [
        "devtools/git@1.0.0::status",
        "devtools/git@1.0.0::diff",
    ]
    assert "Show working tree status" in documents[0].content
    assert documents[0].metadata["artifact_type"] == "rune_command"
    assert documents[0].metadata["rune_id"] == "devtools/git"
    assert documents[0].metadata["command_name"] == "status"
    assert documents[0].metadata["permissions"] == "read_fs"


@pytest.mark.asyncio
async def test_find_by_intent_linear_fallback_uses_loaded_spell_catalog() -> None:
    grim = Grimoire(REPO_DIR)

    matches = await grim.find_by_intent("security threat model stride component", top_k=1)

    assert matches
    assert matches[0].spell.id == "engineering/security_threat_model"
    assert matches[0].score > 0


def test_linear_find_by_intent_filters_blueprint_fields() -> None:
    active = parse_spell(_blueprint_spell_text())
    deprecated = parse_spell(_blueprint_spell_text(status="deprecated").replace(
        "id: test/security_summary", "id: test/old_security_summary"
    ))

    matches = find_spells_by_intent_linear(
        "security reviewer summary",
        [active, deprecated],
        filter_domain="summarization",
        filter_semantic_role=SemanticRole.RECIPIENT,
    )

    assert [match.spell.id for match in matches] == ["test/security_summary"]


def test_linear_find_tools_by_intent_matches_rune_commands() -> None:
    rune = parse_rune(_git_rune_data())

    matches = find_tools_by_intent_linear(
        "show git working tree status",
        [rune],
        tags=["devtools"],
        max_risk="low",
    )

    assert [f"{match.rune.id}::{match.command.name}" for match in matches[:1]] == [
        "devtools/git::status"
    ]
    assert isinstance(matches[0], ToolIntentMatch)


class FakeProceduralRetriever:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def search(
        self,
        query: str,
        *,
        top_k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[ProceduralSearchResult]:
        self.calls.append({"query": query, "top_k": top_k, "filters": filters})
        return [
            ProceduralSearchResult(spell_id="missing/stale", score=0.99),
            ProceduralSearchResult(
                spell_id="engineering/root_cause_analysis",
                score=0.42,
                content="Root cause analysis",
            ),
            ProceduralSearchResult(
                spell_id="engineering/security_threat_model",
                score=0.88,
                highlight="STRIDE threat model",
            ),
        ]


class FakeToolProceduralRetriever:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def search(
        self,
        query: str,
        *,
        top_k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[ProceduralSearchResult]:
        self.calls.append({"query": query, "top_k": top_k, "filters": filters})
        return [
            ProceduralSearchResult(
                spell_id="",
                artifact_type="rune_command",
                rune_id="devtools/git",
                command_name="diff",
                score=0.82,
                highlight="Show changes in the working tree",
            ),
            ProceduralSearchResult(
                spell_id="",
                artifact_type="rune_command",
                rune_id="devtools/git",
                command_name="status",
                score=0.91,
                highlight="Show working tree status",
            ),
        ]


@pytest.mark.asyncio
async def test_find_by_intent_uses_configured_retriever_and_resolves_spells() -> None:
    retriever = FakeProceduralRetriever()
    grim = Grimoire(REPO_DIR, procedural_retriever=retriever)

    matches = await grim.find_by_intent("security review", top_k=2)

    assert [match.spell.id for match in matches] == [
        "engineering/security_threat_model",
        "engineering/root_cause_analysis",
    ]
    assert isinstance(matches[0], IntentMatch)
    assert matches[0].highlight == "STRIDE threat model"
    assert retriever.calls == [{"query": "security review", "top_k": 8, "filters": {}}]


@pytest.mark.asyncio
async def test_find_tools_by_intent_uses_configured_retriever_and_resolves_commands() -> None:
    retriever = FakeToolProceduralRetriever()
    grim = Grimoire(REPO_DIR, procedural_retriever=retriever)

    matches = await grim.find_tools_by_intent("show repository status", top_k=1)

    assert [f"{match.rune.id}::{match.command.name}" for match in matches] == [
        "devtools/git::status"
    ]
    assert matches[0].highlight == "Show working tree status"
    assert retriever.calls == [
        {
            "query": "show repository status",
            "top_k": 4,
            "filters": {"artifact_type": "rune_command"},
        }
    ]


class FakeIndexer:
    def __init__(self) -> None:
        self.spell_ids: list[str] = []

    async def index_spells(self, spells: list[Any]) -> list[str]:
        self.spell_ids = [spell.id for spell in spells]
        return [f"{spell.id}@{spell.version}" for spell in spells]


@pytest.mark.asyncio
async def test_rebuild_procedural_index_uses_configured_indexer() -> None:
    indexer = FakeIndexer()
    grim = Grimoire(REPO_DIR, procedural_indexer=indexer)

    document_ids = await grim.rebuild_procedural_index()

    assert "engineering/security_threat_model" in indexer.spell_ids
    assert "engineering/security_threat_model@1.0.0" in document_ids


@pytest.mark.asyncio
async def test_rebuild_procedural_index_requires_indexer() -> None:
    grim = Grimoire(REPO_DIR)

    with pytest.raises(RuntimeError, match="procedural_indexer"):
        await grim.rebuild_procedural_index()


class FakeEmbedder:
    dimension = 3

    def __init__(self) -> None:
        self.texts: list[str] = []

    async def embed(self, texts: list[str], *, model: str | None = None) -> list[list[float]]:
        del model
        self.texts.extend(texts)
        return [[1.0, 0.0, 0.0] for _ in texts]


class FakeStorage:
    def __init__(self) -> None:
        self.add_calls: list[dict[str, Any]] = []
        self.delete_calls: list[dict[str, Any]] = []

    async def add(
        self,
        collection: str,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[dict[str, Any]] | None = None,
    ) -> None:
        self.add_calls.append(
            {
                "collection": collection,
                "ids": ids,
                "embeddings": embeddings,
                "documents": documents,
                "metadatas": metadatas,
            }
        )

    async def delete(
        self,
        collection: str,
        ids: list[str] | None = None,
        filters: dict[str, Any] | None = None,
    ) -> int:
        self.delete_calls.append({"collection": collection, "ids": ids, "filters": filters})
        return 1


@pytest.mark.asyncio
async def test_procedural_indexer_uses_semantiscan_style_protocols() -> None:
    storage = FakeStorage()
    embedder = FakeEmbedder()
    indexer = ProceduralIndexer(storage=storage, embedder=embedder)
    spell = parse_spell(_blueprint_spell_text())

    document_id = await indexer.index_spell(spell)
    removed = await indexer.remove_spell("test/security_summary", version="1.0.0")

    assert document_id == "test/security_summary@1.0.0"
    assert storage.add_calls[0]["collection"] == "grimoire/spells"
    assert storage.add_calls[0]["ids"] == ["test/security_summary@1.0.0"]
    assert storage.add_calls[0]["metadatas"][0]["spell_id"] == "test/security_summary"
    assert embedder.texts and "security reviewer" in embedder.texts[0]
    assert removed == 1
    assert storage.delete_calls == [
        {
            "collection": "grimoire/spells",
            "ids": ["test/security_summary@1.0.0"],
            "filters": None,
        }
    ]


@pytest.mark.asyncio
async def test_procedural_indexer_indexes_rune_commands() -> None:
    storage = FakeStorage()
    embedder = FakeEmbedder()
    indexer = ProceduralIndexer(storage=storage, embedder=embedder)
    rune = parse_rune(_git_rune_data())

    document_ids = await indexer.index_rune(rune)

    assert document_ids == [
        "devtools/git@1.0.0::status",
        "devtools/git@1.0.0::diff",
    ]
    assert storage.add_calls[0]["ids"] == document_ids
    assert storage.add_calls[0]["metadatas"][0]["artifact_type"] == "rune_command"
    assert storage.add_calls[0]["metadatas"][0]["command_name"] == "status"
