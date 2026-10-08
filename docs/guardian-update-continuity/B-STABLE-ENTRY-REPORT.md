# B stable-entry installer candidate

Status: candidate awaiting independent review; no production installation, push,
dev/main mutation or historical deletion. r11 scope is isolated source and tests.

## Delivered boundary

- New stable candidates use strict `codex plugin list --json`, checked against the
  actual current read-only CLI schema (`installed` rows, local `source.path`).
  Garbage, missing fields, ambiguous same-name registration and unknown coverage
  are `migration_required`, never an empty installation inferred from text failure.
- Fresh origin means only no existing Codex cache paths or prior Codex deployment,
  retirement/bootstrap/marketplace provenance. It is **not** global session drain.
  Shared Claude launcher provenance is allowed; ambiguous ownership is not erased.
- Existing legacy commands refuse before deployment lock, home migration, registry
  mutation or active bootstrap publication. Stable registration copied into an old
  cache does not establish fresh lineage. Stable lineage cannot downgrade to a
  legacy candidate. Explicit legacy candidates retain their old unverified lifecycle.
- Stable continuation binds current deployment, installed tree, bootstrap descriptor
  and exact cache paths/targets/tree hashes. Cache/registry inventory is rechecked
  immediately before prune, including newly appearing paths.
- Immutable bundle preparation is inside the transaction. Bootstrap publication is
  after final lease admission **and** prune inventory checks, before registry removal.
  Bootstrap is part of existing launcher snapshots and postconditions. Rollback
  restores exact bytes (or absence); append-only bundles remain inert and retained.
- The interpreter is the installer's existing verified runtime interpreter, pinned
  by A's descriptor. The entry does not silently choose a different PATH Python.

## Validation

Official isolated B module run at `0caeef44c1eb11327cf39c0149e696e484196123`:

- 11 tests passed; 94.202 seconds; exit 0; `input_drift=false`.
- Run `20261006T041208.581240-0989fb0a2be3` under
  `.codex-agent/s3-c-entry-evidence/` (`.json` and `.log`).
- Log SHA256 `bda79bde38dfc02cccb8489f3e25febab7ac830d813228d13aab23d85e6e90fa`.
- Real installer failpoint after cache removal starts **new processes from the
  actual registered command**: Read stays non-denied, Write/unknown are denied.
  Recover-only restores the old bootstrap bytes and cache. This does not rely on
  an already-open wrapper FD to stand in for a not-yet-started command.
- Final-admission injected refusal runs the actual installer chain and observes
  the publisher was never called, in addition to checking old bootstrap bytes.
  Rollback equality alone is not used to claim zero active mutation.
- Hard-exit after bootstrap publication exercises real recovery and verifies that
  bootstrap is restored while immutable bundle remains.

The fixture's old installer suite now explicitly stages the legacy transport;
the dedicated B suite explicitly stages stable-v1. This is fixture protocol
selection, not a production bypass, and prevents old-cache lifecycle tests from
implicitly claiming migrated stable coverage. Coordinator owns combined regression.

## Candidate findings and unresolved scope

The first new registered-command Read probe failed because the initial A candidate
selected system Python 3.9 from daemon-like PATH. The production runtime producer
had already verified a 3.10 interpreter. A's pinned-interpreter fix and the actual
window rerun passed. This is a **candidate integration defect**, not proof of an
old deployed policy defect.

Cross-source stable upgrades need old sealed bootstrap identity verification rather
than re-rendering old bytes with a new loader implementation.
The new test on A candidate `af51a9f` failed as predicted (20.906 seconds): first
installation succeeded, second full CLI with a benign LOADER source revision
returned `migration_required: stable bootstrap identity is unverified`. This is
candidate red evidence, not a regression ascribed to the old deployed version.

A correction `4c305e8` was incorporated as `5666048`. The identical cross-loader
assertion and the new-process/cache-removal window both passed in the official
incremental run `20261006T042311.714564-7e59eb0f369f`: 2 tests, 60.74 seconds,
exit 0, `input_drift=false`, at HEAD `5666048c1d21952233c6514c3839daf1a70bf133`.
Evidence is in the same directory as the 11-test run; log SHA256
`5120d43b0239d4f882622e58ef2e237290b0ee49c08b27b9388ef64fc589ef7e`.
The second real install uses a harmless LOADER implementation revision injected in
an isolated CLI shim, not a mock of the gate/verification/transaction. It verifies
old sealed bytes and publishes different new bootstrap bytes successfully. This is
producer-variant integration evidence, not a claim of a live production upgrade.

No claim of production Hook trust, hot migration of old in-memory legacy commands,
Windows readiness, or all-session quiescence is made. Legacy migration remains
`migration_required`; starting a new session cannot certify all older sessions.
Future stable installations are supported without inventing a force receipt.

## Combined-suite fixture correction

Coordinator's frozen full run exposed
`test_candidate_install_routes_receipt_evidence_to_canonical_marketplace`.
Independent reproduction failed in 2.506 seconds: the receipt-routing unit fixture
constructed nonexistent candidate/canonical paths, so the new read-only migration
gate fell back to the stable source template and attempted `codex plugin list
--json`; isolated fixture PATH intentionally contained no real Codex binary.
This is a candidate test-input adaptation gap, not an old deployed product defect.
Both fake artifact roots now contain the explicit legacy Hook document from the
already staged fixture. No production function or gate is mocked or relaxed by
the correction. The same single test passed in 2.436 seconds. Full-suite input
remains frozen in the coordinator worktree; this correction awaits later integration.

The frozen S2 extraction AST guard consequently reported a second fixture failure.
Read-only AST comparison found exactly two changes: `prepare_artifact` and the
receipt-routing test above; `setUp`, `tearDown`, `run_installer` and the other 61
test bodies were unchanged. The original AST golden remains byte-for-byte intact.
A separate evolution manifest records only these two before/after hashes, commits
and reasons. The guard checks each original hash before applying that transition,
then still checks all 62 test identities, uniqueness, owners, skip decorators,
helper order/bodies and inherited method ownership. No bulk regeneration occurred.
New in-memory negative injections alter an unregistered method, helper or skip
condition; each still fails the guard. Collection guard and injections passed
2/2 in 0.234 seconds. This is explicit fixture evolution, not a product fix.

The R2 generation-admission unit fixture had the same missing-protocol issue:
`test_block_refuses_before_any_mutation` expected generation rejection but instead
received `command unavailable: codex-fake plugin list --json` (single repro,
0.065 seconds). Its synthetic artifact now declares a legacy Hook document so it
tests its intended generation gate. The production migration gate and ordering
are unchanged; the original rejection text and `_install_locked.assert_not_called`
remain. Both block and observe unit cases passed in 0.058 seconds. This is another
candidate fixture adaptation, not a new production permission exception.

## Sedimentation candidates (not written to shared KB)

- Verified: parse failure is not evidence of absence. Route positive: strict empty
  inventory plus no owned history; route negative: malformed inventory or retained
  provenance. Execution positive: refuse before active publication; negative:
  publish then rollback and label it zero mutation.
- Verified: installer runtime interpreter and Hook bootstrap must consume the same
  identity. Route positive: verified runtime path/hash; negative: incidental PATH.
  Execution positive: start registered command after cache deletion; negative:
  use a previously opened FD as proof of future command reachability.
