# ui-audit/ — audit subagent reports

Output of the `coordinator-maintenance` skill when it dispatches a UI audit subagent. Subagents read design-truth + current implementation, then write findings here.

## Naming

```
{YYYY-MM-DD}-{page-id-or-scope}-audit.md
```

Examples:
- `2026-05-25-03A1-audit.md` (audit of one page)
- `2026-05-25-all-titlebars-audit.md` (sweep across pages)

## Report format

Each audit report should include:

1. **Scope** — which pages / components were audited
2. **Design-truth references read** — file paths + section refs
3. **Findings** — per-page list of mismatches (severity rated)
4. **Recommended actions** — task-md drafts the coordinator should consider

## Lifecycle

Coordinator reads → decides whether to dispatch follow-up task-mds → audit report stays here as historical record. Do not delete; old audits are useful for trend analysis.
