# Grimoire — Library Integration Guide

> How to use Grimoire as a Python library for runtime prompt assembly, tool schema generation, and in-memory binding — without touching the CLI.

This document is the definitive reference for integrating Grimoire into your Python application. It covers the `Grimoire` facade, the lower-level components for advanced use cases, real-world recipes, architecture, and error handling.

---

## Table of Contents

- [Quick Start](#quick-start)
- [The Grimoire Facade](#the-grimoire-facade)
  - [Construction](#construction)
  - [Conjuring Prompts](#conjuring-prompts)
  - [Variable Introspection](#variable-introspection)
  - [Tool Schema Generation](#tool-schema-generation)
  - [In-Memory Binding](#in-memory-binding)
  - [Validation & Linting](#validation--linting)
  - [Catalog & Discovery](#catalog--discovery)
  - [Convenience Accessors](#convenience-accessors)
- [Output Formats](#output-formats)
- [Provenance Tracking](#provenance-tracking)
- [Lower-Level Components](#lower-level-components)
  - [GrimoireRepo](#grimoirerepo)
  - [ConjureEngine](#conjureengine)
  - [BundleAssembler](#bundleassembler)
  - [RitualEvaluator](#ritualevaluator)
  - [Binders](#binders)
- [Integration Recipes](#integration-recipes)
  - [llmcore: Chat with Grimoire Prompts](#llmcore-chat-with-grimoire-prompts)
  - [llmcore: Agent with Grimoire Tools](#llmcore-agent-with-grimoire-tools)
  - [semantiscan: RAG Prompt Assembly](#semantiscan-rag-prompt-assembly)
  - [wairu: Tool Discovery & Policy Injection](#wairu-tool-discovery--policy-injection)
  - [CI/CD: Validation Gate](#cicd-validation-gate)
  - [Agentic: Self-Selecting Prompts](#agentic-self-selecting-prompts)
- [Error Handling](#error-handling)
- [Architecture](#architecture)
- [Thread Safety & Performance](#thread-safety--performance)
- [Type Reference](#type-reference)

---

## Quick Start

```python
from grimoire import Grimoire

# Load a grimoire repository
g = Grimoire("/path/to/my-grimoire")

# Conjure a spell → get OpenAI messages
result = g.conjure("engineering/root_cause_analysis", variables={
    "issue_title": "Database connection timeout",
    "symptoms": "Queries hang after 30s, connection pool exhausted",
})
messages = result.to_messages("openai")
# → [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]

# Get tool schemas for function calling
tools = g.tool_schemas(tags=["devtools"])
# → [{"type": "function", "function": {"name": "devtools__git__status", ...}}, ...]

# Check what variables a spell needs
missing = g.missing_vars("engineering/root_cause_analysis")
# → {"issue_title": VariableSpec(...), "symptoms": VariableSpec(...)}
```

That's the entire setup. No binders to instantiate, no engines to wire, no promptlet dicts to build. The facade handles it all.

---

## The Grimoire Facade

### Construction

```python
from grimoire import Grimoire

# Load from explicit path
g = Grimoire("/path/to/grimoire-repo")

# Load from current directory
g = Grimoire()

# Non-strict mode: leave unresolved variables as {{ placeholders }}
# instead of raising MissingVariableError
g = Grimoire("/path/to/repo", strict=False)
```

Construction loads the repository, indexes all artifacts, wires the conjure engine with all discovered promptlets and runes, and prepares the bundle assembler. Typical load time is under 50ms for repositories with hundreds of artifacts.

#### Reloading after disk changes

```python
# If files were modified on disk, reload to pick up changes
g.reload()
```

#### Properties

```python
g.name       # → "my-grimoire"  (from grimoire.yaml)
g.version    # → "1.0.0"
g.repo       # → GrimoireRepo instance (read-only access to internals)
```

---

### Conjuring Prompts

#### Polymorphic conjure

The `conjure()` method auto-detects the artifact type by looking up the ID across spells, bundles, and rituals (in that order):

```python
# Spell → returns ConjuredPrompt
result = g.conjure("engineering/root_cause_analysis", variables={
    "issue_title": "OOM crash",
    "symptoms": "Process killed by OOM killer at 03:42 UTC",
})
assert isinstance(result, ConjuredPrompt)

# Bundle → returns ConjuredPrompt (after assembly + variant selection)
result = g.conjure("bundles/engineering/rca_with_tools", variables={
    "issue_title": "OOM crash",
    "symptoms": "Process killed",
}, context={"provider": "anthropic"})  # selects the anthropic variant
assert isinstance(result, ConjuredPrompt)

# Ritual → returns list[ConjuredRitualStep]
steps = g.conjure("rituals/rca_loop", variables={
    "issue_title": "OOM crash",
    "symptoms": "Process killed",
})
assert isinstance(steps, list)
for step in steps:
    if not step.skipped:
        print(step.conjured.to_text())
```

#### Typed conjure methods

When you know the artifact type and want static type safety:

```python
# Spell only — always returns ConjuredPrompt
prompt: ConjuredPrompt = g.conjure_spell("engineering/root_cause_analysis", variables={...})

# Bundle only — always returns ConjuredPrompt
prompt: ConjuredPrompt = g.conjure_bundle(
    "bundles/engineering/rca_with_tools",
    variables={...},
    context={"provider": "anthropic"},
)

# Ritual only — always returns list[ConjuredRitualStep]
steps: list[ConjuredRitualStep] = g.conjure_ritual("rituals/rca_loop", variables={...})
```

#### Parameter reference

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `artifact_id` | `str` | required | Spell, bundle, or ritual ID |
| `variables` | `dict[str, Any] \| None` | `None` | Explicit variable values (highest precedence) |
| `defaults` | `dict[str, Any] \| None` | grimoire defaults | Default values (lowest precedence) |
| `context` | `dict[str, str] \| None` | `None` | Bundle variant selection context |
| `strict` | `bool \| None` | instance default | Override strict mode for this call |

---

### Variable Introspection

#### Get the full schema

```python
schema = g.spell_vars("engineering/root_cause_analysis")
# Returns: dict[str, VariableSpec]

for name, spec in schema.items():
    print(f"{name}: type={spec.type.value}, required={spec.required}, "
          f"default={spec.default}, ask={spec.ask!r}")
```

Output:
```
issue_title: type=string, required=True, default=None, ask='Brief title of the issue or incident'
symptoms: type=multiline, required=True, default=None, ask='Observed symptoms (one per line)'
environment: type=string, required=False, default='production', ask='Environment where the issue occurred'
context: type=multiline, required=False, default='', ask='Relevant codebase or system context'
```

#### Find missing variables

```python
# What's still needed for this spell?
missing = g.missing_vars("engineering/root_cause_analysis")
# → {"issue_title": VariableSpec(...), "symptoms": VariableSpec(...)}
# (environment has a default, context has a default → not missing)

# After the user provides some values:
missing = g.missing_vars("engineering/root_cause_analysis", provided={
    "issue_title": "Timeout bug",
})
# → {"symptoms": VariableSpec(...)}

# Works for bundles too:
missing = g.missing_vars("bundles/engineering/rca_with_tools")
```

This is ideal for building interactive UIs or agent loops that progressively collect required inputs.

---

### Tool Schema Generation

Generate OpenAI-compatible function-calling tool definitions from runes:

```python
# All runes
tools = g.tool_schemas()

# Filter by tags
tools = g.tool_schemas(tags=["devtools"])

# Specific runes
tools = g.tool_schemas(rune_ids=["devtools/git", "semantiscan/query"])
```

Each rune command becomes one tool definition:

```json
{
  "type": "function",
  "function": {
    "name": "devtools__git__status",
    "description": "Show working tree status",
    "parameters": {
      "type": "object",
      "properties": {
        "porcelain": {
          "type": "bool",
          "default": true
        }
      }
    }
  }
}
```

Tool names follow the pattern `{rune_id}__{command_name}` with `/` replaced by `__` for JSON compatibility.

---

### In-Memory Binding

Produce bind artifacts in memory without writing to disk:

```python
# Bind for llmcore
result = g.bind("llmcore")
assert result.ok
print(f"Produced {len(result.files)} files, hash={result.compiled_hash}")

# Iterate over produced files
for f in result.files:
    print(f"  {f.relative_path} ({len(f.content)} bytes)")
    # f.content is the full file content as a string

# Filter by tags or specific artifacts
result = g.bind("llmcore", tags=["engineering"])
result = g.bind("llmcore", spell_ids=["examples/greet"])
result = g.bind("wairu", rune_ids=["devtools/git"])

# Specify sub-format
result = g.bind("semantiscan", fmt="toml")
result = g.bind("semantiscan", fmt="legacy_tmpl")

# Write to disk when ready
written_paths = result.write("/path/to/exports/llmcore/")
```

Supported targets: `"llmcore"`, `"semantiscan"`, `"wairu"` (or use `BindTarget` enum).

---

### Validation & Linting

```python
# Full repository validation (structure, references, schemas)
val_result = g.validate()
print(f"Valid: {val_result.ok}")
for diag in val_result.diagnostics:
    print(f"  [{diag.severity.value}] {diag.source}: {diag.message}")

# Lint a single spell (style rules)
lint_result = g.lint("engineering/root_cause_analysis")

# Lint all spells at once
lint_all = g.lint()

# Custom lint configuration
from grimoire.validate.rules import LintConfig
config = LintConfig(
    forbidden_tokens=["TODO", "FIXME", "PLACEHOLDER", "HACK"],
    max_user_block_chars=5000,
    check_engineering_quality=True,
    check_sensitivity=True,
)
lint_result = g.lint("engineering/rca", config=config)
```

---

### Catalog & Discovery

Get an agent-friendly JSON catalog of everything in the grimoire:

```python
import json

catalog = g.catalog()
print(json.dumps(catalog, indent=2))
```

```json
{
  "grimoire": {"name": "my-grimoire", "version": "1.0.0"},
  "spells": [
    {"id": "engineering/root_cause_analysis", "name": "Root Cause Analysis", "version": "1.0.0", "tags": ["engineering", "debugging", "rca"]},
    {"id": "examples/greet", "name": "Greeting Spell", "version": "1.0.0", "tags": ["example", "test"]}
  ],
  "runes": [
    {"id": "devtools/git", "name": "Git (read-only diagnostics)", "version": "1.0.0", "tags": ["devtools", "vcs", "engineering"], "commands": ["status", "diff"]}
  ],
  "rituals": [
    {"id": "rituals/rca_loop", "name": "RCA Loop", "steps": 2}
  ],
  "bundles": [...],
  "skilldocs": [...],
  "promptlets": [...]
}
```

This catalog is designed for agent self-discovery: an LLM agent can read the catalog to decide which spell or rune to use for a given task.

---

### Convenience Accessors

Direct access to individual artifacts and filtered listings:

```python
# Get by ID (raises ArtifactNotFoundError if missing)
spell = g.get_spell("engineering/root_cause_analysis")
rune = g.get_rune("devtools/git")
bundle = g.get_bundle("bundles/engineering/rca_with_tools")
ritual = g.get_ritual("rituals/rca_loop")

# Filtered listings
eng_spells = g.list_spells(tags=["engineering"])
devtools = g.list_runes(tags=["devtools"])
all_bundles = g.list_bundles()
all_rituals = g.list_rituals()
```

---

## Output Formats

A `ConjuredPrompt` can export to multiple formats:

```python
result = g.conjure("examples/greet", variables={"user_name": "Alice"})

# Plain text with role headers
text = result.to_text()
# → "# SYSTEM\nYou are a careful...\n\n# USER\nPlease greet Alice in English."

# OpenAI message array
messages = result.to_messages("openai")
# → [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]

# Anthropic message array (DEVELOPER merged into system)
messages = result.to_messages("anthropic")

# Raw messages (original role names preserved)
messages = result.to_messages("raw")

# Individual blocks
for block in result.blocks:
    print(f"[{block.role.value}] {block.content[:80]}...")
```

---

## Provenance Tracking

Every conjured prompt carries a provenance record:

```python
result = g.conjure("engineering/rca", variables={"issue_title": "Bug", "symptoms": "crash"})

prov = result.provenance
print(f"Spell:    {prov.spell_id}")           # → "engineering/root_cause_analysis"
print(f"Hash:     {prov.spell_hash}")          # → "a1b2c3d4e5f6a7b8"
print(f"Includes: {prov.includes_resolved}")   # → ["safety/base_engineering", "style/principal_swe"]
print(f"Runes:    {prov.runes_referenced}")    # → []
print(f"Vars:     {prov.variables_used}")      # → {"issue_title": "Bug", "symptoms": "crash", ...}
# (SECRET variables are shown as "[redacted]")
```

Provenance enables: drift detection, audit trails, cache invalidation, and debugging which promptlets contributed to a final prompt.

---

## Lower-Level Components

The `Grimoire` facade is built on top of these components. Use them directly when you need fine-grained control.

### GrimoireRepo

The repository loader — discovers and indexes all artifacts from disk:

```python
from grimoire import GrimoireRepo

repo = GrimoireRepo.load("/path/to/grimoire")

# Access artifacts
spell = repo.get_spell("engineering/rca")
rune = repo.get_rune("devtools/git")
promptlet = repo.get_promptlet("safety/base_engineering")

# Listings
spells = repo.list_spells(tags=["engineering"])
runes = repo.list_runes(tags=["devtools"])

# Defaults
defaults = repo.default_vars  # → dict from vars/defaults.yaml

# Catalog
catalog = repo.catalog()

# Facade accessors
repo.prompts.list(tags=["engineering"])
repo.prompts.get("engineering/rca")
repo.prompts.bundles()
repo.skills.contracts(tags=["devtools"])
repo.skills.docs()
```

### ConjureEngine

The deterministic rendering engine — stateless, all context is passed in:

```python
from grimoire import ConjureEngine

engine = ConjureEngine(
    promptlets={p.id: p for p in repo.list_promptlets()},
    runes={r.id: r for r in repo.list_runes()},
)

result = engine.conjure(
    spell,
    variables={"issue_title": "Bug", "symptoms": "crash"},
    defaults=repo.default_vars,
    strict=True,
)
```

### BundleAssembler

Materializes a bundle into a conjurable spell:

```python
from grimoire import BundleAssembler

assembler = BundleAssembler(repo)
assembled_spell = assembler.assemble(
    bundle,
    context={"provider": "anthropic"},  # variant selection
    variables={"issue_title": "Bug"},
)

# The assembled spell can be passed to ConjureEngine
result = engine.conjure(assembled_spell, variables={...})
```

### RitualEvaluator

Evaluates multi-step ritual flows:

```python
from grimoire import RitualEvaluator

evaluator = RitualEvaluator(repo, engine=engine)

# Dry run (inspect without conjuring)
plan = evaluator.dry_run(ritual)
print(f"OK: {plan.ok}, missing spells: {plan.missing_spells}")

# Full evaluation
steps = evaluator.evaluate(ritual, variables={"issue_title": "Bug", "symptoms": "crash"})
for step in steps:
    if step.skipped:
        print(f"  [{step.step_id}] SKIPPED: {step.skip_reason}")
    else:
        print(f"  [{step.step_id}] → {step.spell_id}")
        print(step.conjured.to_text())
```

### Binders

Low-level binder classes for each target:

```python
from grimoire.bind import LLMCoreBinder, SemantiscanBinder, WairuBinder

binder = LLMCoreBinder()
result = binder.bind(repo, tags=["engineering"])
result.compute_hash()
result.write("/path/to/exports/llmcore/")
```

---

## Integration Recipes

### llmcore: Chat with Grimoire Prompts

```python
from grimoire import Grimoire
from llmcore import LLMCore

g = Grimoire("/path/to/grimoire")
llm = await LLMCore.create()

# Conjure a spell
prompt = g.conjure("engineering/root_cause_analysis", variables={
    "issue_title": "Connection pool exhaustion",
    "symptoms": "All database queries timeout after 30s",
    "environment": "production k8s cluster",
})

# Extract system message and user message
messages = prompt.to_messages("openai")
system_msg = next((m["content"] for m in messages if m["role"] == "system"), None)
user_msg = next((m["content"] for m in messages if m["role"] == "user"), "")

# Send to LLM
response = await llm.chat(
    message=user_msg,
    system_message=system_msg,
    enable_rag=False,  # Grimoire controls all context
)
```

### llmcore: Agent with Grimoire Tools

```python
g = Grimoire("/path/to/grimoire")

# Get tool schemas for the agent
tools = g.tool_schemas(tags=["devtools", "engineering"])

# Get the tool-calling policy prompt
policy = g.conjure("agentic/tool_calling_policy_low_risk")
system_msg = policy.to_messages("openai")[0]["content"]

# Use in an agent loop
response = await llm.chat(
    message="Investigate why tests are failing on main",
    system_message=system_msg,
    tools=[Tool.from_dict(t) for t in tools],
    enable_rag=False,
)
```

### semantiscan: RAG Prompt Assembly

```python
g = Grimoire("/path/to/grimoire")

# semantiscan retrieves chunks, then Grimoire assembles the prompt
result = g.conjure("semantiscan/rag_default", variables={
    "context": "\n---\n".join(chunk.text for chunk in retrieved_chunks),
    "question": user_query,
})

# Pass the full prompt to llmcore (external RAG pattern)
response = await llm.chat(
    message=result.to_text(),
    enable_rag=False,
)
```

### wairu: Tool Discovery & Policy Injection

```python
g = Grimoire("/path/to/grimoire")

# Discover available tools from rune contracts
catalog = g.catalog()
available_runes = catalog["runes"]

# Get tool schemas for all runes the session should have
tools = g.tool_schemas(rune_ids=[r["id"] for r in available_runes])

# Inject the appropriate policy spell based on risk level
runes = [g.get_rune(r["id"]) for r in available_runes]
has_high_risk = any(r.risk_level.value == "high" for r in runes)

policy_spell = (
    "agentic/tool_calling_policy_high_risk_requires_approval"
    if has_high_risk
    else "agentic/tool_calling_policy_low_risk"
)
policy = g.conjure(policy_spell)
```

### CI/CD: Validation Gate

```python
import sys
from grimoire import Grimoire

g = Grimoire(".")

# Step 1: Validate structure
val = g.validate()
if not val.ok:
    for d in val.diagnostics:
        print(f"[{d.severity.value}] {d.source}: {d.message}", file=sys.stderr)
    sys.exit(1)

# Step 2: Lint all spells
lint = g.lint()
errors = [d for d in lint.diagnostics if d.severity.value == "error"]
if errors:
    for d in errors:
        print(f"[LINT ERROR] {d.source}: {d.message}", file=sys.stderr)
    sys.exit(1)

# Step 3: Bind and export
for target in ("llmcore", "semantiscan", "wairu"):
    result = g.bind(target)
    result.write(f"exports/{target}/")
    print(f"✓ {target}: {len(result.files)} files, hash={result.compiled_hash}")
```

### Agentic: Self-Selecting Prompts

An agent that uses the catalog to choose which spell to conjure:

```python
g = Grimoire("/path/to/grimoire")

# Give the agent the catalog so it can self-select
catalog = g.catalog()
catalog_json = json.dumps(catalog, indent=2)

# Agent system prompt includes the catalog
agent_system = f"""You have access to a grimoire with these spells:

{catalog_json}

When given a task, select the most appropriate spell, determine the
required variables, and request conjuring.
"""

# After the agent selects a spell:
selected_id = "engineering/root_cause_analysis"

# Check what variables the agent needs to provide
missing = g.missing_vars(selected_id, provided=agent_context)

# Once variables are gathered, conjure
result = g.conjure(selected_id, variables=agent_variables)
messages = result.to_messages("openai")
```

---

## Error Handling

All grimoire errors inherit from `GrimoireError`:

```python
from grimoire import (
    GrimoireError,           # Base exception
    ArtifactNotFoundError,   # Spell/rune/ritual/bundle not found
    AmbiguousArtifactError,  # ID matches multiple types
    MissingVariableError,    # Required variable not provided (strict mode)
    CircularIncludeError,    # Include directives form a cycle
    IncludeError,            # Include target not found
    BundleAssemblyError,     # Bundle base_template not found or inject failure
    RitualError,             # Ritual evaluation failure
    SpellParseError,         # Malformed *.spell.md
    RuneParseError,          # Malformed *.rune.yaml
    RepoError,               # Repository loading failure
)
```

Recommended pattern:

```python
try:
    result = g.conjure(spell_id, variables=user_vars)
except ArtifactNotFoundError:
    # Unknown spell/bundle/ritual ID
    logger.warning(f"Artifact not found: {spell_id}")
except MissingVariableError as e:
    # Required variable not provided and strict=True
    # e.args[0] contains the variable name and spell ID
    logger.error(f"Missing variable: {e}")
except GrimoireError as e:
    # Catch-all for any grimoire error
    logger.error(f"Grimoire error: {e}")
```

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│                  Grimoire Facade                │
│    conjure() · tool_schemas() · bind() · ...    │
├──────────┬───────────┬──────────┬───────────────┤
│  Conjure │  Bundle   │ Ritual   │    Binders    │
│  Engine  │ Assembler │Evaluator │ llm·sem·wairu │
├──────────┴───────────┴──────────┴───────────────┤
│                  GrimoireRepo                   │
│   spell discovery · rune indexing · promptlets  │
├─────────────────────────────────────────────────┤
│                    Parsers                      │
│  spell.md · rune.yaml · ritual.yaml · bundle    │
├─────────────────────────────────────────────────┤
│                   Validators                    │
│   structural · lint · drift detection · golden  │
└─────────────────────────────────────────────────┘
```

Data flow for a typical `conjure()` call:

```
conjure("bundles/engineering/rca_with_tools", variables={...}, context={...})
  │
  ├─ 1. Look up bundle in repo._bundles
  ├─ 2. BundleAssembler.assemble(bundle, context)
  │      ├─ Load base spell
  │      ├─ Select variant (first match on context)
  │      ├─ Inject promptlets at injection points
  │      └─ Return assembled Spell
  ├─ 3. ConjureEngine.conjure(assembled_spell, variables, defaults)
  │      ├─ Build effective variable map (precedence chain)
  │      ├─ For each message block:
  │      │    ├─ Resolve includes (recursive, cycle-detected)
  │      │    ├─ Resolve rune introspection
  │      │    └─ Resolve variables
  │      └─ Build provenance record
  └─ 4. Return ConjuredPrompt(blocks, provenance)
```

---

## Thread Safety & Performance

A `Grimoire` instance is safe for concurrent reads: multiple threads can call `conjure()`, `tool_schemas()`, `catalog()`, etc. simultaneously without locking.

It is **not** safe for concurrent mutation. If the repository files change on disk, call `g.reload()` from a single thread before subsequent reads.

Performance characteristics:
- **Construction**: ~20–50ms for a typical repository (hundreds of artifacts)
- **Conjure (spell)**: ~1–5ms (dominated by include resolution)
- **Conjure (bundle)**: ~2–10ms (assembly + conjuring)
- **tool_schemas()**: <1ms (in-memory transformation)
- **bind()**: ~10–50ms depending on artifact count and target

---

## Type Reference

### Core types

| Type | Module | Description |
|------|--------|-------------|
| `Grimoire` | `grimoire.api` | High-level facade |
| `GrimoireRepo` | `grimoire.store.repo` | Repository loader |
| `ConjureEngine` | `grimoire.conjure.engine` | Rendering engine |
| `BundleAssembler` | `grimoire.bundles.assembler` | Bundle materializer |
| `RitualEvaluator` | `grimoire.rituals.evaluator` | Ritual step evaluator |

### Model types

| Type | Description |
|------|-------------|
| `Spell` | Parsed spell template |
| `RuneSpec` | Parsed rune contract |
| `Bundle` | Parsed bundle recipe |
| `Ritual` | Parsed ritual flow |
| `SkillDoc` | Parsed knowledge document |
| `Promptlet` | Reusable prompt fragment |
| `ConjuredPrompt` | Rendered output (blocks + provenance) |
| `ConjuredRitualStep` | One evaluated ritual step |
| `MessageBlock` | Single role+content pair |
| `Provenance` | Audit trail for a conjured prompt |
| `VariableSpec` | Variable schema (type, required, default, ask) |
| `VariableType` | Enum: string, multiline, integer, float, boolean, choice, list, json, path |

### Bind types

| Type | Description |
|------|-------------|
| `BindResult` | Aggregated output of a bind operation |
| `BoundFile` | Single file with relative_path + content |
| `BindTarget` | Enum: llmcore, semantiscan, wairu |
| `BindFormat` | Enum: toml, legacy_tmpl, registry_bundle, tool_pack |

### Validation types

| Type | Description |
|------|-------------|
| `ValidationResult` | Collection of diagnostics with `.ok` property |
| `Diagnostic` | Single issue: severity, source, message |
| `Severity` | Enum: error, warning, info |
| `LintConfig` | Lint rule configuration |

All types are importable from the top-level `grimoire` package:

```python
from grimoire import (
    Grimoire, GrimoireRepo, ConjureEngine,
    Spell, RuneSpec, Bundle, Ritual,
    ConjuredPrompt, ConjuredRitualStep,
    VariableSpec, VariableType,
    BindResult, BindTarget,
    ArtifactNotFoundError, MissingVariableError,
)
```
