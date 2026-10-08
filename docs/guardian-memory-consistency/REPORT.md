# Guardian memory consistency — implementation report

Date: 2026-09-10
Status: ACCEPTED — FROZEN LOCAL DEVELOPMENT / ISOLATED MACOS SCOPE ONLY
Frozen plan: [PLAN.md](PLAN.md)
Base: `dev@3d4df5412193633b3f26ad1cfa90844068e9489c`
Task branch: `task/guardian-memory-consistency`

## Outcome and boundary

R2 update: explicit new-session source selection and atomic continuation are now
implemented under the native-approved revision 7 scope. Real isolated Allow and
Deny cases pass, including an unrelated source-memory write after preview and
ordinary execution / destructive Pre denial after continuation. Final integrated
acceptance passes: **2,054 passed, 25 skipped, zero failures/errors**. The R1 and
earlier results below are historical, not final-source release evidence. No
task commit, merge, push, production cachebuster or installation was performed.
Main/dev and the existing user changes remain unchanged.

## Final integrated acceptance

`20260910T093502743532Z-integrated-final-r2` ran 2,079 tests in 1,111.936 seconds
(1,113.620 with wrapper), exit 0. The semantic source was unchanged before/after
and independently reread as
`de7c530bccf80acad037e244284e69cb5d4f9e66ce44d205a0a88f4f2539168f`.
Full-byte source hashes differ only because REPORT.md and EVIDENCE.json were
updated during the run; these two reporting files are the declared semantic
exclusions. No runtime/test/Skill source changed during or after this final run.

- Final log SHA256: `aebb7d644cb28db470ad0f3e5392ac8a912c29ea0667ea6ba3bebb040963b0b2`.
- Candidate artifact: `0.2.5+codex.20260909091120-48e0594354:d901cbc65baabd971d7d639391ce6ff45ead5b95502bcf3c0d1bff412a3244bf`.
- Loaded module: `4eebf26591f75d8100704ecbbde2df0d8e0eae472688067be63ceee05ccc87d0`.
- Destructive Pre proof: `d8e42dc54fb4401feead2bff6ef626c995f438a5eb7f847b5a3d495e369d420b`.
- Native continuation audit: `7c532444e2c392447ab8335484aae36dd8564be60410661174d531f42dc83cb6`.
- All 20 indexed historical/current output logs match their retained SHA256.
  Failed historical runs remain failed, not reusable success records.

All candidate-bound memory, continuation, composition, PreTool and worktree
continuity evidence records agree on the artifact generation; each applicable
actual denial also checks the loaded-module identity. Allow/Deny, four crash
boundaries, concurrent prepare, CAS drift, rollback of superseded staging and
idempotent post-commit recovery pass at their documented evidence tiers.

The 25 skips are **17 retired Git-policy tests, 5 Windows-specific cases,
1 nested-OS-sandbox probe and 2 benchmarks requiring explicit baselines**.
They are not counted as passed. The separate task read-path benchmark did run;
the existing single-call composition budget gate also passed its median/p95
limits. Neither result establishes whole-Agent throughput or installation speed.

This accepts the frozen local implementation and isolated macOS verification,
not a production installation, global Guardian V3 readiness, or Windows-native
acceptance. The frozen PLAN is the historical scope; this report is its result.

## R2 implementation and evidence

- `prepare-task-continuation` selects an exact peer contract in the same physical
  workspace and persists only a read-only reference in the current contract.
  Normal new-session isolation stays enabled. Paused/busy/confirmed current
  tasks, source/current/session/route drift and corrupt selections fail closed.
- The native command still targets the current session contract. The v2 card
  binds both revisions/epochs, current lane task-instance state, route predecessor
  and relevant source material state. No cross-contract PermissionRequest bypass
  was introduced; choosing a source is not an Allow.
- Existing native decision journal approval/recovery is reused. Ordered contract
  locks and route CAS serialize publication. A staged route still resolves to the
  original contract until the selected task's atomic commit binds the new lane.
- A post-commit interruption is recoverable from the newly routed session.
  Superseded pre-commit transactions restore only their exact route predecessor;
  terminal records and hashes remain in contract history and append-only audit.
  Historical commit evidence cannot be invalidated by ordinary later lane metadata
  or cause that binding to execute again.
