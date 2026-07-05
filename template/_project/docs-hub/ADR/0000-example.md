---
adr: "0000"
title: "Example: dev fixing a small bug spreads diff to unrelated files"
platforms: [Any]
first_logged: 2026-01-01
recurrence: 1
lint_status: drafted
---

# 0000 — Example: dev fixing a small bug spreads diff to unrelated files

> **This is an example ADR.** It exists to demonstrate the format and serve as a starting point. Delete or archive it once your project has registered its first real ADR (`0001`).

**First logged**: 2026-01-01 (illustrative)
**Platforms**: Any
**Recurrence**: 1
**Lint status**: drafted

---

## Symptom

A Dev is asked to fix a small, well-scoped bug (typically 1 file, 1–5 lines). When the commit lands, the diff actually touches 4+ unrelated files: a typo "fixed" on the way, an import re-organized, a code style nit corrected, a comment rewritten. The Dev mentions none of these in the commit message.

The coordinator notices days later — usually because the unrelated change broke something downstream that nobody connected back to "the small bug fix."

## Root cause

Three contributing causes, in decreasing order of impact:

1. **No explicit scope contract.** The task was dispatched as inline chat ("fix the typo in foo.ts") rather than through a task-md with `§3 scope: in / out`. The Dev infers scope from context, and "while I'm in there" feels efficient.
2. **No self-fix boundary documented.** The Dev's session has no `<docs-hub>/00_shared-rules/self-fix-boundary.md` listing which kinds of incidental changes are OK to bundle (typo, import order) vs which require a separate commit or escalation (anything in a scaffold layer, anything cross-feature).
3. **Code-review culture rewards "leaving the campground cleaner."** Engineers learn this norm early; in a coordinated multi-Dev setup it backfires because the coordinator now has to reconcile changes that were never tracked.

## Cost

- **Audit cost**: each unrelated change in a "single-bug-fix" commit requires the coordinator to trace why it was made, when reviewing handoffs days later
- **Regression risk**: unrelated changes go unmentioned in the commit message, so when one breaks production it's hard to pinpoint
- **Cross-Dev conflicts**: when two Devs are working in adjacent areas and one of them "drive-by-fixes" a file in the other's territory, the merge gets messy

## Mitigation

### Short-term (project-level)

- For any task expected to exceed a few lines, dispatch via task-md with explicit `§3 scope: in / out`
- The `assign` skill reads `§3` and treats out-of-scope files as untouchable

### Medium-term (per-team)

- Author a `<docs-hub>/00_shared-rules/self-fix-boundary.md` listing concretely which incidental changes are OK vs require escalation. Examples of what to call out:
  - Typo fix in a comment in the same file you were already editing: OK, mention in handoff
  - Import re-ordering: NOT OK as drive-by — separate commit
  - Anything in `core-ui/` or scaffold layers: NOT OK — escalate
- Reference `self-fix-boundary.md` from each Dev's CLAUDE.md so it's read once per session

### Long-term (tooling)

- Pre-commit hook that compares the diff's touched-file set against the task-md's declared in-scope list (when there is one)
- Treat any out-of-scope file in a "task-md commit" as a soft warning the Dev must explicitly acknowledge

---

## Related

- (Cross-link to other ADRs as your project accumulates them. Examples: an ADR about commit-message conventions, an ADR about scaffold-layer boundaries, an ADR about handoff format.)

## Why this is an example

Real ADRs in this directory should be triggered by **actual incidents** in your project, not pre-imagined cases. The example above is a common pattern in many teams, but until *your* team has hit it, you don't know the specific shape it takes in your codebase. Wait, observe, then register `0001` from a real incident.
