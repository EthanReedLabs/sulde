# Doctor session-contract repair

- Status: DEVELOPMENT_VERIFIED — not merged or installed
- capability_tier: balanced
- Base: dev `59f8c7a1b02f767b8f90ff867bb6cb3937d03c89`.
- Scope: session-aware diagnostic contract selection, doctor consistency,
  isolated regression/CLI evidence. No install, push, production ledger mutation,
  permission-policy changes or synthetic live Hook claims.
- Acceptance: current session contract throughout all diagnostic domains;
  malformed/missing/mismatched routing never borrows a workspace contract;
  unmapped legacy and scheduler behavior remains compatible; reads stay read-only.
- Verification: medium scoped repair; exercise operational readiness, Guardian,
  host capability and new isolated CLI tests. No unrelated full-suite rerun.
- SessionStart remains a separate real-host acceptance item.

## Result

1. `operational_readiness.project()` uses the existing validated session resolver.
   A valid session contract takes precedence over the shared workspace anchor.
   Missing session routing preserves legacy fallback; an invalid mapping or
   missing mapped target never silently falls back. An explicit workspace
   mismatch is degraded without mixing effect/approval facts. Implicit status
   callers use the mapped root instead of launch-time cwd/environment hints.
2. `guardian_doctor()` supplies its resolved contract path to the nested
   projection, so a concurrent mapping change cannot make the two layers read
   different contracts during that invocation.
3. `head_proof_read_only()` and `load_projection_read_only()` share a stable
   anchored reader. It checks pending publication, validates replay/anchor and
   rechecks the observed bytes. It neither creates locks nor performs recovery.
   Normal maintenance `head_proof()` retains its recovery behavior. Both APIs
   share the same proof builder; local consistency is never external authority.
4. The operational consumer now calls the read-only proof API. An older runtime
   missing that API stays unverified rather than falling back to a writer.

No permission policy, session binding writer, shared production ledger, install
generation or scheduler configuration was changed. The mapping controls which
facts diagnostics read; it grants no execution authority.

## Test record — 2026-09-08

All runs used `scripts/kb/run-isolated-tests.py` with the existing managed Python,
OS write-denial isolation and bytecode disabled. Temporary fixtures contain no
production payloads. CLI tests start actual Python/Guardian CLI processes; their
fixtures are integration evidence, **not production/live Hook observations**.

| Run | Scope | Result | Duration |
|---|---|---|---|
| Red | Two new contract-selection assertions on unchanged product code | 2 failed, reproducing shared-contract selection | 0.301 s |
| Routing pass | Initial 14 new regressions | 12 passed; 2 read-only snapshots exposed head-proof lock creation | 1.739 s |
| Combined | New tests + operational readiness + native journal | 117 passed | 6.180 s |
| Broad dependency | Above + intent Guardian + host capabilities | 416 run: 399 passed, 17 existing retired-policy skips | 62.412 s |
| Implicit-root follow-up | New tests + operational readiness + native journal + host capabilities | 148 passed | 6.300 s |
| Final | Same four modules, with CLI invalid-map and mtime assertions | 149 passed | 6.686 s |

The broad run preceded the final implicit-workspace adjustment. Its affected
operational consumers were rerun in the final set; no claim is made that the
complete repository suite ran on the final tree. `git diff --check` passed.

Final command (relative to task worktree):

```sh
python -B scripts/kb/run-isolated-tests.py tests.test_doctor_session_contract tests.test_operational_readiness tests.test_native_decision_journal tests.test_host_capabilities
```

Final tested-content SHA-256 (report-only changes do not invalidate these):

| File | SHA-256 |
|---|---|
| `scripts/kb/operational_readiness.py` | `9d7d83dc935a08871200f0b32019832fe83d7ddc938ad706a2ccc3f8a323daa7` |
| `scripts/kb/intent_guardian_parts/readiness.py` | `9f45b7df7c7cc2981a4d8c4d3e451f7292731b71540b7b54c5ff720b52e1f354` |
| `scripts/kb/native_decision_journal.py` | `eca7eb2363600d01512a929321b8c1887b01ed7b62cdd542a49ea5d325169bc2` |
| `tests/test_doctor_session_contract.py` | `df167271f4627e37d5857ae8bdcc684284fecdb778985ef437464e12de1d5ccf` |

