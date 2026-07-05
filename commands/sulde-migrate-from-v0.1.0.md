---
description: Migrate a v0.1.0 sulde-cc project to v0.2.0 (config schema + Python hooks + grace period).
---

Run the `configure-sulde` skill in **migrate** mode.

Follow `skills/coordinator/configure-sulde/SKILL.md` §2 — read existing `.sulde-config.yaml`, show schema diff, dry-run to `.sulde-config.yaml.v2-preview`, on confirm back up the original as `.sulde-config.yaml.v0.1.0-backup`, write the upgraded file, drop a `.sulde-grace-started` marker (7-day re-acclimation), and print the v0.1.0 fallback path (`/plugin install skills@sulde-cc@0.1.0`).
