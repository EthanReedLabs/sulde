---
description: Register a scaffold entry in docs-hub/scaffold-map.yaml (and prompt the coordinator to write its contract).
argument-hint: "<name> [trigger-regex]"
---

Run the `configure-sulde` skill in **add-scaffold** mode with args: `$ARGUMENTS`.

Expected: `<name>` and an optional trigger regex — e.g. `AppTopBar "TopBar|TitleBar"`.

Follow `skills/coordinator/configure-sulde/SKILL.md` §6 — append to `<docs-hub>/scaffold-map.yaml` and remind the coordinator to write the scaffold contract doc at `<docs-hub>/scaffolds/<name>.md` so dev terminals can read it from task-mds.
