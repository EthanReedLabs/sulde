# H03 RecoverySupervisor repair2 — report-only closure

## Scope and baseline

H03 repair1 was performed in the independent worktree at frozen baseline
`dev@0eb4fb6553e652b0352750f4bac24aa6bae746d7`. Repair2 continues that exact
candidate and changes only this report; the implementation and test bytes are
preserved.

The handoff path
`guardian-r2-program/task-definitions/H03-recovery-supervisor.json` is absent
from this worktree. The auditable repair2 task input is
`.codex-agent/r2-h03-recovery-supervisor-repair2.task.json`, matching the
repository task definition at
`guardian-program/task-definitions/H03-recovery-supervisor.json`. No authority
or task-definition file was created or changed.

The two dependent projections retain their baseline digests:

- `scripts/kb/human_grant.py`: `6b5ec257cb4ca0edb446f861aab1aea19f43bec17ff6711804bcb7ecbc0cb2d8`
- `scripts/kb/grant_broker.py`: `89432ec4808a470c5e48644b5859436c44485349e9379816266c106cbc9be458`

## Reviewer finding closure

| Finding | Root cause | Repair design | Deterministic regression |
|---|---|---|---|
| FR2-H03-001 | Process probes were caller-authored facts; event ordering could select fabricated `dead`. | Added `sulde-process-observation-receipt-v1`, binding configured/actor probe authority, exact PID+start token, immutable source event, outcome and supervisor receipt time. Unknown, untrusted, foreign, PID-only, access-denied, stale and equal-time contradictory facts are rejected/ambiguous and never prove owner death. | `test_only_trusted_exact_unambiguous_dead_receipt_can_reclaim`, PID-reuse test |
| FR2-H03-002 | Actor `observed_mono` was used as the liveness clock. | Every observation gets durable injected-local-clock receipt time. SLA, lease eligibility and deadlines use receipt monotonic time. Future, impossible and regressive source clocks are quarantined; exact replay retains the first receipt. | `test_future_and_regressive_source_clocks_cannot_suppress_sla`, duplicate/replay tests |
| FR2-H03-003 | Scan baseline and sequence were read outside the durable writer lock. | `SupervisorState.append_derived` computes baseline and derived scan identity in one local+file writer critical section; committed rows carry journal sequence/head metadata. | `test_independent_simultaneous_scans_commit_unique_ordered_identities` |
| FR2-H03-004 | Retry could call `apply` twice, and adapter claims were accepted as verification. | Authorization seals trusted adapter capability and independent verifier identity. Durable prepare commits one effect identity; retry after that boundary only calls `reprobe`, never `apply`. Completion requires a separate exact verifier receipt bound to intervention, adapter, effect, subject, world digest and result. Unknown reprobe remains `awaiting_verification`. | crash matrix test and `test_adapter_completion_without_independent_verification_is_not_success` |
| FR2-H03-005 | Recommendations authorized by ID without rechecking current eligibility. | Recommendations bind eligibility digest and relevant journal head. Authorization re-evaluates under the append transaction; execution re-evaluates again in the prepare transaction. Owner/lease/generation/binding/terminal/conflict drift retires stale work before an executable intervention can be created or dispatched. | `test_recovery_lease_generation_and_terminal_drift_retire_old_work` |
| FR2-H03-006 | Terminal actors remained in liveness, restart, conflict and lock-owner reductions. | Durable business terminal and cancellation are absorbing for supervisor action decisions while their terminal snapshots remain readable. Later transport/liveness noise cannot regress the actor to running. | `test_terminal_and_cancellation_absorb_all_liveness_and_conflict_noise` and existing terminal tests |
| FR2-H03-007 | Blocking `flock(LOCK_EX)` had no deadline. | Added process-local timed serialization plus nonblocking cross-process flock. Contention raises typed `SupervisorStateBusyError` within the bounded contract; no production sleep/retry loop is used and the journal remains unchanged. | `test_held_state_lock_fails_typed_and_bounded_without_journal_damage` |
| FR2-H03-008 | Each operation followed a mutable parent pathname. | Relative input is rejected first. The existing parent is canonicalized once and retained by directory descriptor. All leaves use `dir_fd`, no-follow and CLOEXEC; each operation checks fd/path parent identity, leaf identity, owner, mode, link count, read-only state and metadata substitution. macOS `/var` and `/private/var` canonical equivalence is retained without resolving sensitive leaves. | `test_relative_parent_and_leaf_identity_attacks_fail_closed` |
| FR2-H03-009 | The repair1 managed task environment could not start a nested OS isolation backend while its outer task isolation was active. | Preserve this as a historical environment note only and use the independent coordinator evidence collected after repair1 became quiescent as the acceptance record. No permission widening or alternate result is attributed to the managed worker. | Independent 89-test run, preserved FR2-H03-001..008 attack probe, and supported isolated 162-test runner; all recorded by the coordinator. |

