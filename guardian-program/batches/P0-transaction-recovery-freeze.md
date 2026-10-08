# P0 Transaction Recovery Batch — Frozen Scope

## Authority and baseline

- Program: `guardian-remediation-r97`
- Coordinator / single writer: `guardian-coordinator`
- Source baseline: `9f21a09576f1267612ccf8990e7dfee1ffab3127`
- Integration branch: `dev`
- Batch tasks: `T21`, `T22`, `T23`, followed by serialized `T24`
- Production ledgers and installed plugin cache are read-only inputs. No worker may
  edit, truncate, reorder, delete, or replay them.

## Frozen P0 outcome

This batch fixes only the production blockers reproduced in Codex sessions
`019fee8b-bcad-7623-be8e-dd3743f69039` and
`01a02cbe-3377-7ac1-a9e5-362def3fb765`:

1. typed native authority remains valid when historical untyped audit rows are
   interleaved in the append-only approval store;
2. new proposal approval writes one authoritative lifecycle and cannot be
   authorized by untyped presentation rows;
3. denied or read-only events from another session do not mutate the proposal's
   material CAS world;
4. a real allowed material change in the protected scope still invalidates a
   stale proposal;
5. proposal, decision, apply, provider, session and task lane remain one atomic
   binding, and Codex agent decisions cannot silently use an empty session id;
6. readiness counts only current-lane active mismatches while reporting
   historical and other-lane transactions separately;
7. existing prepared transactions are recoverable through append-only terminal
   events and apply remains exactly once across crash boundaries.

## Explicit non-goals

The following remain P1 candidates and cannot be added to this batch without a
new coordinator decision after T24 acceptance:

- scheduler repair or reload;
- effect-debt resource scoping;
- workspace repair mode / circuit breaker;
- plugin installation, live workspace recovery, or production ledger mutation;
- unrelated classifier, exporter, notification, UI, documentation, or refactor
  work;
- broad Intent Guardian decomposition beyond seams required by the seven P0
  outcomes above.

## Parallel ownership

| Task | Scope | Exclusive source ownership |
| --- | --- | --- |
| T21 | approval authority producer, historical projection and append-only native recovery | approval/native journal/recovery modules and their focused tests |
| T22 | material CAS and mandatory Codex session/lane binding | policy, state, task ownership, CLI entry and focused tests |
| T23 | current-lane readiness projection | operational readiness module and its tests |
| T24 | serialized integration, shared-suite additions, production-fixture replay and total acceptance | shared integration tests and batch evidence only |

Workers may not edit `guardian-program/**`, the shared Git index, production KB,
installed cache runtime, or paths owned by another task. A worker reports a new
fact as a finding; it does not create a task, change this scope, change a shared
schema, merge, install, or declare acceptance.

## Frozen shared contracts

- Existing approval rows remain immutable and sequence-contiguous.
- Typed authority is identified per row and per request lifecycle, not by being
  a positional suffix of the file.
- Untyped rows are non-authoritative and cannot satisfy native authority.
- `audit_sequence` describes observation order; `material_sequence` changes only
  for a finally allowed material action. A denied `started` event never changes
  it.
- The minimum binding tuple is provider, session id, workspace, intent id,
  revision, task epoch and proposal digest.
- Current readiness is scoped to the exact binding tuple. Historical and other
  lane facts remain visible but are not current CAS failures.
- All recovery is append-only and idempotent. No stale proposal or receipt is
  applied after its material or binding world changes.

## Change-control rule

A discovered issue is handled in exactly one of these ways:

1. `fixed_current`: necessary to satisfy an acceptance clause and within the
   task's owned paths;
2. `transferred`: blocks a later registered task in this frozen batch;
3. `rejected_with_evidence`: not reproducible or already covered;
4. recorded as a P1 sedimentation candidate without implementation.

No fifth path exists. In particular, findings do not silently become tasks.

## Merge and verification gate

1. T21, T22 and T23 may run concurrently from the same baseline.
2. Each worker stops at `implemented` with changed-file, test, failure-injection,
   finding and rollback evidence.
3. The coordinator verifies and merges in order T21, T22, T23.
4. T24 starts only after all three are integrated.
5. T24 must run targeted tests, the full isolated suite, an immutable sanitized
   copy of the observed production ledger shape, two-session concurrency tests,
   and prepared/apply crash recovery tests.
6. This batch is accepted only when all seven frozen outcomes have direct
   evidence, all findings have an explicit disposition, and `dev` is clean.
7. Installation and live recovery require a separate user-visible decision
   after the source batch report is accepted.

