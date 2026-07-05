# 00_shared-rules — Cross-session shared rules

This directory holds rules that **all Claude Code sessions in your project read** — coordinator, every Dev, every audit subagent. They are the project's "constitution": one source of truth for conventions, boundaries, and references.

Sulde leaves this directory **empty by design**. The rules your team needs depend on your specific stack, team size, design tool, and accumulated incidents. Sulde provides the slot; you fill it.

## Suggested files to author (when relevant)

Pick the subset that fits your project. Skip the rest. There is no Sulde-prescribed list — these are common patterns.

### `data-sources.md`

> Which sources of truth take priority when they disagree.

A short, ordered list: e.g. "user explicit input > design source > product spec > implementation doc > existing code." When two sources conflict, the higher one wins. The coordinator cites this when writing task-mds; the Dev cites it when self-fixing.

### `self-fix-boundary.md`

> Which kinds of changes a Dev may make without prior coordinator approval.

A table of categories with concrete examples. See ADR `0000-example.md` for why this matters. Patterns to typically include:
- Trivial style/typo fixes within an already-edited file: OK
- Scaffold-layer changes (UI primitives, navigation, base classes): escalate
- Data-source URL/endpoint changes: escalate
- Anything touching ≥3 unrelated files: escalate

### `verify-build.md`

> The canonical build, install, and runtime-verify recipe for each frontend.

Steps the Dev must run before declaring a task done — compile commands, lint scripts, real-device install, screenshot/log evidence. Per-frontend if the steps differ.

### `model-strategy.md`

> Which Claude model to use for which kind of task.

Project's view on opus / sonnet / haiku trade-offs. Coordinator writes `model:` in task-mds based on this; Dev's `assign` skill honors it.

### `perf-diagnosis.md` (if your project has performance-sensitive UI or backend paths)

> Gate criteria before a "fix this slowness" task gets dispatched.

Requirement: measured numbers, top-3 candidate root causes, profiler/trace artifact. Prevents fix-by-guessing on perf issues.

### `language.md`

> Output-language conventions.

When and where each language applies: real-time responses, handoff docs, commit messages, code comments. Mixed-language teams should be explicit; single-language teams can skip this.

## How sessions discover these rules

The Sulde plugin does not auto-load this directory. Each session loads them by convention — typically referenced from your project root `CLAUDE.md` or from a per-frontend `CLAUDE.md`. Example (in `CLAUDE.md`):

```
Before any action that fits one of these scenarios, read the corresponding rule:

| If I'm doing this | I must read |
|---|---|
| Writing a task-md | docs-hub/00_shared-rules/self-fix-boundary.md, data-sources.md |
| Building or verifying | docs-hub/00_shared-rules/verify-build.md |
| Picking model: header  | docs-hub/00_shared-rules/model-strategy.md |
```

This way you control which rules are mandatory reads, not the framework.

## When to add a new file here

A rule moves into `00_shared-rules/` only when **all sessions** need it. Otherwise:

- One session only → put it in that session's local config
- One frontend only → put it in that frontend's directory
- Process-specific → put it in the relevant skill or task-md template
