# Guardian coupling decoupling — frozen scope

Status: **five source acceptance gates passed; not installed; physical rename not performed**.

## Control boundary

User request: “把这些耦合都解开”. This explicitly replaces the earlier
no-more-source-fixes restriction. Native revision 7 was applied in the current
Codex session. Base: dev `5bfe9a322cfc01accee6299bde05cd4ae1eaf714`.
Branch: `task/guardian-coupling-decouple`, using the existing clean isolated
`.worktrees/repository-relocation-r6` checkout. The R6 branch, report and ignored
evidence remain intact; reusing the checkout does not declare R6 complete.

Only the following five items are in scope. Findings outside them are recorded,
not silently added to this task. No production ledger/cache edits, installation,
physical rename, remote push, main merge, other application work or runtime
rewrite. Do not interpret approval for this source repair as relocation authority.

| ID | Boundary | Evidence / implementation | Acceptance | Status |
| --- | --- | --- | --- | --- |
| C1 | Workspace locator vs task identity/authority | Explicit in-repository allowed/frozen path facts follow the physical move, including linked-task references to the shared root. Prose, relative/outside/ambiguous paths are not text-replaced. | Same intent facts, new paused epoch, no old authority; clone and 0400 drift rejected. Old frozen plans retain their own path-fact policy during recovery. | accepted |
| C2 | Historical review state vs real outstanding operations | Drafts and Skill frames no longer serve as execution-debt blockers. Original bytes are fenced/archived; the new contract has no inherited execution runtime. | Full transaction preserves exact history; real debt, open operations, live approvals and unfinished native transactions still block; interruption tests pass. | accepted |
| C3 | Observation vs approval freshness | Existing control-plane/read/passthrough exclusions were correct. Added regression coverage instead of changing production CAS rules. | Read/Skill/control observations between the question and Allow preserve the proposal; material writes and policy drift remain protected. | accepted, existing mechanism verified |
| C4 | Maintenance diagnosis vs expensive evidence/release | `repository-relocation-preflight --assessment-only` diagnoses local prerequisites without content traversal. Full preflight now checks cheap blockers first. No release/global-doctor dependency added. | Assessment cannot create a fence or authorize execution; real debt fails before hashing; full evidence/revalidation remains required for execution. | accepted |
| C5 | Fixture owner lifetime vs descendants | Shared creation/cleanup owns a dedicated POSIX process group; all `NativeCanary` callers use it. Successful repeated cleanup cannot signal a reused PID. | Same-group children removed, unrelated group untouched, caller-group cleanup rejected, errors visible, other resources finalized even if cleanup fails. | accepted on POSIX |

## Verification and merge gates

1. Add targeted positive/negative regression cases, run via official isolated
   test runner. Prefer the small affected classes while developing.
2. Run affected module integration, including actual isolated native Allow/Deny
   where applicable. No fixture skip is production live evidence.
3. Record exact commands, results and unresolved findings here. Review diff for
   source-only scope and fail-closed invariants before task commit/dev merge.
4. Only all five accepted rows can close this repair. Installation and the
   actual directory rename remain separate, explicitly unperformed outcomes.

## Findings / work log

- Initial read-only inspection: task checkout clean, old R6/base at the same dev
  commit. No need to rebuild the task plan or restart this session.
- C3 correction: the assumption that *all* Guardian observations advance
  material sequence is false in the current source. Existing exclusions must
  be tested rather than replaced with another generalized exemption.
- C2 safety dependency: relocation archives original contracts and publishes
  paused successors with empty execution runtime. Allowing real effect debt
  through that route would hide obligations; those gates remain mandatory.
- C4 workflow distinction: a source repair may need one later official install
  to be used. That does not make plugin release or global historical readiness
  part of every local path-maintenance operation.
- KB symptom searches returned no directly applicable original adopted for this
  repair. One memory-scope result explicitly classified the queried route as
  `skip`; it is not justification to remove memory freshness checks.
- First targeted run: 13 tests / 12 pass / 1 failure (7.357 s). The failed test
  injected an invalid `pre_execution_gaps` row that normal validation discarded;
  it did not actually establish the intended blocker. Replaced that synthetic
  dict with `intervention.begin_attempt`, then proved the real authoritative
  debt rejects before `_content` is called. This was a fixture correction, not
  a reason to relax runtime validation.
