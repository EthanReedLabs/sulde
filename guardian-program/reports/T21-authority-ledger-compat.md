# T21 — Authority ledger compatibility and recovery

## Control identity

- Task: `T21-authority-ledger-compat`
- Frozen baseline: `9f21a09576f1267612ccf8990e7dfee1ffab3127`
- Worker commit: `78ce09fd3528e66f7998be583a6dd038a1dbfe64`
- Verification run: `run-gpe-c4d6a18cabdc0a254f1a2eb5`
- State at report: implemented and independently task-verified; not integrated,
  installed, system-verified, or accepted.

## Implemented outcome

- Typed and untyped approval rows are replayed row by row. Historical untyped
  rows remain readable but never grant authority, even when they appear after a
  typed lifecycle.
- New Codex proposals create one typed `PermissionRequest` lifecycle; they no
  longer append the generic untyped `proposal_review` lifecycle to the
  canonical authority store.
- Native binding v4 includes the exact task epoch. Existing v3 rows remain
  readable as historical compatibility, but no new v3 authority is emitted.
- Prepared native transactions recover append-only and apply exactly once. A
  stale task epoch is superseded before apply, and an already consumed receipt
  cannot be replayed.
- Direct Agent API calls validate a non-empty, bounded Codex session id and any
  host-observed `CODEX_THREAD_ID` before authority is written.
- An expired undecided request may be re-evaluated against the same material
  snapshot using a new domain-separated request identity. The expired receipt
  remains unusable and the refreshed request still requires a new native
  decision.

## Changed files

- `scripts/kb/approval_invariant.py`
- `scripts/kb/native_decision_journal.py`
- `scripts/kb/intent_guardian_parts/approvals.py`
- `scripts/kb/intent_guardian_parts/recovery.py`
- `tests/test_approval_invariant.py`
- `tests/test_native_decision_journal.py`

All changed paths are inside T21's frozen ownership set.

## Independent verification

- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -q
  tests.test_approval_invariant.ApprovalTypedCASLedgerTests
  tests.test_native_decision_journal`: 79 tests, PASS.
- Seven focused journeys covering the single typed lifecycle, expired-request
  refresh, task-epoch drift, prepared crash recovery, Codex session validation,
  external-write routing and legacy event-question cancellation: 7 tests,
  PASS.
- Python compilation and worker-tree diff inspection: PASS.

The wider baseline retains three unrelated known failures: the initial intent
card fixture reports `intent card changed`, and two guardian-recovery lexical
alias/pathname cases remain red. The full shared integration fixture also
contains old calls without explicit Codex session identity and old dual-request
assertions; T24 owns those fixture updates. None is presented as passing T21
evidence.

## Findings and integration obligations

- F21-001: the typed-suffix positional assumption rejected valid interleaved
  history; fixed by per-row classification.
- F21-002: Codex proposals emitted both generic untyped and typed authority
  lifecycles; fixed by one typed producer.
- F21-003: v3 native binding omitted task epoch and could alias a later task;
  fixed for new authority by v4 exact-epoch binding.
- F21-004: a same-snapshot expired request could not be safely re-evaluated;
  fixed with a new domain-separated identity and no receipt reuse.
- T22 must supply the provider/session/lane values consumed by the v4 producer.
- T23 must interpret v3 rows as history and scope only exact v4 bindings as
  current authority.
- T24 must replace shared legacy fixture expectations with explicit sessions
  and the single typed lifecycle, then exercise the composed implementation.

## Residual risk and rollback

Historical untyped rows remain visible for audit but intentionally cannot be
promoted to authority. A refresh does not extend or mutate the old request; it
creates a new decision boundary. Rollback before integration is
`git revert 78ce09f`; no production state, installed cache, scheduler or ledger
was changed.

## 沉淀候选

### Candidate: typed authority replay assumed one positional suffix

- 证据状态: `verified`
- 问题语境: a canonical ledger contained older untyped rows interleaved with
  typed native rows; replay rejected the ledger although typed authority was
  individually well formed.
- 根因: the reader treated migration as a global cutover position instead of a
  per-row schema distinction.
- 路由正例: classify every row independently; typed rows enter native authority
  validation and untyped rows remain audit-only.
- 路由反例: require every row after the first typed row to also be typed.
- 执行正例: only a complete, bound and consumed typed lifecycle may apply.
- 执行反例: infer authority from row position or from a legacy approval word.

### Candidate: timeout refresh reused an expired authority identity

- 证据状态: `verified`
- 问题语境: the five-minute pairing window expired while the material snapshot
  and task lane were unchanged; retry either stayed permanently blocked or
  risked replaying the old receipt.
- 根因: request identity mixed the material proposal with the lifetime of one
  human-decision attempt.
- 路由正例: after expiry and only while undecided, derive a domain-separated new
  request id bound to the same snapshot and require a new native decision.
- 路由反例: mutate the old expiry, treat timeout as approval, or accept its old
  receipt.
- 执行正例: append the refreshed lifecycle and consume it exactly once.
- 执行反例: overwrite history or apply both old and refreshed receipts.
