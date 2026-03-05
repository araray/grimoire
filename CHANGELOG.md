# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] — Phase 3 + Quick Wins + Live-Bind API

### Added — Live-Bind API (spec §10.2, §12)

**Grimoire Facade** (`api.py`)
- `Grimoire(repo_path, strict=)` — single-entry-point facade for programmatic access
- `reload()` — re-load repo from disk after file changes
- **Polymorphic conjure**: `conjure(artifact_id, variables=, defaults=, context=, strict=)`
  auto-detects spell / bundle / ritual and returns the correct type
- **Typed conjure**: `conjure_spell()`, `conjure_bundle()`, `conjure_ritual()` for
  statically-typed callers
- **Variable introspection**: `spell_vars(spell_id)` returns full variable schema;
  `missing_vars(artifact_id, provided=)` identifies required variables not yet supplied
- **Tool schema generation**: `tool_schemas(rune_ids=, tags=, schema_format=)` produces
  OpenAI-compatible function-calling tool definitions from runes
- **In-memory bind**: `bind(target, fmt=, spell_ids=, rune_ids=, tags=)` produces
  `BindResult` without disk writes (live-bind mode)
- **Validation**: `validate()` for repo-level checks; `lint(spell_id=, config=)` for
  style rules on individual or all spells
- **Catalog**: `catalog()` returns agent-friendly JSON of all artifacts
- Convenience accessors: `get_spell`, `get_rune`, `get_bundle`, `get_ritual`,
  `list_spells`, `list_runes`, `list_bundles`, `list_rituals`

**New exception** (`exceptions.py`)
- `AmbiguousArtifactError(RepoError)` — artifact ID matches multiple types

**Tests**
- 74 new tests: `test_api.py` covering construction, conjure (polymorphic + typed),
  variable introspection, tool schemas, in-memory bind, validation, lint, catalog,
  accessors, error paths, and end-to-end live-bind workflows
- Total: 544 tests passing (was 470); coverage 87% (was 85.13%)

### Added — Phase 3: Rituals

**Ritual Parser** (`rituals/parser.py`)
- `parse_ritual(data, source_path)` — parse from pre-loaded dict
- `parse_ritual_file(path)` — parse `*.ritual.yaml` from disk
- Full field parsing: `id`, `name`, `version`, `description`, `tags`, `steps`
- Step-level fields: `id`, `spell`, `when`, `description`, `conjure`, `output`
- Detailed error messages via `RitualParseError`

**Ritual Evaluator** (`rituals/evaluator.py`)
- `RitualEvaluator(repo, engine)` — stateless evaluator wrapping repo + conjure engine
- `dry_run(ritual)` → `RitualAssemblyPlan` — inspect without conjuring; detects missing spells
- `evaluate(ritual, variables, defaults)` → `list[ConjuredRitualStep]` — step-by-step evaluation
- Step output capture: conjured text stored into named context variable
- Context flow: captured variables available to subsequent steps' `when` conditions
- Safe `when`-condition evaluator (no `eval()`): supports `{{ var }}`, `.contains()`,
  `.startswith()`, `.endswith()`, `== "value"`, `!= "value"`, and boolean literals

**Ritual Validator** (`rituals/validator.py`)
- `validate_ritual(ritual, repo)` — structural + reference validation
- Checks: missing spell IDs, duplicate step IDs, `when` syntax, `output.capture` identifier validity, `output.format` values

**New data classes** (`models.py`)
- `RitualStepPlan` — one step in a dry-run assembly plan
- `RitualAssemblyPlan` — full plan with `.ok` property and `missing_spells` list
- `ConjuredRitualStep` — one evaluated step (spell_id, skipped, conjured, captured_var/value)

**Updated `Ritual`/`RitualStep` models** (`models.py`)
- `Ritual` gains `description`, `tags` fields
- `RitualStep` gains `description` field; `conjure`/`output` dict semantics documented

**CLI: `grimoire ritual`** (`cli/commands/ritual.py`)
- `grimoire ritual list [--tag TAG] [--json]` — list rituals with tag filtering
- `grimoire ritual show <ID> [--json]` — human-readable or JSON detail view
- `grimoire ritual dry-run <ID> [--json] [--no-validate]` — assembly plan with color diagnostics

**Validation integration** (`validate/rules.py`)
- `validate_repo()` now includes ritual validation via `validate_ritual()`

**Store** (`store/repo.py`)
- `list_rituals(tags=...)` now supports tag filtering (consistent with `list_spells`/`list_runes`)
- Ritual discovery uses proper `parse_ritual_file()` from parser module

