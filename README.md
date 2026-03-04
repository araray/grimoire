# Grimoire

**Prompt & tool control plane for the llmcore ecosystem.**

Grimoire is a CLI + library that becomes the **definitive source of truth** for:

- **Spells** — prompt templates with typed variables, message blocks, and output contracts
- **Runes** — skill contracts describing callable commands with parameters, safety, and schemas
- **Rituals** — multi-step prompt flows (Phase 3)
- **Grimoires** — packs/repos containing spells, rituals, runes, and profiles

Built to power **llmcore · semantiscan · wairu** while staying vendor-neutral and composable.

## Status

**Phase 0 — Skeleton**: ✅ Complete
- Grimoire repository manifest + loading
- Spell parser (`.spell.md` with YAML frontmatter + message blocks)
- Rune parser (`.rune.yaml` with command schemas)
- Promptlet discovery (reusable `.md` components)
- Conjure engine (deterministic rendering with variable resolution, includes, rune introspection)
- Validation rules (spell/rune/repo diagnostics)
- CLI (`init`, `spell`, `rune`, `conjure`, `doctor`)

**Phase 1 — CLI MVP**: ✅ Complete
- Profile overlay loading (`--profile user/alice`)
- Interactive variable fill (`--ask-missing`, `--ask-all`) with full type validation

**Phase 2 — Binding Targets**: ✅ Complete
- Semantiscan binder (TOML + legacy `.tmpl` export)
- llmcore binder (prompt registry + activity definitions + manifest)
- Wairu binder (tool packs + augmentations + manifest)
- CLI `grimoire bind <target>` command with `--dry-run`, filters, format selection

**198 tests, 87%+ coverage, lint-clean**

## Architecture

```
grimoire/
├── src/grimoire/
│   ├── __init__.py           # Public API exports
│   ├── models.py             # Core data models (Pydantic v2)
│   ├── exceptions.py         # Exception hierarchy
│   ├── spells/               # Spell parsing
│   │   └── parser.py         # *.spell.md → Spell model
│   ├── runes/                # Rune parsing
│   │   └── parser.py         # *.rune.yaml → RuneSpec model
│   ├── conjure/              # Rendering engine
│   │   └── engine.py         # Variable resolution, includes, rune introspection
│   ├── store/                # Repository loading
│   │   └── repo.py           # Discovery, indexing, catalog
│   ├── validate/             # Validation rules
│   │   └── rules.py          # Spell/rune/repo diagnostics
│   ├── bind/                 # Binding targets (Phase 2)
│   │   ├── base.py           # Abstract binder + result types
│   │   ├── semantiscan.py    # TOML + legacy .tmpl export
│   │   ├── llmcore.py        # Registry bundle (JSON prompts + activities)
│   │   └── wairu.py          # Tool pack (YAML tools + augmentations)
│   ├── cli/                  # Click CLI
│   │   ├── __init__.py       # Main group + global options
│   │   ├── helpers.py        # Shared CLI utilities, profiles, interactive fill
│   │   └── commands/         # Subcommands
│   │       ├── init.py       # grimoire init
│   │       ├── spell.py      # grimoire spell list|show|vars
│   │       ├── rune.py       # grimoire rune list|show|validate
│   │       ├── conjure.py    # grimoire conjure
│   │       ├── bind.py       # grimoire bind semantiscan|llmcore|wairu
│   │       └── doctor.py     # grimoire doctor
│   ├── rituals/              # (Phase 3 stub)
│   ├── config/               # (Phase 1+ config)
│   └── get_version.py        # Version from pyproject.toml
├── tests/
│   ├── unit/                 # 198 unit + integration tests
│   ├── golden/               # Golden test outputs (Phase 1)
│   └── fixtures/             # Sample grimoire repo + artifacts
├── pyproject.toml            # Project configuration
└── README.md
```

## Quick Start

### Install

```bash
pip install -e ".[test]"
```

### Create a Grimoire

```bash
grimoire init my-grimoire
cd my-grimoire
```

### List & Inspect Spells

```bash
grimoire spell list
grimoire spell show examples/hello
grimoire spell vars examples/hello
```

### Conjure a Spell

```bash
# Text format (default)
grimoire conjure examples/hello --set name=Alice

# OpenAI message format
grimoire --format openai conjure examples/hello --set name=Alice

# With provenance tracking
grimoire conjure examples/hello --set name=Alice --provenance

# Interactive variable fill
grimoire conjure examples/hello --ask-missing
```

### Manage Runes

```bash
grimoire rune list
grimoire rune show devtools/git
grimoire rune validate
```

### Bind to Runtime Targets

```bash
# Export for semantiscan (TOML format)
grimoire bind semantiscan --format toml

# Export for llmcore (registry bundle)
grimoire bind llmcore --out exports/llmcore/

# Export for wairu (tool pack)
grimoire bind wairu --runes devtools/git

# Dry run (preview without writing)
grimoire bind semantiscan --dry-run --tags rag
```

### Diagnose Issues

```bash
grimoire doctor
```

## Design Principles

1. **Deterministic conjuring** — same inputs → same output
2. **Separation of concerns** — catalog (content) vs conjuring (render) vs binding (export)
3. **Content hashing** — drift detection via SHA-256 content hashes
4. **Provenance tracking** — full audit trail of variables, includes, and runes used
5. **Vendor-neutral** — exports to OpenAI, Anthropic, raw text formats

## Dependencies

- Python 3.11+
- `pydantic>=2.0` — data model validation
- `pyyaml>=6.0` — YAML parsing
- `click>=8.0` — CLI framework
- `rich>=13.0` — terminal formatting

## Testing

```bash
pytest                                    # Run all tests
pytest --cov=src/grimoire                 # With coverage
pytest tests/unit/test_conjure_engine.py  # Specific module
ruff check src/ tests/                    # Lint
```

## License

MIT
