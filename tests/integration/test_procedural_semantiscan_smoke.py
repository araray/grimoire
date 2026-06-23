"""Cross-repo smoke for Grimoire procedural discovery over Semantiscan protocols."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest

from grimoire import Grimoire
from grimoire.procedural import ProceduralIndexer, ProceduralRetriever

semantiscan_api = pytest.importorskip("semantiscan.api")
standalone = pytest.importorskip("semantiscan.adapters.standalone")


class KeywordEmbedder:
    """Tiny deterministic embedder that makes the smoke test semantic enough."""

    _vocab: ClassVar[list[str]] = [
        "security",
        "threat",
        "stride",
        "component",
        "root",
        "cause",
        "incident",
        "symptoms",
        "summary",
        "reviewer",
    ]

    @property
    def dimension(self) -> int:
        return len(self._vocab)

    async def embed(self, texts: list[str], *, model: str | None = None) -> list[list[float]]:
        del model
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        lowered = text.lower()
        return [float(lowered.count(term)) for term in self._vocab]


def _write_grimoire_repo(root: Path) -> None:
    (root / "spells").mkdir(parents=True)
    (root / "grimoire.yaml").write_text(
        """\
name: procedural-smoke
version: 0.1.0
spell_paths: [spells/]
rune_paths: [runes/]
ritual_paths: [rituals/]
promptlet_paths: [promptlets/]
bundle_paths: [bundles/]
skilldoc_paths: [skills/]
vars_path: vars/defaults.yaml
""",
        encoding="utf-8",
    )
    (root / "spells" / "security.spell.md").write_text(
        """\
---
id: smoke/security_threat_model
name: Security Threat Model
description: STRIDE security threat model for a component.
intent_description: create a STRIDE security threat model for a component
semantic_blueprint:
  scene_goal: create a STRIDE security threat model for a component
  participants:
    - role: architect
      semantic_role: Agent
    - role: component
      semantic_role: Patient
    - role: reviewer
      semantic_role: Recipient
  action_to_complete: identify security threats and mitigations
  domain: security
  keywords: [security, threat, stride, component]
  status: active
---

# USER
Model threats for {{ component }}.
""",
        encoding="utf-8",
    )
    (root / "spells" / "rca.spell.md").write_text(
        """\
---
id: smoke/root_cause_analysis
name: Root Cause Analysis
description: Root-cause analysis for software incidents.
intent_description: diagnose an incident from symptoms and identify root cause
semantic_blueprint:
  scene_goal: diagnose an incident from symptoms and identify root cause
  participants:
    - role: investigator
      semantic_role: Agent
    - role: incident
      semantic_role: Patient
  action_to_complete: explain the root cause and validation plan
  domain: debugging
  keywords: [root, cause, incident, symptoms]
  status: active
---

# USER
Analyze {{ symptoms }}.
""",
        encoding="utf-8",
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_grimoire_procedural_discovery_over_semantiscan(tmp_path: Path) -> None:
    _write_grimoire_repo(tmp_path)
    storage = standalone.InMemoryVectorStore()
    embedder = KeywordEmbedder()

    async def retrieve_with_backends(**kwargs):
        return await semantiscan_api.retrieve(
            **kwargs,
            storage=storage,
            embedder=embedder,
        )

    retriever = ProceduralRetriever(retrieve_with_backends)
    indexer = ProceduralIndexer(storage=storage, embedder=embedder)
    grim = Grimoire(tmp_path, procedural_retriever=retriever, procedural_indexer=indexer)

    document_ids = await grim.rebuild_procedural_index()
    matches = await grim.find_by_intent(
        "security threat model using STRIDE",
        top_k=1,
        filter_domain="security",
    )

    assert sorted(document_ids) == [
        "smoke/root_cause_analysis@1.0.0",
        "smoke/security_threat_model@1.0.0",
    ]
    assert [match.spell.id for match in matches] == ["smoke/security_threat_model"]
    assert matches[0].score > 0