## Durable state and authority model

`SupervisorState` is an owner-only append-only JSONL hash chain. Malformed,
torn, tampered, symlink, hardlink, replacement, broad-mode, wrong-owner,
read-only, parent replacement and fd/path substitution cases fail closed. The
same durable critical section performs check/reduce/append operations for scan
allocation, first-receipt selection, authorization and dispatch preparation.

The protocol separates these authorities:

1. source observations are evidence metadata only;
2. supervisor receipts establish trusted local receipt time and accepted source identity;
3. recommendations describe a current eligible state and carry no execution authority;
4. authorizations seal adapter, capability, verifier, subject and world state;
5. prepare commits one dispatch/effect identity;
6. adapter result is not trusted verification;
7. only an independently bound verifier receipt can produce terminal `completed`.

The implementation still mints no HumanGrant, external-effect, path-expansion,
provider-switch, merge, signal, deletion or Git authority.

## SLA and replay properties

- Registration receipt or the most recent accepted cursor-increasing receipt is
  the liveness baseline. At exactly 5 seconds a stable visible status card is
  projected; each 30-second no-progress window emits the typed reason.
- Caller wall/monotonic fields never advance the authoritative liveness clock.
  Exact replay returns the original receipt; valid out-of-order reduction is
  deterministic, and future/regressive/impossible fields are rejected.
- Lock reclamation still requires both an expired exact lease and one trusted,
  exact, unambiguous `dead` receipt. Its 10-second execution bound derives from
  supervisor monotonic eligibility.
- Business terminal/cancellation suppress all later liveness, restart,
  conflict-pause and lock-owner actions without deleting their snapshots.
- Restart caps, exact binding, backoff, minimal-lane conflict handling and
  reversed-order observation preservation remain covered.

## Crash and concurrency evidence

| Boundary or race | Expected/observed invariant |
|---|---|
| state append before write / after write / after fsync | retry converges to one hash-chain event or fails closed on damage |
| authorization before / after append | one stable intervention identity |
| prepare before / after append | no dispatch before durable prepare; one effect identity after it |
| apply before / after return | non-idempotent adapter is invoked at most once |
| dispatch receipt before / after append | retry reprobes the same adapter/effect; it does not apply again |
| reprobe before / after return | unknown remains nonterminal and awaits verification |
| verifier before / after return and verifier-receipt append | no adapter self-verification; exact independent receipt is required |
| intervention receipt before / after append | at most one terminal completion receipt |
| two independent supervisor instances scan simultaneously | distinct durable ordered scan sequences `1` and `2` |
| second process holds private state lock | typed busy result before five seconds; unchanged readable journal |

## Verification evidence

The following evidence was produced by the independent coordinator after
repair1 became quiescent. It is not attributed to the repair1 managed worker.

- `PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest tests.test_recovery_supervisor tests.test_sulde_supervisor tests.test_runtime_provider tests.test_operational_readiness tests.test_terminal_invariants`: exit 0; 89 tests in 2.442 seconds; `OK`.
- The preserved attack probe covered all FR2-H03-001..008 cases with these safe observations:
  - fabricated process fact: no recommendation and no authorization;
  - future source clock: authoritative progress stayed at local receipt time,
    two status cards appeared, and `future_source_clock` was recorded;
  - concurrent scans: unique sequences `[1, 2]`;
  - crash after adapter application: one apply, one reprobe, and independently
    verified completion;
  - stale owner/lease recommendation: authorization rejected;
  - durable business terminal: no liveness card;
  - contradictory equal-time facts: no selected dead fact, no recommendation,
    and explicit ambiguity reasons;
  - held lock returned an immediate typed busy result within the five-second SLA;
  - parent replacement was rejected without state written into either substitute.
