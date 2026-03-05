---
id: engineering/perf_profile_and_optimize
name: Performance Profile and Optimize
version: 1.0.0
tags: [engineering, performance, optimization]
description: Performance profiling analysis and optimization plan.
variables:
  component:
    type: string
    required: true
    ask: "Component or function to profile"
  baseline_metrics:
    type: multiline
    required: true
    ask: "Current baseline metrics (latency, throughput, memory, CPU)"
  target_metrics:
    type: string
    required: true
    ask: "Target performance goals"
---

# SYSTEM
{{ include("safety/base_engineering") }}
{{ include("style/principal_swe") }}

Performance optimization follows the scientific method:
1. **Assumptions**: what the profiling data implies
2. **Bottleneck Analysis**: identify the limiting resource (CPU, IO, memory, lock)
3. **Hypotheses**: ordered by expected impact
4. **Experiments**: each hypothesis → concrete benchmark change
5. **Recommended Optimizations**: with estimated gain and implementation risk
6. **Failure Modes**: what could regress (correctness, latency tail, memory)
7. **Validation Plan**: how to confirm improvement without regression

Do not optimize prematurely. Only target the measured bottleneck.

# USER
**Component**: {{ component }}
**Baseline**: {{ baseline_metrics }}
**Target**: {{ target_metrics }}
