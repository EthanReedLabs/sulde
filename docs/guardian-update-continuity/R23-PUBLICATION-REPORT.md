# r23 — 唯一发布候选已验证，生产未安装

2026-10-07。冻结提交 f1b57fbd255fab2fd2e9ed038787bbd250b0cb50，
tree 2d4a15ef37f3b85bc60420ef82fbc1d214526666。
当前状态：唯一候选验证与 dev 合入准备经集中独立复核有界通过；不自称生产 ready。

## 1. 权限与实际修改

原生 handoff 回执 2d8600040b40c0f8454dd23367142344cc88d47d6e3f500c78f8440e1fdea8b7
将当前会话从 dev 合同切到任务 worktree，不继承执行权限。
r23 原生方案回执见 R23-PUBLICATION-TASK.md。Codex 密封 grant 消费一次，
独立内容 verifier 完成；此后才修改 Claude 源 manifest version。

- Codex：0.2.5+codex.20261007132614-423ac8f6e0。
- Claude：0.8.11。现役 Claude Sulde 仍 0.8.10，本候选没有覆盖旧缓存；
  版本无冲突仅限本机本次检查范围，不声称外部全局注册表唯一。
- 两个 manifest 的 JSON 除 version 外与 b320353 完全相同。
- 除本任务文档/runner 与两个版本字段，产品代码、测试、依赖无差异。
- runner 是可执行变动，不伪称 Markdown-only；经本轮真实执行验收。

## 2. 最终候选证据

运行 20261007T133247.744835Z，入口记录在
`.codex-agent/layered-r23/20261007T133247.744835Z/`。
Codex candidate `/private/tmp/sulde-s3c-r23-20261007T133247.744835Z/r23-posix`。

官方 prepare 2.174s，verify 24.263s，exit 0。
receipt SHA 58759804f0b9ecc0033f889766a4230e7c603d7b58cacf884dae4df78567d572。
runtime SHA c1856020660c0e4a4b2a9dcd09b2ea84c2cf217939b0e3efb3067a3e8f6aaaa3；
plugin tree SHA c5ba726182af86ca1cfccb79c95a15f38a7e53f233a6cce9da4f85029b70c4f2。
runtime 内容与 r22 相同；plugin manifest 版本已变，plugin tree 摘要相应改变。

实际 CLI app-server/unified exec：正例执行，普通计划外写入执行，破坏性负例
PreToolUse 拒绝且 marker 不存在，外部模型请求 0。
event ae981e33648a7b15cfe089d0，call candidate_native_2，
session 01a11691-4556-7482-9ce2-29b8b5273ebc，
proof da821d9eb8cd2a13a9dd1e7a53b1d72080f2aa5fbab12a70b0e3862fa1c63002。
loaded module generation df25fe7b0b7558218e27e9d8ceb76d0d2d59f0bebb0aae44da8f79c6ab4ff75e；
artifact generation 为新 Codex 版本加上述 runtime SHA，各自匹配，不要求两者相等。

Claude 官方 stage 0.510s，CLI strict validate 0.779s，success/strict true，851 文件；
identity 文件 SHA 0921e57694de0b99a7c355995d13ecebfede7ad2c2b29980c37963f6c96bcd57。
最终 Claude artifact 位于入口记录目录下的 claude-artifact/，没有正式注册。

替代边界未变化：candidate 合同 agent-policy，不是真人审批；native_permission_ui
78/unobserved、scheduler_host 79/unobserved、scheduler 仅隔离 dry-run；初始
hooks untrusted 与 doctor degraded 保留。不能据此宣称生产 native/launchd 已就绪。
deployment、Codex config、Claude registry/marketplaces 四个文件前后 SHA 一致，
仅证明四项，不外推整个 HOME 零变化。没有 promotion 消费。

## 3. L2 复用与过程失败

基线 b320353 全量 2961 passed、29 skipped、零失败，详见 R22 报告。
behavior-equivalence 实际 git diff 和两个 manifest JSON 比较通过；复用产品行为
全量结果，不把凭据 HEAD 重写为 f1b57fb，不将 skip 视为通过。
版本相关构建和实际入口已重新执行；没有重复全量。

保留两次失败：

- 20261007T133035.429041Z：prepare 成功，verify 11.489s 报 Operation not permitted；
  与外层沙盒限制一致，未证明更低层归因，未 promote。
- 20261007T133123.797720Z：prepare 调用 codex plugin list 30s 超时；独立只读
  复查 exit 0 后同冻结输入再次 prepare/verify 成功。超时低层原因未证明，
  不将其升级为已修复产品缺陷。
- 首次 helper 的 env 包装分类缺口及恢复详见任务文件；原 Pre/Post 未改写，
  正式密封调用和独立验证是不同事件，不把前次 unknown 追认为 grant 消费。

## 4. 归档与剩余边界

Optimus `Sulde/tasks/guardian-unified-plan-20261004/S3-C-repair/r23-publication-20261007T133335.836883Z/`，
61 文件回读一致，自排除 manifest SHA
b1aa9533f7dced18aed38a9018d062be8695895adcfcb255b4d6b5646dfbe786。
未复制生产凭据或整个 HOME，r22 全量仍引用原唯一归档。

本轮未合 dev/main、未推送、未安装两宿主、未杀用户进程。
下一步：集中独立复核通过后，在新的明确范围内合 dev，冻结 L3 维护 plan/bundle、
新旧版本、cohort 与恢复资产，通过原生维护确认后执行。源码发布件、维护执行器、
真实宿主证明必须分别绑定；Claude 官方安装/恢复仍单独核验。

发布顺序约束：安装器严格比较 receipt.source.commit/tree 与执行源码 HEAD/tree
（install_codex_plugin.py 的 _validated_candidate_receipt），即使仅报告提交也不能
沿用旧 receipt 直接 promote。最短序列是本轮报告提交和获准的 dev 合入先完成，
冻结最终 HEAD 后官方 prepare/verify 一次；随后只把验收事实写到外部证据目录，
安装前不再提交报告或刷新版本。此处是工件身份重绑定，不重跑等价源码全量。

集中独立复核已回读：manifest 等价、receipt 自摘要、Codex 工件/双身份、
Claude 851 文件、Optimus 61 文件、两次失败及四项生产文件摘要。结论为
unique candidate verified / dev merge preparation passed。复核指出的三项
报告精度问题已按上文收紧。真正合入仍需本轮文档提交 clean 和新的合入范围；
最终 receipt 及 L3 前置不可省略。
