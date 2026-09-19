<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/branding/logo_dark_grimoire.png">
    <img src="assets/branding/logo_light_grimoire.png" alt="grimoire" width="720">
  </picture>
</p>

# Grimoire

**Prompt & tool control plane for LLM applications.**

Grimoire is a CLI + Python library that keeps your prompts, tool contracts and
multi-step flows in one versioned, validated, deterministic place — and serves
them to runtimes at request time or exports them ahead of time.

```
spells      prompt templates with typed variables, message blocks and output contracts
promptlets  reusable prompt fragments (safety rails, personas, output rubrics)
runes       skill/tool contracts: commands, parameter schemas, risk & approval metadata
rituals     multi-step prompt flows with conditions and captured outputs
bundles     composition recipes (base spell + variants + injected promptlets + runes)
skilldocs   knowledge documents with tag-filterable sections
profiles    variable overlays (per user / persona / environment)
```

It powers the **llmcore · wairu · semantiscan** ecosystem (llmcore hard-depends on
it as *the* prompt/tool control plane) but has no runtime dependency on any of them —
just `pydantic`, `pyyaml`, `click` and `rich`.

## Highlights

- **Deterministic conjuring** — same inputs → same output, with full provenance
  (variables, includes, runes, timestamps) and SHA-256 content hashes for drift detection.
- **Typed variables** — string / int / float / bool / list / choice / json / path with
  defaults, validation, secret redaction and interactive fill.
- **Tool schemas from contracts** — every rune command becomes an OpenAI-style function
  schema, an MCP `tools/list` entry, or an llmcore/wairu tool definition; OWASP LLM
  Top-10 metadata rides along and is auditable.
- **Layered control plane (0.4.0)** — compose a shipped pack, an admin overlay and a user
  overlay into one view for *every* artifact type; strict fail-loud loading; per-layer
  validation; memoized catalog/tool schemas.
- **Two operating modes** — *live-bind* (runtimes call the library and conjure on demand)
  or *pre-bind* (`grimoire bind` exports runtime-native files in CI).
- **Intent discovery** — find spells or tool commands from a natural-language intent
  (in-memory fallback, or a semantiscan-backed index).
- **MCP server** — expose runes and prompts over JSON-RPC (`initialize`, `tools/list`,
  `tools/call`, `prompts/list`, `prompts/get`) with bearer-token auth.
- **Quality gates** — structural validation (`doctor`), style lint, golden-output tests,
  drift detection against running runtimes.

## Install

Requires Python 3.11+.

```bash
pip install "grimoire @ git+https://github.com/araray/grimoire.git@v0.4.0"

# optional extras
pip install "grimoire[mcp] @ git+https://github.com/araray/grimoire.git@v0.4.0"         # MCP server (FastAPI + uvicorn)
pip install "grimoire[federation] @ git+https://github.com/araray/grimoire.git@v0.4.0"  # llmcore event-envelope adapters
```

From a checkout: `pip install -e ".[dev]"`.

## Quick start

```bash
grimoire init my-grimoire && cd my-grimoire      # scaffold: grimoire.yaml, spells/, vars/, …

grimoire spell list                              # catalog
grimoire spell show examples/hello
grimoire spell vars examples/hello               # variables a spell needs

# Global options (--set, --vars, --profile, --format, --out) go BEFORE the subcommand
grimoire --set name=Alice conjure examples/hello
grimoire --set name=Alice --format openai conjure examples/hello
grimoire --set name=Alice conjure examples/hello --provenance
grimoire conjure examples/hello --ask-missing    # interactive fill

grimoire doctor                                  # broken includes, schema issues, missing deps
```

A spell is Markdown with YAML front matter and role-headed message blocks:

```markdown
---
id: examples/hello
name: Hello World Spell
version: 1.0.0
tags: [example]
variables:
  name:  { type: string, required: true, ask: "What is your name?" }
  topic: { type: string, required: false, default: "anything" }
---

# SYSTEM
You are a helpful assistant.

# USER
Hello {{ name }}! Let's talk about {{ topic }}.
```

