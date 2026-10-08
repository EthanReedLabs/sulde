# T23 — Current-lane native readiness

## Control identity

- Task: `T23-current-lane-readiness`
- Frozen baseline: `9f21a09576f1267612ccf8990e7dfee1ffab3127`
- Worker commit: `74061a6`
- Verification run: `run-gpe-29520e7a7b23276c16fbdd20`
- State at report: implemented and independently task-verified; not integrated,
  installed, system-verified, or accepted.

## Implemented outcome

- Approval requests and native transactions are projected into mutually
  exclusive current, other-lane, historical, terminal and malformed scopes.
- A scoped contract treats only a v4 binding with exact workspace, intent,
  revision, provider, session, task epoch and current-lane proposal target as a
  current transaction.
- Historical v1/v3 bindings remain visible but cannot become current authority
  after task lanes exist. Legacy contracts without a lane retain compatibility
  projection.
- Historical, terminal and other-lane facts no longer add to current
  `cas_mismatch`.
- Exact-current request/binding inconsistency remains fail-closed. Multiple
  exact-current active transactions produce one scoped conflict instead of a
  count proportional to unrelated history.

## Changed files

- `scripts/kb/operational_readiness.py`
- `tests/test_operational_readiness.py`

Both paths are inside T23's frozen ownership set.

## Independent verification

- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -q
  tests.test_operational_readiness`: 27 tests, PASS.
- Production-shape cases cover 25 terminal plus four historical/other-lane
  transactions with zero current mismatch.
- Adding 40 historical terminal transactions leaves one real current fault at
  exactly one mismatch.
- Python compile and `git diff --check 6872570..74061a6`: PASS.

## Findings

- F23-001: historical and other-lane transaction counts were linearly added to
  current CAS mismatch. Fixed in the candidate.
- F23-002: a historical v3 binding without task epoch could match current
  provider/session/revision. Fixed by requiring v4 for scoped current authority.
- F23-003: more than one active transaction for the exact current tuple needs a
  real fail-closed signal. Fixed as one `native_current_scope_conflict`.
- The proposed approval-row task-epoch expansion was rejected by the control
  plane because it would unnecessarily change the timeout-policy schema. Task
  epoch remains in native v4 binding; no task or owned path was added.

## Integration obligations and rollback

T24 must verify the final T21 v4 binding and T22 lane `proposal_digest` contract
together. Exact-current committed authority remains subject to independent T06
external-head verification. Rollback before integration is `git revert
74061a6`; no production state, scheduler, installed cache or ledger was changed.

## 沉淀候选

### Candidate: historical audit volume amplified current readiness failures

- 证据状态: `verified`
- 问题语境: one workspace retained many historical native transactions while a
  new Codex session evaluated its current proposal.
- 根因: readiness iterated every same-workspace/same-intent transaction and
  counted any non-exact binding as a current CAS mismatch before classifying
  lifecycle status or lane ownership.
- 路由正例: first classify exact-current, other-lane, historical, terminal and
  malformed; only exact-current inconsistency controls the current gate.
- 路由反例: treat every old or foreign-lane record as evidence that the current
  transaction is corrupt.
- 执行正例: report scope counts separately and collapse one same-scope conflict
  to one actionable blocker.
- 执行反例: let journal length linearly increase the blocker count and obscure
  the one request that an operator must repair.

