# S1-B bounded SSH recovery candidate

Baseline: `ac5dc9c16527e41ef959ebbcef88593b71548e83` (`dev`).
Task branch: `task/guardian-s1-recovery-20261004`.
Status: module candidate tested; coordinator integration and independent review required.

## Result and integration contract

The existing verification recovery remains unchanged: an unsupported historical
effect cannot acquire a fabricated postcondition, and abort does not settle it.
The candidate adds a distinct, non-authorizing scope-risk review over one
unresolved attempt. It never appends, resolves, grants, or executes an effect.

`intent_guardian_parts.remote_identity.ssh_material_request(command)` recognizes
only a literal SSH invocation with `-F /dev/null`, explicit account and IP,
`BatchMode=yes`, `PermitLocalCommand=no`, `StrictHostKeyChecking=yes`,
`UpdateHostKeys=no`, and a single `/bin/mkdir -p -- /absolute/path` (or
`/usr/bin/mkdir`). Optional `-p`, `-n`, `-T` are bounded. Root scope, aliases,
configuration, forwarding, compound commands, expansion and other actions fail
closed. It returns `effect`, `operation`, `target`, `resource_key`,
`resource_context`, identity quality, limitations and redacted telemetry.

The coordinator's trusted normalizer must populate `remote_request` with that
result plus `target`, `effect_resource_key`, `effect_resource_context`; remote
identity must not inherit a local path resolution base. The full target is
appropriate for the human card, not policy telemetry. Only the `telemetry`
subobject excludes account, IP, path and raw command.

`ssh_resource_identity(endpoint, path)` is shared with A's constrained read
probe. It binds the requested account/IP/port/path, but does not assert a
verified host, remote filesystem object, or historical success. Such identities
cannot prove settlement or separate unresolved remote aliases; typed local path
identity remains a different resource domain. No connection/config lookup or
remote process is executed.

`intervention.effect_risk_review_context(path, event)` returns
`guardian-effect-risk-review-v1`: attempt ID/state, binding digest, exact target,
operation/effect, identity quality, human explanation and limitations, with
`effect_verified=false` and `execution_authorized=false`.

`effect_risk_acceptance_matches(path, event, review)` checks exact freshness,
not authority. Both helpers must run under the caller's existing contract lock.
They require one unresolved blocker only, in unknown/verifying state; they bind
the old attempt and its intervention snapshots, the existing `policy_digest`
(including acceptance criteria, skills, MCP and other material intent fields),
and stable event scope/arguments/provider/session. A second debt, lane/action or
contract change invalidates the review. Runtime observation bookkeeping and
enrichment of copied events do not stale their own card.

The coordinator owns the separate native HumanGrant route, receipt validation,
one-use consumption, and the narrow blocker exception after receipt validation.
Ordinary `material_event_blocker` remains blocking. No ordinary-grant exclusion
is weakened here. Native prepare → observation → Allow → claim and repeated-use
denial must be tested in integration; module helper success is not that evidence.

## Evidence

Normal controls ran before injected history: 3 existing tests passed, covering
supported reprobe, local/remote mutations, and ordinary read/destructive pairing.

Same-input/same-assertion counterexample:

```
S1_SOURCE_ROOT=/Users/eric/ClaudePlugin/sulde-pro/.worktrees/guardian-v3-dev-merge \
  python3 -B tests/test_guardian_s1_recovery.py \
  RecoveryTests.test_normal_no_debt_then_old_opaque_must_block_precise_ssh
```

Baseline exit 1: the normal no-debt control passes, then an aborted opaque
unknown effect is incorrectly considered disjoint from the new precise SSH
request (`assertIsNotNone(blocker)` fails). The candidate passes the identical
test. This is a validated matcher counterexample using a canonical request
fixture, not a claim that the old producer already emitted the new identity.

Final scoped regression (exit 0):

```
python3 -B -m unittest tests.test_guardian_s1_recovery \
  tests.test_effect_recovery_20261004 tests.test_intervention \
  tests.test_intervention_batch tests.test_guardian_recovery
```

137 tests passed in 2.630 s. Dedicated tests cover exact parser positives and
negative boundaries, runtime/enrichment freshness, lane/arguments/contract/debt
drift, no append or authority from review (unknown and verifying), read without settlement, opaque
history conflicts, alias/account/address uncertainty, and actual `interventions`
CLI output retaining unknown/unsupported status. Existing effect recovery tests
include native preview and real PreTool hook denial; these are isolated fixtures,
not live host approvals or remote execution.

Two test-authoring errors were corrected before final verification: an invalid
CLI action name (`effect-report`, corrected to `interventions`) and a misplaced
fixture variable. Neither was a product regression. `git diff --check` passed.

SHA-256 of tested artifacts:

| Artifact | SHA-256 |
| --- | --- |
| scripts/kb/intervention.py | 06d5a1edfc6f873f6049bc72279d8f0aa0da2f0634ab53d2584837754d2d1942 |
| scripts/kb/intent_guardian_parts/remote_identity.py | 493f8da8c3b29f29c60d4e38a9e919862ae55ccbd8cd6731cb3f78c8b31990f6 |
| tests/test_guardian_s1_recovery.py | c23e90930b8d12a66581ed403793179cb6176a29a1339190519b8992fec5f410 |

