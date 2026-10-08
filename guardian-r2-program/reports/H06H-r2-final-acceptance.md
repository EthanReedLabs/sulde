# H06H R2 最终总纲验收候选报告

## 结果

H06I 已 accepted，本机 Codex 发布闭环与当前代码交付已完成；任务分支和 `dev` 均已推送远端。H06H 仍为 `system_verified`，不声明 production accepted 或 R2 program complete。最终生产源提交为 `920fd4c79ccc37971e2962ca2b27abd5d9a1d3ac`，正式安装 generation 为 `0.2.5+codex.20260828081159:efac6801160919fbbc4e7a638982b1c45e53efa7d6e83601acf1817a6ad6b46a`。真实 Claude live 与原生 Windows 作为非阻塞远端 follow-up 保留。

## 过程

✅ 完成检查：`PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v tests.test_r2_guardian_integration`，exit 0，`Ran 3 tests in 2.986s`，`OK`。其中组合用例串行调用 16 个 accepted public-boundary test，且要求零 failure、零 error、零 skip；另外对 incident、failure axis、authority、hard gate 与 synthetic live PASS 分别做真实红绿攻击。

✅ 完成检查：`PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v tests.test_human_grant tests.test_grant_broker tests.test_recovery_supervisor tests.test_resource_adapters tests.test_recovery_lane tests.test_agent_runtime tests.test_native_agent_broker tests.test_r2_guardian_integration`，exit 0，`Ran 198 tests in 46.036s`，`OK`。

✅ 完成检查：`git diff --check`，exit 0，无输出。

✅ 完成检查：`PYTHONDONTWRITEBYTECODE=1 python3 -B scripts/kb/run-isolated-tests.py tests.test_human_grant tests.test_grant_broker tests.test_recovery_supervisor tests.test_resource_adapters tests.test_recovery_lane tests.test_agent_runtime tests.test_native_agent_broker tests.test_r2_guardian_integration`，exit 0，最终 H06I + H06H 组合候选 `Ran 214 tests`、`OK`，且 quiet-window 运行没有 concurrent production-KB warning。

✅ 完成检查：`PYTHONDONTWRITEBYTECODE=1 /Users/eric/.claude/plugins/data/sulde-cc/kb/venv/bin/python -B -m unittest -v tests.test_intent_guardian tests.test_intervention tests.test_agent_runtime tests.test_native_decision_journal tests.test_operational_readiness tests.test_sulde_statusline tests.test_codex_plugin_install tests.test_stage_plugin tests.test_stage_release_inventory`，exit 0，`Ran 524 tests in 220.449s`，`OK (skipped=1)`；唯一 skip 为当前 macOS 无法执行的 native Windows PowerShell。该次运行观察到无关会话并发更新生产 KB，所以它仅作为代码绿证据，quiet-window 权威仍使用上面的 214-test 运行。

✅ 完成检查：`/Users/eric/.claude/plugins/data/sulde-cc/kb/venv/bin/python -B scripts/release/install_codex_plugin.py --json`，exit 0。official installer 把 source、stage、persistent artifact 与 installed cache 绑定为同一 generation；初始 `installed_degraded` 只表示 scheduler/live 尚待随后验收，不是安装失败。

✅ 完成检查：`/Users/eric/.codex/plugins/cache/sulde-local/sulde/0.2.5+codex.20260828081159/runtime/scripts/kb/install-agents.sh --runtime-root /Users/eric/.codex/plugins/cache/sulde-local/sulde/0.2.5+codex.20260828081159/runtime --provider codex --accept-llm-data-egress`，exit 0。live doctor 随后报告 scheduler `managed=15`、`loaded=15`、missing/failed/retired 均为空，generation 与 runtime tree 全部匹配。

✅ 完成检查：真实 `codex exec` 新会话 `01a04775-6b8b-79c3-a17a-89d25eefedcc` 在最终安装 generation 上执行精确只读 `git status --short --branch` 与 in-turn doctor，exit 0，返回 `R2_CODEX_LIVE_READY_CANARY_OK`。SessionStart、UserPrompt、PreToolUse、PostToolUse 均为 `live_verified`，host 为 `interactive_ready`，effect debt clear，native decision settled。该 canary 合同为 shadow 且没有 task lane，仅证明 live Hook/runtime readiness，不冒充 enforce-mode 写授权。

✅ 完成检查：`PYTHONDONTWRITEBYTECODE=1 /Users/eric/.claude/plugins/data/sulde-cc/kb/venv/bin/python -B -m unittest -v <five final-source installer rollback tests>`，exit 0，`Ran 5 tests in 52.089s`，`OK`。覆盖 installed-smoke rollback、launcher publish 进程死亡、rollback journal 进程死亡、native authority drift 与 partial legacy cache exact-artifact recovery；全部使用临时根，没有回滚或修改当前生产安装。

