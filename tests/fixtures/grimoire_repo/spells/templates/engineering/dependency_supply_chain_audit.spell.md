---
id: engineering/dependency_supply_chain_audit
name: Dependency Supply Chain Audit
version: 1.0.0
tags: [engineering, security, dependencies]
description: Supply chain risk audit for a package or dependency.
variables:
  package_name:
    type: string
    required: true
    ask: "Package name to audit"
  version:
    type: string
    required: true
    ask: "Package version (e.g. 1.2.3 or ^1.2)"
  ecosystem:
    type: choice
    required: false
    default: "pypi"
    choices: [pypi, npm, cargo, maven, go, nuget]
    ask: "Package ecosystem"
---

# SYSTEM
{{ include("safety/base_engineering") }}
{{ include("style/principal_swe") }}

Perform a supply chain audit covering:
- **Maintainability**: active maintenance, bus-factor, last release
- **Security History**: known CVEs, disclosure response time
- **License Compliance**: SPDX identifier, compatibility with project license
- **Dependency Surface**: transitive dependency count and risk
- **Assumptions**: what is unknown without running the audit toolchain
- **Failure Modes**: what happens if this package is compromised or abandoned
- **Recommendation**: keep / pin / replace / isolate (with justification)
- **Validation Plan**: automated checks to add to CI

# USER
**Package**: {{ package_name }} @ {{ version }} ({{ ecosystem }})
