# Recovery approval stage repair

Date: 2026-09-07. capability_tier: deep.
Intent: completion:6cbefb0ee2086d965bbeb099, revision 3.

## Result

Implemented and verified in the independent `task/guardian-recovery-live-acceptance`
worktree based on dev `9f33396c9030aac17fe99b5464141d6e6bf6ce94`.
**Development verification passed; production/live acceptance remains pending.**
The preceding `guardian-recovery-live-acceptance.md` is retained as failure evidence,
not overwritten as a success report.

Native proposal receipt:
`154a403acd0b7f519e8c6cbd7ccc1b3da818147d5b7bafd1e8519c1f40948ddb`.
It authorized source/test/report changes only; no install or further production fault.

## Fix and security boundary

- Move exact readable-text comparison into the `PermissionRequest` branch of
  `ProductionRecoveryControl.observe`. PreToolUse still validates command argv,
  provider/session, sealed capability, workspace/intent, expiry, target prestate,
  current generation and executor identity. It returns defer, never Allow.
- A pre-event may lack approval text or carry a generic tool description without
  fabricating a prompt, human decision, dispatch or other recovery authority.
- PermissionRequest still requires the exact readable description and an
  interactive mode. Missing, empty, altered and conflicting descriptions fail.
- The executor is unchanged: without its genuine paired native prompt it refuses
  execution. Existing at-most-once apply, independent verification, re-entry and
  crash/reprobe behavior are preserved.
- Split stage fixtures so the main isolated journey no longer supplies approval
  text to PreToolUse. Four additional regression tests cover stage separation and
  negative boundaries. The fixtures are explicitly constructed, not raw captured
  host events or proof that a human clicked Allow/Deny.

The live failure identified the rejected comparison. The exact transformation or
omission of the raw host pre-event text remains inconclusive. The repaired stage
invariant does not depend on guessing which description field the host supplies.

## Tests and reusable evidence

Evidence directory (task-local): `.sulde/data/test-evidence/`.
Each run has a JSON record and SHA-bound log; records retain source/workspace,
command, runner, environment, scope, timestamps and a 30-day expiry. No failed
record was reused as successful evidence. No automatic deletion ran.

| Run | Result | Evidence ID |
| --- | --- | --- |
| Initial sandbox attempt | OS nested sandbox setup denied; not a test failure | `20260907T064011.982574-ed78e68e814a` |
| Before source fix | 18 tests, 4 failures reproducing description denial | `20260907T064103.267311-97187ca9f302` |
| After source fix | 18 tests passed; harness 7.092 s | `20260907T064144.369920-331d29206f48` |
| Impact regression | 72 tests passed; unittest 11.728 s, harness 12.380 s | `20260907T064258.964611-40558db5d678` |

The 18 tests are included in the 72; do not add the counts. Impact scope:
`tests.test_production_recovery_control`, `tests.test_production_recovery_readiness`,
`tests.test_launcher_split_recovery`, `tests.test_codex_hook_bridge`,
`tests.test_recovery_lane`.

The repository runner's OS isolation remained enabled. It was launched with native
escalation because the outer host sandbox forbids nested `sandbox-exec` setup.
No full suite was needed for moving one check to its correct event stage; direct
consumers, negative boundaries and the existing isolated journey were exercised.
All evidence runs report zero source bytecode cleanup before and after.

Tested content SHA256 (unchanged when included in the repair commit):

- `scripts/kb/production_recovery_control.py`:
  `b4c9bef050ce1f147dc2b0f6f67c63ba2af3643e35dfb59db94078ae0c45f882`.
- `tests/test_production_recovery_control.py`:
  `8d3164a1f8ca3ec02a1ef30b6381c7ea82347a056af53049d62c8411f71ab084`.
- Red log: `2038f09fa9ab6254041cf8dedc8fce4cc9f02dbcc2ff05881bffab31990b3a4f`.
- Impact log: `9d937cf9138d97de705565d1e996afbde985cac38844ccf607e835747edc319a`.

These runs tested the working-tree content above, not a claim of tests rerun on a
later documentation-only commit. `git diff --check` passed.

## Production preservation and next gate

No production file was changed by this repair. The installed version remains
`0.2.5+codex.20260907050036-0fc70680ae`, without this source fix. The public
model-dispatch launcher hash remains
`537e3f1a1ed2e0ed50a8dcddeb5ded14534c4d0c99c0a24c7af5188cb6ee0c1b`.
The previous recovery journal still hashes to
`7dfd17976c6db194fb876cbb46dd64f6a553c4834d2a92c6e3301c5ab76c1793`;
its unused failed-journey plan was not cleared, reused or declared successful.
No dev/main merge, push, installation, fault injection or session restart occurred.

Next: source-bound candidate/release through its normal approved workflow, then
actual same-session PreToolUse -> native PermissionRequest -> exact repair ->
independent verifier -> original command continuation. A true user Deny observation
must not be fabricated from a fixture or from a missing prompt. Windows native
acceptance remains Windows-owned.

## 沉淀候选更新

- 问题类型：host-inconsistency / workflow；来源为上轮真实失败及本轮红绿测试。
- 已验证缺陷：恢复 PreToolUse 提前要求后续审批文案；修复将文案绑定移到正确阶段。
- 尚未确认：上轮宿主原始文案字段具体如何变化；不冒充已捕获完整 payload。
- 路由正例（observed / apply）：精确恢复命令在审批展示前因文案校验被拒绝。
- 路由反例（constructed / skip）：PermissionRequest 的完整文案真实被篡改，应拒绝。
- 执行合格例（constructed / pass，隔离实跑）：PreTool 不生成授权，后续精确审批
  阶段才记录问题，未配对执行被拒绝；有配对的隔离流程只执行一次并独立验证。
- 执行失败例（observed / fail）：测试提前填充完整审批文案，从而漏掉真实前置拒绝。
- 安装/真实宿主成功仍未证实，不能将开发回归结论升级为整体恢复能力 ready。
- 上浮前删除私人路径、session/receipt、提交及运行标识；建议 anti-patterns，供
  Hook 适配器与宿主验收消费。事实知识库未直接写入。

Intent Guardian supplied the scoped native code-change approval. Dispatch-task
rendered the current-host continuation configuration. KB search read ap-0247 in
full; its already-Allow consumption incident is distinct from this before-prompt
failure and was not adopted as the root cause. A bounded Codex memory edge records
the stage dependency separately from the fact knowledge base. Independent graph
readback found edge 1993 with `truth_status=unverified` (no source memory entry);
it is a recall hint, not additional verified evidence.
