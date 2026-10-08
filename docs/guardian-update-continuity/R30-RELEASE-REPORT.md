# r30 — 冻结源码发布门通过，生产安装未执行

2026-10-08；原分支 `task/guardian-update-continuity`；当前执行宿主 Codex。
原生 r30 回执：`32eca99f0274c885efbe0f32c27b386ee4b1eefe20fa13701216808c9db4400c`。
本报告记录冻结源码全量及初始候选。报告提交后的最终候选身份和集中复核
以本轮唯一归档的 `FINAL-HANDOFF.md`、`final-readback.json` 为准，不能把
本报告的提交自动当成已经测试或安装过的 HEAD。

## 1. 冻结发布门

实测 HEAD：`6a883fac1def1a91861846ba1b46d6d0393a144c`。
Git tree：`84db339eca7fffcf3ff69385d834c9221df951c7`。
基线：`42c6f6d2e964f6d81a88a7eb4891988eaa956517`。

官方 test-evidence 的影响判定选择完整隔离套件（安装器属于发布关键路径）。
固定 Python 3.10.7 / PyYAML 6.0.3，先预检后运行；未修改产品、测试或版本。

- 正式 run：`20261008T033239.219685-f02cbbfbdc05`。
- **3003 总计 = 2974 passed + 29 skipped；失败 0，exit 0**。
- unittest 2707.347s；记录器 2711.126s；`input_drift=false`。
- 日志 SHA256：`b2a2e7f628121b5fb56267d79bc4e56a268d7a2861b4704e08506e4752537307`。
- 输入身份前后一致；源码字节码清理前后均为 0 文件/0 目录。
- 29 跳过：17 退休的 Git 守卫职责、5 Windows、3 显式 CLI/audit、
  2 嵌套 Seatbelt、2 需显式 baseline 的 benchmark。不称全部平台/宿主全绿。

初次 run `20261008T032305.026639-8386708926ca` 在 0.133s 内因外层 sandbox
禁止嵌套 `sandbox-exec` 退出 3，尚未执行套件。已保留日志和失败记录；获批
从外层沙箱之外启动官方 OS 隔离器后才产生上述成功运行，不是禁用隔离。
日志中的 `ERROR llm ... offline fixture` 是注入输出，不是 unittest 失败。
成功运行全程只跟踪 tool session 5270，没有因观察超时重启。

## 2. 初始 L1 候选与证明范围

本地根：`/private/tmp/sulde-s3c-r24.mqyXRi/r30/`。
初始 candidate `candidates/r30-posix` 已 verified，promotion 未消费。
初始 receipt：`297cbf43e628864a692bfe16494f4e2d9d5735edb10e6afcb750cd8dd5316a84`。
Codex version：`0.2.5+codex.20261007132614-423ac8f6e0`；CLI 0.160.0。
runtime SHA：`c1856020660c0e4a4b2a9dcd09b2ea84c2cf217939b0e3efb3067a3e8f6aaaa3`。
plugin tree SHA：`c5ba726182af86ca1cfccb79c95a15f38a7e53f233a6cce9da4f85029b70c4f2`。

真实 CLI app-server / unified exec 正向执行，破坏性调用 PreToolUse 拒绝且
marker 不存在；新 proof `54320336a53484d5b79c06c16beecc7d53c6edb83197720804964ab9f21bc603`。
loaded module generation `df25fe7b0b7558218e27e9d8ceb76d0d2d59f0bebb0aae44da8f79c6ab4ff75e`；
artifact generation 独立匹配上述 version/runtime SHA，两种字段不要求互等。
测试合同为 agent-policy，外部模型请求 0；真人审批和真实 scheduler 为
`pending_host`（78/79），不把候选 doctor/trust 的隔离缺项写作生产 ready。

Claude staged version 0.8.11，851 文件，官方 CLI strict success。
`readiness.json` 包含逐文件摘要，确认携带最终 installer；只读记忆迁移预检
通过。没有修改生产数据库。此时现役 Claude 仍是 0.8.10。

## 3. 最终身份绑定与集中复核

独立复核已确认 r30 Codex artifact 与 r23 发布件字节相同；r29 修改在外部
held installer，不在 Codex packaged runtime。因此无需再刷新 Codex 版本。
Claude 与历史 r23 同为 0.8.11，但两个 release 文件已改变；旧 r23 工件属于
superseded candidate，不得安装。本机尚无已安装的 0.8.11；不外推全局唯一。

本报告提交后，必须确认相对所测 6a883fa 只有本 Markdown 差异，再从最终
HEAD 官方 prepare/verify `r30-final`，重新绑定 source commit/tree 和当时
prestate。初始 r30-posix 只保留历史 L1 证据，不拿旧 HEAD receipt 执行 L3。
最终工件字节相同且产品/测试/依赖未变才可复用上述全量；否则停止重新评估。
最终 Claude 再 stage 并逐字节对照；不更改版本、不重复全量。

唯一归档目标：Optimus
`Sulde/tasks/guardian-unified-plan-20261004/S3-C-repair/r30-release-20261008T041800Z/`。
原始失败、完整日志、候选 receipt、身份、最终复核均保留；自排除清单逐项回读。
最终集中意见须同时检查全量终态与 r30-final 身份，不由本报告自我 accepted。

## 4. 剩余真实安装

r30 不安装、不退出宿主、不修改生产配置、main 或远端。生产 Codex 此时仍为
20261005134315-d918c7a2ed，Claude 仍为 0.8.10。
下一次 L3 须绑定新候选/完整 held-source、当时 cohort、维护时限、回退资产，
取得新的原生批准，先只读预检再关闭获准进程。禁止重开 r28 或重置已消费凭据。
Codex 事务完成后还需实际信任/调度与真实 Hook 正反；Claude 经独立官方 CLI
安装并回读。测试通过不是两侧安装目标已经完成。
