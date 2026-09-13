# Anti-pattern ADR Index

This directory holds Anti-pattern Decision Records (ADRs) — a registry of recurring problems your team has hit, why they happen, and how to prevent them.

**Sulde ships one example ADR (`0000-example.md`) to demonstrate the format.** Your project's real ADRs start at `0001` and grow from actual incidents.

## How to register a new ADR

1. Pick the next free four-digit id (`0001`, `0002`, ...)
2. Create `{id}-{kebab-case-slug}.md`
3. Fill the frontmatter per [`_frontmatter.schema.yaml`](./_frontmatter.schema.yaml):
   - `adr`, `title`, `platforms`, `first_logged`, `recurrence: 1`, `lint_status: pending`
4. Write the body (Symptom / Root cause / Cost / Mitigation / Related)
5. Add a row to the table below
6. Commit

## How to update an existing ADR (recurrence)

When a known pattern recurs:
1. Increment `recurrence:` in the frontmatter
2. Add the new incident date in the body
3. Update the `last_seen` column in the table below

When you ship a lint rule that catches the pattern:
1. Set `lint_status: shipped`
2. Reference the lint rule path under "Mitigation"

## Registered ADRs

| id | title | platforms | first | last | recurrence | lint |
|---:|---|---|---|---|:-:|---|
| 0000 | Example: dev fixing a small bug spreads diff to unrelated files | any | 2026-01-01 | — | 1 | drafted |
| 0001 | Coordinator drafts task-mds from memory instead of grepping the repo | coordinator | 2026-01-01 | — | 1 | shipped |
| 0002 | Feature code bypasses scaffold contract (one-off impl instead of shared component) | android, ios, flutter, harmony | 2026-01-01 | — | 1 | pending |
| 0003 | Cold Flow / Publisher used where Hot StateFlow / @Published is needed for L1 truth source | android, ios | 2026-01-01 | — | 1 | pending |
| — | (your project's first real ADR lands here as `0004`) | | | | | |

> **Note**: rows 0000-0003 ship as mobile examples in the sulde v0.2.0 template. Replace or extend with your project's actual incidents over time. Row 0001 is enforced by `hooks/lib/check_task_md_baseline.py` (`lint_status: shipped`).

## Conventions

- **Title style**: action-oriented and recognizable from the title alone. Avoid jargon-only titles ("scope creep" — too abstract; "Dev fixing X bug spreads to Y file" — recognizable).
- **No retroactive renumbering**: once an id is assigned, never reuse it, even if the ADR is later retired (mark it archived, keep the id).
- **One ADR per pattern**, not per incident: when a known pattern recurs, increment `recurrence:` rather than registering a new ADR.

## Audit cadence

Run `grep` for `lint_status: pending` in this directory quarterly. Patterns sitting at `pending` for 6+ months are candidates either for being downgraded to `infeasible` (cannot reasonably lint-detect) or for a focused effort to author the lint rule.
