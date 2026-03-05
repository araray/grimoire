## Patch-Only Output Rubric

When producing a code fix:

- Output the **minimal diff** — change only what is strictly required.
- Do NOT refactor, rename, reformat, or "clean up" unrelated code.
- Do NOT add new dependencies unless the fix requires them.
- Do NOT change public APIs, function signatures, or schemas unless the bug is in those.
- Include a one-sentence explanation of **why** the change fixes the issue.
- List **side effects considered**: what else this change might affect.
- State the **validation command**: exactly which test(s) to run to confirm.
