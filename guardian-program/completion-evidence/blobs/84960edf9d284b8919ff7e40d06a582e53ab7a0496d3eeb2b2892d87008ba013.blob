# T22 — Material CAS and Codex lane binding

## Control identity

- Task: `T22-material-cas-lane-binding`
- Frozen baseline: `9f21a09576f1267612ccf8990e7dfee1ffab3127`
- Worker commit: `ba98d33c990e57b0aebe2cf2393092a77b2eace7`
- Verification run: `run-gpe-656b9b20b4b4882b1199d002`
- State at report: implemented and independently task-verified; not integrated,
  installed, system-verified, or accepted.

## Implemented outcome

- `material_sequence` advances once for a finally allowed material action. A
  denied, read-only, or control-plane event does not change proposal CAS.
- A matching completion does not double count its allowed start. An allowed
  completion without an observed start advances once as a fail-closed boundary.
- Codex `agent-decide-proposal` requires an explicit session id and rejects a
  mismatch with host-observed `CODEX_THREAD_ID` before calling the authority
  producer.
- The existing contract-lock apply path now records the exact task epoch and
  proposal digest in the current task lane; injected contract-write failure
  leaves neither a new revision nor a partially bound lane.
- F00-002 is handled through a literal exact-target compatibility exception for
  `.codex-agent`. Repository roots, ancestors, wildcards and `.git` remain
  denied; there is no broad control-directory allowlist.
- Codex CLI proposal entry points forward the resolved provider into the T21
  authority producer interface.

## Changed files

- `scripts/kb/intent-guardian.py`
- `scripts/kb/intent_guardian_parts/policy.py`
- `scripts/kb/task_ownership.py`
- `tests/test_material_cas_lane_binding.py`

All changed paths are inside T22's frozen ownership set.

## Independent verification

- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -q
  tests.test_material_cas_lane_binding tests.test_intent_guardian_state
  tests.test_critic_checkpoint`: 55 tests, PASS.
- Three focused failure-injection tests for partial apply, missing/mismatched
  session and unmatched completion: 3 tests, PASS.
- Python compile and `git diff --check 6872570..ba98d33`: PASS.

The wider `tests.test_intent_guardian` baseline still has two non-T22 outcomes:
one shared fixture expects the now-forbidden empty Codex session id and is owned
by T24; one legacy hook environment assertion depends on unavailable PyYAML and
predates this commit. Neither is presented as passing T22 evidence.

## Findings and integration obligations

- F00-002: fixed in the T22 candidate and remains an acceptance obligation until
  the coordinator records integrated evidence.
- Direct Python `decide_proposal_as_agent` session validation is owned by T21;
  CLI validation alone is not sufficient for integrated acceptance.
- The T21 provider parameter must be integrated before dynamic CLI
  `revise`/`propose-revision` verification.
- T23 consumes `runtime.task_lanes[].proposal_digest` plus exact provider,
  session and task epoch. Workspace, intent and revision remain contract-owned.

## Residual risk and rollback

An allowed completion without a matching start conservatively invalidates an
older proposal. This can create a safe retry but cannot authorize stale work.
Rollback before integration is `git revert ba98d33`; no production state,
installed cache, scheduler or ledger was changed.

## 沉淀候选

### Candidate: denied observation polluted a workspace-global proposal CAS

- 证据状态: `verified`
- 问题语境: two Codex sessions shared one workspace contract; a denied unknown
  event from one session advanced `material_sequence` between another session's
  proposal and decision.
- 根因: material state was advanced before the final policy decision and for
  both started and completed observations.
- 路由正例: denied/read-only/control event → audit sequence only; finally
  allowed material action → material sequence once.
- 路由反例: classify every unknown observation as a material mutation before
  knowing whether it ran.
- 执行正例: an allowed start owns the increment; an unmatched allowed completion
  increments once to fail closed.
- 执行反例: increment denied starts or count a matched start and completion
  twice.

### Candidate: compatibility control path exception became a directory allowlist

- 证据状态: `verified`
- 问题语境: an explicitly approved `.codex-agent` artifact was denied by a
  blanket path rule, while a broad exception would expose the whole control
  directory.
- 根因: the policy had only unconditional deny or normal descendant allowlist
  semantics, with no exact compatibility target identity.
- 路由正例: exact literal target under `.codex-agent`, already present in the
  human-reviewed allowed paths → evaluate that target only.
- 路由反例: allow `.codex-agent/**`, the workspace root, an ancestor or `.git`.
- 执行正例: resolve both target and approved literal under the workspace and
  require identical lexical-relative and resolved identities.
- 执行反例: authorize by substring, basename, glob expansion or directory
  membership alone.