- No source grants, approval receipts, authorized/open events, pending effects,
  effect debt or tokens are copied. Relevant/unknown effects keep their resource
  boundaries. Independent-memory freshness is a projection, not debt settlement.
- `skill-creator` kept the instruction change limited to explicit selection and
  native continuation. The official Skill and plugin validators pass.
  `plugin-creator` is used only for newly staged, isolated candidates; production
  registry, cachebuster, generation and scheduler remain unchanged.

Scope regression `20260910T092839644227Z-scoped-final-r2`: **495 tests, 477 passed,
18 skipped**, 207.015 seconds (207.980 including wrapper). It includes memory,
Guardian, native journal, session history/continuity, architecture and all actual
CLI/MCP/Hook canaries. Its semantic source is `f5349ea743c18f381d28474f11ee6ffe612303d916599b32c09c77f56b8336da`.

After that scope run, only the selected-task current-lane CAS/paused guard and
its regressions changed. Both actual native cases passed on that tree; one unit
assertion exposed an imprecise error message for the paused top-level status.
The message was corrected, with **18/18** final selected-task/architecture checks
passing in 1.194 seconds. The final full run covers this exact last tree:
`de7c530bccf80acad037e244284e69cb5d4f9e66ce44d205a0a88f4f2539168f`.

Real-host evidence uses fresh candidate-bound Codex CLI app-server processes,
unified exec, actual Hook discovery and an actual SQLite-backed MCP server. Only
the response endpoint and one-shot simulated human decisions are test fixtures;
no Hook event, receipt or proof is manufactured. Allow and Deny are independent
new-session cases; a denied command is not immediately retried as an Allow case.
The destructive canary is Pre-denied and its marker survives; the event binds
both loaded-module and artifact generation. Windows native runs remain Windows-owned.

Final read-path benchmark `benchmark-20260910T093419Z.json`: five alternating
rounds of 500 warmed samples. Median round p50 **0.536042 → 0.5338955 ms**;
median round p95 **0.563708 → 0.566208 ms**. No material change beyond round noise
is evident. This measures normalization/evaluation, not full Hook startup,
installation duration, or whole-Agent throughput.

### R2 execution issues retained, not hidden as successful runs

- Contract persistence normalizes/replaces nested dictionaries. The first
  implementation consumed a detached receipt reference after the prepare write.
  Re-resolving the exact receipt in the normalized contract fixed it; clean and
  all four interrupted paths pass.
- A non-subjective first prompt can have `confirmation.required=false` while
  `mode=shadow` and `confirmed_by=unconfirmed`. Selection now recognizes that
  precise non-authorizing provisional form, not the flag alone.
- Deny and Allow must be tested as separate host decisions. Immediate retry of
  the same denied command did not produce a second native approval. No Guardian
  policy was weakened to force that test sequence to pass.
- An ordinary post-approval command was Pre-allowed but could not write inside
  nested macOS sandboxes. The native card keeps workspace-write/on-request;
  later fixture tools rely on the repository's existing outer OS sandbox. Hooks
  remain active, and the real destructive denial is still required.
- A paused task was correctly denied but initially reported the generic
  unconfirmed-task reason. The final guard reports the actual paused state.
- The host reported saving an exact approval prefix for revision 7 even though
  the Agent supplied no `prefix_rule`. No broader prefix or reusable authority
  was requested or consumed; attribution of host persistence remains inconclusive.

## R1 acceptance completion — historical result

- Removed delayed imports in composition normalization and evaluation.
  `CompositionServices` passes explicit parser dependencies without a resources
  back-import. All three architecture gates pass; neither the architecture gate
  nor the 3000-line limits were weakened.
- Fixed the native continuity fixture, not the deletion policy. Codex rejects
  `rm -f` before Guardian sees it. Exact non-recursive cleanup is Agent-owned,
  so replacing it with `rm --` was not a valid negative either. The corrected
  fixture uses explicit recursive semantics (`rm -r --`) on a disposable target.
  Both native scenarios observe all three exact Hook-denied calls (composition,
  opaque receiver, destructive probe); subsequent ordinary calls succeed.
- Composed events now recompute the shared versioned host-call identity after
  final action/target/digest projection. Different sessions/call IDs differ;
  Pre/Post for the same call agree. This closes a missed path in plan item 7.
