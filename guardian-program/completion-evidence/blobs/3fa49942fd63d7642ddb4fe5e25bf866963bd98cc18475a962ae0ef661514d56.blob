# T24 — Frozen P0 transaction integration acceptance

## Control identity

- Task: `T24-p0-transaction-integration`
- Frozen baseline: `9f21a09576f1267612ccf8990e7dfee1ffab3127`
- Integrated source commit: `2d6528440c7c525c251ec368d4da556f23202d40`
- Verification run: `run-gpe-9d84a3e7e26d5694fbc0c75a`
- Integration order: T21 `04d90b7` + `26b4627`, T22 `cf5358d` +
  `c8dea7f`, T23 `90f520d`, then T24 `2d65284`.
- This report accepts only the frozen P0 source batch on `dev`. It does not
  claim production installation, scheduler readiness, live workspace recovery,
  a `dev` to `main` release merge, or an all-green repository suite.

## Implemented integration scope

- Shared Codex AgentPolicy fixtures now bind an explicit session id to the
  matching host-observed `CODEX_THREAD_ID`; ambient sessions cannot silently
  authorize a fixture.
- Native proposal recovery fixtures now expect one typed request and one
  `allow` outcome instead of a duplicate untyped `approved` shadow lifecycle.
- Launcher tests copy only declared runtime inputs and exclude generated Python
  bytecode, so test order cannot alter a launcher digest.
- A seven-row sanitized ledger fixture preserves the observed production shape:
  v1 legacy rows, a typed v2 lifecycle, then later untyped v2 audit rows. The
  source fixture is replayed read-only and contains no production values.
- A focused integration module exercises two concurrent Codex sessions and an
  injected `after_prepared` crash through recovery and exactly-once replay.

All changed product-test paths are inside T24's registered ownership set. No
production module was changed by T24.

## Frozen outcome trace

1. Interleaved typed and untyped rows replay: sanitized fixture and T21 replay
   cases pass; untyped rows never set `execution_authorized`.
2. One authoritative proposal lifecycle: one request has typed outcome `allow`;
   recovery and repeated execution do not append a second request.
3. Foreign-session denied/read-only events: concurrent sibling observations
   leave `material_sequence` unchanged.
4. Real allowed material drift: the composed T22 material-CAS gate still
   invalidates an already approved stale proposal.
5. Atomic provider/session/task-lane binding: a sibling session receives
   `awaiting_human`, writes no authority transaction, and the bound owner applies.
6. Current-lane readiness: T23 projects current, other-lane, historical and
   terminal transactions separately; its 27-test gate remains green.
7. Append-only recovery and exactly once: an injected prepared-stage crash is
   recovered to committed once; replay returns `already_decided`, revision stays
   2, and transaction count stays 1.

## Verification results

- Dependency-complete direct gate: 183/183 PASS.
- Supported isolated gate from the development worktree: 183/183 PASS.
- Clean-clone byte verification at `2d65284`: 183/183 PASS.
- T21 through T23 composed gate recorded before T24: 161/161 PASS.
- Cross-domain gate recorded before T24: 158/158 PASS.
- Full isolated discovery was executed in a clean full clone with a real `.git`,
  a `main` ref, PyYAML and NumPy, and `PYTHONDONTWRITEBYTECODE=1`: 1338 tests,
  1324 passed, 6 skipped, 6 failures and 2 errors.

The full-suite result is not reported as a pass. Seven red tests reproduce at
the frozen baseline or are pre-recorded baseline defects: later-session initial
intent confirmation, two event-observer/intervention cases, two recovery path
alias cases, and the subprocess encoding guard. The only P0 delta is an old E2E
assertion that still expects both `allow=1` and a duplicate legacy
`approved=1`; the frozen P0 contract intentionally produces one typed lifecycle,
so the observed result is `allow=1`, `approved=0`. Restoring a shadow untyped
approval would violate frozen outcome 2. The assertion is therefore rejected as
a product-regression signal and retained as visible release-suite debt. This is
why no `dev` to `main` merge or production installation is claimed here.

## Findings and scope control

- F24-001: shared AgentPolicy fixtures inherited a live Codex thread and could
  fail for the wrong session. Fixed within T24 by explicit dual binding.
- F24-002: generated source bytecode made launcher tests order-dependent. Fixed
  within T24-owned tests by hashing a clean copy of declared runtime inputs.
- F24-003: one legacy E2E assertion requires the duplicate untyped lifecycle
  removed by frozen outcome 2. Rejected as a product regression with A/B and
  focused typed-lifecycle evidence; retained as non-green release-suite debt.

No new task, source owner, scheduler work, plugin install, production ledger
repair, or broad decomposition was added.

## Rollback

Before any release merge or installation, revert `2d65284` to remove only the
T24 test changes. T21, T22 and T23 have their own separately recorded reverts.
Production state has no T24 rollback because T24 did not mutate it.

## 沉淀候选

### Candidate: host session identity must be explicit in approval fixtures

- 证据状态: `verified`
- 问题语境: tests passed alone but failed inside a live Codex session because an
  inherited `CODEX_THREAD_ID` disagreed with the fixture's decision session.
- 路由正例: bind the fixture provider session and host-observed session to the
  same explicit value.
- 路由反例: clear or ignore the production session guard merely to make a test
  pass.
- 执行正例: exercise missing, mismatched and exact session identities before an
  authority transaction is written.
- 执行反例: let an empty or ambient session silently select a task lane.

### Candidate: source-tree bytecode can poison launcher integrity tests

- 证据状态: `verified`
- 问题语境: a test runner imported runtime modules before launcher verification,
  leaving `__pycache__` under the hashed source tree.
- 路由正例: verify a clean declared runtime-input copy and run discovery with
  bytecode output disabled or redirected.
- 路由反例: weaken the production launcher contract to accept executable
  bytecode in an install source.
- 执行正例: retain the production fail-closed rule and isolate test artifacts.
- 执行反例: make pass/fail depend on test order.

### Candidate: migration fixtures need ledger shape, not production data

- 证据状态: `verified`
- 问题语境: the production failure required legacy rows after a typed lifecycle,
  which ordinary fresh-contract fixtures did not represent.
- 路由正例: preserve schemas, ordering and lifecycle relationships while
  replacing every production identity and value.
- 路由反例: copy a real ledger into tests or assume one schema generation is a
  contiguous file suffix.
- 执行正例: replay the sanitized fixture read-only and assert its bytes are
  unchanged.
- 执行反例: repair tests by editing, truncating or reordering the source ledger.
