---
description: Add a new frontend (android / ios / flutter / harmony) to an existing sulde-cc project.
argument-hint: "<name> <path> <stack>"
---

Run the `configure-sulde` skill in **add-frontend** mode with args: `$ARGUMENTS`.

Expected: `<name> <path> <stack>` — e.g. `harmony ./harmony mobile-harmony`.

Follow `skills/coordinator/configure-sulde/SKILL.md` §3 — append to `frontends:`, copy `template/<stack>/*` into `<path>/`, install the per-frontend git pre-commit hook, and tell the user the next step is `/sulde-add-team-member` for the new frontend.

Valid stacks (v0.2.0): `mobile-android`, `mobile-ios`, `mobile-flutter`, `mobile-harmony`.
