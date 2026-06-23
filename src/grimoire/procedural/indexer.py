"""Semantiscan-compatible indexing helpers for procedural spell discovery."""

from __future__ import annotations

import inspect
from typing import Any

from grimoire.models import RuneSpec, Spell

from .documents import (
    DEFAULT_PROCEDURAL_COLLECTION,
    build_rune_command_index_documents,
    build_spell_index_document,
    spell_document_id,
)


class ProceduralIndexer:
    """Index spells through Semantiscan-style embedder and vector-store protocols."""

    def __init__(
        self,
        *,
        storage: Any,
        embedder: Any,
        collection: str = DEFAULT_PROCEDURAL_COLLECTION,
        embedding_model: str | None = None,
    ) -> None:
        self.storage = storage
        self.embedder = embedder
        self.collection = collection
        self.embedding_model = embedding_model

    async def index_spell(self, spell: Spell) -> str:
        """Upsert one spell into the procedural retrieval collection."""
        document = build_spell_index_document(spell)
        embeddings = await _maybe_await(
            self.embedder.embed([document.content], model=self.embedding_model)
        )
        await _maybe_await(
            self.storage.add(
                self.collection,
                [document.document_id],
                embeddings,
                [document.content],
                [document.metadata],
            )
        )
        return document.document_id

    async def index_spells(self, spells: list[Spell]) -> list[str]:
        """Upsert multiple spells into the procedural retrieval collection."""
        document_ids: list[str] = []
        for spell in spells:
            document_ids.append(await self.index_spell(spell))
        return document_ids

    async def index_rune(self, rune: RuneSpec) -> list[str]:
        """Upsert all commands for one rune into the procedural collection."""
        documents = build_rune_command_index_documents(rune)
        if not documents:
            return []
        embeddings = await _maybe_await(
            self.embedder.embed(
                [document.content for document in documents],
                model=self.embedding_model,
            )
        )
        await _maybe_await(
            self.storage.add(
                self.collection,
                [document.document_id for document in documents],
                embeddings,
                [document.content for document in documents],
                [document.metadata for document in documents],
            )
        )
        return [document.document_id for document in documents]

    async def index_runes(self, runes: list[RuneSpec]) -> list[str]:
        """Upsert all commands for multiple runes into the procedural collection."""
        document_ids: list[str] = []
        for rune in runes:
            document_ids.extend(await self.index_rune(rune))
        return document_ids

    async def remove_spell(self, spell_id: str, version: str | None = None) -> int:
        """Remove one spell from the procedural retrieval collection."""
        if version is not None:
            ids = [f"{spell_id}@{version}"]
            result = await _maybe_await(self.storage.delete(self.collection, ids=ids))
        else:
            result = await _maybe_await(
                self.storage.delete(self.collection, filters={"spell_id": spell_id})
            )
        return int(result or 0)

    async def remove_spell_version(self, spell: Spell) -> int:
        """Remove a concrete spell version from the procedural collection."""
        result = await _maybe_await(
            self.storage.delete(self.collection, ids=[spell_document_id(spell)])
        )
        return int(result or 0)

    async def remove_rune(self, rune_id: str, version: str | None = None) -> int:
        """Remove indexed commands for a rune from the procedural collection."""
        filters = {"artifact_type": "rune_command", "rune_id": rune_id}
        if version is not None:
            filters["version"] = version
        result = await _maybe_await(self.storage.delete(self.collection, filters=filters))
        return int(result or 0)


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


__all__ = ["ProceduralIndexer"]
