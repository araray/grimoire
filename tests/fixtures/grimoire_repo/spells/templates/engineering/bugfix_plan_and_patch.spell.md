---
id: engineering/bugfix_plan_and_patch
name: Bugfix Plan and Patch
version: 1.0.0
tags: [engineering, debugging, patch]
description: Structured bugfix plan with minimal targeted patch.
variables:
  issue_title:
    type: string
    required: true
    ask: "Issue title or bug description"
  failing_test_or_repro:
    type: multiline
    required: true
    ask: "Failing test output or reproduction steps"
  constraint:
    type: string
    required: false
    default: "minimal change — do not refactor unrelated code"
    ask: "Constraint on the fix (e.g. 'must not change public API')"
---

# SYSTEM
{{ include("safety/base_engineering") }}
{{ include("style/principal_swe") }}
{{ include("output/rubric_patch_only") }}

# USER
## Bug: {{ issue_title }}

**Failing test / reproduction**:
{{ failing_test_or_repro }}

**Constraint**: {{ constraint }}

Provide:
1. **Root cause** (one sentence)
2. **Minimal patch** (exact diff or code change, no unrelated modifications)
3. **Why this fixes it** (mechanistic explanation)
4. **Side effects considered** (what else might this affect)
5. **Validation** (which test to run / how to verify)
