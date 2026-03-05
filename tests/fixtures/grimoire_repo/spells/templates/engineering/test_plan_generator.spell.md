---
id: engineering/test_plan_generator
name: Test Plan Generator
version: 1.0.0
tags: [engineering, testing, quality]
description: Generate a comprehensive test plan for a component.
variables:
  component_name:
    type: string
    required: true
    ask: "Component or feature to test"
  test_type:
    type: choice
    required: false
    default: "all"
    choices: [unit, integration, end-to-end, property-based, performance, all]
    ask: "Type of tests to generate"
  coverage_target:
    type: string
    required: false
    default: "90%"
    ask: "Coverage target (e.g. 90%)"
---

# SYSTEM
{{ include("safety/base_engineering") }}
{{ include("style/principal_swe") }}

Generate a rigorous test plan with:
- **Assumptions** about testability and test infrastructure
- **Test Scope**: what is and is not covered
- **Happy-Path Tests**: primary use cases
- **Edge Cases**: boundary conditions, empty inputs, max values
- **Failure Modes**: error injection, timeout, partial failure
- **Validation Plan**: how coverage is measured and verified

# USER
Generate a {{ test_type }} test plan for **{{ component_name }}**.

Target coverage: {{ coverage_target }}

Produce executable test code (pytest) with clear docstrings. Prefer small,
focused tests. Use parametrize for data-driven cases. Include at least one
property-based test using Hypothesis if applicable.
