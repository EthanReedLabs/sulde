---
description: Bootstrap sulde into a new project (interactive 8-step wizard).
argument-hint: "[project-dir]"
---

Run the `configure-sulde` skill in **init** mode.

Project root: `$ARGUMENTS` if provided, otherwise current working directory.

Follow `skills/coordinator/configure-sulde/SKILL.md` §1 — ask Q1-Q7, write `.sulde-config.yaml`, copy `template/_project/*` + per-stack templates, install git pre-commit hooks, write `.sulde-grace-started` marker (7-day grace), and print next-steps including the `pip install pyyaml>=6.0` reminder.
