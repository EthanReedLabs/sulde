# tasks/ — coordinator-drafted task-mds

Each `*.md` here is a single unit of work the coordinator handed off to this frontend's Dev session.

## Naming

```
{YYYY-MM-DD}-{slug}.md
```

Optional suffix when the same date has multiple drafts: `{YYYY-MM-DD}-{slug}-v2.md`.

## Lifecycle

1. **Drafted** by coordinator (PreToolUse hook `check_task_md_baseline.py` enforces `§起草前 baseline 实证` section).
2. **Executed** by Dev (`/assign` reads frontmatter, switches branch + git identity).
3. **Resolved** — Dev writes a handoff at `../handoff/{date}-{slug}-result.md`. Task-md itself stays here, **not** moved (history-preservation).

## Archive

Move retired / cancelled task-mds to `tasks/archive/` to declutter without losing history. The baseline hook treats `tasks/archive/` as exempt (no `§起草前 baseline` requirement).
