# P0 Release And Live Recovery — Frozen Scope

## Authority and baseline

- Program: `guardian-remediation-r97`
- Coordinator / single writer: `guardian-coordinator`
- Source baseline: `f87d58689968372cf4332860ac0ee155241e5424`
- Integration branch: `dev`
- Release order: `T25-release-gate-closure`, then
  `T26-production-session-recovery`
- Production contracts, event logs, approval stores and effect ledgers remain
  append-only inputs. They may not be edited, deleted, reordered or replayed.

## Frozen outcome

This release phase contains exactly two tasks:

1. T25 closes the eight red cases disclosed by T24 and proves a clean full
   isolated repository suite without weakening typed authority, intervention
   verification or unknown-generation fail-closed behavior.
2. T26 merges the verified candidate through `dev` to `main`, updates the
   plugin cachebuster, uses the repository's official transactional Codex
   installer, reconciles the installed scheduler generation, and verifies live
   recovery for exactly these existing Codex sessions:
   - `019fee8b-bcad-7623-be8e-dd3743f69039`
   - `01a02cbe-3377-7ac1-a9e5-362def3fb765`

## T25 exact red inventory

The only source defects and stale tests in scope are the eight T24 red cases:

- later-session initial intent confirmation compares an obsolete presentation
  card under lock and fails after native Allow;
- supervision E2E still expects the removed duplicate untyped `approved` row;
- event observer does not project supported v2 approval/intervention rows;
- one intervention fixture lacks a canonical typed resource key;
- two recovery alias fixtures do not actually create a distinct path alias;
- the subprocess text-encoding guard has one behavior-equivalent false positive;
- intervention subprocess reads omit explicit UTF-8 replacement decoding.

Observer support is limited to existing v1 and v2 schemas. Unknown v3 remains
unsupported and nested authority/evidence payloads remain private. Projection
cache state must change when the projection contract changes.

## Explicit non-goals

- No new feature, broad refactor or additional Intent Guardian decomposition.
- No weakening of typed native authority, material CAS, resource verification,
  privacy projection or fail-closed rules.
- No manual repair, truncation or deletion of production JSON/JSONL ledgers.
- No approval replay, fabricated hook evidence, synthetic live canary or reuse
  of an old receipt.
- No installation before T25 is accepted, `dev` is clean and the full isolated
  suite passes.
- A newly discovered source defect stops the release and is reported to the
  user; it does not silently become a third task.

## Control and merge gates

1. T25 runs in one isolated repository worktree from the frozen dev baseline.
2. T25 may touch only its registered files and records every finding and
   disposition before acceptance.
3. Focused tests, failure injections, the composed P0 gate and a clean full
   isolated suite must pass before T25 merges to `dev`.
4. `dev` may merge to `main` only after an independent release verification on
   the exact dev commit and both branches are clean.
5. T26 uses `scripts/release/install_codex_plugin.py`; installed cache runtime
   is never patched directly. Old versioned cache trees are retained for
   rollback and only the official stable hook bridges may be refreshed.
6. Scheduler recovery must be generation-fenced. Effect debt is settled only by
   its registered verifier or an exact native intervention; the side effect is
   never repeated.
7. A session is accepted only after real host observations for the installed
   generation and doctor evidence show its current lane operational. Source
   tests or synthetic callbacks cannot satisfy this gate.

## Change-control rule

Every discovery is classified as `fixed_current`, `rejected_with_evidence`, or
`blocked_release`. No discovery creates another task without an explicit user
scope decision. T26 begins only after T25 acceptance.