✅ 完成检查：任务分支 `task/r2-guardian-human-authority-lifeform` 已推送到 `origin`；`dev` 以 merge commit `72e9799` 集成任务分支。随后在 `dev` 实际合并树运行八模块组合回归，exit 0，`Ran 214 tests in 43.184s`，`OK`；运行 `tests.test_guardian_program tests.test_r2_guardian_integration`，exit 0，`Ran 64 tests in 3.393s`，`OK`。远端 `dev` 推送成功，Windows 可从任务分支或 `dev` 拉取完整树。

## 遇到的问题

先前协调运行错误地使用了 `r2-h06c-final-acceptance-fullclone` 中未跟踪的 H06C/H06D fixture/test；199/73 次绿测试不能证明 H06H。该问题已登记为 `FR2-H06H-003`，旧证据不得用于本候选验收。

本轮第一次 release-level 运行误用了不含 PyYAML 的 `/opt/homebrew` Python，使 `test_legacy_pre_gate_does_not_leave_phantom_guardian_event` 得到错误的零返回码；同一测试改用仓库正式 KB venv 后通过，随后 524-test matrix 全绿。该失败属于验证环境不完整，不是产品回归，失败输出保留为反证。

安装后的 deployment 文件仍保持 `installed_live_unverified` / `operational_ready=false` 的安装时快照，而 in-turn live doctor 已真实报告 scheduler ready 与 Codex Hook live；两者是不同时间点/权威域，不能用旧静态字段覆盖新的 live readback，也不能反过来篡改安装收据。

## 解决方式

从 accepted incident fixture、manifest 和生产公共边界重新生成 H06H v2 replay fixture 与集成测试。fixture 绑定 H06H task、精确 base、I01-I19、十三 failure axes、十四 hard gates，并将 live/Windows/installed 项保持为独立证据要求。

Amendment-010 只在测试局部作用域中移除并恢复 `SULDE_TEST_MODE`，闭合 isolated harness 对 production-path regression 的误投影；H06I 与 H06H 随后以 214 direct、214 quiet isolated 和 64 control tests 组合通过。发布阶段使用唯一 cachebuster、official installer、scheduler reconciliation 和新 Codex session，分别生成不可互相替代的 program evidence。

统一控制账本已记录 H06I `accepted`，并登记最终 `full_isolated_suite`、`installed_generation`、`scheduler_owner`、`live_host_canary_codex` 与 `rollback_evidence`。权威 final-check 当前只剩 H06H、Claude live 与 final traceability；H06C/H06D 为 append-only superseded predecessor，将由 H06H accepted 后吸收。

用户随后以 `SCOPE-FREEZE-AMENDMENT-011` 明确调整交付顺序：当前 Codex/macOS 代码、证据和安装闭环可以提交、合并到 `dev` 并推送；Windows 从远端完整任务分支自行修改/验收，Claude 等额度恢复后再验收，两者不再阻塞当前代码交付。该修订只改变交付排序，不把两项未验证事实改写为 PASS，也不允许提前声明 R2 production complete。

## 遗留风险与建议

真实 Claude live 当前因 Claude 额度不可用尚未执行；按冻结规则不得由 Codex、静态 fixture 或 synthetic callback 替代。原生 Windows PowerShell 当前宿主不可用；macOS 上 staged Windows artifact 测试通过但只能算制品验证，不能冒充 native Windows。两项都必须绑定当前 generation；完成后才能生成 `program-live-host-canary-claude.json`、把 native Windows artifact identity 写入新的 H06H `system_tests` 与 `program-final-traceability.json`，再将 H06H accepted、合并 dev/main 并完成 program。

Windows 续行入口：拉取 `origin/task/r2-guardian-human-authority-lifeform`，在原生 Windows 上运行 `python -B -m unittest -v tests.test_stage_plugin.StagePluginTests.test_windows_launchers_fall_back_from_broken_python3`，并记录测试提交、宿主/Python 身份、完整终态、staged Windows generation descriptor 及其 SHA-256。Windows 如需修复，应在自己的 follow-up branch 追加提交，不得改写当前已验收提交。

沉淀候选（evidence status: verified）：长测试终态与控制账本晋级曾依赖人工再次发送“继续”，导致测试已经 `OK` 但任务外观停住。正样本是测试进程终态后由协调器自动消费 exit/output、写入 scoped evidence、推进 task transition 并立即运行 final-check；反样本是只显示测试输出、不登记状态，或在不可用的 Claude/Windows 门前无限等待且不给出剩余门槛。路由应由统一控制边接管，执行仍严格区分可自动完成的本机门和必须由真实外部宿主完成的硬门。
