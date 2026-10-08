# Guardian V3 stale-event reconciliation acceptance

Status: implementation and exact runtime test baseline verified; candidate and
production receipts are recorded by the release controller rather than copied
into this source report.

## Closed defect

An abandoned `local_write` dispatch from another Codex session could remain in
`runtime.open_events` forever and globally prevent a later proposal. The old
fallback was also unsafe: it used age and lane equality without proving that
the source session had ended, without checking the authoritative dispatch row,
and without an append-first settlement record.

The new reconciler has five explicit projections:

1. current-lane blockers;
2. other-lane stale events;
3. real effect or authority debt;
4. settled `inconclusive` events;
5. quarantined high-risk, control-plane, corrupt, or mismatched events.

Proposal blocking is lane/effect/resource scoped. An unrelated proposal is no
longer denied merely because another lane has a retained event. A proposal that
overlaps the same unresolved resource remains denied.

## Settlement invariant

Automatic settlement requires all of the following:

- the effect is exactly `local_write`;
- the source dispatch is uniquely present in the append-only Guardian audit and
  exactly matches the projected event, including attempt/grant/profile fields;
- every target is a typed workspace-local path and is not Guardian, Hook,
  release, CI, environment, or other control-plane state;
- no effect attempt, continuation use, grant/profile, authorized fingerprint,
  or pending verification links the event to material authority;
- the event is older than the safety window;
- the source lane has a formal task continuation, a live host `session_end`, or
  a durable workspace handoff to another contract.

`Stop` is not terminal evidence. External, destructive, unknown, fresh, active,
malformed, mismatched, and unreadable-ledger cases never auto-settle.

The settlement id binds contract identity, source event id, source audit-line
SHA-256, and classifier version. Under the contract lock, the reconciler checks
its projection CAS, appends one immutable settlement first, and only then
removes the event from the mutable projection. A crash between those writes is
replayed idempotently. The outcome is always `inconclusive` with
`authority_transferred=false` and `effect_asserted=false`; it never claims that
the tool succeeded or that no write occurred.

## Boundary behavior

- Proposal creation reconciles before evaluating lane/effect/resource blockers.
- Task continuation audits before the request and again after the exact native
  continuation is applied.
- Doctor exposes all five projections and audit-integrity state separately.
- The no-open-event hot path does not replay the audit or effect ledger.

The production-shaped r193 event `bf54cf4dfbd0808a4b5e39b8` is the negative
control: it resolves to the Guardian/Hook control-plane paths, remains retained
under `quarantined_high_risk`, blocks the same resource, and does not block an
unrelated typed path.

## Verification

- Scoped Guardian suite: 252 passed, 18 skipped.
- Exact runtime commit: `23ae85f7cc887a2c7f71b780351341c610fd9709`.
- Full isolated suite: 1767 passed, 25 skipped in 502.235 seconds.
- Test evidence key:
  `bdd51456aaa852a4cd6bcaa602a9e0fb3fa3148a91048b5561c84fe53616cb21`.
- Log SHA-256:
  `dfc73c06ab3b4c051b5505574e5a0eb8e7061fad2dc8de97ede0dd9ed854ffa9`.
- Source bytecode cleanup before/after: zero files and zero directories.

The existing pre-execution v2 tests also require both
`loaded_module_generation` and `artifact_generation`; a single legacy
`runtime_generation` cannot satisfy release proof.

## Release boundary

Candidate preparation and verification must use a new process and isolated
Codex/Sulde/KB/workspace/scheduler roots. Promotion consumes only the exact
candidate receipt and repeats the live-prestate CAS under the deployment lock.
A failed candidate leaves the installed production generation untouched.

## Sedimentation candidate

Evidence status: conclusive.

- Problem context: a missing completion callback made historical local work a
  global, permanent proposal lock.
- Routing positive: settle only a typed ordinary local write after an
  independently durable source-lane terminal boundary.
- Routing negative: retain current-lane, control-plane, external, destructive,
  unknown, linked, fresh, corrupt, or source-mismatched events.
- Execution positive: contract lock, projection CAS, stable idempotency key,
  append-first settlement, replayable projection, and resource-scoped blocking.
- Execution negative: deleting audit history, treating `Stop` as session end,
  inferring success from age, or letting an unrelated stale event block every
  future task.
