# Grimoire — Usage Guide

## Spell Format (`*.spell.md`)

Spells use YAML frontmatter + Markdown message blocks:

```markdown
---
id: engineering/bug_root_cause
name: Root cause analysis
version: 1.0.0
tags: [debugging, rca, engineering]
requires_runes:
  - engineering/observability
variables:
  issue_title:
    type: string
    required: true
    ask: "Issue title"
  environment:
    type: multiline
    required: false
    default: "(unknown)"
---

# SYSTEM
You are a principal software engineer.

# DEVELOPER
{{ include("spells/promptlets/style/principal_swe") }}

# USER
Root-cause analysis for: {{ issue_title }}
Environment: {{ environment }}
```

### Message Block Roles

| Role | Purpose | Maps to (OpenAI) | Maps to (Anthropic) |
|------|---------|-------------------|---------------------|
| `# SYSTEM` | System instructions | `system` | `system` |
| `# DEVELOPER` | Developer context | `developer` | `system` (merged) |
| `# USER` | User request | `user` | `user` |
| `# ASSISTANT_PREFILL` | Prefill for the assistant | `assistant` | `assistant` |

### Variable Types

| Type | Description | Extra fields |
|------|-------------|-------------|
| `string` | Single-line text | — |
| `multiline` | Multi-line text | — |
| `integer` | Whole number | `min_value`, `max_value` |
| `float` | Decimal number | `min_value`, `max_value` |
| `boolean` | True/false | — |
| `choice` | Enum selection | `choices: [a, b, c]` |
| `list` | List of values | — |

### Template Syntax

| Syntax | Purpose |
|--------|---------|
| `{{ var }}` | Variable substitution |
| `{{ var\|default("val") }}` | Variable with fallback |
| `{{ include("path/id") }}` | Include a promptlet |
| `{{ runes.list(tags=["x"]) }}` | List matching runes |
| `{{ runes.describe("id") }}` | Describe a rune |
| `{{ runes.command("id", "cmd").signature }}` | Command signature |
| `{{{{` / `}}}}` | Literal `{{` / `}}` |

## Rune Format (`*.rune.yaml`)

```yaml
---
id: devtools/git
name: Git (read-only diagnostics)
version: 1.0.0
tags: [devtools, vcs]
risk_level: low
permissions: [read_fs]
commands:
  - name: status
    summary: Show working tree status
    params:
      - name: porcelain
        type: bool
        default: true
    returns:
      type: object
      properties:
        stdout: { type: string }
    side_effects: []
```

## CLI Commands

### `grimoire init [PATH]`

Creates a repository skeleton with starter spell, promptlet, and manifest.

```bash
grimoire init my-project
grimoire init . --name "my-grimoire" --force
```

### `grimoire spell list|show|vars`

```bash
grimoire spell list                    # List all spells
grimoire spell list --tags debugging   # Filter by tag
grimoire spell list --json             # JSON output
grimoire spell show engineering/rca    # Show details
grimoire spell vars engineering/rca    # Show variable schema
```

### `grimoire rune list|show|validate`

```bash
grimoire rune list                     # List all runes
grimoire rune show devtools/git        # Show details + commands
grimoire rune validate                 # Validate all runes
grimoire rune validate devtools/git    # Validate specific rune
```

### `grimoire conjure <spell_id>`

```bash
# Basic usage
grimoire conjure examples/hello --set name=Alice

# Load variables from YAML
grimoire --vars incident.yaml conjure engineering/rca

# Multiple output formats
grimoire --format openai conjure examples/hello --set name=Alice
grimoire --format anthropic conjure examples/hello --set name=Alice
grimoire --format json conjure examples/hello --set name=Alice --provenance

# Write to file
grimoire --out prompt.md conjure examples/hello --set name=Alice

# Interactive mode
grimoire conjure examples/hello --ask-missing

# Non-strict (leave unresolved vars as placeholders)
grimoire conjure examples/hello --no-strict
```

### `grimoire doctor`

```bash
grimoire doctor   # Diagnose repo issues
```

### Global Options

```bash
grimoire --repo /path/to/grimoire ...    # Set repo root
grimoire --profile user/alice ...         # Apply profile overlay
grimoire --vars config.yaml ...           # Load vars file
grimoire --set key=value ...              # Set individual variable
grimoire --format openai ...              # Set output format
grimoire --out output.txt ...             # Write to file
grimoire --log-level debug ...            # Set log level
```

## Library API

```python
from grimoire import (
    GrimoireRepo,
    ConjureEngine,
    parse_spell,
    parse_rune,
)

# Load a grimoire repository
repo = GrimoireRepo.load("/path/to/grimoire")

# List spells
for spell in repo.list_spells(tags=["engineering"]):
    print(f"{spell.id}: {spell.name}")

# Conjure a spell
spell = repo.get_spell("engineering/rca")
engine = ConjureEngine(
    promptlets={p.id: p for p in repo.list_promptlets()},
    runes={r.id: r for r in repo.list_runes()},
)
result = engine.conjure(
    spell,
    variables={"issue_title": "DB timeout", "symptoms": "Queries hang"},
    defaults=repo.default_vars,
)

# Export to provider format
messages = result.to_messages(fmt="openai")

# Get provenance
print(result.provenance.spell_hash)
print(result.provenance.includes_resolved)

# Agent-friendly catalog (JSON-serializable)
catalog = repo.catalog()
```

## Variable Precedence

Variables resolve in this order (highest → lowest):

1. CLI `--set key=value`
2. `--vars file.yaml`
3. Profile overlays (`--profile`)
4. Grimoire defaults (`vars/defaults.yaml`)
5. Spell defaults (in frontmatter)
6. Built-ins (`grimoire.now.*`, `grimoire.spell.*`)

## Repository Structure

```
my-grimoire/
  grimoire.yaml              # Pack manifest
  spells/
    promptlets/               # Reusable components
      safety/                 # Safety rails
      style/                  # Persona overlays
      output/                 # Output contracts
    templates/                # Spell files (*.spell.md)
      engineering/
      agentic/
    bundles/                  # Pre-composed spell sets
  rituals/                    # Multi-step flows (*.ritual.yaml)
  runes/
    contracts/                # Skill contracts (*.rune.yaml)
    docs/                     # RuneDocs (knowledge skills)
  profiles/                   # User/persona/project profiles
  vars/
    defaults.yaml             # Default variable values
  tests/
    golden/                   # Golden test outputs
```
