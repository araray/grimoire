---
id: semantiscan/commit_enrichment
name: Commit Enrichment
version: 1.0.0
tags: [semantiscan, git, enrichment]
description: Enrich commit metadata for search indexing.
variables:
  commit_message:
    type: string
    required: true
    ask: "Original commit message"
  diff_summary:
    type: multiline
    required: true
    ask: "Summary of changed files and functions"
---

# SYSTEM
You enrich commit metadata for code search indexing. Output ONLY valid JSON.
No preamble, no markdown, no explanation.

# USER
Commit message: {{ commit_message }}
Diff summary: {{ diff_summary }}

Return JSON: {"keywords": [...], "intent": "...", "risk": "low|medium|high", "tags": [...]}
