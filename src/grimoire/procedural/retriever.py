"""Retrieval adapters for procedural spell discovery."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from .documents import DEFAULT_PROCEDURAL_COLLECTION
from .models import ProceduralSearchResult


class ProceduralRetriever:
    """Wrap a Semantiscan-style retrieval callable for spell intent search."""

    def __init__(
        self,
        retrieve: Callable[..., Any],
        *,
        collection: str = DEFAULT_PROCEDURAL_COLLECTION,
        strategy: str = "vector",
    ) -> None:
        self.retrieve = retrieve
        self.collection = collection
        self.strategy = strategy

    async def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[ProceduralSearchResult]:
        """Run retrieval and normalize the result shape."""
        try:
            batch = self.retrieve(
                query=query,
                collection=self.collection,
                top_k=top_k,
                filters=filters,
                strategy=self.strategy,
            )
        except TypeError:
            batch = self.retrieve(
                query,
                collection=self.collection,
                top_k=top_k,
                filters=filters,
            )
        batch = await _maybe_await(batch)
        return normalize_procedural_results(batch)


def normalize_procedural_results(batch: Any) -> list[ProceduralSearchResult]:
    """Normalize common Semantiscan retrieval result shapes."""
    rows = _result_rows(batch)
    normalized: list[ProceduralSearchResult] = []
    for row in rows:
        metadata = _metadata(row)
        artifact_type = str(metadata.get("artifact_type") or _value(row, "artifact_type", "spell"))
        spell_id = metadata.get("spell_id") or _value(row, "spell_id")
        if not spell_id:
            chunk_id = _value(row, "chunk_id") or _value(row, "id")
            if isinstance(chunk_id, str) and "@" in chunk_id:
                spell_id = chunk_id.rsplit("@", 1)[0]
        rune_id = str(metadata.get("rune_id") or _value(row, "rune_id", "") or "")
        command_name = str(
            metadata.get("command_name") or _value(row, "command_name", "") or ""
        )
        if not spell_id and artifact_type != "rune_command":
            continue
        normalized.append(
            ProceduralSearchResult(
                spell_id=str(spell_id or ""),
                score=float(_value(row, "score", 0.0) or 0.0),
                content=str(_value(row, "content", _value(row, "document", "")) or ""),
                metadata=metadata,
                highlight=str(
                    _value(row, "highlight", _value(row, "explanation", "")) or ""
                ),
                artifact_type=artifact_type,
                rune_id=rune_id,
                command_name=command_name,
            )
        )
    return normalized


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _result_rows(batch: Any) -> list[Any]:
    if batch is None:
        return []
    if isinstance(batch, list):
        return batch
    if isinstance(batch, dict):
        results = batch.get("results", [])
        return results if isinstance(results, list) else []
    results = getattr(batch, "results", [])
    return results if isinstance(results, list) else []


def _metadata(row: Any) -> dict[str, Any]:
    metadata = _value(row, "metadata", {})
    return dict(metadata) if isinstance(metadata, dict) else {}


def _value(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


__all__ = ["ProceduralRetriever", "normalize_procedural_results"]
