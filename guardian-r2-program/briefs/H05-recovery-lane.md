/model
选择:gpt-5.6-sol（若当前可用列表无此型号，选择 deep 档或更高的 Codex 模型）
/reasoning
选择:high 或更高
执行任务文件:guardian-r2-program/task-definitions/H05-recovery-lane.json

# H05 always-reachable recovery lane

Implement only the already-registered H05 task. Do not rebuild the R2 plan,
repeat H00-H03, start H04/H06, install a plugin, or modify production state.

The full clone HEAD is the frozen
`dev@0eb4fb6553e652b0352750f4bac24aa6bae746d7` baseline required by task
authority. The coordinator projects these accepted dependencies as read-only,
ignored files:

- `scripts/kb/grant_broker.py` SHA-256
  `89432ec4808a470c5e48644b5859436c44485349e9379816266c106cbc9be458`;
- `scripts/kb/recovery_supervisor.py` SHA-256
  `831b2ef13b6107039bf13a89866b825e1e2227d55c6fbbfd696a699b6697a67a`;
- `scripts/kb/supervisor_state.py` SHA-256
  `131c13c9c702e092dbad2a6be26398fb25c02070bf1d64abfe4e0377fab54f9e`.

Read and compose with those exact APIs. Do not modify, stage, replace or claim
ownership of any dependency projection.

Before implementation, consume the full local KB sources already selected by
the coordinator: `knowledge/anti-patterns/0243-control-composition-misclassified-as-destructive-pause.md`,
`0242-read-only-mcp-interruption-false-effect-intervention.md`,
`0181-live-session-plugin-hot-update-dangling-path.md`, and `0074-git.md`.
Preserve their hard negative boundaries while fixing reachability.

## Recovery capability and routing

- Implement a versioned, sealed `RecoveryCapability` and `RecoveryLane` that
  remain reachable when the ordinary task lane is paused, review-required,
  unavailable, schema-invalid, effect-debt blocked, scheduler-degraded or the
  launcher/runtime contract has drifted.
- Recovery classification and capability validation must occur before the
  ordinary PreToolUse decision that may be broken. Do not first route a valid
  recovery action through the unavailable component it is intended to repair.
- The recovery lane is narrow, not a bypass. Bind provider, session, workspace,
  installed generation, exact recovery action, target identity, expected
  pre-state, allowed changes, expiry and independent verifier. Unknown action,
  target drift, forged capability, replay or wider command fails closed.
- Support typed status, doctor, settle/abort of one exact source transaction,
  launcher repair, generated-bytecode repair, uninstall and rollback routes.
  Each route has distinct constraints; no generic shell, arbitrary patch,
  arbitrary deletion or `do anything` authority.
- Invalid composition of a trusted control command is denied without launching
  any segment and without pausing the task or creating effect debt. Real
  destructive actions, untrusted lookalikes and unresolved external writes
  retain the existing hard safety behavior.

## Human interaction and self-lock prevention

- A readable recovery card must reach the host PermissionRequest UI before the
  ordinary lane can block it. Provide `Allow`, `Deny`, `查看差异` and `稍后` as
  typed outcomes. Ordinary chat text, fixed phrases, copied digests and pasted
  terminal commands are never approval authority.
- Once the exact current-session Allow settles successfully, the authorized
  mechanical action must not be re-denied by the same unchanged default policy.
  Drift creates one new readable decision; it does not loop the old card.
- If the host cannot render the UI, expose a typed unavailable diagnosis and a
  still-reachable independent recovery path. Do not tell the user to trigger a
  command that the same PreToolUse necessarily blocks.
- Historical malformed/read-only/terminal-quarantined debt is settled by
  append-only isolation. Do not delete or rewrite the audit journal, and do not
  let an unrelated terminal debt globally block recovery or safe reads.

## Status, progress and output budget

- Integrate with accepted H03 supervisor facts. A managed action with no visible
  progress must project a status within five seconds and a changed stage or
  typed stalled/degraded reason within each thirty-second window.
- Persist the full local execution log and stable run/stage identifiers. The
  interactive surface displays concise stage changes, progress and next action
  by default; repeated `Waiting for agents`/poll text without changed state is
  suppressed. Poll count is not progress.
- Terminal success/failure/cancelled/blocked is emitted once and remains
  readable. Crash/retry/reprobe is bounded and idempotent; recovery never loops
  Stop/PreTool hooks indefinitely.
- Statusline and readiness must distinguish stale startup snapshots from
  current doctor truth, current versus old hook generation, hook hot-rebind
  from static skill-catalog restart, and task-lane degradation from recovery
  lane availability.

## Deterministic failure matrix

Add focused local tests for at least:

1. each ordinary state: paused, review_required, unavailable, schema-invalid,
   effect-debt blocked, scheduler degraded and launcher digest drift;
2. status/doctor/readback reachable without task-lane binding;
3. exact settle/repair/uninstall/rollback capability positives and forged,
   expired, replayed, target/generation/pre-state substituted negatives;
4. native recovery card visible before ordinary guard, all four UI outcomes,
   one exact Allow consumption and no fixed-text fallback;
5. PreTool self-lock where the guard blocks its own repair, malformed trusted
   command composition, real destructive command and untrusted lookalike;
6. 5/30-second fake-clock SLA, long-running unchanged output suppression,
   bounded retry, crash at durable boundaries and one terminal result;
7. old/new hook generation split, current launcher versus static skill restart,
   stale status snapshot and read-only historical debt settlement;
8. no actual uninstall, repair, signal, Git write, network, device, Figma,
   plugin install or production mutation.

Use deterministic fake hosts/adapters and temporary local state only. Do not
sleep in real time or depend on the current machine's live scheduler/session.

## Verification, findings and report

- Run focused recovery/readiness/statusline tests, adjacent accepted H02/H03
  composition, deterministic failure injection, AST/compile checks,
  `git diff --check`, exact eight-path scope and no generated bytecode.
- The task report is a mandatory durable record. For every problem discovered
  during implementation or independent review, record an FR2-H05 identifier,
  symptom, evidence status, root cause, resolution or explicit unresolved
  disposition, verification evidence, and remaining risk. Preserve failed
  candidates and failed command outcomes as history.
- The report must include capability/routing schemas, state matrix, UI result
  matrix, 5/30-second/output metrics, exact commands and observed counts,
  actual changed paths, all findings and dispositions, known limits, and
  `沉淀候选` with problem context, evidence status, and routing/execution
  positive and negative samples.
- Do not claim H04/H06, real installation/uninstall, live-host, Windows,
  Claude, release, push, merge, dev/main or production acceptance.

## Hard boundaries

Only modify these eight paths:

1. `scripts/kb/recovery_lane.py`
2. `scripts/kb/intent_guardian_parts/recovery.py`
3. `scripts/kb/operational_readiness.py`
4. `scripts/kb/sulde-status.py`
5. `tests/test_recovery_lane.py`
6. `tests/test_operational_readiness.py`
7. `tests/test_sulde_statusline.py`
8. `guardian-r2-program/reports/H05-recovery-lane.md`

Do not modify read-only dependency projections, task/brief authority, the R2
event log/task graph, other source/tests, installed plugins, production state,
`dev` or `main`. Do not commit, push, merge, run a real repair/uninstall,
invoke Claude, install, or clean pre-existing artifacts.

The final response must include each heading exactly once: `结果`, `过程`,
`遇到的问题`, `解决方式`, `遗留风险与建议`, `沉淀候选`. Include at least one
`✅ 完成检查：` line with a backticked command, `exit 0`, and a concrete
observable result.
