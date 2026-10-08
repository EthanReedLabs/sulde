# Codex CLI 0.155.1 compatibility audit

Base: local dev `c82d537642334645c4a08cd95f59f5c0aef86d14`.
Branch: `task/codex-01551-contract-audit`.
Scope approved by current-session native proposal, revision 21.

## Scope

Audit the already installed CLI, without upgrading it. Capture physical executable
identity, canonical help surfaces and version-specific generated protocol schema.
Exercise real CLI PreToolUse/PostToolUse, session continuation and native authority
consumers with local response fixtures and disposable candidate homes. Only after
behavioral evidence passes may the exact version pin and affected fixtures move.
Reject unsupported versions, executable/help drift and invalid receipts as before.

No production installation, scheduler changes, merge, push, old worktree cleanup,
full-suite run or formal knowledge-base mutation. Keep private machine evidence
under this task's ignored `.sulde/cli-contract-audit/` directory. Capture source
hashes, logs and actual exit codes; setup failure or skipped tests are not PASS.

## Acceptance

- Native behavior first; schema/help alone never confer compatibility.
- Related installer, staged artifact, managed runtime and broker regressions pass.
- Retain negative cases and historical reports; do not rewrite old evidence.
- Bound the conclusion to macOS CLI, distinguishing fixtures from human approval.
- Commit only this task after review; report outstanding installation requirements.
