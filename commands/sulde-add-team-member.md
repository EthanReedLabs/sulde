---
description: Add a team member + create the per-project `git as-<alias>` shell alias.
argument-hint: "<alias> <name> <email> <frontend>"
---

Run the `configure-sulde` skill in **add-team-member** mode with args: `$ARGUMENTS`.

Expected: `<alias> <name> <email> <frontend>` — e.g. `as-c Carol carol@team.com flutter`.

Follow `skills/coordinator/configure-sulde/SKILL.md` §4 — append to `team:` in `.sulde-config.yaml`, install a per-repo git alias that sets `SULDE_COMMIT_ALIAS=<alias>` (so the `check_commit_alias.sh` pre-commit hook lets the commit through), and remind the user the alias is per-repo (new clones must re-run this command or recreate the alias).