The new regression file has 26 tests covering completion anchors, non-Git
session contracts, two sessions and two providers, paused sibling approvals,
current/sibling external debt, pre-execution gaps, missing/malformed/digest-
mismatched routing, explicit/implicit workspaces, mapping changes during doctor,
real CLI positive/negative cases, head-proof byte equality, missing journals,
pending recovery, anchor tampering, torn tails and concurrent appends. CLI/read
snapshots compare filenames, content hashes, modification timestamps and modes.

## Agent execution retrospective

- Outcome: verified source repair; production activation and real SessionStart
  remain outside this task, not inferred from fixture success.
- Initial nested `sandbox-exec` returned `Operation not permitted`. Resolution:
  native host escalation for the supported isolated runner; the runner's own OS
  write-denial check remained enabled. No weaker test route was substituted.
- First test invocation omitted the `tests.` package prefix and failed import.
  Resolution: qualified unittest module names. That run is an invocation error,
  not a product regression or passing test record.
- Read-only snapshots exposed the second product defect. The allowed source
  scope was explicitly amended through native approval before adding the
  journal API. No production lock/log was deleted to satisfy assertions.
- Model dispatch returned task-only instructions and no model actions.

## Remaining release boundary

- Commit this task branch; merge/install are not authorized by this revision.
- Preserve the worktree while its commit is not merged. The normal completed-
  workspace cleanup can run after merge; do not delete this unmerged candidate.
- Production doctor continues to execute the previous installed bytes until a
  normal candidate/install flow activates the repair.
- A real current-session `SessionStart` still needs host-lifecycle evidence.
  Neither this CLI fixture nor native approval manufactures that observation.
- Windows host execution was not performed; no Windows production claim.

## 沉淀候选（Layer1；未写共享知识库或记忆图谱）

- **问题类型**：host-inconsistency / regression
- **任务目标 / 用户预期**：当前 session 的真实状态可独立诊断，诊断本身不写控制面。
- **触发场景**：同项目已完成任务被迁移到 session completion anchor，共享工作区仍有不同审批历史。
- **可观察症状**：doctor 外层合同正确，内层读到共享合同并报告不属于当前任务的未结算；只读测试又出现新锁文件。
- **已确认根因**：聚合器丢弃已解析的合同路径后重新按 workspace 构造路径；只替换 journal replay 为只读仍不够，head-proof 消费者另有恢复写入口。
- **已排除假设**：不是当前 Allow 未发生、不是需要清空账本，也不是 SessionStart 缺失能解释审批合同不一致。
- **证据状态**：verified（源码与隔离回归）；生产修复生效仍为未验。
- **一手证据**：修复前两项红测、14 项快照反例、最终 149 项定向测试及以上源码摘要。
- **正确做法**：复用经验证的 session 路由，贯穿传递所选合同；只读 head 和 replay 共用稳定快照读取，无恢复副作用。

| 样本 | 内容 | 固定预期 | 判定原因 | 来源 |
|---|---|---|---|---|
| 路由正例 | 同项目 doctor 内外合同路径不同且错误呈现审批债务 | apply | 聚合消费者丢失 session 选择上下文 | observed |
| 路由反例 | 当前正确合同确有未验证外部效果 | skip | 正确作用域内的真实债务不能靠路由修复清除 | constructed |
| 执行合格例 | 两个 session 读取各自合同；损坏映射失败；真实 CLI 诊断前后文件/hash/mtime/mode 不变 | pass | 同时满足隔离、失败闭合和只读不变量 | observed in isolated tests |
| 执行失败例 | 只改外层路径或只读 replay，内层重选共享合同/head-proof 仍创建锁 | fail | 仍串读或仍由诊断修改控制面 | observed |

- **上浮边界**：泛化工作区、session/receipt 标识及源码摘要，禁止复制生产日志正文。
- **可复用内核**：诊断聚合必须传递同一个作用域选择；只读约束覆盖整个依赖调用链。
- **建议容器 / 消费者**：anti-patterns；doctor、状态汇总、测试门禁与代码评审。
