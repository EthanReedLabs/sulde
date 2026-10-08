# P0 Codex 0.149.1 host-audit freeze

## Frozen outcome

T31 is the sole approved successor to F30-002. It may replace the exact audited
Codex host contract from 0.149.0 to 0.149.1 only after real local probes prove
the version, help/profile and app-server surfaces. It inherits T30's integrated
KB aging source and production acceptance obligations unchanged.

## Exact owned implementation paths

1. `scripts/kb/agent-runtime.py`
2. `scripts/release/install_codex_plugin.py`
3. `tests/test_agent_runtime.py`
4. `tests/test_codex_plugin_install.py`
5. `integrations/codex/plugins/sulde/.codex-plugin/plugin.json`
6. `guardian-program/reports/T31-codex-0149-1-host-audit.md`

Control-plane task, brief, evidence and append-only event records remain
coordinator artifacts and do not grant the worker additional source ownership.

## Bootstrap exception

The installed and source 0.149.0 runtime rejects the current 0.149.1 provider
before a worker can start. After recording read-only real-host probes, the
coordinator may pre-stage in an isolated full clone only the exact 0.149.1
version/help evidence literals and corresponding expected tests inside the
owned paths. That pre-stage is not verified implementation evidence. The
updated clone must then launch through its own `agent-runtime.py`; the worker
must review, complete, test and report the task normally.

## Prohibited expansion

- No semver or patch-range acceptance.
- No Codex downgrade, symlink replacement or alternate executable.
- No direct edits to installed cache, native authority, launcher, marketplace,
  LaunchAgent, production contract, events ledger or effect ledger.
- No interaction with iquokka or any other external project.
- No new task unless a new verified root cause is outside all six owned paths.

## Merge and release order

`T31 candidate → dev → full-clone official suite → main → official staging and
installer → launcher/runtime/native-authority readback → scheduler 15/15 → one
post-install Sulde-owned Codex session → doctor/final-check`.

