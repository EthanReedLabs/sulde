---
description: Add a UserPromptSubmit trigger regex → skill reminder mapping.
argument-hint: "<regex> <skill> [role]"
---

Run the `configure-sulde` skill in **add-skill-trigger** mode with args: `$ARGUMENTS`.

Expected: `<regex> <skill> [role]` — e.g. `"pen-truth.*更新" update-design coordinator`. `role` defaults to `any` if omitted.

Follow `skills/coordinator/configure-sulde/SKILL.md` §7 — append to `skill_triggers:` in `.sulde-config.yaml`. The `skill_trigger.py` hook merges user triggers with the built-in defaults at every UserPromptSubmit.
