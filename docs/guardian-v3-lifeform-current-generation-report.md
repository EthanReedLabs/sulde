# “生命体”升级当前代验收报告

状态：`ACCEPTED_CURRENT_CODEX_MACOS_GENERATION`

## 历史批次结论

“生命体”升级来自 `task/r2-guardian-human-authority-lifeform`，已通过 merge commits
`72e9799`、`7d5662a` 进入 Dev，当前 Dev 相对该任务分支没有遗失代码。

历史 H06H 报告的准确结论仍是：当时的 Codex/macOS 代码、安装与 live canary 已通过，
但真实 Claude live 与原生 Windows 仍是 follow-up，因此 H06H 只能标记
`system_verified`，不能追溯改写成 R2 production accepted。本报告不替代或覆盖那一历史事实。

## 当前代码代结果

当前任务从 `dev@fe175c12affbc581a0aa7fc5c4a541ae6bd4f0c7` 开始，并在包含本次 Guardian
性能与诊断修复的完整工作树上重新验证“生命体”边界：

- `agent_runtime`、`guardian_recovery`、`life_cycle`、`native_agent_broker`、
  `r2_guardian_integration`、`recovery_lane`、`recovery_supervisor`、
  `scheduler_entrypoints`、`sulde_supervisor`、`supervision_lifecycle_e2e`：
  `Ran 205 tests in 55.328s`，`OK`，零 skip。
- 同一最终候选的全量仓库测试：`Ran 1670 tests in 405.202s`，`OK (skipped=23)`。
- Codex POSIX/Windows staging 均为 634 文件、380 文档，runtime tree SHA-256 均为
  `58cdc18e37db5d2d4be3d5b0568904954292ae09d006686669133c8e660d7fcb`。

这些结果证明恢复监督器、恢复 lane、生命周期状态机、scheduler 入口、Agent runtime 与
原生 broker 在当前代码代没有被本次性能改造破坏。

## 安装终态门

当前 Codex/macOS generation 已完成以下安装终态验收：

- Dev exact code tree、POSIX/Windows staging、artifact、installed runtime 与 stable launcher
  指向 runtime tree `58cdc18e...`；正式版本为 `0.2.5+codex.20260831025657`。
- Runtime owner generation 为 `0.2.5+codex.20260831025657:58cdc18e...`，activation ID
  `80a8805c1a3b49ff832beba8f4da8d8b`，`operational_ready=true`。
- 16/16 managed actor 已加载，failed/missing/retired labels 为空；`com.sulde.life-cycle`
  `runs=1`、`last exit code=0`，最新日志为
  `LIFE CYCLE: READY L2=ready L3=ready L4=ready evolution=ready`。
- 新会话和安装前旧会话的真实 Hook canary 均为 Git 放行、越界写入执行前拒绝、marker
  未产生；installed MCP 的 initialize/status/search/暖查询均通过。
- `main@265c5473...` 未修改，既有 `.ua` 用户修改保持不动。

因此，“生命体”升级在当前 Codex/macOS 代码代、安装代和运行代的结论为接受；本结论覆盖
当前 generation 的 agent runtime、broker、recovery、scheduler 与 lifecycle 回归及现场运行，
不追溯扩大历史报告的宿主范围。

真实 Claude live 与原生 Windows 仍按历史 H06H 的宿主事实分别保留，不由 macOS/Codex
测试冒充；但它们不是本次“当前 Codex/macOS generation 是否安装可用”的阻塞项。
