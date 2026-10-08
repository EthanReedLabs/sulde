# Codex CLI 0.155.1 scoped audit — 2026-09-23

## Verdict and boundary

The scoped macOS CLI contract audit passes using the original regression run plus
the documented corrective reruns below. This is **not** a claim that the original
277-test run was green, a full-suite release verdict, or production installation.
The task branch is suitable for coordinator review and integration into dev.

Base: `c82d537642334645c4a08cd95f59f5c0aef86d14`.
Task: `task/codex-01551-contract-audit`, native-approved revision 21.
Production installation, scheduler, main/dev, remote refs and old worktrees were
not changed. No CLI upgrade/downgrade, model-service request or KB write occurred.

## Changes

- Move the single production CLI pin from exact `0.154.0` to exact `0.155.1`.
- Migrate installer/runtime/stager/candidate fixtures and the public-overlay
  compatibility statement. Historical release reports remain unchanged.
- Explicitly reject 0.154.0, 0.155.0, 0.156.0, decorated versions, unsuccessful
  version commands, executable drift and help/authority drift. No range acceptance.
- Add an opt-in real CLI test that executes under the supported isolation runner.
  The old `SULDE_TEST_CODEX_EXECUTABLE` input is deliberately sanitized by that
  runner; merely exporting it outside does not prove those tests execute.
- Add a bounded private-evidence runner, preserving failed runs and source hashes.
  Private evidence is ignored locally, not staged with source changes.

## Evidence identity

- Actual CLI: `codex-cli 0.155.1`.
- Resolved executable SHA-256:
  `61b0194f3bb6534439c8d26a3ed57d0805f84b884588b761795323eeb92fcf70`.
- Canonical global/exec/app-server help digest:
  `e43e581885833e1908433408a728376e1a0f0a1e48c9a6b7962076e106532edd`.
- 437 generated JSON schema files are individually hashed in `surfaces-2/run.json`.
  Thread start retains the consumed cwd/config/approvalPolicy/sandbox inputs;
  its response exposes sandbox, approval policy and thread identity. Command
  approval requests expose thread/turn/item identity and decisions still include
  accept/decline/cancel. Schema inspection alone is not behavioral acceptance.