- The actual native human-card transport applies the first explicit independent
  proposal. The fixture supplies an exact one-shot simulated human `accept`,
  matching command, description, session and cwd. It never accepts a persistent
  prefix/session grant. This is not a production approval or a person click;
  no receipt or Hook proof is manually injected.

Current scoped regression: `20260910T084408991650Z-acceptance-scoped-r1` ran 375
tests: **357 passed, 18 skipped**, zero failures/errors, 181.750 seconds (182.744
including the wrapper). This includes architecture, composition, Guardian,
writer/MCP/recall, the two real memory cases, two real continuity cases and a
separate destructive PreTool proof. The failed cross-contract acceptance is a
separate required gate, not part of that green count.

- Semantic source: `d8da33fd4d2e46bd0525ab0497d8574dfeb2d9881e0601436811a15a53891081`
- Artifact: `0.2.5+codex.20260909091120-48e0594354:2b3e6aecaf04d7bd76eca7d621ebd1244e5dd0d3d1070d3a0213e11db1cbab70`
- Loaded module: `64e2ff77353ee4c84857b30b2fb3737a84c3915a20b7ded2793b3b02f3f9a065`
- PreTool proof: `cbc5b90ef23507fce2ea663524e60a524ae4d8c4ae80991c4d3007eb313480d4`
- Passing log SHA256: `388dbe656c1ab201d19f176c993eb3791e6bf3a50303d4db1869fdda367f6a08`
- Failed discovery log SHA256: `54b6b3f6bccc269661569a16be71e8296dae405033b548e2fa73e88a8b3fa06c`

Both final receipts bind the same semantic tree; only report/evidence edits
followed. The failed discovery run took 18.752 seconds (19.454 with wrapper).

R1 warmed read-path comparison (`benchmark-20260910T084907Z.json`, five alternating
rounds, 500 samples each): median round p50 is **0.548875 → 0.550958 ms**; median
round p95 is **0.720500 → 0.719209 ms**. No material regression is evident relative
to round variation. This measures normalization/evaluation only, not end-to-end
Hook startup or whole-Agent throughput.

### Confirmed R1 defect — repaired by R2 above

`continuation-discovery-regression` is a **failed** actual CLI/Hook acceptance:

1. The source session has a natively approved memory-independent contract.
2. A second actual CLI process completes SessionStart/UserPromptSubmit.
3. `audit.py:observe_user_prompt` intentionally creates a separate session
   contract when another lane owns the workspace anchor.
4. `approvals.py:_task_continuation_context_locked` still requires the target
   session to already have `review_required` in the source contract.
5. The source has zero target lanes; the target owns one separate contract.
   The old preview cannot be prepared. No continuation Allow, memory mutation
   after preview or successful continuation application is claimed.

The contracts can share the legacy workspace-derived `intent_id` label. That
label does not prove shared ownership or permission; the defect concerns
separate contract routing and absent source review state. The fixture does not
create a lane by hand, transfer a token or borrow a grant to pass. Its failing
assertion is retained, not skipped or marked expected-success.

This is a session-isolation/explicit-continuation integration omission, not a
memory writer failure or proof that the dependency projection is wrong. Older
documentation assumes every new session gets a review lane in the workspace
anchor; current isolation no longer does that. Another terminal cannot supply
the missing explicit source-task selection.

### R1 proposed scope — subsequently approved and implemented as R2

Add explicit source-task selection and read-only continuation review through the
existing control plane. Bind the native card to both contracts, revisions/epochs,
provider/session, route and relevant world digests. Allow must revalidate under
ordered locks/CAS, append the receipt and atomically publish the route. Deny,
staleness or failure keeps the prior independent destination route. Never share
a workspace contract implicitly, transfer execution grants, erase debt or treat
another session's continuation token as authority. Preserve both audit histories
and the unknown/related-effect boundary. No second task-state service is needed.

This ownership-boundary expansion requires a readable scope amendment before
implementation. Then run native independent/dependent continuation positive and
negative cases, followed by integrated final-tree acceptance. A full-suite rerun
while this known native gate fails cannot close the gap, so R1 does not repeat it.

## Earlier implementation outcome (superseded by R1)

