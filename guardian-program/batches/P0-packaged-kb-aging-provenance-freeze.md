# P0 Packaged KB Aging Provenance — Frozen Scope

## Authority and baseline

- Program: `guardian-remediation-r97`
- Coordinator / single writer: `guardian-coordinator`
- Source baseline: `0bbce250c399c7b8e7d430bf4612157d32adb7a1`
- Integration branch: `dev`
- Sole successor: `T30-packaged-kb-aging-provenance`
- Superseded acceptance task: `T29-sulde-local-live-acceptance`
- User decision: explicitly confirmed this one bounded source correction after the
  coordinator proved the current installed actor fails only because immutable
  runtime lacks Git history provenance.

## Frozen design

1. Keep Git commit history as the source-of-truth age signal in a checkout.
2. During official staging, generate one deterministic `knowledge/HISTORY.json`
   before sealing the delivery generation.
3. Bind the history payload to the verified corpus fingerprint and exact
   document path/content hashes. Validate its own canonical digest; the delivery
   generation provides the outer immutable-tree seal.
4. In a packaged runtime with no `.git`, `kb-aging` must read only the validated
   history payload. It must fail closed on missing, malformed, tampered, duplicate,
   incomplete, timezone-free or corpus-mismatched evidence.
5. Validate the artifact at staging and installation boundaries. Prove the real
   no-`.git` topology in tests.
6. Bump the Codex plugin cachebuster only after source tests pass, then use the
   official validator/installer and generation-fenced scheduler reconciliation.

## Explicit non-goals

- No pointer from a LaunchAgent or installed runtime to a mutable source checkout.
- No `.git` directory or raw repository history in a plugin artifact.
- No file mtime substitution and no silent fallback when packaged provenance is
  missing or invalid.
- No change to aging thresholds, feedback semantics, report content or scheduler
  topology beyond restoring the existing actor.
- No production contract/ledger edit, cache patch, manual plist edit, iquokka
  interaction, unrelated cleanup, new feature, or additional task decomposition.

## Merge and completion order

1. Run one approved L3 worker in an isolated full clone against the exact base and
   owned paths.
2. Coordinator reviews the candidate and independently runs targeted, tamper and
   packaged-runtime tests.
3. Merge to `dev`, run composed and official OS-isolated gates, then merge the
   exact verified candidate to `main`.
4. Build, validate and install through the official Codex plugin chain; do not
   edit the installed cache directly.
5. Reconcile and verify all 15 actors on the new generation; explicitly prove
   `com.sulde.kb-aging` exits zero.
6. Complete one post-install Sulde-owned live Codex canary, register all evidence,
   run the program final check, then clean merged stale worktrees.
