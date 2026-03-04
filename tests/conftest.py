# tests/conftest.py
"""Shared test fixtures for Grimoire tests."""

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
GRIMOIRE_REPO_DIR = FIXTURES_DIR / "grimoire_repo"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def grimoire_repo_dir() -> Path:
    return GRIMOIRE_REPO_DIR


@pytest.fixture
def sample_spell_text() -> str:
    """Minimal spell text for unit tests."""
    return """\
---
id: test/simple
name: Simple Test Spell
version: 1.0.0
tags: [test]
variables:
  topic:
    type: string
    required: true
    ask: "Topic?"
  detail:
    type: string
    required: false
    default: "brief"
---

# SYSTEM
You are a helpful assistant.

# USER
Tell me about {{ topic }} in {{ detail }} detail.
"""


@pytest.fixture
def sample_rune_data() -> dict:
    """Minimal rune dict for unit tests."""
    return {
        "id": "test/echo",
        "name": "Echo Tool",
        "version": "1.0.0",
        "tags": ["test"],
        "risk_level": "none",
        "commands": [
            {
                "name": "echo",
                "summary": "Echo back input",
                "params": [
                    {"name": "message", "type": "string", "required": True},
                ],
                "side_effects": [],
            }
        ],
    }
