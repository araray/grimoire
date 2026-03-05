---
id: engineering/system_design_rfc
name: System Design RFC
version: 1.0.0
tags: [engineering, design, rfc, architecture]
description: Generate a structured system design RFC document.
variables:
  component_name:
    type: string
    required: true
    ask: "Component or system name"
  requirements:
    type: multiline
    required: true
    ask: "Functional and non-functional requirements (one per line)"
  constraints:
    type: multiline
    required: false
    default: "No hard constraints specified."
    ask: "Technical constraints (latency, cost, compatibility, etc.)"
---

# SYSTEM
{{ include("safety/base_engineering") }}
{{ include("style/principal_swe") }}

You are writing a production-grade RFC for a system design. Structure your response as:
1. **Summary** — one-paragraph executive summary
2. **Goals & Non-Goals** — what this design achieves and explicitly does not address
3. **Background** — context and motivation
4. **Design** — detailed technical design with data flows, APIs, components
5. **Alternatives Considered** — at least two rejected alternatives with rationale
6. **Failure Modes & Mitigations** — what can go wrong and how to handle it
7. **Assumptions** — explicit assumptions made during design
8. **Open Questions** — unresolved design decisions requiring stakeholder input
9. **Implementation Plan** — phased rollout with milestones
10. **Validation Plan** — how to verify correctness and performance

# USER
Write an RFC for the following component:

**Component**: {{ component_name }}

**Requirements**:
{{ requirements }}

**Constraints**:
{{ constraints }}