- Follow-up targeted runs: 5/5 pass (5.705 s), then 2/2 pass (10.473 s).
- Version review found that changing successor path facts without a frozen
  policy marker would reinterpret old recovery recipes. New plans bind
  `sulde-repository-path-facts-v1` in their preflight/card. A transaction whose
  root already moved under an old plan successfully recovers its original
  paused draft under the new runtime. Unknown future path-fact policy rejects.
- Shared fixture lifecycle was the only new helper module. No supervisor,
  scheduler, approval protocol replacement, dependency installation or global
  process scan was introduced.

## Final verification evidence

Official isolated runner: **650 tests, 633 passed, 17 existing retired skips,
0 failures/errors; 567.775 seconds**. No new skips were added. Twelve test
methods were added; the additional existing native consumers cover the shared
fixture change, not additional implementation tasks.

```sh
/Users/eric/.pyenv/versions/3.10.7/bin/python3.10 -B scripts/kb/run-isolated-tests.py \
  tests.test_repository_relocation tests.test_intent_guardian \
  tests.test_approval_invariant tests.test_intervention tests.test_intervention_batch \
  tests.test_native_decision_journal tests.test_native_session_continuity \
  tests.test_production_recovery_control tests.test_production_recovery_readiness \
  tests.test_native_control_composition tests.test_native_memory_consistency \
  tests.test_native_memory_continuation \
  tests.test_guardian_string_flow.GuardianStringFlowNativeTests \
  tests.test_candidate_codex_plugin
```

Complete captured log (650 test headers, no truncated chunks), owner-only 0600:
`.worktrees/repository-relocation-r6/.sulde/public-export/guardian-coupling-decoupling-20260914/integration.log`
relative to the main repository root. SHA-256:
`660728a4831b2f52f1a66baedb3eefe392a9df4e11b634cf95eaa58f08744bb2`.

Actual Codex CLI/app-server in disposable candidate environments verified:

- Native Allow: exactly one approval and one verified physical move; old
  business authority not inherited; an unreviewed business write denied.
- Native Deny: no physical move and no execution transaction.
- Session continuation, memory missing-post recovery, attribution rejection,
  safe control batches and retained destructive rejection all passed using the
  shared host. These fixture choices are **not production human approvals**.
- All reported candidate artifact generations used runtime digest
  `906afdcc83614c954843c50fbe5b67ffde2520708d2bfe52a11f740457220d95`.

Source/test file hashes were unchanged across the complete integration run.
`git diff --check` passed. The original R6 control report was not changed.

## Delivery boundary and remaining work

- Source acceptance: **5/5 accepted**, scoped to the table above. Commit only
  the seven source/test files and this report. Merge into dev only by a
  fast-forward to that tested source tree; no main merge or remote push.
- Production installation: **not performed**. The installed runtime does not
  acquire these fixes merely because the source tests passed.
- Actual local repository rename: **not performed**. The original R6 outcome
  remains separate and incomplete; this report does not replace its evidence.
- A moved task still needs review before new business authority is granted.
  Path-fact rebasing is not automatic transfer of receipts, grants or lanes.
- Real outstanding operations are intentionally not bypassed: this relocation
  model archives source contracts, so hiding their unresolved obligations would
  be unsafe. They must be settled through their supported recovery route.
- Fixture cleanup owns the POSIX group it created. It does not claim to discover
  escaped sessions or implement a Windows process-tree supervisor.
- Keep this checkout and the original R6 branch/evidence: they also hold the
  still-unfinished R6 task. A source merge is not permission to delete that
  shared evidence or declare the original rename complete.

Skills used: intent-guardian froze native source-repair authority and prohibited
production mutations; dispatch-task kept continuation in the current Codex host
without model-switch ceremony; kb-search checked symptom matches without
treating excerpts or a `skip` result as implementation authority.

## 沉淀候选

### Layer1: non-executing history coupled to maintenance readiness

