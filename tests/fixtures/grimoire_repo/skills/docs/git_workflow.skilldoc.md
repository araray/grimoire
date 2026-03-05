---
id: skills/git/workflow
name: Git Workflow Guide
version: 1.0.0
description: Best practices for Git branching, rebasing, and collaboration.
tags: [git, devtools, vcs]
sections:
  - id: branching
    tags: [branching, workflow]
  - id: rebase
    tags: [rebase, history]
  - id: commit_messages
    tags: [commits, workflow]
---

## branching

Use short-lived feature branches off `main`. Naming: `<type>/<ticket>-<brief-desc>`.

Types: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`.

Delete branches after merge. Keep `main` always deployable.

## rebase

Prefer rebase over merge for integrating upstream changes on feature branches:

```
git fetch origin
git rebase origin/main
```

Interactive rebase to clean up commits before PR: `git rebase -i origin/main`.
Squash WIP commits, ensure each remaining commit is a logical unit.

Never rebase shared branches (`main`, `release/*`).

## commit_messages

Follow Conventional Commits: `<type>(<scope>): <imperative summary>`

- 50 chars max for subject line
- Blank line before body
- Body: what changed and why (not how)
- Reference issues: `Fixes #123`

Good: `fix(parser): handle empty frontmatter in spell files`
Bad: `fixed bug` / `WIP` / `various changes`
