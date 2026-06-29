from __future__ import annotations

from grimoire.federation import (
    federate_mcp_request,
    federate_mcp_response,
    federate_mcp_tool_call,
    federate_rune_command,
    federate_rune_commands,
)
from grimoire.mcp_server.models import JSONRPCError, JSONRPCRequest, JSONRPCResponse
from grimoire.models import CommandSpec, Permission, RiskLevel, RuneSpec


def test_federate_mcp_request_normalizes_jsonrpc_request() -> None:
    request = JSONRPCRequest(
        jsonrpc="2.0",
        id="req-1",
        method="tools/call",
        params={
            "name": "devtools__git__status",
            "arguments": {"porcelain": True},
        },
    )

    federated = federate_mcp_request(request, correlation_id="corr-1")

    assert federated.event_id == "grimoire-mcp-request-req-1-tools/call"
    assert federated.source_system == "grimoire"
    assert federated.source_component == "mcp.server"
    assert federated.category == "mcp"
    assert federated.event_type == "mcp.request.tools_call"
    assert federated.correlation_id == "corr-1"
    assert federated.payload["method"] == "tools/call"
    assert federated.payload["params"]["name"] == "devtools__git__status"


def test_federate_mcp_response_marks_jsonrpc_error() -> None:
    response = JSONRPCResponse(
        id="req-2",
        error=JSONRPCError(code=-32602, message="Invalid params"),
    )

    federated = federate_mcp_response(
        response,
        request_method="tools/call",
        correlation_id="corr-2",
    )

    assert federated.event_id == "grimoire-mcp-response-req-2-tools_call-error"
    assert federated.event_type == "mcp.response.tools_call.error"
    assert federated.severity == "error"
    assert federated.payload["error"]["code"] == -32602
    assert federated.payload["error"]["message"] == "Invalid params"


def test_federate_mcp_tool_call_pending_approval() -> None:
    tool = {
        "name": "wairu__shell__run",
        "_meta": {
            "grimoire.rune_id": "wairu/shell",
            "grimoire.command_name": "run",
            "grimoire.risk_level": "high",
            "grimoire.owasp_categories": ["LLM06_excessive_agency"],
            "grimoire.requires_approval": True,
            "grimoire.execution_target": "local",
            "grimoire.tool_name": "wairu__shell__run",
        },
    }
    result = {
        "isError": False,
        "_meta": {
            "grimoire.call_status": "pending_approval",
            "grimoire.pending_tool": "wairu__shell__run",
        },
    }

    federated = federate_mcp_tool_call(
        tool,
        {"command": "rm -rf /tmp/example"},
        result=result,
    )

    assert federated.event_id == "grimoire-mcp-tool-call-wairu__shell__run-pending_approval"
    assert federated.event_type == "mcp.tool_call.pending_approval"
    assert federated.severity == "warning"
    assert federated.payload["rune_id"] == "wairu/shell"
    assert federated.payload["command_name"] == "run"
    assert federated.payload["risk_level"] == "high"
    assert federated.payload["owasp_categories"] == ["LLM06_excessive_agency"]
    assert "owasp:LLM06_excessive_agency" in federated.tags
    assert federated.payload["requires_approval"] is True
    assert federated.payload["arguments"]["command"] == "rm -rf /tmp/example"


def test_federate_mcp_tool_call_unavailable_is_error() -> None:
    tool = {
        "name": "devtools__git__status",
        "_meta": {
            "grimoire.rune_id": "devtools/git",
            "grimoire.command_name": "status",
            "grimoire.risk_level": "low",
            "grimoire.requires_approval": False,
        },
    }
    result = {
        "isError": True,
        "_meta": {"grimoire.call_status": "unavailable"},
    }

    federated = federate_mcp_tool_call(tool, {"porcelain": True}, result=result)

    assert federated.event_type == "mcp.tool_call.unavailable"
    assert federated.severity == "error"
    assert federated.payload["risk_level"] == "low"


def test_federate_rune_command_uses_risk_and_approval_metadata() -> None:
    command = CommandSpec(
        name="run",
        summary="Run a shell command",
        risk_level=RiskLevel.HIGH,
        owasp_categories=["LLM05_supply_chain"],
        requires_approval=True,
        side_effects=["executes shell command"],
        execution_target="local",
    )
    rune = RuneSpec(
        id="wairu/shell",
        name="Shell",
        risk_level=RiskLevel.MEDIUM,
        owasp_categories=["LLM06_excessive_agency"],
        permissions=[Permission.EXEC],
        tags=["runtime", "shell"],
        commands=[command],
    )

    federated = federate_rune_command(rune, command)

    assert federated.event_id == "grimoire-rune-command-wairu/shell-run"
    assert federated.source_system == "grimoire"
    assert federated.source_component == "runes.registry"
    assert federated.category == "rune"
    assert federated.event_type == "rune.command_registered"
    assert federated.severity == "warning"
    assert "risk:high" in federated.tags
    assert "owasp:LLM05_supply_chain" in federated.tags
    assert federated.payload["rune_id"] == "wairu/shell"
    assert federated.payload["command_name"] == "run"
    assert federated.payload["risk_level"] == "high"
    assert federated.payload["owasp_categories"] == ["LLM05_supply_chain"]
    assert federated.payload["requires_approval"] is True
    assert federated.payload["permissions"] == ["exec"]


def test_federate_rune_commands_maps_all_commands() -> None:
    rune = RuneSpec(
        id="devtools/git",
        name="Git",
        risk_level=RiskLevel.LOW,
        commands=[
            CommandSpec(name="status", summary="Show status"),
            CommandSpec(name="diff", summary="Show diff"),
        ],
    )

    events = federate_rune_commands(rune)

    assert [event.payload["command_name"] for event in events] == ["status", "diff"]
    assert all(event.payload["risk_level"] == "low" for event in events)
