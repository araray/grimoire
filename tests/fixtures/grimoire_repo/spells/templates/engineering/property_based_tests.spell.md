---
id: engineering/property_based_tests
name: Property-Based Tests Generator
version: 1.0.0
tags: [engineering, testing, property-based, hypothesis]
description: Generate Hypothesis property-based tests for a function.
variables:
  function_signature:
    type: multiline
    required: true
    ask: "Function signature and docstring to test"
  invariants:
    type: multiline
    required: true
    ask: "Invariants / properties to verify (one per line)"
---

# SYSTEM
{{ include("safety/base_engineering") }}
{{ include("style/principal_swe") }}

Generate rigorous property-based tests using Python Hypothesis.

Rules:
- Each test verifies exactly one invariant
- Use `@given` + `@settings` with explicit max_examples
- Use `assume()` for preconditions (not if/else)
- Include at least one regression test for discovered edge cases
- Document: what property is being tested, why it matters, what failure looks like

Include: assumptions about the function's contract, failure modes the tests reveal,
and a validation plan for running the tests in CI.

# USER
**Function**:
{{ function_signature }}

**Invariants to verify**:
{{ invariants }}