Blocks can `{{ include("style/principal_swe") }}` promptlets, introspect runes
(`{{ runes.describe("devtools/git") }}`) and use `{{ var|default("…") }}` fallbacks.

## As a library

```python
from grimoire import Grimoire

g = Grimoire("/path/to/grimoire")                       # or Grimoire() for cwd

messages = g.conjure("examples/hello", variables={"name": "Alice"}).to_messages("openai")
tools    = g.tool_schemas(tags=["devtools"])            # OpenAI function-calling schemas from runes
missing  = g.missing_vars("engineering/rca", provided={"issue_title": "OOM"})
result   = g.bind("llmcore", tags=["engineering"])      # in-memory export; .write(dir) to persist
assert g.validate().ok and g.lint().ok
```

### Layered control plane

```python
g = Grimoire.layered([
    ("builtin", "/opt/app/grimoire",         False),   # shipped, read-only
    ("admin",   "/etc/app/grimoire",          True),   # overlay
    ("user",    "~/.config/app/grimoire",     True),   # highest precedence; scaffolded if missing
])
g.get_spell("agent/system")            # highest layer wins, for every artifact type
g.resolve_layer("agent/system")        # -> "user" | "admin" | "builtin"
g.validate(layer="user")               # validate one overlay in isolation (fail-loud startup)
g.write_spell(spell)                   # writes go to the highest writable layer
```

Layers load in strict mode by default: a parse failure or duplicate id inside any
layer raises `RepoError` naming the layer instead of being skipped.

### Intent discovery & MCP

```python
hits  = await g.find_by_intent("summarize a pull request for reviewers", top_k=3)
tools = await g.find_tools_by_intent("run the unit tests", max_risk="medium")
manifest = g.to_mcp_tool_manifest(tags=["devtools"])   # MCP tools/list payload
```

```bash
GRIMOIRE_MCP_TOKEN=secret grimoire mcp serve --host 127.0.0.1 --port 8765   # JSON-RPC at /mcp
```

## CLI overview

| Command | Purpose |
|---|---|
| `init` | Scaffold a new grimoire repository |
| `spell list\|show\|vars\|new\|edit\|rm` | Catalog, inspect and write spells |
| `conjure <id>` | Render a spell / bundle / ritual (`--format text\|openai\|anthropic\|json`) |
| `rune list\|show\|validate\|audit` | Tool contracts; `audit` reports OWASP coverage |
| `ritual list\|show\|dry-run\|run` | Multi-step flows |
| `bundle list\|show\|validate\|assemble` | Composition recipes |
| `skill list\|show\|validate\|docs\|export` | SkillDocs + contracts; export to `openai-tool-schema` / `llmcore-activities` / `wairu-tools` |
| `prompt lint\|test` | Style rules; golden-output regression tests |
| `bind semantiscan\|llmcore\|wairu` | Export runtime-native artifacts (`--dry-run`, `--tags`, `--spells`, `--runes`) |
| `sync from-wairu\|from-llmcore\|from-semantiscan\|drift` | Import runtime artifacts as runes/spells; detect drift |
| `mcp serve` | Serve runes and prompts over MCP JSON-RPC |
| `doctor` | Diagnose the repository |

Global options: `--repo`, `--profile` (repeatable), `--vars` (repeatable), `--set key=value`
(repeatable), `--format`, `--out`, `--log-level`.

## Documentation

- [Usage guide](docs/USAGE.md) — artifact formats, template syntax, variable system, full CLI reference, integration patterns
- [Library integration guide](docs/AS_LIBRARY.md) — the `Grimoire` facade, layered mode, lower-level components, recipes, error handling
- [Changelog](CHANGELOG.md)

## Development

```bash
pip install -e ".[dev]"
pytest                          # 670+ tests (unit + integration + golden)
pytest --cov=src/grimoire
ruff check src/ tests/
```

CI runs ruff and the test suite on Python 3.11 and 3.12 for every PR.

## License

MIT