The frozen memory-registration repairs are implemented in this task worktree.
The final affected-scope run completed 368 tests: **350 passed, 18 skipped**,
with zero failures/errors, in 93.914 seconds (94.786 seconds including the
isolation wrapper). An additional real-host missing-Post scenario and the
ten-annotation scenario both passed, in 35.618 seconds. The separate actual
destructive PreTool canary passed with an absent marker.

This is **not** full Guardian V3 acceptance or production readiness. One existing
architecture gate and two existing native-continuity gates fail on untouched dev.
No task commit, merge, push, production cachebuster or production installation was
performed. The plan remains FROZEN, not ACCEPTED. Main's three existing `.ua`
changes and untracked root `.sulde/` remain; dev is clean and still equals
origin/dev at the base above. The task's source edits and local evidence remain.

## Implemented items

| Plan | Implementation | Evidence and limits |
| --- | --- | --- |
| 1 | Removed the lifetime three-use authorization condition. Bounded batch shape, task authority and independent verification remain. | Ten real MCP calls pass; wrong current-host attribution is Pre-denied. The old constant remains a compatibility export, not an active quota. |
| 2 | Shared versioned annotation normalization/schema for MCP, CLI and Guardian; explicit actor, finite confidence, strict types and bounds. | Missing/conflicting actor and invalid values reject before interactive dispatch; Codex never defaults to Claude. |
| 3 | One `BEGIN IMMEDIATE` transaction covers check/write/receipt. Created, already-present and conflict are distinct. | Identical concurrent retries store one receipt; whole-batch conflict rollback; original row provenance is retained. Receipt verification proves storage, not semantic truth. |
| 4 | Digest-bound verification recipe survives open/pending state. Recovery independently reads the receipt and exact rows, never replays the writer. | Unit lost-Post/restart/idempotency tests, actual exclusive DB lock, and real CLI/MCP/Hook missing-Post recovery pass. Two fresh CLI recovery passes find no remaining debt. |
| 5 | Optional memory conflict scope is explicit, not an unconditional debt bypass. Proposal source audit and authoritative attempt identity are checked. | Typed memory may be irrelevant to an independent local proposal; external/destructive/control/unknown/corrupt rows remain blocking. Original audit/debt remains intact. |
| 6 | Total sequence remains; scoped freshness subtracts only validated memory increments. First independent declaration requires human review. | Dependent proposals still detect memory changes. Ordinary local writes and old writers that advance only total invalidate scoped freshness. Continuation also checks authoritative attempts before filtering a memory projection. |
| 7 | Pair by provider/session/dispatch epoch/call ID and content shape. Host-call event identity is versioned. | Equal arguments with distinct calls, session/epoch mismatch, duplicate callbacks and provider file-change fanout regressions pass. The isolation auditor accepts explicit old/new identity formats, not arbitrary digest mismatch. |
| 8 | Open and pending state is not truncated at 100; protected continuation uses survive bounded settled history. | 151 outstanding rows and 151 protected uses survive validation/persistence. Corrupt row types fail visibly. Derived completed-call history is not authority. |
| 9 | MCP-to-CLI write fallback is limited to backend absence before entering the writer. | Business conflicts/validation failures do not retry; an uncertain write outcome requires independent recovery. |
| 10 | Explicit graph queries and automatic associations share truth/source validation. Graph reads use read-only SQLite connections. | Planned/uncertain/stale/source-less relations are not injected as facts. Read APIs cannot create/migrate the database. |
| 11 | Source-project guardrails on recall and MCP graph project filtering; keyless edges are not implicit shared project knowledge. | Cross-project/keyless negative tests pass. Global entity namespace and multi-source graph identity migration remain out of scope. |

Task facts are recorded in authorized task artifacts first. Optional graph
enrichment must not block an explicitly independent deliverable; if graph
maintenance itself is requested, an unknown graph outcome is still incomplete.
The two source Skills and global host instruction templates reflect this split.

## Earlier implementation evidence and attribution

These records precede R1 and remain historical evidence. R1 receipts supersede
their source/artifact identities; no old green record certifies the current tree.

Evidence files are retained under `.sulde/data/guardian-memory-consistency/`.
Each wrapper receipt contains command, interpreter/platform, HEAD, canonical
path-sorted source hashes before/after, duration, exit code and output-log SHA256.
Failed runs remain diagnostic evidence, never reusable successful caches.