- **问题类型**：bug-fix / workflow / performance。
- **任务目标与真实预期**：仓库路径维护不因无关的历史流程状态反复挂起，同时保留数据与真实授权边界。
- **触发场景**：仓库内已无执行副作用，但合同保留 pending proposal 或 Skill frame。
- **可观察症状与差异**：原预检把这些字段与未验证操作统一拒绝，而且拒绝前先扫描全仓内容。
- **已确认根因**：`_binding_inventory` 的统一字段门禁；完整内容扫描早于便宜的绑定/债务检查。
- **已排除假设**：并非当前版本所有控制面观察都会破坏 material CAS；本轮提案原生事务测试证实观察隔离有效。
- **证据状态**：verified（源码、隔离事务与回归）；生产安装效果尚未验证。
- **一手证据**：C2/C3/C4 diff、完整集成日志、草案/Skill 归档事务测试、真实 `begin_attempt` 的快速拒绝测试。
- **正确做法及验证**：非授权历史原样归档；真实未决操作保持阻断；轻量诊断与完整执行证据使用不同输出。

| 样本 | 内容 | 固定预期 | 判定原因 | 来源 |
| --- | --- | --- | --- | --- |
| 路由正例 | 路径维护被无执行副作用的旧提案/Skill 记录挡住 | apply | 历史工作流状态被当成执行债务 | constructed，已由事务回归验证 |
| 路由反例 | 同一迁移范围存在真实未验证外部写入 | skip | 不能用历史记录豁免去隐藏真实债务 | constructed，经真实账本入口验证 |
| 执行合格例 | 原合同字节归档，继任合同暂停且无旧授权，完整迁移只提交一次 | pass | 历史与权限边界均保留 | observed，隔离事务测试 |
| 执行失败例 | 删除 active JSON/ledger 后把 readiness 改成 ready | fail | 丢失义务与授权来源 | constructed，未执行 |

- **上浮边界**：泛化项目名、绝对路径、会话/提交/审批标识。
- **可复用内核**：诊断信息、执行义务与授权分别建模；快速诊断不能冒充执行证据。
- **建议容器与消费者**：anti-patterns；维护工具、Hook、恢复逻辑和 review checklist。

### Layer1: process exit is not fixture completion

- **问题类型**：regression / workflow。
- **任务目标与真实预期**：测试完成后释放自身资源，不影响其他会话，不用删除重试掩盖活跃写入者。
- **触发场景**：宿主父进程退出，同组后台子进程仍活着。
- **可观察症状与差异**：等待父进程不足以证明临时目录可以安全清理。
- **已确认根因**：共享 `NativeCanary` 原收尾只处理直接子进程；本轮真实父子进程夹具证明生命周期差异。
- **未确认项**：原 R6 目录清理失败时具体是哪一个 Git 写入进程，仍为 inconclusive，不据此改写事故事实。
- **已排除假设**：无需按进程名称扫描或杀掉其他终端，也无需重启生产宿主。
- **证据状态与一手证据**：verified（POSIX 隔离夹具、真实 Codex 调用方和完整日志）；生产进程树治理不在本轮范围。
- **正确做法及验证**：创建时确立进程组所有权，有限等待/终止，成功后幂等收尾；失败保持可见，同时释放其他资源。

| 样本 | 内容 | 固定预期 | 判定原因 | 来源 |
| --- | --- | --- | --- | --- |
| 路由正例 | 父进程已退出但同组子进程仍存活 | apply | 所有者退出不等于资源生命周期结束 | constructed，真实 OS 进程夹具 |
| 路由反例 | 另一个会话的进程仍在合法工作 | skip | 不属于本夹具的所有权范围 | constructed，与合格例同时验证 |
| 执行合格例 | 仅自身进程组消失，其他组存活，二次收尾不再发信号 | pass | 有边界且幂等 | observed，隔离回归 |
| 执行失败例 | 全局按 codex/git 名称杀进程或对未退出写入者反复删除目录 | fail | 误伤其他工作或掩盖问题 | constructed，未执行 |

- **上浮边界**：删除本机 PID、路径、会话及具体项目标识。
- **可复用内核**：资源完成证据应来自其完整受管生命周期，而不是单个父进程返回值。
- **建议容器与消费者**：anti-patterns / test harness、release canary 与 review checklist。

以上仅为本任务来源卡，未直接写入共享知识库。