- The [official app-server documentation](https://developers.openai.com/codex/app-server)
  explains that CLI-generated schemas match the generating version; the local
  executable and actual runs, not the latest website, bind this audit.

## Executed tests

Private evidence root: `.sulde/cli-contract-audit/` in this task worktree.
Each run retains real exit code, elapsed time, executable/source hashes and logs.

| Run | Result | Interpretation |
|---|---|---|
| surfaces-1 | exit 1 | Audit harness omitted creating its isolated CODEX_HOME; unknown stderr correctly rejected. Not a product incompatibility. |
| surfaces-2 | exit 0 | Existing isolated home; canonical help and generated schema captured. |
| native-1 | 19 passed, 67.773 s | Real PostToolUse, command composition, session continuity; synthetic receipt concurrency tests separately identified. |
| regression-1 | 273 passed, 1 failed, 3 skipped; 390.690 s | 277 total; original failure retained, never relabeled green. |
| lifecycle-1 | 1 failed, 0.993 s | Isolated reproduction of the same umask-induced fixture failure. |
| lifecycle-2 | 1 passed, 2.539 s | Test child inherits original umask, without relaxing product validation. |
| closure-1 | 3 passed, no skips, 21.160 s | Final real authority/PTY chain, staged candidate PreToolUse and corrected lifecycle test. |

The three regression skips are two older environment-gated CLI entries and one
Windows PowerShell test. The new opt-in test actually executes both CLI behaviors
(PTY/pipe and installer→staged-runtime authority) in regression-1 and closure-1.
Windows remains unverified here; no Windows claim is made.

The regression failure was caused by this task's first harness applying `umask
077` to test children. A temporary completion blob consequently failed the
existing portable-mode check. The fix keeps evidence private but passes the
caller's `022` umask to test processes. The failing test body and product check
were not changed. This does not establish that every product path supports 077.
No unrelated source fix was mixed into the CLI audit.

The native and regression groups initially used the outer OS isolation boundary;
their `dangerFullAccess` inner policy does not prove inner workspace sandbox
denials. Those were covered in the prior path-boundary task and are not relabeled
as new inner-sandbox evidence here.

## Actual candidate chain

Final real app-server/unified-exec/PreToolUse proof:
`02e026c369278bad213e21aaeb510c66202c609ab17a2670ba4639ef2708edc3`.

- Artifact generation:
  `0.2.5+codex.20260922005243-95a8cf2d92:b59f38733f11e47e49a3417a86ec11d24c367c99574d680dce7651d53c4e942f`.
- Loaded module generation:
  `4f723803be8759d00d7fc98687e01f5612bc3fb5e77dfb2aa4858222993e1e30`.
- Positive write executed; destructive negative was denied before execution;
  negative marker absent. An outside-plan ordinary write remained permitted as
  required by the current narrowed Guardian policy.
- Fresh staged runtime consumed the installation-bound authority. Exact help,
  strict permission-profile parse, Hook parse and app-server initialize succeeded.
  Re-signed broker digest drift was rejected. PTY and pipe help observations match.
- Synthetic receipt consistency tests are not a real human Allow/Deny on this
  candidate generation. Current-session revision approval belongs to the installed
  control plane, not the newly staged candidate. Production approval readiness is
  therefore not inferred from these tests.

Final closure log SHA-256:
`07904e0c8b906e64422bc75440586f3ae1785c90f12a949f94ce675c556bcf49`.
Original regression log SHA-256:
`51983b66954188230741ee30fc9871565a8bf12a65e395bbf55f8e689761df01`.

## Next release step

Review and merge the task into dev, then run the authorized candidate release /
cachebuster / transactional promotion procedure with exact final source identity.
Recheck CLI bytes at promotion and perform the required live current-generation
approval/Hook readback. Reuse this evidence only while its relevant inputs match.
Do not reclassify the complete Guardian program as closed from this CLI audit.
No installation, merge or push is authorized by this task's revision 21.

## 沉淀候选（Layer1，未写入正式知识库）

- 问题类型：workflow / regression。
- 任务目标及真实预期：升级宿主兼容结论需要真实链路证据，不能靠跳过测试或改常量获得绿灯。
- 触发场景：隔离测试器清除 SULDE_*，同时取证脚本给测试进程施加私有证据 umask。
- 可观察症状：两项真实门禁被 skip；Git 临时 blob 因模式不可移植失败。
- 已确认根因：测试启用变量被隔离清理；取证权限设置泄漏到被测进程。
- 已排除假设：该 blob 失败不是 0.155.1 协议变化；仅改子进程 umask 后原测试通过。
- 证据状态：verified；一手证据为上述原始日志、复验和新显式入口。
- 正确做法：将证据隐私与测试环境分离；检查真实门禁执行而非只看退出码。

| 样本 | 内容 | 预期 | 原因 | 来源 |
|---|---|---|---|---|
| 路由正例 | 外层设置 CLI 门禁变量但隔离层清除后测试被跳过 | apply | 门禁未执行 | observed |
| 路由反例 | 平台专属测试在另一个平台明确跳过且未声称覆盖 | skip | 不是隐藏覆盖缺失 | observed |
| 执行合格例 | 新入口真实执行生产权威链；原 umask 失败保留并单项复验 | pass | 来源与结果可核验 | observed |
| 执行失败例 | 只统计 suite 退出码，忽略关键 skip；放宽文件模式检查 | fail | 假覆盖或改变不变量 | constructed |

上浮时删除个人路径、会话与提交标识；可复用内核是“测试隔离不能默默取消必需验收，
取证进程配置不能无意改变被测环境”。建议并入已有 schema/fixture 真实执行工作模型，
消费者为测试 runner、release checklist 和 reviewer；由单写者流程判重处理。
