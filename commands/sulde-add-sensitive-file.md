---
description: Mark a file as sensitive — Dev terminals must not self-fix it without coordinator task-md.
argument-hint: "<path>"
---

Run the `configure-sulde` skill in **add-sensitive-file** mode with args: `$ARGUMENTS`.

Expected: `<path>` relative to project root or frontend root — e.g. `core-ui/AppRouter.kt`.

Follow `skills/coordinator/configure-sulde/SKILL.md` §5 — append to `scope_sensitivity.sensitive_files:` and remind the coordinator/dev terminals that future self-fixes touching this path will be blocked by the `self-fix-boundary.md` rules.
