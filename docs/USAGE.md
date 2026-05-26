# Grimoire — Usage Guide

> **Version 0.1.0** — Prompt & tool control plane for the llmcore ecosystem.

Grimoire manages **spells** (prompt templates), **runes** (skill contracts), **rituals** (multi-step flows), **bundles** (composition recipes), and **skilldocs** (knowledge artifacts) — and can **conjure** them into provider-ready messages or **bind** them into runtime-native formats for llmcore, semantiscan, and wairu.

This guide covers every feature: artifact formats, CLI commands, the library API, variable resolution, binding, validation, and integration patterns.

---

## Table of Contents

- [Getting Started](#getting-started)
- [Artifact Formats](#artifact-formats)
  - [Spells](#spells)
  - [Promptlets](#promptlets)
  - [Runes](#runes)
  - [Rituals](#rituals)
  - [Bundles](#bundles)
  - [SkillDocs](#skilldocs)
- [Template Syntax](#template-syntax)
- [Variable System](#variable-system)
- [CLI Reference](#cli-reference)
- [Library API (Live-Bind)](#library-api-live-bind)
- [Binding to Runtime Targets](#binding-to-runtime-targets)
- [Sync & Drift Detection](#sync--drift-detection)
- [Validation & Linting](#validation--linting)
- [Repository Structure](#repository-structure)
- [Profiles & Overlays](#profiles--overlays)
- [Integration Patterns](#integration-patterns)

---

## Getting Started

### Install

```bash
pip install -e ".[dev]"
```

### Create a grimoire

```bash
grimoire init my-project
cd my-project
```

This creates a skeleton with a manifest (`grimoire.yaml`), a starter spell, a starter promptlet, and a `vars/defaults.yaml`.

### Your first conjure

```bash
# List available spells
grimoire spell list

# Conjure the starter spell
grimoire conjure examples/hello --set name=Alice

# Same thing, but as OpenAI messages
grimoire --format openai conjure examples/hello --set name=Alice
```

---

## Artifact Formats

### Spells

A **spell** (`*.spell.md`) is a structured prompt template with YAML frontmatter and Markdown message blocks.

```markdown
---
id: engineering/bug_root_cause
name: Root cause analysis (engineering-grade)
version: 1.0.0
tags: [debugging, rca, troubleshooting, systems]
description: Structured RCA for software incidents.
requires_runes:
  - engineering/observability
suggests_runes:
  - devtools/git
runes_export:
  mode: reference
  tags: [engineering, observability]
variables:
  issue_title:
    type: string
    required: true
    ask: "Issue title"
  symptoms:
    type: multiline
    required: true
    ask: "Observed symptoms"
  environment:
    type: multiline
    required: false
    default: "(unknown)"
output_contract:
  type: markdown
  rubric:
    - include: rubric/engineering_quality
---

# SYSTEM
{{ include("safety/base_engineering") }}

# DEVELOPER
{{ include("style/principal_swe") }}

# USER
Root-cause analysis for: {{ issue_title }}

## Symptoms
{{ symptoms }}

## Environment
{{ environment }}

## Requested output
- hypotheses ranked by likelihood
- evidence needed per hypothesis
- experiments to confirm/deny
- likely root cause
- fix plan with rollback strategy
- validation steps
```

#### Message block roles

| Role | Heading | OpenAI mapping | Anthropic mapping |
|------|---------|----------------|-------------------|
| System instructions | `# SYSTEM` | `system` | `system` |
| Developer context | `# DEVELOPER` | `developer` | `system` (merged) |
| User request | `# USER` | `user` | `user` |
| Assistant prefill | `# ASSISTANT_PREFILL` | `assistant` | `assistant` |

#### Variable types

| Type | Description | Extra fields |
|------|-------------|-------------|
| `string` | Single-line text | — |
| `multiline` | Multi-line text | — |
| `integer` | Whole number | `min_value`, `max_value` |
| `float` | Decimal number | `min_value`, `max_value` |
| `boolean` | True/false | — |
| `choice` | Enum selection | `choices: [a, b, c]` |
| `list` | Comma-separated values | — |
| `json` | Parsed JSON object/array | — |
| `path` | Filesystem path | — |

#### Variable sensitivity

Variables can be marked `sensitivity: secret` to ensure they are redacted in provenance logs and CLI output:

```yaml
variables:
  api_key:
    type: string
    required: true
    sensitivity: secret
```

### Promptlets

A **promptlet** is a reusable Markdown fragment (safety rails, style guides, output rubrics, tool policies) that spells include via `{{ include("path/id") }}`. Promptlets live under `spells/promptlets/` and are plain `.md` files with no frontmatter required.

```markdown
<!-- spells/promptlets/safety/base_engineering.md -->
You are a careful, safety-conscious engineer.
Never make changes without understanding impact.
Always verify assumptions before proceeding.
```

Promptlets can themselves contain `{{ include() }}` directives (up to 16 levels deep), variable references, and rune introspection.

### Runes

A **rune** (`*.rune.yaml`) is a machine-readable contract describing callable commands with parameter schemas, return types, safety metadata, and side effects.

```yaml
---
id: devtools/git
name: Git (read-only diagnostics)
version: 1.0.0
description: Git commands for diagnostics and patch review.
tags: [devtools, vcs, engineering]
platforms: [any]
risk_level: low
permissions: [read_fs]
commands:
  - name: status
    summary: Show working tree status
    params:
      - name: porcelain
        type: bool
        default: true
        description: Use machine-readable format
    returns:
      type: object
      properties:
        stdout: { type: string }
        exit_code: { type: integer, minimum: 0, maximum: 255 }
    side_effects: []
    examples:
      - call: { porcelain: true }
        expect: "stdout contains file paths and states"
  - name: diff
    summary: Show changes between commits, working tree, and index
    params:
      - name: staged
        type: bool
        default: false
    side_effects: []
```

#### Safety model

| Field | Values | Meaning |
|-------|--------|---------|
| `risk_level` | `none`, `low`, `medium`, `high` | Risk classification |
| `permissions` | `read_fs`, `write_fs`, `network`, `exec` | Semantic capabilities |
| `requires_approval` | per-command or per-rune | Whether human approval is needed |
| `side_effects` | list of strings | What the command changes |

### Rituals

A **ritual** (`*.ritual.yaml`) is a multi-step flow that sequences spells with conditional gating and variable capture.

```yaml
id: rituals/rca_loop
name: RCA Loop
version: 1.0.0
description: Iterative root-cause analysis workflow.
tags: [engineering, debugging]
steps:
  - id: step_1
    spell: engineering/bug_root_cause
    description: Generate initial RCA
    conjure:
      vars:
        inherit: true
    output:
      capture: rca_report

  - id: step_2
    when: "{{ rca_report.contains('NEEDED_INPUTS') }}"
    spell: engineering/request_missing_inputs
    conjure:
      ask_missing: true
    output:
      capture: additional_info
      format: text
```

Steps support `when` conditions using a safe expression evaluator (no `eval()`): `{{ var }}`, `.contains()`, `.startswith()`, `.endswith()`, `== "value"`, `!= "value"`, and boolean literals.

### Bundles

A **bundle** (`*.bundle.yaml`) is a composition recipe that selects a base spell, injects promptlets at specific positions, optionally exposes tool descriptions, and supports named variants.

```yaml
id: bundles/engineering/rca_with_tools
name: RCA with Engineering Tools
version: 1.0.0
tags: [engineering, rca, tools]
base_template: engineering/root_cause_analysis
inject:
  system_prepend:
    - safety/base_engineering
  system_append:
    - tool_policy/low_risk
tools:
  diagnostic_tools:
    - devtools/git
    - semantiscan/query
variants:
  - id: anthropic_concise
    when:
      provider: anthropic
    inject:
      system_append:
        - style/concise
```

Injection points: `system_prepend`, `system_append`, `user_prepend`, `user_append`. Variant selection is first-match based on the `context` dict.

### SkillDocs

A **skilldoc** (`*.skilldoc.md`) is a knowledge artifact with YAML frontmatter and section-based content, compatible with llmcore's SkillLoader.

```markdown
---
id: workflows/git
name: Git Workflow Guide
tags: [git, devops, workflow]
---

## Branching Strategy
<!-- tags: branching, strategy -->
Use feature branches off main. Merge via PR with at least one review...

## Commit Messages
<!-- tags: commits, conventions -->
Follow conventional commits: feat:, fix:, docs:, refactor:...
```

Sections can be filtered by tag, heading, ID, or keyword using the `SkillDocSelector`.

---

## Template Syntax

Grimoire uses a deterministic Jinja-like subset for all template rendering:

| Syntax | Purpose | Example |
|--------|---------|---------|
| `{{ var }}` | Variable substitution | `{{ issue_title }}` |
| `{{ var\|default("val") }}` | Variable with fallback | `{{ env\|default("production") }}` |
| `{{ include("path/id") }}` | Include a promptlet | `{{ include("safety/base_engineering") }}` |
| `{{ runes.list(tags=["x"]) }}` | List matching runes | `{{ runes.list(tags=["devtools"]) }}` |
| `{{ runes.describe("id") }}` | Full rune description | `{{ runes.describe("devtools/git") }}` |
| `{{ runes.command("id", "cmd").signature }}` | Command signature | `{{ runes.command("devtools/git", "diff").signature }}` |
| `{{{{` / `}}}}` | Literal `{{` / `}}` | For embedding raw template syntax |

Include resolution is recursive (up to 16 levels) with cycle detection.

---

## Variable System

### Resolution precedence (highest wins)

1. **CLI `--set key=value`** — explicit overrides
2. **`--vars file.yaml`** — variable files
3. **Profile overlays** (`--profile user/alice`)
4. **Grimoire defaults** (`vars/defaults.yaml`)
5. **Spell defaults** (in frontmatter `default:` field)
6. **Built-in variables** (`grimoire.now.*`, `grimoire.host.*`, `grimoire.git.*`, `grimoire.spell.*`, `grimoire.run.*`)

### Built-in variables

| Variable | Example value | Description |
|----------|--------------|-------------|
| `grimoire.now.iso` | `2026-03-04T12:00:00+00:00` | Current time (ISO 8601) |
| `grimoire.now.date` | `2026-03-04` | Current date |
| `grimoire.now.time` | `12:00:00` | Current time |
| `grimoire.spell.id` | `engineering/rca` | Current spell ID |
| `grimoire.spell.name` | `Root Cause Analysis` | Current spell name |
| `grimoire.spell.version` | `1.0.0` | Current spell version |
| `grimoire.host.username` | `alice` | OS username |
| `grimoire.host.hostname` | `dev-machine` | Hostname |
| `grimoire.host.cwd` | `/home/alice/project` | Working directory |
| `grimoire.git.repo_name` | `my-service` | Git repository name |
| `grimoire.git.ref` | `main` | Current git branch/ref |
| `grimoire.run.session_id` | `a1b2c3d4-...` | UUID4 per session |
| `grimoire.run.invocation_id` | `e5f6a7b8-...` | UUID4 per conjure call |

### Interactive fill

```bash
# Prompt for missing required variables only
grimoire conjure engineering/rca --ask-missing

# Confirm all variables interactively (including defaults)
grimoire conjure engineering/rca --ask-all
```

Type-aware prompting: booleans get yes/no, choices get a numbered menu, multiline accepts blank-line termination, numbers validate against min/max.

---

## CLI Reference

### Global options

```
--repo PATH          Grimoire repo root (default: cwd)
--profile NAME       Profile overlay (repeatable, merged in order)
--vars FILE.yaml     Variable file (repeatable)
--set key=value      Set individual variable (repeatable)
--format FORMAT      Output format: text|openai|anthropic|json
--out PATH           Write output to file
--log-level LEVEL    trace|debug|info|warn|error
-h, --help           Show help
--version            Show version
```

### `grimoire init [PATH]`

Create a new grimoire repository skeleton.

```bash
grimoire init my-project
grimoire init . --name "my-grimoire" --force
```

### `grimoire spell list|show|vars`

```bash
grimoire spell list                       # List all spells
grimoire spell list --tags engineering    # Filter by tag
grimoire spell list --json               # JSON output
grimoire spell show engineering/rca      # Show spell details
grimoire spell show engineering/rca --json
grimoire spell vars engineering/rca      # Show variable schema
```

### `grimoire spell new|edit|rm` (write API)

Create, edit, and delete spells from the CLI (writes to the repo's primary
spell directory, `spells/<id>.spell.md`):

```bash
# Create a spell (at least one of --system/--user, or *-file, is required)
grimoire spell new team/reviewer \
  --name "Reviewer" --tags "code,quality" --description "Reviews code" \
  --attributes '{"color": "#0a0"}' \
  --system "You are a meticulous reviewer." \
  --user   "Review: {{ diff }}"

# Body blocks may also be read from a file ('-' = stdin)
grimoire spell new team/reviewer --system-file ./system.md --user-file -

# Edit in place — only supplied fields change; the body is preserved otherwise
grimoire spell edit team/reviewer --tags "code,quality,strict" --description "…"

# Delete (use --yes to skip confirmation)
grimoire spell rm team/reviewer --yes
```

`--attributes` accepts a JSON object that is stored verbatim in the spell's
opaque `attributes:` front-matter (grimoire never interprets it).

### `grimoire rune list|show|validate`

```bash
grimoire rune list                        # List all runes
grimoire rune list --tags devtools       # Filter by tag
grimoire rune show devtools/git          # Show rune + commands
grimoire rune validate                   # Validate all runes
grimoire rune validate devtools/git      # Validate specific
```

### `grimoire conjure <artifact_id>`

Renders spells, bundles, or rituals into final messages.

```bash
# Spell conjuring
grimoire conjure examples/greet --set user_name=Alice
grimoire --format openai conjure engineering/rca --vars incident.yaml
grimoire --format json conjure engineering/rca --set issue_title="Bug" --provenance
grimoire --out prompt.md conjure engineering/rca --set issue_title="Bug" --set symptoms="crash"

# Bundle conjuring (auto-detected by ID prefix)
grimoire conjure bundles/engineering/rca_with_tools --set issue_title="Bug" --set symptoms="crash"

# Interactive mode
grimoire conjure engineering/rca --ask-missing
grimoire conjure engineering/rca --ask-all

# Non-strict (leave unresolved vars as placeholders)
grimoire conjure engineering/rca --no-strict
```

### `grimoire ritual list|show|dry-run|run`

```bash
grimoire ritual list                       # List rituals
grimoire ritual list --tag engineering    # Filter by tag
grimoire ritual show rituals/rca_loop     # Show steps
grimoire ritual dry-run rituals/rca_loop  # Assembly plan (no conjuring)
grimoire ritual run rituals/rca_loop --vars incident.yaml
grimoire ritual run rituals/rca_loop --json --format openai
```

### `grimoire bundle list|show|validate|assemble`

```bash
grimoire bundle list                                # List bundles
grimoire bundle show bundles/engineering/rca_with_tools
grimoire bundle validate                            # Validate all
grimoire bundle assemble bundles/engineering/rca_with_tools --context provider=anthropic
```

### `grimoire skill list|show|validate|docs|export`

```bash
grimoire skill list                        # List all (runes + skilldocs)
grimoire skill list --docs-only           # SkillDocs only
grimoire skill show devtools/git          # Show a rune
grimoire skill show workflows/git         # Show a skilldoc
grimoire skill validate                   # Validate all
grimoire skill docs workflows/git         # Render skilldoc content
grimoire skill docs workflows/git --sections branching
grimoire skill export --to openai-tool-schema
grimoire skill export --to llmcore-activities
```

### `grimoire prompt lint|test`

```bash
grimoire prompt lint                       # Lint all spells
grimoire prompt lint engineering/rca       # Lint specific spell
grimoire prompt lint --fail-on-warnings   # Strict mode (non-zero exit on warnings)
grimoire prompt lint --json               # JSON diagnostics
grimoire prompt test                       # Golden-file comparison
grimoire prompt test --update-golden      # Update golden files
grimoire prompt test --format openai      # Compare in OpenAI format
```

### `grimoire bind <target>`

Export/compile artifacts to runtime-specific formats.

```bash
# Semantiscan
grimoire bind semantiscan --format toml
grimoire bind semantiscan --format legacy_tmpl
grimoire bind semantiscan --tags rag --out exports/semantiscan/

# llmcore
grimoire bind llmcore
grimoire bind llmcore --tags engineering --out exports/llmcore/

# wairu
grimoire bind wairu
grimoire bind wairu --runes devtools/git

# Common options
grimoire bind llmcore --dry-run            # Preview only
grimoire bind llmcore --spells engineering/rca,examples/greet
```

### `grimoire sync from-wairu|from-llmcore|from-semantiscan|drift`

```bash
grimoire sync from-wairu                   # Import wairu tools as runes
grimoire sync from-wairu --out runes/imported/ --overwrite
grimoire sync from-llmcore                # Import llmcore activities
grimoire sync from-semantiscan            # Import semantiscan templates
grimoire sync drift --target wairu        # Detect drift vs wairu
grimoire sync drift --target all --json   # Drift for all targets
```

### `grimoire doctor`

```bash
grimoire doctor    # Diagnose repo issues (broken includes, schema violations, etc.)
```

---

## Library API (Live-Bind)

The `Grimoire` facade provides the single-entry-point API for programmatic access. For the comprehensive library integration guide with patterns, recipes, and architecture diagrams, see **[LIBRARY.md](LIBRARY.md)**.

```python
from grimoire import Grimoire

g = Grimoire("/path/to/repo")

# Polymorphic conjure: auto-detects spell / bundle / ritual
result = g.conjure("engineering/rca", variables={"issue_title": "OOM", "symptoms": "crash"})
messages = result.to_messages("openai")

# Variable introspection
missing = g.missing_vars("engineering/rca", provided={"issue_title": "Bug"})

# Tool schemas for function calling
tools = g.tool_schemas(tags=["devtools"])

# In-memory bind (no disk writes)
bind_result = g.bind("llmcore", tags=["engineering"])

# Validation
g.validate()    # Repo-level
g.lint()        # All spells
```

---

## Binding to Runtime Targets

### Two operating modes

| Mode | When to use | How |
|------|-------------|-----|
| **Pre-bind** (CI/offline) | Checked-in exports, CI pipelines | `grimoire bind <target> --out exports/` |
| **Live-bind** (library) | Runtime consumption, agentic systems | `g = Grimoire(path); g.conjure(...)` |

### What each target gets

| Target | Spells become | Runes become |
|--------|---------------|-------------|
| **llmcore** | Prompt registry JSON (messages + vars + hash) | ActivityDefinition JSON + OpenAI tool schemas |
| **semantiscan** | PromptManager TOML or legacy `.tmpl` templates | — |
| **wairu** | Agentic augmentation prompts | Tool pack YAML (commands, risk, approval) |

---

## Validation & Linting

### Structural validation (`grimoire doctor` / `g.validate()`)

Checks for broken include references, missing rune dependencies, duplicate IDs, invalid variable schemas, and schema violations across all artifact types.

### Prompt lint (`grimoire prompt lint` / `g.lint()`)

| Rule | Description | Severity |
|------|-------------|----------|
| Forbidden tokens | `TODO`, `FIXME`, `PLACEHOLDER` in templates | ERROR |
| Variable naming | camelCase variables → prefer snake_case | WARNING |
| Required var prompts | Required variables should have `ask:` text | INFO |
| Secret naming | `*_key`, `*_secret`, `*_token` should be `sensitivity: secret` | WARNING |
| Engineering quality | Engineering-tagged spells must mention assumptions, failure modes, or validation | WARNING |
| USER block length | Configurable max character limit per USER block | WARNING |

---

## Repository Structure

```
my-grimoire/
  grimoire.yaml                # Pack manifest (name, version, paths)
  spells/
    promptlets/                # Reusable components (.md)
      safety/                  # Safety rails
      style/                   # Persona overlays
      output/                  # Output rubrics
      tool_policy/             # Tool use policies
    templates/                 # Spell templates (*.spell.md)
      engineering/
      agentic/
      semantiscan/
    bundles/                   # Composition recipes (*.bundle.yaml)
  rituals/                     # Multi-step flows (*.ritual.yaml)
  runes/
    contracts/                 # Skill contracts (*.rune.yaml)
  skills/
    docs/                      # Knowledge skills (*.skilldoc.md)
  profiles/                    # Variable overlays (.yaml)
    user/
    persona/
    env/
  vars/
    defaults.yaml              # Default variable values
  tests/
    golden/                    # Golden test outputs
  exports/                     # Generated artifacts (gitignored)
```

---

## Profiles & Overlays

Profiles are YAML files under `profiles/` that supply variable presets:

```yaml
# profiles/user/alice.yaml
name: Alice
team: platform
preferred_format: markdown
```

Apply with `--profile` (repeatable, merged in order — last wins for conflicts):

```bash
grimoire --profile user/alice --profile env/staging conjure engineering/rca
```

---

## Integration Patterns

### llmcore — prompt registry + agent tools

```python
g = Grimoire("/path/to/repo")
messages = g.conjure("engineering/rca", variables={...}).to_messages("openai")
tools = g.tool_schemas(tags=["devtools"])
# → feed messages and tools into llmcore's chat() call
```

### semantiscan — RAG prompt templates

```python
g = Grimoire("/path/to/repo")
result = g.conjure("semantiscan/rag_default",
                   variables={"context": retrieved_chunks, "question": user_query})
# → pass result.to_text() to llmcore with enable_rag=False
```

### wairu — tool catalog + approval prompts

```python
g = Grimoire("/path/to/repo")
tools = g.tool_schemas(tags=["devtools"])
policy = g.conjure("agentic/tool_calling_policy_high_risk_requires_approval")
```

### CI/CD quality gate

```bash
grimoire doctor && grimoire prompt lint --fail-on-warnings && grimoire prompt test
```

```python
g = Grimoire(".")
if g.validate().ok and g.lint().ok:
    g.bind("llmcore").write("exports/llmcore/")
```