**Tests**
- 68 new tests: `test_ritual_parser.py` (20), `test_ritual_evaluator.py` (48)
- Total: 266 tests passing (was 198); coverage 86.5% (floor: 85%)

### Added — Quick Wins

**W1: Missing model fields** (`models.py`)
- `CommandSpec.execution_target: str | None` — hints `"local"`, `"sandbox"`, or `"remote"` for sync adapters
- `RuneSpec.mappings: dict[str, str]` — cross-runtime name mapping (`wairu.tool_name`, `llmcore.activity_name`, etc.)

**W2: Additional built-in variables** (`conjure/engine.py`)
- `grimoire.host.username` — current user (graceful fallback to `USER`/`USERNAME` env)
- `grimoire.host.hostname` — host name
- `grimoire.host.cwd` — current working directory
- `grimoire.git.repo_name` — git repository name (graceful fallback when git unavailable)
- `grimoire.git.ref` — current git branch/ref
- `grimoire.run.session_id` — UUID4 per session
- `grimoire.run.invocation_id` — UUID4 per conjure call
- All new built-ins degrade gracefully (no crash when git is absent)

**W3: Variable types** (`models.py`)
- `VariableType.JSON = "json"` — parsed JSON dict/list value
- `VariableType.PATH = "path"` — filesystem path string

**W4: Variable sensitivity** (`models.py`)
- `VariableSensitivity` enum: `PUBLIC`, `SECRET`
- `VariableSpec.sensitivity: VariableSensitivity` — redaction hint for provenance/logs (default: PUBLIC)

**Exceptions** (`exceptions.py`)
- `RitualParseError(RitualError)` — ritual YAML is malformed
- `RitualValidationError(RitualError)` — ritual fails semantic validation



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

### Added — Phase 1 Completion: CLI MVP

**Profile Overlays** (`cli/helpers.py`)
- `--profile user/name` loads YAML overlay files from profiles/ directory
- Multiple profiles supported; merged in order (last wins)
- Profile resolution across all configured profile_paths

**Interactive Variable Fill** (`cli/helpers.py`)
- `--ask-missing` prompts for missing required variables with type validation
- `--ask-all` confirms all variables interactively (including defaults)
- Type-aware prompting: boolean (yes/no), choice (numbered menu),
  multiline (blank line terminates), integer/float (with min/max validation),
  list (comma-separated)

### Added — Phase 2: Binding Targets

**Bind Module** (`bind/`)
- Abstract `Binder` base class with `BindResult`, `BoundFile`, `BindTarget` types
- Three concrete binders: `SemantiscanBinder`, `LLMCoreBinder`, `WairuBinder`
- Disk-write support: `result.write(out_dir)` with automatic directory creation
- Pre-bind (CI/offline) mode for all targets

**Semantiscan Binder** (`bind/semantiscan.py`)
- TOML export (PromptManager format): `[metadata]`, `[prompts]`, `[defaults]` sections
- Legacy `.tmpl` export: single-string templates with `{context}` / `{question}`
- Automatic variable syntax conversion: `{{ var }}` → `{var}`
- Built-in variable remapping: `grimoire.now.date` → `current_date`, etc.
- Auto-injection of `{context}` / `{question}` when missing from legacy templates

**llmcore Binder** (`bind/llmcore.py`)
- Prompt registry bundle: JSON per spell with messages, variables, content hash
- Activity definitions from runes: JSON with risk levels, parameter schemas
- OpenAI-compatible tool/function schemas generated from rune commands
- Registry manifest (`manifest.json`) with prompt and activity indexes

**Wairu Binder** (`bind/wairu.py`)
- Tool pack export: YAML per rune with tool definitions, risk/approval metadata
- Augmentation prompts: auto-detected agentic spells exported as companion files
- Tool manifest (`tool_manifest.json`) with indexes and risk summaries
- Source tracking (`_source: grimoire`, `_content_hash`) for drift detection

**CLI** (`cli/commands/bind.py`)
- `grimoire bind semantiscan [--format toml|legacy_tmpl]`
- `grimoire bind llmcore`
- `grimoire bind wairu`
- `--spells`, `--runes`, `--tags` filters for selective binding
- `--dry-run` to preview output without writing
- `--out` to specify output directory (default: `exports/<target>/`)

**Testing**
- 198 tests (unit + integration)
- 87%+ branch coverage
- Clean ruff lint