| Record | Result | Meaning |
| --- | --- | --- |
| `20260909T152821616400Z-integrated-suite` | 2052 tests; 8 failure entries, 1 error, 25 skips; 992.109 seconds | Full suite on an earlier implementation tree. Not a final success record. Its new regressions were repaired and affected checks rerun. |
| `20260910T000339958966Z-dev-failure-confirmation` | Untouched exact dev reproduces five gate failure entries | Separates baseline issues from this task. Two entries (component length and encoding fixture) are now repaired in the task; three remain below. |
| `20260910T001435171901Z-final-scoped` | 350 passed, 18 skipped; 93.914 seconds | Guardian, writer, MCP/CLI migration, recall, isolation, composition, and actual ten-call native MCP/exec/Hook chain. |
| `20260910T001715698416Z-final-native-boundary` | Real PreTool canary + two architecture checks pass; one baseline architecture check fails | Mixed result: do not classify the whole command as successful. The negative canary itself has explicit proof and both identities. |
| `20260910T002041959412Z-native-lost-post-r2` | Both native memory tests pass; 35.618 seconds | Actual missing Post in a fresh configured thread, actual Stop verifier, two new CLI read-only recovery passes; also reruns the ten-call positive/identity negative. |

The final scoped semantic source hash is
`67954aaf03ff65773d764f49de9463f2f2686982c70ccf995b09a95028bfb705`.
After that run, **only `tests/test_native_memory_consistency.py` changed**, to add
and verify real callback-loss injection. Its final semantic source hash is
`dc5cd8df8a97d6eb1442b9307bbbeb970a6e6f00e8c1f7c5168f12dae587fec9`.
No runtime/Skill/template code changed between these two trees. Both native runs
and the boundary canary produced the same artifact generation below. This
test-only extension was rerun as an affected check, not used to justify another
unrelated full-suite run. REPORT.md and EVIDENCE.json are explicitly excluded
from the semantic hash; their exclusions are recorded in each final receipt.

All final real-host evidence agrees on:

- Artifact: `0.2.5+codex.20260909091120-48e0594354:ca5812d161560dd77f387bf8276cb9b8360f399d4561e46e4e69fabaa7986844`
- Loaded module: `64e2ff77353ee4c84857b30b2fb3737a84c3915a20b7ded2793b3b02f3f9a065`
- Actual destructive denial proof: `45fed025c4af57b340e45c84f49baef14cef30d73ab60a613f5d39501337798c`
- Actual denial event: `3076134dcf6a29ed259de960`
- Final ten-call memory audit: `1a3832a47d2ab8ef8f8675a606bf1d7444fc16aaa6c1707658d1809f6e75466a`
- Missing-Post memory audit: `4fdb9a4fc449e79c2835ddffc7bcd395f9cab4cb852e398386c32e7960eec856`

The artifact version string was not promoted or cachebusted into production.
Candidate processes were newly loaded from isolated staged artifacts. The model
endpoint alone was a deterministic loopback fixture; CLI, unified exec, MCP
server, Hooks and SQLite were real. No manufactured proof input was used.
The existing `test_real_preexecution_activates_enforce_through_candidate_cli`
uses a mocked runner and is only an activation-adapter test; live claims rely on
`test_native_pretool_delivery` and `test_native_memory_consistency`, not its name.

Isolated MCP authority was configured for exactly the local test
`memory_annotate` tool. This is not evidence that production native MCP approval
settings have changed. For callback-loss injection, only the disposable host's
Post Hook was disabled; actual Pre, MCP writer and Stop remained active. The
first attempt to disable it in an already-created thread did not lose Post and
was correctly recorded as failed, not passed.

## Performance and compatibility cost

`benchmark-20260910T001540Z.json` alternates baseline/candidate five times, with
500 warmed samples per variant per round, under Python 3.10.7. Median of round
p50 values: baseline **0.57294 ms**, candidate **0.56738 ms**. Median of round p95
values: baseline **0.66133 ms**, candidate **0.66638 ms**. Differences are small
relative to observed round variation; no material read-classification regression
was observed. These numbers exclude process startup, full Hook persistence,
memory recall and whole-Agent execution. They are not a percentage speedup claim.

Additional work is intentionally on memory writes/recovery or proposal and
continuation boundaries, not ordinary read classification. Retaining unsettled
rows may grow runtime state until effects are honestly settled; it is not a new
permission grant or authorization to delete old facts. Ambiguous/conflicting
annotations now produce explicit errors where INSERT OR IGNORE previously hid
the conflict. Legacy dependencies stay conservative until the user approves an
independent task. Static Skill refresh remains separate from this source repair.

