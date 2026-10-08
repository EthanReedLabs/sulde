# Recovery live acceptance — blocked, fault rolled back

Date: 2026-09-07. Result: **NOT ACCEPTED**. This is a failure report, not a
release acceptance or authorization to modify the recovery implementation.

## Scope and identity

- Task branch: `task/guardian-recovery-live-acceptance`, based on dev
  `9f33396c9030aac17fe99b5464141d6e6bf6ce94`.
- Existing Codex session: `01a04634-318f-7203-ba2d-26fa6ac442b0`.
- Installed version: `0.2.5+codex.20260907050036-0fc70680ae`.
- Artifact generation tree:
  `b54d7c1e3fb28aa8988b765e334d7e3792a15f526d13ee7d59ad1d1646daa249`.
- Same-session workspace handoff returned `bound`, `authority_transferred=false`;
  receipt `7a1a91a18780ab0e87d2449ad5094c6c308e6399c170d8cfdced078274dc604c`.
- A separate native human approval applied revision 2 to workspace contract
  `66416c393e0ce081a752146a`; proposal
  `6f0a3e462e5aa8a14d8f03b82d05aed352d7bd0dd183f15cbf5f4dca03c21f37`, receipt
  `66002d38a8db38522fd24cc872d375cdc311107894fc544db5a8aaf8f3210fc7`.
- Scope explicitly authorized a permission-only launcher fault, exact recovery
  through native approval, and hash-checked permission rollback on failure.
  Installation, source changes, debt clearing, push and resource deletion were excluded.

## Actual journey

1. Baseline `/Users/eric/.sulde/bin/model-dispatch` was a regular single-link
   file, mode `0755`, SHA256
   `537e3f1a1ed2e0ed50a8dcddeb5ded14534c4d0c99c0a24c7af5188cb6ee0c1b`.
   Its original command returned exit 0.
2. Following approval, an actual tool call changed only its mode to `0644`.
   The same launcher command returned exit **126**, `permission denied`.
3. Installed `production-recovery.py prepare --action repair_launcher
   --target model-dispatch` first encountered sandbox lock creation denial.
   Normal native escalation allowed preparation; no repair authority was created.
4. Preparation froze the actual `0644` state and current generation, with capability
   `sha256:8751000e5bcb0aca29a57deca997566109a66137602bc198e55751d9e419fb61`.
   Card: `sha256:5edb29e0726905fdd3563825261146c419578406855351463d03c5705275a86e`.
5. The returned exact `command_argv` was submitted through actual unified exec
   with `sandbox_permissions=require_escalated`, the returned `description`
   verbatim as `justification`, and **no prefix_rule**. PreToolUse refused it:
   `native recovery description differs from current card`.
   The recovery approval UI was not reached, and the recovery executor did not run.
6. The pre-approved rollback independently checked the original file hash and
   regular/single-link identity, then restored mode `0755`. It did not replace bytes.
7. A fresh readback confirmed the original hash, mode `0755`, and
   `RepairTarget.passed(snapshot)=true`. The original command again returned exit 0.
   This is **rollback recovery**, not successful execution of the new repair channel.

The identical command used before fault, during fault, and after rollback was:

```sh
/Users/eric/.sulde/bin/model-dispatch --provider codex --tier deep --task /Users/eric/ClaudePlugin/sulde-cc-pro/.worktrees/guardian-v3-dev-merge/docs/guardian-recovery-release-r20.md
```

Actual call output chunks: baseline `406ad4`; mode change `18dc9d`; failed
launcher `64ddd7`; sandbox prepare `c0dc44`; prepared plan `046c18`; rollback
`046035`; resumed launcher `45a880`. The refusal is the tool failure immediately
following preparation, before any recovery PermissionRequest.

## Independent readback and acceptance limits

- Strict read-only recovery journal snapshot contained exactly one event:
  `production_recovery_prepared`. There were **zero** recovery prompts, human
  decisions, dispatch starts, or successful recovery runs.
- Recovery ledger retained at `/Users/eric/.sulde/state/recovery-lane.jsonl`, SHA256
  `7dfd17976c6db194fb876cbb46dd64f6a553c4834d2a92c6e3301c5ab76c1793`.
  The unused ten-minute capability is retained; rollback changed its bound
  prestate. It must not be reused or silently relabelled as completed.
- Launcher manifest SHA256 remained
  `ec3632fe31aad72ca14b2588a726ac53c983c8093b272c73e80dd99790646714`;
  descriptor SHA256 remained
  `c0949a73a79f14054c83a621113810c9c4ca7ad515d585748169d8b41db48094`.
