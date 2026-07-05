---
description: End the 7-day onboarding grace period immediately; switch to the configured enforcement_level.
---

Run the `configure-sulde` skill in **end-grace** mode.

Follow `skills/coordinator/configure-sulde/SKILL.md` §8 — confirm `.sulde-grace-started` exists, write `.sulde-grace-ended` marker file in project root, and inform the user that hooks now enforce at the level configured in `.sulde-config.yaml: enforcement_level` (default `balanced`).
