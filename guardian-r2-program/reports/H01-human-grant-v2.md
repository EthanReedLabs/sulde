# H01 — HumanGrantV2 and risk taxonomy

## Control identity

- Task: H01-human-grant-v2
- Frozen baseline: 0eb4fb6553e652b0352750f4bac24aa6bae746d7
- Worktree branch: task/r2-h01-human-grant-v2
- State at report: implemented and locally verified in the isolated worktree;
  not integrated, installed, live-host verified, committed, merged, or released.
- Intent lineage: l3:r2-h01-human-grant-v2-repair1 (repair continuation of
  l3:r2-h01-human-grant-v2).

## Implemented outcome

- Added a pure standalone HumanGrantV2 protocol leaf with no ledger and no
  file, network, host, or default-policy I/O.
- The sealed grant binds provider, session, 24-hex task epoch, subject,
  capability, effect, constraints, card, request, typed receipt, world state,
  expiry, and verifier. Exact plain-JSON field sets, immutable-by-value copies,
  domain-separated canonical SHA-256 identities, and revalidation at consume
  make omission, subclass injection, and post-issuance tampering fail closed.
- Added the closed risk taxonomy read, reversible_local,
  external_or_destructive, and integrity_unknown. Complete exact boolean facts
  are required; missing, extra, malformed, unverified, or unknown facts classify
  as integrity_unknown rather than a safer class.
- A native typed human allow receipt bound to the exact card/request/grant
  binding can produce an available grant. Text, a copied binding digest, deny,
  agent authority, timeout, display, silence, and chat cannot do so.
- An unchanged available grant produces executable authority directly, with
  default_policy_recheck_required=false. Consumption returns a deterministic
  version 0 to version 1 CAS transition and a sealed consumed grant.
- A world-state mismatch returns fresh_decision_required with a stable,
  recursively sorted JSON Pointer diff. It returns no authority or CAS mutation
  and leaves the input grant unchanged. Provider, session, epoch, subject,
  capability, effect/resource, constraints, and verifier replacement reject
  immediately instead of being treated as world drift.

## Repair result — FR2-H01-002

- Independently reproduced that an operation=read fact set with either
  local_effect=true or reversible=true was incorrectly classified as read.
- A read classification now requires the internally consistent no-effect shape:
  local_effect=false, reversible=false, external_effect=false,
  destructive=false, and integrity_verified=true. Either local/reversibility
  contradiction returns integrity_unknown.
- Verified external or destructive facts are still evaluated first and remain
  external_or_destructive; the repair does not downgrade high-risk facts.
- Added two focused contradiction subtests, one for local_effect=true and one
  for reversible=true. FR2-H01-002 is closed by the focused and combined
  regression results below.

## Requirement traceability

| Requirement | Implementation evidence | Test evidence |
| --- | --- | --- |
| HumanGrantV2 exact bindings | Strict material, nested card/request/receipt, current-context, seal, and receipt equality validation | grant creation binding, typed receipt mismatch, current provider/session/epoch mismatch, tampering |
| Four-class closed taxonomy | classify_risk with an exact six-field fact set and derived capability risk | all four classes; omitted, extra, wrong-type, unknown, subclass, and magic-object cases |
| Canonical identity and immutable data | UTF-8 sorted compact JSON, allow_nan=false, domain separation, deep copies, seal revalidation | order-independent/domain-separated identity, no input alias or mutation |
| Approved unchanged one-shot consume | no policy argument; executable authority plus versioned consumption CAS | unchanged authority, duplicate rejection, deterministic concurrent projections |
| World drift requires a new human decision | stable recursive JSON Pointer diff, no authority, no consumed state | repeatable ordered diff and byte-equivalent input grant |
| Negative authority cases | exact native typed receipt and complete current bindings | text, copied digest, timeout/display/silence/chat, deny, old provider/session/epoch, expiry/future receipt, tampering, replacement, non-plain JSON |
| Pure standalone boundary | standard-library value transforms only; no persistence or effect execution | source inspection, AST parse, focused and existing-module regression gates |

## Verification

- PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v
  tests.test_human_grant: 23 tests ran, all passed (including two focused
  FR2-H01-002 contradiction subtests).
- PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -q
  tests.test_human_grant tests.test_approval_cas_schema
  tests.test_approval_timeout_policy tests.test_approval_invariant: 116 tests
  ran, all passed.
- PYTHONDONTWRITEBYTECODE=1 python3 -c with ast.parse over the source and test:
  AST OK: 2 files.
- git diff --check and an exact H01 path inventory: no whitespace errors; the
  only H01 outputs are the three paths listed below.
- No test command created or removed repository bytecode.

## Actual changed paths

- scripts/kb/human_grant.py
- tests/test_human_grant.py
- guardian-r2-program/reports/H01-human-grant-v2.md

The three untracked guardian-program H01 coordinator inputs (the repair brief,
original brief, and task definition) were present before repair and retain their
pre-repair SHA-256 identities. No other guardian-r2-program file exists or
changed.

## Known limits

- This pure layer projects a deterministic compare-and-swap transition but does
  not persist it. A future owner must atomically commit the returned expected
  and next consumption identities; accepting two stale projections without
  that CAS would violate exactly-once semantics.
- The layer binds a native typed verifier document and channel but does not
  authenticate a host signature or invoke a native prompt. Those are adapter
  responsibilities outside H01.
- Subject, effect, constraints, world-state, and verifier payload semantics are
  intentionally caller-defined plain JSON. H01 guarantees exact identity and
  drift detection, not external truth discovery.
- This report makes no H02 integration, durable-ledger, production-state, or
  live-host proof claim.

## 沉淀候选

### Candidate: pure exactly-once authority requires an explicit CAS handoff

- 问题语境: a pure protocol cannot truthfully serialize concurrent consumers or
  mutate durable state, but returning an executable token without a commit
  precondition would let two stale copies both be accepted.
- 证据状态: verified in the pure layer; durable-store composition is not yet
  verified.
- 路由正例: route both concurrent calls through the same available consumption
  identity and require the owner to atomically replace expected version 0 with
  the returned version 1 identity.
- 路由反例: infer uniqueness because two pure calls returned equal objects, or
  add hidden process-local mutable state to a supposedly standalone protocol.
- 执行正例: commit one CAS transition, execute its bound effect once, and reject
  the consumed grant on replay.
- 执行反例: execute before CAS commit, accept both stale transitions, or treat a
  duplicate receipt as idempotent execution authority.

### Candidate: approval-looking observations must remain non-authoritative

- 问题语境: text saying approved, a displayed digest, silence, timeout, or chat
  can resemble human consent while lacking a typed request-bound receipt.
- 证据状态: verified in H01 unit tests; native-host issuance is not live-proven.
- 路由正例: accept only the exact native typed receipt schema bound to provider,
  session, task epoch, verifier, request, card, effect, world, and expiry.
- 路由反例: route text, display state, a copied digest, timeout, or absence of a
  denial into receipt creation.
- 执行正例: consume the unchanged typed allow exactly once without a second
  default-policy decision.
- 执行反例: promote an approval-looking observation or stale receipt to
  executable authority.