- `PYTHONDONTWRITEBYTECODE=1 /Users/eric/.claude/plugins/data/sulde-cc/kb/venv/bin/python -B scripts/kb/run-isolated-tests.py tests.test_recovery_supervisor tests.test_sulde_supervisor tests.test_agent_runtime tests.test_dual_runtime_contract tests.test_runtime_provider tests.test_operational_readiness tests.test_terminal_invariants`: exit 0; 162 tests in 72.846 seconds; `OK`.

The supported isolated runner also observed concurrent external production-KB
changes to `codex-harvest-state.json` and `memory.db` behind its verified
read-only boundary. Those external changes are not attributable to H03, and no
H03 write targeted them.

Environment note: the repair1 managed task environment could not start a nested
OS isolation backend while the outer task isolation was active. This is a
historical environment capability note, not a completion or acceptance
command. The successful coordinator runs above are the acceptance evidence for
FR2-H03-009.

Repair1 code and test bytes remain identical. The repair2 post-edit hash
recheck records:

- `scripts/kb/recovery_supervisor.py`: `831b2ef13b6107039bf13a89866b825e1e2227d55c6fbbfd696a699b6697a67a`
- `scripts/kb/supervisor_state.py`: `131c13c9c702e092dbad2a6be26398fb25c02070bf1d64abfe4e0377fab54f9e`
- `tests/test_recovery_supervisor.py`: `11f8922e84d44f7023135fd31d1a2c38c9ffb8bdc7ad1c7f2146ee219acdc60a`

## Changed paths

The candidate status remains exactly these four task-owned paths:

1. `?? scripts/kb/recovery_supervisor.py`
2. `?? scripts/kb/supervisor_state.py`
3. `?? tests/test_recovery_supervisor.py`
4. `?? guardian-r2-program/reports/H03-recovery-supervisor.md`

Within repair2, only the report bytes changed. The three sealed paths retain the
hashes above. No commit, push, merge, install, real process signal,
production-state mutation, Claude invocation, plugin change, or work outside
this worktree was performed.

## H03 scope boundary

- The accepted evidence is scoped to the H03 supervisor protocol and synthetic
  test adapters.
- H04 real adapters, the H05 recovery lane, and H06 live-host/install evidence
  are separate task scopes; this report makes no claims for them.
- The historical nested-isolation limitation is fully covered by the
  coordinator-run supported isolated runner evidence.

## 沉淀候选

### Candidate A — durable effect prepare plus independent verification

- 问题语境：不可判定的 crash 边界若只记录 adapter 返回值，重试会重复非幂等 effect，且 adapter 可自证成功。
- 证据状态：`confirmed`；apply/prepare/reprobe/receipt/verifier 全边界确定性 crash matrix 已覆盖。
- 路由正样本：recommendation → sealed authorization → durable prepare/effect ID → apply once → reprobe on uncertainty → independent verifier receipt。
- 路由负样本：crash 后再次 apply；把 `local_only`/`external_effect` 等 adapter 声明当作信任证据；unknown reprobe 记成功。
- 执行正样本：prepare 与 world-state 复核在同一 writer transaction；所有 retry 复用 exact adapter/effect identity。
- 执行负样本：锁外 check-then-dispatch；用调用返回替代 durable dispatch boundary；由 adapter 生成 verifier identity。

### Candidate B — retained-directory identity for sensitive journals

- 问题语境：仅保存 canonical path 会在父目录改名并同名替换后跟随攻击者的新目录。
- 证据状态：`confirmed`；parent/leaf replacement、symlink、hardlink、mode、owner、read-only、fd/path substitution 回归均 fail closed。
- 路由正样本：先拒绝 relative input → canonicalize existing parent once → retain directory fd → derive fixed leaves with `dir_fd`/no-follow → validate identity each operation。
- 路由负样本：每次重新 resolve 完整敏感路径；只检查字符串相等；打开后不比较 named/opened inode；允许 hardlink。
- 执行正样本：同时校验 parent fd、named parent、leaf fd、named leaf、owner、mode、link count 和 retained identity。
- 执行负样本：用 unbounded flock 隐藏身份检查；遇到 pathname drift 自动跟随或重建；把 macOS `/var` alias 误判为 replacement。