Local paired matcher microbenchmark, minimum of five 20,000-call runs on the
same normal opaque identity: baseline 0.008900 s; candidate 0.011345 s. This is
about 0.12 microseconds additional work per comparison, with no I/O/model calls
added to ordinary matching. No predeclared performance threshold was frozen for
this measurement; it is descriptive evidence only. Full pipeline budget remains
the coordinator's integration responsibility. Risk snapshot replay occurs only
on the explicitly requested recovery route.

## Authority and limits

All edits and tests ran inside the assigned worktree or disposable fixture
directories. Tool calls allowed those local operations; no independent child
native approval receipt was requested, copied, generated, or asserted. This
does not prove live host gate coverage. No installed runtime, production ledger,
remote server, dev/main merge, push or installation was changed. Historical
attempts remain replayable and unknown. Material risk acceptance does not prove
that the old and current targets coincide, that the old write succeeded, or
that a future retry succeeds. New writes require independent evidence.

## 沉淀候选

- 问题语境：将未解析命令摘要升级成精确 SSH 请求身份时，普通 opaque 键不等
  被误当成资源互斥证明，可能绕过旧 unknown 效果。
- 证据状态：verified（同断言旧红新绿；仅本地模块/CLI/Hook 夹具）。
- 根因：请求身份精度与远端对象身份/别名证据混为一谈。
- 路由正例：历史 SSH 命令摘要债务与新 literal SSH 路径请求相遇；应应用。
- 路由反例：已独立验证的本地路径与明确不同资源域；不把所有读取都升级成债务。
- 执行正例：保留 unknown，独立绑定只读探测与一次精确风险接受，效果结算另验。
- 执行反例：abort 即清债、不同命令摘要即不同资源、把当前状态当历史成功。
- 建议路由：协调端判重合并到 ap-0242 或 durable-effect-claim-and-ledger-identity；
  本子任务未写知识库。

## Integration follow-up: consumed native grant at the inner attempt barrier

Coordinator integration found that the native Allow/claim path still reached
`begin_attempt`'s same-resource barrier. The prior candidate did not change this
inner creation boundary; this follow-up supplies authenticated linkage rather
than a caller-controlled skip flag. Parent's failing actual GuardianSession
test remains the integration red/green evidence; this module does not claim
the shared policy glue was exercised in its isolated worktree.

New `begin_attempt` kwargs (all required together for risk recovery):

```
risk_grant_transaction_id = human_grant_dispatch["transaction_id"]
risk_event = event
risk_dispatch = human_grant_dispatch["dispatch"]
```

Under the effect mutation lock, the implementation independently reads the
no-follow validated GrantBroker journal. It requires a native typed Allow,
persisted grant consumption, exact durable dispatch winner and consumer/source
event identity, matching provider/session/intent/revision/epoch/action/target/
arguments/fingerprint, current policy digest, and the unchanged sole historical
blocker. Risk acceptance cannot mix with compensation, retry authority or a
post-only observation gap. No receipt or dispatch dict from the caller alone
can grant this exception.

The new attempt stores a compact `risk_grant` linkage: transaction/dispatch/
authority digests, source event, old accepted attempt, review binding and the
bounded normalized event fields. It stores no `execution_authorized` ticket.
One transaction cannot create two attempts; exact idempotent readback retains
the same attempt. Replay validates the persisted broker source, link identity,
historical prefix snapshot and uniqueness. Later contract revision does not
invalidate authentic historical replay. Historical unknown is unchanged.

The internal review computation accepts the already replayed effect projection
and the sealed policy digest, avoiding recursive effect-ledger reads. Broker
readback has no broker write lock and no callback into the effect ledger;
the existing contract → effect lock ordering is retained. The existing native
broker's decision, consumption and dispatch records remain authoritative.

Final follow-up checks (exit 0): the same five effect suites plus
`tests.test_grant_broker`, 155 tests in 3.440 s; `git diff --check` clean.
Six new cases cover actual native context → prompt observation → native decision
→ consumption → dispatch → begin, forged/foreign dispatch and call binding,
unanswered question, policy/second-debt drift, link tampering, and offline archive
failure. The first fixture run exposed broker projection audit metadata
(`source_event_sha256`); comparison now uses the broker's existing `_public`
projection rather than inventing a new dispatch serialization.

Follow-up tested artifact SHA-256 (supersedes the earlier hashes for these files):

- intervention.py: `423dd669b6aeea42c22f80296f6d7dfb0c6ca051f6bd92f75447848c9ebe1f08`
- test_guardian_s1_recovery.py: `9242f958158ba3d97e1eb9dda0128058ec6acd9fb540c778a0e52e44db9e6502`

Explicit bounded limitation accepted by the coordinator: new risk-linked records
require the retained Broker journal for authenticated active replay. An offline,
self-contained effect-only archive has no broker proof, so its replay fails
closed. The negative test retains the original authoritative logs and confirms
no truncation. A cross-ledger archival protocol is excluded from this batch;
there is no unauthenticated fallback, and existing archives are unaffected.

All native decisions above are isolated test protocol fixtures. They are not
live user approvals, production grant consumption, or external execution. The
parent still owns policy wiring and the complete GuardianSession journey.
