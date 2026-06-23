"""JSON-RPC models used by the Grimoire MCP server."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

JSONRPC_VERSION: Literal["2.0"] = "2.0"
JSONRPCId = str | int | None


class JSONRPCError(BaseModel):
    """JSON-RPC error object."""

    code: int
    message: str
    data: Any | None = None


class JSONRPCRequest(BaseModel):
    """Single JSON-RPC request supported by the MCP skeleton."""

    model_config = ConfigDict(extra="forbid")

    jsonrpc: Literal["2.0"]
    id: JSONRPCId = None
    method: str
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("params", mode="before")
    @classmethod
    def _default_empty_params(cls, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        raise ValueError("params must be an object")


class JSONRPCResponse(BaseModel):
    """Single JSON-RPC response."""

    jsonrpc: Literal["2.0"] = JSONRPC_VERSION
    id: JSONRPCId = None
    result: dict[str, Any] | None = None
    error: JSONRPCError | None = None

    @model_validator(mode="after")
    def _require_result_or_error(self) -> "JSONRPCResponse":
        has_result = self.result is not None
        has_error = self.error is not None
        if has_result == has_error:
            raise ValueError("JSON-RPC response must contain exactly one of result or error")
        return self


__all__ = [
    "JSONRPC_VERSION",
    "JSONRPCError",
    "JSONRPCId",
    "JSONRPCRequest",
    "JSONRPCResponse",
]