- Doctor: artifact ready; scheduler **16/16**, no failed/missing/retired labels;
  no open task events, pending verifications, interventions or effect debt.
- Recovery doctor correctly remains `diagnosis_available`,
  `human_confirmation=unobserved`, `repair_execution=unverified`,
  `recovery_verified=false`.
- Interactive doctor separately reports `degraded` for `host_interactive_fresh`
  in the new worktree lane (no lane SessionStart/UserPromptSubmit). Actual current
  lane supervision and proposal approval were live. Its restart suggestion is
  not a remedy for the earlier description refusal and was not followed.
- No runtime code, generation, scheduler configuration, dev or main changes.
  Main's existing three `.ua` modifications remain. No reinstall, full test
  rerun, push, worktree deletion or session restart occurred.
- Native Allow repair, native Deny behavior, adapter backup/write, independent
  repair verifier settlement, and continuation **after that adapter's repair**
  remain unaccepted. The earlier installed ordinary denial proof is not this proof.

## Confirmed defect boundary and proposed repair scope

`scripts/kb/production_recovery_control.py:193` compares the readable description
before distinguishing `PreToolUse` from `PermissionRequest`. The actual call
supplied the preview justification verbatim but failed at this check. The raw
host-delivered pre-event description was not retained here, so whether it was
absent, transformed, or shadowed by a different field remains **inconclusive**.

`tests/test_production_recovery_control.py:87` constructs one payload containing
`justification` and feeds it to both stages. Its real subprocesses do not make
the payload a real host event, nor prove that the host supplies identical fields
at both stages. This explains why that fixture did not cover this live failure.

Next repair should freeze the two event schemas separately: PreToolUse validates
the exact command, identity, capability and prestate without pretending the
approval has already been presented; PermissionRequest must bind the full exact
readable card and interactive mode. Execution must still require its genuine
paired native request. This is a proposed design, not an implemented fix.

Required negative coverage: missing/altered approval text at PermissionRequest,
wrong session/target/generation, expiry, absent prompt, and duplicate execution.
Then repeat a bounded real same-session canary; do not replace it with another
fixture-only success claim or bypass the current denial.

## 沉淀候选（Layer1；未写入事实知识库）

- 问题类型：host-inconsistency / workflow。
- 任务目标与用户预期：同会话完成真实恢复，不依赖新开终端。
- 触发场景：受控启动器权限故障后，提交恢复器返回的精确原生修复命令。
- 症状与差异：预期进入恢复 Allow/Deny；实际在 PreToolUse 被文案不匹配拒绝。
- 已确认：拒绝位置与两阶段共用 fixture 文案假设；证据状态 verified。
- 尚未确认：真实 PreTool 文案字段的具体丢失/变化方式，inconclusive。
- 已排除：目标原本健康、命令未复现故障、安装代际变化、修复执行后才失败。
- 正确处置及验证：按预批哈希检查恢复权限；原命令成功；恢复账本无执行记录。
- 路由正例（observed / apply）：精确 preview 的真实恢复命令在审批前因文案被拒绝；
  命中事件阶段契约差异。
- 路由反例（constructed / skip）：PermissionRequest 确实带了被篡改的文案；
  这种拒绝属于必要保护，不得按本问题放行。
- 执行合格例（constructed / pass）：真实 PreTool 结构校验、真实原生确认、精确
  单次修复、独立验证、原命令继续全部形成证据；本次未达到。
- 执行失败例（observed / fail）：只读准备成功和人工回滚后入口可用，被称作正式
  恢复通道验收通过；缺少真实审批和修复执行事实。
- 上浮时删除：项目、私人路径、session、提交、receipt 和 capability 标识。
- 可复用内核：按实际宿主阶段验证字段，测试不得向早期事件补入后期独有上下文。
- 建议容器/消费者：anti-patterns；Hook 适配器、恢复控制器、宿主集成验收。

Knowledge search was used to check known launcher pitfalls. The full ap-0235
source was read; its stale generated-wrapper incident is not this permission/card
failure and was not treated as this incident's root cause. Intent Guardian scoped
the approval/rollback, and dispatch-task supplied the original-command probe.

Execution notes: an initial read-only audit helper omitted required clock
arguments; it was corrected without state writes. Doctor output was initially
truncated; final fields were parsed from complete output. No such diagnostic
failure was reused as passing evidence. The host reported saving exact command
prefixes despite omission of prefix_rule; they were not reused as new authority.