## Handoff boundary — release actions not performed

The final stable-tree integrated run and independent source/log/generation
readback are complete. No required local implementation acceptance remains open.
Task commit, merge, push and production install were not performed; merge, push
and installation are excluded from revision 7 and require a later release scope.
Windows native acceptance remains Windows-owned, not a local macOS claim.

## Agent execution issues recorded during this task

R1 additionally recorded and resolved fixture issues: new runtime modules must
be tracked before the official stager includes them; `propose-revision` takes a
positional contract; two loopback hosts need distinct host configuration roots;
the official registry validator must see the same CODEX_HOME as its subprocess.
These were not product fixes or successful acceptance records. A diagnostic run
also encountered a temporary-directory cleanup race after host failure; its
receipt remains failed. Early hypotheses about the missing uncertainty denial
were disproved by actual call attribution and were not used to change policy.

| Observation | Classification and disposition |
| --- | --- |
| Default Python 3.14 lacked PyYAML for official candidate/Skill validation. | Verified environment mismatch. Used existing supported Python 3.10.7 + PyYAML 6.0.3; no global dependency install. Official Skill validators and plugin validator pass. |
| Git fixtures failed with a TMPDIR nested inside the task repository. | Verified fixture isolation error. Use a task-prefixed temporary root outside the repository so child Git discovery cannot inherit the parent. |
| Native MCP tool is exposed under a namespace, and standalone registration/explicit test-tool authority were absent. | Verified fixture setup errors. Follow actual exposed schema and isolated native registration; never reinterpret a failed/no-write call as success. |
| Candidate environment scrubbing erased the flag saying the outer test sandbox already exists. | Verified fixture bug. Capture that flag before replacing the process environment; avoid nested macOS sandbox while retaining the outer production-write boundary. |
| New call-ID event digest was rejected by the old isolation auditor. | Verified integration omission, fixed with explicit identity schema and compatible validation. No digest mismatch exemption. |
| Post disabling did not affect a previously-created candidate thread. | Verified observation on this CLI test. New thread plus explicit absence check made fault injection real. Do not generalize this to every host/hot-update mechanism. |

## 沉淀候选（not written to the production KB or memory graph）

### A. Registration idempotency and verifier must share a contract

- 问题类型：bug-fix / workflow。
- 任务目标与真实预期：记录已确认任务事实，登记不因历史次数或重复行造成自锁。
- 触发场景：相同关系重复提交、跨宿主来源声明、Post 丢失。
- 症状：旧次数门表现为缺少 grant；INSERT OR IGNORE 与精确 verifier 不一致。
- 已确认根因：授权条件、输入规范、存储幂等和验证证据使用了不同契约。
- 已排除：不是“第四次登记天然高风险”，不是工具返回成功即可证明写入。
- 证据状态：verified；来源为代码差异、final-scoped 和真实 native-lost-post-r2。
- 正确做法：共享版本化请求摘要，事务回执和独立只读校验；保留原来源；未知不重放。

| 样本 | 内容 | 固定预期 | 判定原因 | 来源 |
| --- | --- | --- | --- | --- |
| 路由正例 | 有授权、相同输入的第十次记忆登记 | apply | 幂等与验证边界，不应是次数授权问题 | observed: native canary |
| 路由反例 | 控制面或外部破坏性动作要求复用记忆豁免 | skip | 不属于限定本地记忆能力 | constructed: regression |
| 执行合格例 | 十次调用只存一条关系；丢 Post 后独立结算 | pass | 有真实存储和读取证据，无写入重放 | observed: native canary |
| 执行失败例 | 工具报成功但无匹配回执，直接消除未知债务 | fail | 无法证明执行结果 | constructed: receipt regression |

- 上浮时泛化项目、分支、会话和摘要；保留“幂等请求/来源/存储证明/语义真值分离”。
- 建议容器：work-model；消费者：Guardian、MCP writer、verifier、验收清单。

### B. Optional enrichment needs explicit dependency projection

