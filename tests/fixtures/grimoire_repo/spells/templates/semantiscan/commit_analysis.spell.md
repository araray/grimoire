---
id: semantiscan/commit_analysis
name: Commit Analysis
version: 1.0.0
tags: [semantiscan, git, analysis]
description: Analyze a git commit for quality, intent, and risk.
variables:
  commit_hash:
    type: string
    required: true
    ask: "Commit hash"
  diff:
    type: multiline
    required: true
    ask: "Git diff content"
  context:
    type: multiline
    required: false
    default: ""
    ask: "Additional context (related issues, PR description)"
---

# SYSTEM
You are a code review assistant analyzing git commits for quality and risk.

# USER
**Commit**: {{ commit_hash }}

**Diff**:
{{ diff }}

{% if context %}
**Context**:
{{ context }}
{% endif %}

Analyze this commit and produce:
1. **Summary**: one-sentence description of what the commit does
2. **Intent**: inferred purpose (bugfix / feature / refactor / chore / docs)
3. **Risk Level**: low / medium / high, with rationale
4. **Quality Assessment**: code quality, test coverage, documentation
5. **Concerns**: anything that warrants closer review
