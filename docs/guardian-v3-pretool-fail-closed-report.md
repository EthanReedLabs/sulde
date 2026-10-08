# Guardian V3 PreToolUse 失败关闭修复报告

日期：2026-09-01

状态：`IMPLEMENTED_PENDING_EXACT_HEAD_AND_LIVE_ACCEPTANCE`

## 结论

新会话续接协议本身成功绑定任务，但当前已安装 generation 的 Codex PreToolUse 桥在运行时
异常或返回空响应时会静默 `exit 0`。Codex 将空成功响应解释为无策略决定并继续执行工具，
所以越界 `touch` 已经落盘，Guardian 只能在 PostToolUse 形成
`task_scope_denied` gap。这是 Sulde 的确定性 fail-open 缺陷，不是“新会话不得继承旧执行
权限”的设计结果。

真实失败证据绑定：

- session：`01a05854-0c5b-7b53-86ed-ca89da202a48`；
- intent revision：14；
- exact dev：`2f89958320ba5b6fe30f26e3663f876552f87491`；
- marker：`/private/tmp/sulde-pre-execution-canary-66765ded2a0288845c1ce66b9959a679`；
- 结果：工具 exit 0，probe=`executed`，无 `started_event_id`，随后才有 PostToolUse gap；
- cachebuster/install grant 均未消费，故失败候选没有进入安装链。

失败 marker 在验收完成前保留为原始证据，不把清理动作伪装成未执行。

## 排除的错误方向

早期报告把失守归因于统一 `functions.exec` 外层 JavaScript 没有在 PreToolUse 被投影。该解释
不完整，不能继续作为根因：Codex 0.151 的真实宿主与官方源码都表明，Code Mode 内层
`exec_command` 会单独进入 PreToolUse；受控的真实 Codex 回环测试也成功消费了 Sulde 的
结构化 deny，marker 未产生。

`functions.exec` 静态投影仍保留为防御性兼容层，但它不是 Codex 嵌套工具执行前拦截的主
证明。验收权威必须是宿主实际消费内层 PreToolUse 决定、原工具未完成且 marker 不存在。

## 修复边界

三层 Codex 桥统一采用显式策略响应：

1. 共享 runtime 对 Codex 正常路径显式输出结构化 `allow` 或 `deny`；空 stdout 保留为基础
   设施失败信号。
2. 本地 adapter、稳定 launcher 与稳定 CLI 只有收到可校验的显式决定才接受成功。
   exception、非零退出、`exit 0 + empty`、畸形 JSON 或错误事件均进入降级分类。
3. 降级分类只放行已知只读工具和一条无 shell 组合符的普通 Git 命令；物质或未知动作输出
   结构化 deny 并以成功 Hook 响应返回，避免 Codex 把 Hook 进程失败误当成策略放行。
4. Git 仍由 Agent、人和宿主原生授权负责；这里的 Git 降级通道只保证 Guardian 自身故障时
   不接管 Git，不生成 Sulde grant、pause 或 effect debt。
5. `native_session_continuation` lane 在当前安装 generation 没有同 session 的密封负向
   canary proof 时，interactive readiness 必须保持 `unverified`。旧 generation proof、
   Hook inventory、synthetic callback 或 PostToolUse receipt 都不能满足该门禁。

POSIX 与 PowerShell bridge 保持同一协议。Windows 原生 bootstrap 与运行验收仍由 Windows
主机完成；macOS 上的静态 PowerShell 产物检查不会被写成 Windows 实机通过。

## 最终验收矩阵

以下各项全部完成后才能把本文状态改为 `ACCEPTED`：

- exact task HEAD：bridge、Guardian、readiness、stage、release inventory、installer 专项通过；
- exact dev merge HEAD：官方隔离全量与 release preflight 通过，工作树 clean；
- 新 cachebuster/install grant 分别只消费一次，source/artifact/installed runtime 三方同代；
- 安装结果保持 `operational_ready=false`，直到真实新 Codex session 完成当前 generation 的
  task-continuation Allow 与负向 canary；
- canary 在 PreToolUse 被拒绝、工具无 completed、marker 不存在、proof finalize 成功；
- 正向只读与普通 Git 仍通过，越界非 Git 写入拒绝且不创建 effect debt；
- scheduler owner、16 个 actor、launcher、MCP、effect debt 与 native pairing 独立回读；
- `main` 与用户既有修改保持不动；Windows native 仍明确标记为独立待验收。

## 原生 approval prefix 审计

真实 rollout 多次出现：调用方没有请求 `prefix_rule`、
`proposed_execpolicy_amendment=null`，宿主仍把完整命令保存为精确 approval prefix；读 Hook
清单和一次性 canary 都能复现。现有证据把它归类为 Codex 宿主/UI 的持久化行为，而不是
Sulde 扩权请求。Sulde 不自动编辑用户的 `~/.codex/rules/default.rules`；精确 continuation
命令还绑定 session/digest，重放会被 Sulde CAS 拒绝，但宿主规则残留仍需由 Codex 侧单独
修复或提供关闭“自动保存精确命令”的设置。

## 沉淀候选

### Hook 空成功响应把控制面异常转换为执行许可

证据状态：`verified`。

- 问题语境：多层 launcher 为保持宿主可用性，把 adapter exception、非零退出及空响应统一
  吞成 `exit 0 + empty`，物质动作因此绕过 PreToolUse。
- 路由正例：完整 runtime 明确返回 allow/deny；降级分类只允许只读与单条普通 Git。
- 路由反例：Hook inventory healthy、PostToolUse deny、receipt 或进程 exit 0 都不能证明宿主
  在执行前消费了策略。
- 执行正例：物质/未知动作在任一桥接层失败时返回结构化 deny，真实 marker 不存在。
- 执行反例：exception 后空输出、畸形输出透传、结构化 deny 搭配失败退出，或 synthetic
  callback 代替真实宿主 canary。

### 未请求的 exact approval prefix 被宿主持久化

证据状态：`verified_host_behavior_root_cause_inconclusive`。

- 问题语境：调用方未给 `prefix_rule`，宿主仍保存精确命令规则。
- 路由正例：Sulde 原生决定只消费 session/digest/revision 精确绑定，并把宿主规则视为外部
  授权面。
- 路由反例：不得因为 exact prefix 存在就视为 Sulde 已申请长期授权，也不得静默改写用户
  规则文件。
- 执行正例：审计 rollout 的原始请求与规则落盘事实，重放仍经 Sulde CAS 拒绝。
- 执行反例：自动删除用户规则、扩大 prefix、或把宿主持久化行为归因于 Guardian 策略。
