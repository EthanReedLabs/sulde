---
description: Mark a file as sensitive — Dev terminals must not self-fix it without coordinator task-md.
argument-hint: "<path>"
---

Run the `sulde-add-sensitive-file` skill with args: `$ARGUMENTS`.

Expected: `<path>` relative to project root — e.g. `core-ui/AppRouter.kt`.

Follow `skills/sulde-add-sensitive-file/SKILL.md` end to end. Register the path in both `.sulde-config.yaml: scope_sensitivity.sensitive_files` and project `.claude/settings.json: permissions.deny`, preserving existing settings and keeping repeated runs idempotent.
