# baseline/ — pre-task evidence snapshots

Output of the `§起草前 baseline` step the coordinator runs **before drafting a task-md**.

Each file documents the grep / git-log / scaffold-query outputs that justify a coordinator's task-md draft. The hook `check_task_md_baseline.py` only checks that the task-md *itself* contains the `§起草前 baseline 实证` section; the grep evidence is normally inline in that section, but you can also store extended outputs as separate files here when too long.

## Naming

```
{YYYY-MM-DD}-{task-slug}-baseline.md
{YYYY-MM-DD}-{task-slug}-baseline.json    # for tooling output
```

## Lifecycle

Append-only. Old baselines aid post-mortem analysis ("what did the coordinator think the truth was on date X?").
