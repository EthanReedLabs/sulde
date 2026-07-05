# session-resume/ — long-context session continuations

When a Claude Code session runs close to its context budget, it can write a **session-resume doc** here capturing what remains. The next session reads it on startup to continue without losing thread.

## Naming

```
{YYYY-MM-DD}-{role}-{slug}.md
```

Examples:
- `2026-05-25-dev-feature-foo-impl.md`
- `2026-05-25-coordinator-mid-audit-pause.md`

## What to capture

- Active task-md path(s) being worked on
- Files already modified (with line ranges)
- Decisions made this session (and why)
- What was NOT done (so the next session does not redo)
- Open questions for the user

## Lifecycle

Read once by the next session, then move to `session-resume/archive/` after the next session confirms the resume.
