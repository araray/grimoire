# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — 2026-03-04

### Added — Phase 0: Skeleton

**Core Models** (`models.py`)
- `Spell` — structured prompt template with typed variables, message blocks, output contracts
- `Promptlet` — reusable prompt component (safety, style, persona)
- `RuneSpec` / `CommandSpec` / `ParamSpec` — skill contract with command schemas
- `Ritual` / `RitualStep` — multi-step flow (data model only; evaluation is Phase 3)
- `ConjuredPrompt` / `Provenance` — rendered output with full provenance tracking
- `GrimoireManifest` — repository manifest
- Content hashing (SHA-256, 16-char) for drift detection
- Export to OpenAI, Anthropic, and raw text message formats

**Spell Parser** (`spells/parser.py`)
- YAML frontmatter extraction from `*.spell.md` files
- Message block splitting (`# SYSTEM`, `# DEVELOPER`, `# USER`, `# ASSISTANT_PREFILL`)
- Typed variable schema parsing with validation
- Output contract and rune export config parsing

**Rune Parser** (`runes/parser.py`)
- YAML parsing of `*.rune.yaml` files
- Command, parameter, return spec, and example parsing
- Risk level, permissions, and approval metadata

**Conjure Engine** (`conjure/engine.py`)
- Deterministic template rendering (same inputs → same output)
- Variable substitution: `{{ var }}`, `{{ var|default("...") }}`
- Promptlet inclusion: `{{ include("path/id") }}` with cycle detection
- Rune introspection: `runes.list()`, `runes.describe()`, `runes.command().signature`
- Literal brace escaping: `{{{{` → `{{}}`
- Variable precedence: explicit > vars file > grimoire defaults > spell defaults > builtins
- Built-in variables: `grimoire.now.*`, `grimoire.spell.*`
- Full provenance tracking (variables, includes, runes, timestamps)

**Repository Store** (`store/repo.py`)
- Grimoire manifest loading (`grimoire.yaml`)
- Recursive discovery of spells, runes, promptlets, rituals
- Default variable loading from `vars/defaults.yaml`
- Tag-based filtering for spells and runes
- Agent-friendly JSON catalog export

**Validation** (`validate/rules.py`)
- Spell validation: block presence, ID convention, variable prompts, engineering lint
- Rune validation: command presence, summaries, risk/approval consistency
- Repository validation: dependency resolution, aggregated diagnostics

**CLI** (`cli/`)
- `grimoire init` — create repository skeleton with starter spell
- `grimoire spell list|show|vars` — catalog and inspect spells
- `grimoire rune list|show|validate` — discover and validate rune contracts
- `grimoire conjure <spell_id>` — render spells with variables, includes, provenance
- `grimoire doctor` — diagnose repository issues
- Global options: `--repo`, `--profile`, `--vars`, `--set`, `--format`, `--out`, `--log-level`
- Output formats: text, openai, anthropic, json

**Testing**
- 128 tests (unit + integration)
- 86%+ branch coverage
- Clean ruff lint
