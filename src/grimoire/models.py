# src/grimoire/models.py
"""
Core data models for Grimoire.

Defines the canonical in-memory representations for all artifact types:
- Spell: prompt template with typed variables and message blocks
- Promptlet: reusable prompt component (safety rail, persona, etc.)
- Rune / CommandSpec / ParamSpec: skill contracts
- Ritual / RitualStep: multi-step prompt flows
- ConjuredPrompt: rendered output with provenance

Design Principles:
    - Pydantic v2 for validation + serialization
    - Immutable after construction (frozen models where sensible)
    - Content hashes for determinism / drift detection
    - All IDs are slash-separated paths (e.g. "engineering/bug_root_cause")
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

# =============================================================================
# ENUMERATIONS
# =============================================================================


class MessageRole(str, Enum):
    """Recognized message block roles in a spell."""
    SYSTEM = "SYSTEM"
    DEVELOPER = "DEVELOPER"
    USER = "USER"
    ASSISTANT_PREFILL = "ASSISTANT_PREFILL"


class VariableType(str, Enum):
    """Variable types supported in spell schemas."""
    STRING = "string"
    MULTILINE = "multiline"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    CHOICE = "choice"
    LIST = "list"


class RiskLevel(str, Enum):
    """Risk level for rune commands."""
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Permission(str, Enum):
    """Semantic permissions for runes."""
    READ_FS = "read_fs"
    WRITE_FS = "write_fs"
    NETWORK = "network"
    EXEC = "exec"


class RuneExportMode(str, Enum):
    """How runes are exposed when conjuring a spell."""
    NONE = "none"
    REFERENCE = "reference"
    INLINE = "inline"
    PROVIDER_TOOLS = "provider_tools"


class OutputContractType(str, Enum):
    """Supported output contract formats."""
    MARKDOWN = "markdown"
    JSON = "json"
    TEXT = "text"


# =============================================================================
# VARIABLE SCHEMA
# =============================================================================


class VariableSpec(BaseModel):
    """
    Schema for a single spell variable.

    Defines type, constraints, defaults, and interactive prompt text.
    """
    model_config = ConfigDict(extra="forbid")

    type: VariableType = VariableType.STRING
    required: bool = True
    default: Any = None
    ask: str | None = None
    description: str | None = None
    choices: list[str] | None = None  # for type=choice
    min_value: float | None = None
    max_value: float | None = None

    @model_validator(mode="after")
    def _validate_constraints(self) -> "VariableSpec":
        if self.type == VariableType.CHOICE and not self.choices:
            raise ValueError("Variable of type 'choice' must specify 'choices'")
        if self.default is not None:
            self.required = False
        return self


# =============================================================================
# MESSAGE BLOCK
# =============================================================================


class MessageBlock(BaseModel):
    """A rendered or raw message block within a spell."""
    model_config = ConfigDict(frozen=True)

    role: MessageRole
    content: str


# =============================================================================
# OUTPUT CONTRACT
# =============================================================================


class RubricInclude(BaseModel):
    """Reference to a rubric promptlet."""
    model_config = ConfigDict(extra="forbid")
    include: str


class OutputContract(BaseModel):
    """Output contract specifying expected format and rubrics."""
    model_config = ConfigDict(extra="forbid")

    type: OutputContractType = OutputContractType.MARKDOWN
    json_schema: dict[str, Any] | None = Field(default=None, alias="schema")
    rubric: list[str | RubricInclude] | None = None


# =============================================================================
# RUNE EXPORT CONFIG
# =============================================================================


class RuneExportConfig(BaseModel):
    """Configuration for how runes are exported alongside a spell."""
    model_config = ConfigDict(extra="forbid")

    mode: RuneExportMode = RuneExportMode.NONE
    tags: list[str] = Field(default_factory=list)
    ids: list[str] = Field(default_factory=list)


# =============================================================================
# SPELL
# =============================================================================


class Spell(BaseModel):
    """
    A structured prompt template.

    Contains metadata, typed variable schema, message blocks
    (SYSTEM/DEVELOPER/USER/ASSISTANT_PREFILL), optional output contract,
    and optional rune dependencies.

    The `raw_blocks` field holds the unparsed template text per role,
    while `source_path` records where the spell was loaded from.
    """
    model_config = ConfigDict(extra="forbid")

    # Metadata
    id: str
    name: str
    version: str = "1.0.0"
    tags: list[str] = Field(default_factory=list)
    description: str | None = None
    license: str | None = None

    # Variable schema
    variables: dict[str, VariableSpec] = Field(default_factory=dict)

    # Rune dependencies
    requires_runes: list[str] = Field(default_factory=list)
    suggests_runes: list[str] = Field(default_factory=list)
    runes_export: RuneExportConfig | None = None

    # Output contract
    output_contract: OutputContract | None = None

    # Message blocks (raw templates — not yet conjured)
    raw_blocks: list[MessageBlock] = Field(default_factory=list)

    # Provenance
    source_path: str | None = None
    content_hash: str | None = None

    @model_validator(mode="after")
    def _compute_hash(self) -> "Spell":
        """Compute content hash from raw blocks for drift detection."""
        if self.content_hash is None and self.raw_blocks:
            hasher = hashlib.sha256()
            for block in self.raw_blocks:
                hasher.update(block.role.value.encode())
                hasher.update(block.content.encode())
            object.__setattr__(self, "content_hash", hasher.hexdigest()[:16])
        return self

    def required_variables(self) -> dict[str, VariableSpec]:
        """Return only variables that are required and have no default."""
        return {k: v for k, v in self.variables.items() if v.required}

    def optional_variables(self) -> dict[str, VariableSpec]:
        """Return variables with defaults or not required."""
        return {k: v for k, v in self.variables.items() if not v.required}


# =============================================================================
# PROMPTLET
# =============================================================================


class Promptlet(BaseModel):
    """
    A reusable prompt component (safety rail, persona overlay, style, etc.).

    Promptlets are simple: an id and content string, loadable from files.
    """
    model_config = ConfigDict(frozen=True)

    id: str
    content: str
    source_path: str | None = None


# =============================================================================
# RUNE & COMMAND
# =============================================================================


class ParamSpec(BaseModel):
    """Parameter specification for a rune command."""
    model_config = ConfigDict(extra="forbid")

    name: str
    type: str = "string"
    required: bool = False
    default: Any = None
    description: str | None = None
    # JSON-schema-like constraints
    minimum: float | None = None
    maximum: float | None = None
    enum: list[str] | None = None
    pattern: str | None = None


class ReturnSpec(BaseModel):
    """Return type specification for a rune command."""
    model_config = ConfigDict(extra="allow")

    type: str = "object"
    properties: dict[str, Any] = Field(default_factory=dict)


class CommandExample(BaseModel):
    """Example invocation for a rune command."""
    model_config = ConfigDict(extra="forbid")

    call: dict[str, Any] = Field(default_factory=dict)
    expect: str | None = None


class CommandSpec(BaseModel):
    """
    A single command within a rune contract.

    Describes name, parameters, return schema, side effects,
    risk level, and examples.
    """
    model_config = ConfigDict(extra="forbid")

    name: str
    summary: str | None = None
    params: list[ParamSpec] = Field(default_factory=list)
    returns: ReturnSpec | None = None
    side_effects: list[str] = Field(default_factory=list)
    risk_level: RiskLevel | None = None
    requires_approval: bool = False
    examples: list[CommandExample] = Field(default_factory=list)


class RuneSpec(BaseModel):
    """
    A skill contract describing an action surface.

    Contains metadata, platform constraints, permissions,
    and a list of command specifications.
    """
    model_config = ConfigDict(extra="forbid")

    # Metadata
    id: str
    name: str
    version: str = "1.0.0"
    description: str | None = None
    tags: list[str] = Field(default_factory=list)

    # Constraints
    platforms: list[str] = Field(default_factory=lambda: ["any"])
    risk_level: RiskLevel = RiskLevel.LOW
    permissions: list[Permission] = Field(default_factory=list)
    requires_approval: bool = False

    # Commands
    commands: list[CommandSpec] = Field(default_factory=list)

    # Provenance
    source_path: str | None = None
    content_hash: str | None = None

    @model_validator(mode="after")
    def _compute_hash(self) -> "RuneSpec":
        """Compute content hash from commands for drift detection."""
        if self.content_hash is None and self.commands:
            hasher = hashlib.sha256()
            for cmd in self.commands:
                hasher.update(cmd.name.encode())
                if cmd.summary:
                    hasher.update(cmd.summary.encode())
            object.__setattr__(self, "content_hash", hasher.hexdigest()[:16])
        return self

    def get_command(self, name: str) -> CommandSpec | None:
        """Look up a command by name."""
        for cmd in self.commands:
            if cmd.name == name:
                return cmd
        return None


# =============================================================================
# RITUAL (stub — Phase 3 will expand)
# =============================================================================


class RitualStep(BaseModel):
    """A single step in a ritual flow."""
    model_config = ConfigDict(extra="allow")

    id: str
    spell: str | None = None
    when: str | None = None
    conjure: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)


class Ritual(BaseModel):
    """
    A multi-step prompt flow composed of spells.

    Phase 0 includes the data model only; evaluation is Phase 3.
    """
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    version: str = "1.0.0"
    steps: list[RitualStep] = Field(default_factory=list)
    source_path: str | None = None


# =============================================================================
# CONJURED PROMPT (render output)
# =============================================================================


class Provenance(BaseModel):
    """Provenance record for a conjured prompt."""
    model_config = ConfigDict(frozen=True)

    spell_id: str
    spell_hash: str | None = None
    variables_used: dict[str, str] = Field(default_factory=dict)
    includes_resolved: list[str] = Field(default_factory=list)
    runes_referenced: list[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ConjuredPrompt(BaseModel):
    """
    The output of conjuring a spell: rendered message blocks + provenance.

    Can be exported to provider-specific formats (OpenAI messages array, etc.).
    """
    model_config = ConfigDict(frozen=True)

    blocks: list[MessageBlock] = Field(default_factory=list)
    provenance: Provenance | None = None

    def to_messages(self, fmt: str = "openai") -> list[dict[str, str]]:
        """
        Export blocks as provider message arrays.

        Args:
            fmt: Target format — "openai" (default), "anthropic", "raw".

        Returns:
            List of {"role": ..., "content": ...} dicts.
        """
        role_map: dict[str, dict[MessageRole, str]] = {
            "openai": {
                MessageRole.SYSTEM: "system",
                MessageRole.DEVELOPER: "developer",
                MessageRole.USER: "user",
                MessageRole.ASSISTANT_PREFILL: "assistant",
            },
            "anthropic": {
                MessageRole.SYSTEM: "system",
                MessageRole.DEVELOPER: "system",
                MessageRole.USER: "user",
                MessageRole.ASSISTANT_PREFILL: "assistant",
            },
            "raw": {
                MessageRole.SYSTEM: "SYSTEM",
                MessageRole.DEVELOPER: "DEVELOPER",
                MessageRole.USER: "USER",
                MessageRole.ASSISTANT_PREFILL: "ASSISTANT_PREFILL",
            },
        }

        mapping = role_map.get(fmt, role_map["raw"])
        messages: list[dict[str, str]] = []

        for block in self.blocks:
            messages.append({
                "role": mapping.get(block.role, block.role.value),
                "content": block.content,
            })

        # Anthropic: merge consecutive system messages
        if fmt == "anthropic" and len(messages) > 1:
            merged: list[dict[str, str]] = []
            for msg in messages:
                if merged and merged[-1]["role"] == msg["role"] == "system":
                    merged[-1]["content"] += "\n\n" + msg["content"]
                else:
                    merged.append(msg)
            return merged

        return messages

    def to_text(self) -> str:
        """Render as plain text with role headers."""
        parts: list[str] = []
        for block in self.blocks:
            parts.append(f"# {block.role.value}\n{block.content}")
        return "\n\n".join(parts)


# =============================================================================
# GRIMOIRE MANIFEST
# =============================================================================


class GrimoireManifest(BaseModel):
    """
    The grimoire.yaml manifest describing a grimoire pack/repo.
    """
    model_config = ConfigDict(extra="allow")

    name: str = "default"
    version: str = "0.1.0"
    description: str | None = None
    authors: list[str] = Field(default_factory=list)
    license: str | None = None
    tags: list[str] = Field(default_factory=list)

    # Paths (relative to repo root)
    spell_paths: list[str] = Field(default_factory=lambda: ["spells/"])
    rune_paths: list[str] = Field(default_factory=lambda: ["runes/contracts/"])
    ritual_paths: list[str] = Field(default_factory=lambda: ["rituals/"])
    profile_paths: list[str] = Field(default_factory=lambda: ["profiles/"])
    promptlet_paths: list[str] = Field(default_factory=lambda: ["spells/promptlets/"])
    vars_path: str = "vars/defaults.yaml"
