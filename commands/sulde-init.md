---
description: Bootstrap sulde-cc into a new project (interactive 8-step wizard).
argument-hint: "[project-dir]"
---

Run the `configure-sulde` skill in **init** mode.

Project root: `$ARGUMENTS` if provided, otherwise current working directory.

Follow `skills/coordinator/configure-sulde/SKILL.md` §1 — ask Q1-Q7, write `.sulde-config.yaml`, copy missing files from `template/_project/*` + per-stack templates without overwriting existing project content, install git pre-commit hooks, write `.sulde-grace-started` marker, and print next steps including Python 3.10+/PyYAML 6.0+, `sulde doctor`, and `sulde kb lint`.
