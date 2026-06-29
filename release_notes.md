# Grimoire Release Notes - June 2026 Procedural Tools and MCP Release

Prepared for merging `av/improvements_june-2026` into `main`.

Baseline: changes since merge base `13895ac39f6d` with `origin/main`.

## Release Story

This release turns Grimoire into a stronger prompt and tool control plane for the ecosystem. Rune command schemas are now exportable, spells can be discovered by intent, and an MCP/JSON-RPC server exposes rune tools and prompt endpoints to external runtimes.

## Highlights

- Centralizes rune command schema export for downstream tool adapters.
- Adds intent-based spell and rune-command discovery.
- Adds Semantiscan-backed procedural discovery smoke coverage.
- Exposes an MCP tool manifest through the public API.
- Adds a JSON-RPC MCP server with tool calls and prompt endpoints.
- Adds MCP authentication, execution, handler, and model layers.
- Adds ecosystem federation adapters for MCP and rune events.
- Adds OWASP metadata to rune contracts and a rune audit command.
- Updates LLMCore and Wairu bindings to consume the richer tool surface.

## Developer Impact

Tool consumers can now ask Grimoire for structured rune command schemas instead of scraping command details from parser internals. Intent-based discovery lets agents find the most relevant procedural asset without hard-coding spell names.

The MCP server gives external clients a standard JSON-RPC route into Grimoire's prompt and tool catalog, which makes Grimoire easier to plug into IDEs, agents, and service boundaries.

## Operator Impact

The new federation adapters and OWASP metadata make Grimoire activity more visible and reviewable. Operators can audit rune contracts, observe exported tool manifests, and expose MCP endpoints where a service-style integration is preferable to direct library calls.

## Compatibility Notes

- The `mcp` optional extra now pulls in FastAPI/Uvicorn support.
- Rune contracts include additional metadata that downstream validators should preserve.
- Intent-based procedural discovery is additive; existing spell/rune parsing paths remain in place.

## Validation Focus

Reviewers should focus on:

- MCP server request/response behavior for manifests, tool calls, and prompt endpoints.
- Rune schema export compatibility with LLMCore and Wairu adapters.
- Procedural discovery ranking and Semantiscan-backed smoke behavior.
- OWASP metadata parsing and audit command output.

## By the Numbers

- 10 commits since the merge base.
- 42 files changed.
- 3,742 insertions and 142 deletions before this release-note commit.

## Representative Commits

- `659d58b` - centralize command schema export.
- `b186cf6` and `566fd2e` - add intent-based procedural discovery.
- `6e64070`, `bc0a694`, and `b06b8a9` - expose MCP manifests, tool calls, and prompt endpoints.
- `4d638d5` - add MCP and rune federation adapters.
- `47f7893` and `3e98553` - add OWASP metadata and auditing.
