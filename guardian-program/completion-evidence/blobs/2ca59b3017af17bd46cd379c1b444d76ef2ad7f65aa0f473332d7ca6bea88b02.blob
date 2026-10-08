# T25 — Release gate closure report

## Control identity

- Task: `T25-release-gate-closure`
- Frozen baseline: `f87d58689968372cf4332860ac0ee155241e5424`
- Worker branch: `release/t25-release-gate-closure`
- Worker commit: `2c0f8f96098c52be8178eca18dff24fb892472f7`
- Verification run: `run-gpe-45a0eac272952f59169b6fef`
- This report covers source release readiness only. It does not claim a
  `dev`-to-`main` merge, plugin installation, scheduler recovery, effect-debt
  settlement or live recovery of either production Codex session.

## Implemented scope

- Initial-intent confirmation now rechecks the semantic decision content under
  the contract lock instead of reconstructing an obsolete four-field
  presentation card. The full card, target and binding are still checked before
  the lock and intent id, revision and workspace remain checked under it.
- The read-only event observer accepts the existing v1 and v2 approval and
  intervention generations, including typed prompt observation, replacement
  and atomic batch events. Unknown generations remain unsupported.
- The observer publishes only counts, controlled labels and digests; nested
  snapshots, typed receipts, raw resources and free-form evidence are not
  copied. Projection cache state advances from 1 to 2 so old unsupported
  projections cannot survive the adapter change.
- The external-effect observer fixture now supplies the canonical URI resource
  key required for replay-authoritative human settlement. Product settlement
  rules were not weakened.
- Recovery lexical-alias fixtures now create a real `//` alias for any absolute
  test root and prove it differs from the canonical input.
- Text subprocesses in intervention filesystem probing explicitly decode UTF-8
  with replacement. The critic expression was rewritten without behavior
  change so the static guard recognizes its already-safe text branch.
- The supervision E2E now expects one typed `allow` lifecycle and no duplicate
  untyped `approved` shadow row. Its cache assertions reflect a healthy v2
  source: exact hit followed by tail replay.

All ten changed files are inside T25's frozen ownership set. No production
contract, event log, approval store, effect ledger, installed cache or scheduler
state was modified.

## Verification results

- Approval, observer, MCP entry, recovery, subprocess encoding, supervision,
  intervention and critic-focused modules passed after the fixes.
- Native decision journal, intervention batch, critic and composed P0 gates
  passed 312/312 on the worker commit.
- A direct worktree discovery was intentionally not accepted as release
  evidence: its Git pointer-file layout triggered the broker's full-clone guard
  and the outer sandbox added a Codex PATH-alias warning.
- The first complete-clone isolated run reached all source tests but correctly
  failed seven launcher cases because the runner's parent interpreter had
  already emitted `scripts/kb/__pycache__/audit_cursor.cpython-314.pyc`.
- After deleting only that disposable bytecode directory and starting the
  parent with `PYTHONDONTWRITEBYTECODE=1`, the official OS-isolated runner
  completed 1340/1340 PASS with 6 platform skips and zero production-write
  violations. The clone had a real `.git` directory, its local `main` pointed
  at the exact candidate, and the production sentinel was an empty local test
  directory rather than the real KB.

## Findings and dispositions

- F25-001 — Later-session initial confirmation compared an obsolete
  presentation card after native Allow, leaving the contract unconfirmed.
  `fixed_current` by semantic decision-content comparison plus lifecycle
  assertions (`open=0`, `allow=1`, `cancelled=1`).
- F25-002 — v2 approval/intervention rows were produced by current code but
  treated as unsupported by the observer. `fixed_current` with explicit v1/v2
  adapters, typed/batch/privacy coverage and unknown-v3 rejection.
- F25-003 — The external-effect observer fixture created keyless legacy debt
  and could not safely attest it. `fixed_current` in the fixture by using the
  canonical URI resource key; settlement authority remains fail closed.
- F25-004 — Two alias tests used a macOS `/private/tmp` substitution even though
  their fixtures now live under the repository, so no alias was created.
  `fixed_current` with a root-independent lexical alias helper.
- F25-005 — The initial complete-clone run was polluted by parent-process
  bytecode before the isolated child environment existed.
  `rejected_with_evidence` as a product regression: the clean no-bytecode rerun
  passed all 1340 tests and launcher integrity remained strict.
- F25-006 — The supervision E2E expected the duplicate untyped approval removed
  by P0 and old mixed-cache behavior caused by unsupported v2 rows.
  `fixed_current` as stale test expectations; no shadow authority was restored.
- F25-007 — Two real text subprocess reads lacked explicit cross-locale
  decoding, while one critic expression was a static-analysis false positive.
  `fixed_current` with UTF-8 replacement decoding and a behavior-equivalent
  conditional rewrite.

No finding created a new task or expanded the frozen T25/T26 graph.

## Rollback

Before production installation, revert
`2c0f8f96098c52be8178eca18dff24fb892472f7` to remove the ten T25 changes.
There is no production rollback action for T25 because it changed no production
state.

## 沉淀候选

### Candidate: lock-time CAS should compare stable semantics, not presentation cards

- 证据状态: `verified`
- 问题语境: a readable approval card gained operation and decision metadata,
  while an under-lock check reconstructed an older UI shape and rejected a
  valid native Allow after already writing the typed decision.
- 路由正例: validate the full immutable presentation before entering the lock,
  then recheck stable semantic content and exact contract identity under lock.
- 路由反例: reconstruct a duplicated UI dictionary in the executor or remove
  the under-lock intent/revision/workspace CAS.
- 执行正例: assert terminal request counts and confirmed contract state after a
  later-session native decision.
- 执行反例: treat a successful prompt click as proof that the contract transition
  also committed.

### Candidate: event adapter generation and projection cache version are one change

- 证据状态: `verified`
- 问题语境: authoritative producers moved to v2 while a read-only observer and
  its durable cache remained v1-only, causing healthy rows to appear degraded
  and old unsupported projections to persist.
- 路由正例: add only declared schema generations, keep future generations
  unsupported, redact nested authority, and bump the cache state version.
- 路由反例: accept any `v*` schema, copy typed receipts/snapshots, or leave the
  durable cache version unchanged.
- 执行正例: cover v1, v2, archive identity, batch rows, privacy, unknown v3 and
  old-cache invalidation together.
- 执行反例: make observer acceptance influence approval or intervention
  authority.

### Candidate: the test runner parent can poison source integrity before child isolation

- 证据状态: `verified`
- 问题语境: the supported runner imported a source module before building its
  bytecode-free child environment, creating a `.pyc` that strict launcher
  verification correctly rejected.
- 路由正例: set `PYTHONDONTWRITEBYTECODE=1` on the parent invocation and verify a
  clean full clone with a real `.git` directory.
- 路由反例: weaken launcher integrity, ignore `__pycache__`, or accept worktree
  pointer-file failures as product failures.
- 执行正例: disclose the polluted run, remove only disposable derived bytes,
  then rerun the complete suite from the exact candidate.
- 执行反例: report only focused green tests as a full release pass.
