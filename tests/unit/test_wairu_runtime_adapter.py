from __future__ import annotations

from types import SimpleNamespace

import pytest

from grimoire.bind.wairu import (
    register_wairu_plugin_tools,
    wairu_tool_to_rune,
    wairu_tools_to_runes,
)
from grimoire.models import RiskLevel


def test_wairu_tool_object_to_rune_preserves_runtime_metadata() -> None:
    tool = SimpleNamespace(
        name="read_file",
        description="Read a file from an allowed path.",
        parameters={"path": {"type": "string", "required": True, "description": "File path"}},
        requires_approval=True,
        risk_level="high",
        owasp_categories=["LLM06_excessive_agency"],
        owasp=["A01:2021-Broken Access Control"],
    )

    rune = wairu_tool_to_rune(tool, plugin_name="shell")

    assert rune.id == "wairu/plugins/shell/read_file"
    assert rune.name == "shell.read_file"
    assert rune.risk_level is RiskLevel.HIGH
    assert rune.requires_approval is True
    assert rune.owasp_categories == [
        "LLM06_excessive_agency",
        "A01:2021-Broken Access Control",
    ]
    assert "plugin:shell" in rune.tags
    assert "owasp:LLM06_excessive_agency" in rune.tags
    assert "owasp:A01:2021-Broken Access Control" in rune.tags
    assert rune.mappings["wairu.qualified_tool"] == "shell.read_file"

    command = rune.commands[0]
    assert command.name == "read_file"
    assert command.risk_level is RiskLevel.HIGH
    assert command.owasp_categories == rune.owasp_categories
    assert command.requires_approval is True
    assert command.params[0].name == "path"
    assert command.params[0].required is True
    assert command.params[0].description == "File path"


def test_wairu_tool_dict_to_rune_accepts_json_schema_parameters() -> None:
    tool = {
        "name": "run_command",
        "description": "Run an approved shell command.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Command to run",
                    "pattern": "^[a-z]+",
                },
                "timeout": {
                    "type": "integer",
                    "default": 30,
                    "minimum": 1,
                    "maximum": 120,
                },
                "mode": {"type": "string", "enum": ["read", "write"]},
            },
            "required": ["command"],
        },
        "requires_approval": "true",
        "risk_level": "medium",
        "tags": ["shell"],
    }

    rune = wairu_tool_to_rune(tool, plugin_name="shell tools", rune_id_prefix="runtime")

    assert rune.id == "runtime/shell_tools/run_command"
    assert rune.risk_level is RiskLevel.MEDIUM
    assert "shell" in rune.tags

    params = {param.name: param for param in rune.commands[0].params}
    assert params["command"].required is True
    assert params["command"].pattern == "^[a-z]+"
    assert params["timeout"].required is False
    assert params["timeout"].default == 30
    assert params["timeout"].minimum == 1
    assert params["timeout"].maximum == 120
    assert params["mode"].enum == ["read", "write"]


def test_wairu_tools_to_runes_converts_iterable() -> None:
    tools = [
        {"name": "one", "description": "First", "parameters": {}},
        {"name": "two", "description": "Second", "parameters": {}},
    ]

    runes = wairu_tools_to_runes(tools, plugin_name="sample", tags=["runtime"])

    assert [rune.id for rune in runes] == [
        "wairu/plugins/sample/one",
        "wairu/plugins/sample/two",
    ]
    assert all("runtime" in rune.tags for rune in runes)


def test_register_wairu_plugin_tools_updates_repo_and_facade_engine() -> None:
    target = SimpleNamespace(
        _repo=SimpleNamespace(_runes={}),
        _engine=SimpleNamespace(_runes={}),
    )
    tools = [{"name": "inspect", "description": "Inspect state", "parameters": {}}]

    runes = register_wairu_plugin_tools(target, tools, plugin_name="state")

    assert runes[0].id == "wairu/plugins/state/inspect"
    assert target._repo._runes[runes[0].id] is runes[0]
    assert target._engine._runes[runes[0].id] is runes[0]


def test_register_wairu_plugin_tools_rejects_duplicate_when_requested() -> None:
    target = SimpleNamespace(_runes={})
    tools = [{"name": "inspect", "description": "Inspect state", "parameters": {}}]
    register_wairu_plugin_tools(target, tools, plugin_name="state")

    with pytest.raises(ValueError, match="Rune already registered"):
        register_wairu_plugin_tools(target, tools, plugin_name="state", overwrite=False)
