"""Tests for Grimoire's MCP JSON-RPC server skeleton."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from grimoire import Grimoire
from grimoire.mcp_server import MCPRequestHandler, build_app
from grimoire.mcp_server.handlers import ERROR_INVALID_PARAMS, ERROR_METHOD_NOT_FOUND

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
REPO_DIR = FIXTURES_DIR / "grimoire_repo"
TOKEN = "test-token"


@pytest.fixture
def grim() -> Grimoire:
    return Grimoire(REPO_DIR)


@pytest.fixture
def client(grim: Grimoire) -> TestClient:
    app = build_app(grim, auth_token=TOKEN, server_version="test-version")
    return TestClient(app)


@pytest.fixture
def executable_client(grim: Grimoire) -> TestClient:
    app = build_app(
        grim,
        auth_token=TOKEN,
        server_version="test-version",
        tool_callables={
            "devtools__git__status": lambda porcelain=True: {
                "porcelain": porcelain,
                "stdout": "clean",
            },
            "wairu__shell__run": lambda **kwargs: kwargs,
        },
    )
    return TestClient(app)


def _rpc(client: TestClient, payload: dict[str, Any], token: str = TOKEN) -> dict[str, Any]:
    response = client.post(
        "/mcp",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    return response.json()


def test_build_app_requires_auth_token(grim: Grimoire) -> None:
    with pytest.raises(ValueError, match="auth_token is required"):
        build_app(grim, auth_token="")


def test_rejects_missing_bearer_token(client: TestClient) -> None:
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["detail"] == "Missing or invalid bearer token"


def test_rejects_wrong_bearer_token(client: TestClient) -> None:
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        headers={"Authorization": "Bearer wrong"},
    )

    assert response.status_code == 401


def test_initialize_returns_mcp_server_capabilities(client: TestClient) -> None:
    payload = {
        "jsonrpc": "2.0",
        "id": "init-1",
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "clientInfo": {"name": "pytest", "version": "0"},
        },
    }

    response = _rpc(client, payload)

    assert response == {
        "jsonrpc": "2.0",
        "id": "init-1",
        "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {
                    "listChanged": False,
                },
                "prompts": {
                    "listChanged": False,
                },
            },
            "serverInfo": {
                "name": "grimoire",
                "version": "test-version",
            },
        },
    }


def test_tools_list_returns_grimoire_rune_manifest(client: TestClient) -> None:
    payload = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
        "params": {"rune_ids": ["devtools/git"]},
    }

    response = _rpc(client, payload)

    assert response["jsonrpc"] == "2.0"
    assert response["id"] == 2
    result = response["result"]
    assert result["_meta"]["grimoire.schema_version"] == "grimoire.mcp_tool_manifest.v1"
    assert {tool["name"] for tool in result["tools"]} == {
        "devtools__git__status",
        "devtools__git__diff",
    }
    status_tool = next(tool for tool in result["tools"] if tool["name"] == "devtools__git__status")
    assert status_tool["inputSchema"]["properties"]["porcelain"]["type"] == "boolean"
    assert status_tool["_meta"]["grimoire.rune_id"] == "devtools/git"
    assert status_tool["annotations"] == {
        "readOnlyHint": True,
        "destructiveHint": False,
    }


def test_tools_list_accepts_camel_case_rune_ids(client: TestClient) -> None:
    response = _rpc(
        client,
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/list",
            "params": {"runeIds": ["wairu/shell"]},
        },
    )

    assert [tool["name"] for tool in response["result"]["tools"]] == ["wairu__shell__run"]


def test_tools_list_validates_filter_types(client: TestClient) -> None:
    response = _rpc(
        client,
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/list",
            "params": {"rune_ids": "devtools/git"},
        },
    )

    assert response["error"]["code"] == ERROR_INVALID_PARAMS
    assert "rune_ids" in response["error"]["message"]


def test_tools_call_returns_unavailable_without_registered_callable(
    client: TestClient,
) -> None:
    response = _rpc(
        client,
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "devtools__git__status", "arguments": {"porcelain": True}},
        },
    )

    result = response["result"]
    assert result["isError"] is True
    assert "No callable registered" in result["content"][0]["text"]
    assert result["_meta"]["grimoire.call_status"] == "unavailable"


def test_tools_call_executes_registered_low_risk_callable(
    executable_client: TestClient,
) -> None:
    response = _rpc(
        executable_client,
        {
            "jsonrpc": "2.0",
            "id": 50,
            "method": "tools/call",
            "params": {"name": "devtools__git__status", "arguments": {"porcelain": False}},
        },
    )

    result = response["result"]
    assert result["isError"] is False
    assert '"stdout": "clean"' in result["content"][0]["text"]
    assert '"porcelain": false' in result["content"][0]["text"]
    assert result["_meta"]["grimoire.call_status"] == "executed"
    assert result["_meta"]["grimoire.rune_id"] == "devtools/git"


def test_tools_call_returns_pending_approval_for_high_risk_rune(
    executable_client: TestClient,
) -> None:
    response = _rpc(
        executable_client,
        {
            "jsonrpc": "2.0",
            "id": 51,
            "method": "tools/call",
            "params": {
                "name": "wairu__shell__run",
                "arguments": {"command": "rm -rf /tmp/example"},
            },
        },
    )

    result = response["result"]
    assert result["isError"] is False
    assert "Approval required" in result["content"][0]["text"]
    assert result["_meta"]["grimoire.call_status"] == "pending_approval"
    assert result["_meta"]["grimoire.requires_approval"] is True


def test_tools_call_validates_arguments_object(client: TestClient) -> None:
    response = _rpc(
        client,
        {
            "jsonrpc": "2.0",
            "id": 52,
            "method": "tools/call",
            "params": {"name": "devtools__git__status", "arguments": []},
        },
    )

    assert response["error"]["code"] == ERROR_INVALID_PARAMS
    assert "arguments" in response["error"]["message"]


def test_tools_call_validates_required_tool_arguments(client: TestClient) -> None:
    response = _rpc(
        client,
        {
            "jsonrpc": "2.0",
            "id": 520,
            "method": "tools/call",
            "params": {"name": "wairu__shell__run", "arguments": {}},
        },
    )

    assert response["error"]["code"] == ERROR_INVALID_PARAMS
    assert "Missing required argument 'command'" in response["error"]["message"]


def test_tools_call_validates_tool_argument_types(client: TestClient) -> None:
    response = _rpc(
        client,
        {
            "jsonrpc": "2.0",
            "id": 521,
            "method": "tools/call",
            "params": {
                "name": "devtools__git__status",
                "arguments": {"porcelain": "yes"},
            },
        },
    )

    assert response["error"]["code"] == ERROR_INVALID_PARAMS
    assert "porcelain" in response["error"]["message"]
    assert "boolean" in response["error"]["message"]


def test_prompts_list_returns_spells(client: TestClient) -> None:
    response = _rpc(
        client,
        {
            "jsonrpc": "2.0",
            "id": 53,
            "method": "prompts/list",
            "params": {"tags": ["engineering"]},
        },
    )

    result = response["result"]
    assert result["_meta"]["grimoire.schema_version"] == "grimoire.mcp_prompt_manifest.v1"
    prompt = next(
        item for item in result["prompts"] if item["name"] == "engineering/root_cause_analysis"
    )
    assert prompt["description"] == "Structured root-cause analysis for software incidents."
    assert {arg["name"] for arg in prompt["arguments"]} >= {"issue_title", "symptoms"}
    issue_arg = next(arg for arg in prompt["arguments"] if arg["name"] == "issue_title")
    assert issue_arg["required"] is True


def test_prompts_get_conjures_spell_messages(client: TestClient) -> None:
    response = _rpc(
        client,
        {
            "jsonrpc": "2.0",
            "id": 54,
            "method": "prompts/get",
            "params": {
                "name": "engineering/root_cause_analysis",
                "arguments": {
                    "issue_title": "Workers fail on startup",
                    "symptoms": "ImportError during boot",
                },
            },
        },
    )

    result = response["result"]
    assert result["_meta"]["grimoire.spell_id"] == "engineering/root_cause_analysis"
    assert result["messages"][0]["role"] == "system"
    user_message = next(message for message in result["messages"] if message["role"] == "user")
    assert "Workers fail on startup" in user_message["content"]["text"]
    assert "ImportError during boot" in user_message["content"]["text"]


def test_prompts_get_reports_missing_required_variables(client: TestClient) -> None:
    response = _rpc(
        client,
        {
            "jsonrpc": "2.0",
            "id": 55,
            "method": "prompts/get",
            "params": {"name": "engineering/root_cause_analysis", "arguments": {}},
        },
    )

    assert response["error"]["code"] == ERROR_INVALID_PARAMS
    assert "Required variable 'issue_title' not provided" in response["error"]["message"]


def test_unknown_method_returns_json_rpc_error(client: TestClient) -> None:
    response = _rpc(
        client,
        {
            "jsonrpc": "2.0",
            "id": 56,
            "method": "resources/list",
            "params": {},
        },
    )

    assert response == {
        "jsonrpc": "2.0",
        "id": 56,
        "error": {
            "code": ERROR_METHOD_NOT_FOUND,
            "message": "Unsupported MCP method: resources/list",
        },
    }


def test_rejects_non_object_params(client: TestClient) -> None:
    response = _rpc(
        client,
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/list",
            "params": [],
        },
    )

    assert response["error"]["code"] == -32600
    assert response["error"]["message"] == "Invalid JSON-RPC request"


def test_handler_rejects_non_object_payload(grim: Grimoire) -> None:
    handler = MCPRequestHandler(grim)

    response = handler.handle_payload([])

    assert response["error"]["code"] == -32600
    assert response["error"]["message"] == "JSON-RPC request must be an object"
