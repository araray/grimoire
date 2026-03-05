---
id: engineering/root_cause_analysis
name: Root Cause Analysis
version: 1.0.0
tags: [engineering, debugging, rca]
description: Structured root-cause analysis for software incidents.
variables:
  issue_title:
    type: string
    required: true
    ask: "Brief title of the issue or incident"
  symptoms:
    type: multiline
    required: true
    ask: "Observed symptoms (one per line)"
  environment:
    type: string
    required: false
    default: "production"
    ask: "Environment where the issue occurred"
  context:
    type: multiline
    required: false
    default: ""
    ask: "Relevant codebase or system context"
---

# SYSTEM
{{ include("safety/base_engineering") }}
{{ include("style/principal_swe") }}

You are performing a structured root-cause analysis. Your output must follow the engineering quality rubric:
- **Assumptions**: what you are taking for granted
- **Failure Modes**: what could have caused the symptoms
- **Hypotheses**: ranked by likelihood with supporting evidence
- **Root Cause**: the most probable cause with justification
- **Fix**: minimal, targeted remediation
- **Validation Plan**: how to confirm the fix worked
- **Prevention**: systemic changes to avoid recurrence

# USER
## Issue: {{ issue_title }}

**Environment**: {{ environment }}

**Symptoms**:
{{ symptoms }}

{% if context %}
**Context**:
{{ context }}
{% endif %}

Perform a thorough root cause analysis. Be specific about assumptions. List all plausible
hypotheses before converging on a root cause. The fix must be minimal and targeted — do not
refactor unrelated code. The validation plan must be concrete and measurable.