- 问题类型：bug-fix / performance。
- 任务目标：独立业务任务不被可选图谱增强的后台状态变化拖回审批循环。
- 触发场景：提案展示到应用期间有记忆事件；旧写者只更新总 sequence。
- 症状：全局序列把不相关记忆变化视为提案的业务世界变化。
- 已确认根因：冲突资源域与审批 freshness 域不一致；单独新域计数又会遗漏旧写者。
- 已排除：不能以清债、伪造成功或忽略全部 local_write 解决。
- 证据状态：verified；R2 已补齐真实 CLI 原生续接与源会话记忆变化的组合证据（人工按钮输入为隔离夹具）。
- 正确做法：显式、人确认的无依赖声明；总量减已证明记忆增量；过滤前校验权威 attempt。

| 样本 | 内容 | 固定预期 | 判定原因 | 来源 |
| --- | --- | --- | --- | --- |
| 路由正例 | 已声明不依赖记忆的报告修订遇到限定记忆债务 | apply | 结果独立，债务保留而非清除 | constructed: regression |
| 路由反例 | 用户要求修复图谱本身或资源身份不明 | skip | 记忆结果相关或不能证明无关 | constructed: regression |
| 执行合格例 | 可选记忆不失效续接卡；相关记忆变化仍失效 | pass | 兼容旧计数者且不扩大授权 | observed: native canary + constructed: regression |
| 执行失败例 | 仅凭标签过滤一个实际 external_write attempt | fail | 投影不能覆盖权威事实 | constructed: regression |

- 上浮时删除私有路径、提交和人物；内核是依赖投影不是权限继承。
- 建议容器：anti-patterns / work-model；消费者：proposal、continuation、review checklist。

### C. Isolation and explicit continuation must compose (R1 finding, R2 repair)

- 问题类型：regression / workflow。
- 任务目标：完成记忆无依赖任务的新会话原生续接验收。
- 用户真实预期：新会话可经确认续接，不串任务、不继承旧执行权限。
- 触发场景：源会话已批准任务，新 session 经真实 SessionStart/UserPromptSubmit 进入同一目录。
- 可观察症状：源合同无目标 lane；新 session 有自己的合同，旧续接 preview 要求源合同中的 review lane。
- 期望与实际差异：R1 缺少显式源任务选择，不能展示对应续接卡；R2 已补齐。
- 已确认根因：隔离入口改成分 session 合同，续接入口仍依赖旧的共享合同前置状态。
- 已排除假设：不是 Hook 未执行、不是缺少 Python 依赖，也未执行到记忆 writer；不是需要复制 token。
- 证据状态：verified（失败链路与隔离修复验证）；不代表生产已安装。
- 一手证据：`20260910T084342491338Z-continuation-discovery-regression`、R2 scoped-final-r2 与 lane-final 回归。
- 正确做法及验证：显式双合同审查、原生决定、原子映射发布；真实 Allow/Deny 与后续工具正负例通过，未手工灌 lane。

| 样本 | 内容 | 固定预期 | 判定原因 | 来源 |
| --- | --- | --- | --- | --- |
| 路由正例 | 新 session 已隔离，但旧续接入口要求它预先属于源合同 | apply | 两个状态模型缺少显式转换 | observed |
| 路由反例 | 新 session 要开启完全不同任务，独立合同正常建立 | skip | 隔离正是预期，不应自动绑定旧任务 | constructed |
| 执行合格例 | 原生双合同卡后原子切换，旧 grant/debt 不转移，Deny 保持原路由 | pass | 同时满足续接和隔离边界 | observed: actual CLI, fixture human decision |
| 执行失败例 | 为通过测试手工创建旧合同 lane，或把 Hook completed 当作已续接 | fail | 缺少真实归属转换与原生批准证据 | constructed |

- 上浮边界：删除项目、路径、提交、会话与摘要；复用内核是“隔离与迁移协议必须组合验收”。
- 建议容器：work-model；消费者：任务路由、原生审批、真实宿主验收清单。
- 未写入生产知识库或记忆图谱，留协调端判重。

## Skill influence

Intent Guardian/dispatch discipline fixed scope and kept work on the task branch;
KB search supplied the asynchronous-enrichment and canonical-evidence rules.
Skill Creator validated the instruction changes. Plugin Creator informed the
official isolated staging/registry/validation path; no hand-edited production
marketplace/cache, no production install, and no disposable marketplace link was
presented as an installed user plugin.
