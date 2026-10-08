# Guardian V3 新会话续接验收报告

日期：2026-08-31；2026-09-01 增补

## 结论

Guardian V3 已增加同一任务的新 Codex 会话续接协议。新会话默认保持
`review_required`；只有当前会话展示的原生 Allow 被消费后，才绑定到当前
`intent revision` 与 `task_epoch`。该转换只继承任务目标、约束、验收标准和工作区
政策，不转移旧会话的 grant、批准回执、open event、pending verification、effect
debt、continuation token 或其他执行权限。

本轮继续验收又发现两个不能用旧结论掩盖的控制面缺陷，并已在最终 Dev 候选中修复：

1. 工作区内另一 session 的待决 proposal 被误当成所有 lane 的共同阻断条件，既污染当前
   已绑定任务的续接上下文，又把一个人工问题重复计为两个 readiness 阻断项。
2. 早期把执行前失守归因于统一 `functions.exec` 的外层 JavaScript 投影；后续真实宿主与
   官方源码验证推翻了该单一归因。Codex 会对内层 `exec_command` 独立触发 PreToolUse，
   真正缺陷是 Sulde adapter/launcher 把异常或空响应吞成成功空输出，令宿主继续执行。

修复后的规则是：proposal 按来源 lane 归属；外来 proposal 不再阻断已经 `bound` 的当前
任务 lane，但所属 `review_required` lane 仍保持一个、且仅一个人工阻断条件。统一执行器
静态投影保留为防御性兼容层；Codex 的主拦截证明改为内层 PreToolUse 的显式 Allow/Deny。
任一桥接层异常、空响应或畸形响应只允许只读与单条普通 Git 降级通过，物质/未知动作必须
结构化拒绝，不能降级成事后审计。

Windows bootstrap 的真实运行验收按人工决定转交 Windows 主机。本报告不把 macOS
模拟 Windows launcher 的结果声明为 Windows 通过，也不为模拟环境改写 Windows 行为。

## 决策与恢复边界

- 决策种类：`task-continuation`，只接受 `approve`；宿主 Deny 不执行控制命令，目标
  lane 因而保持只读 `review_required`。
- 决策主体绑定当前 contract、revision、task epoch、policy/proposal digest、material
  sequence、权限状态摘要、源/目标 lane、目标 prompt 和 task instance。
- Allow 复用既有 `PermissionRequest` 与 native decision journal；请求、卡片或世界状态
  漂移时 fail closed。
- Allow 提交后生成新的 lane continuation token，并写入
  `sulde-task-continuation-v1` 审计记录；记录固定
  `authority_transferred=false`。
- native journal 在 prepared、approval-decided 与提交边界崩溃后可恢复，且不会要求第二次
  人工决定。
- 升级兼容只迁移一种旧 lane：当前 task epoch、`source=approved_revision`、`state=bound`
  且 proposal digest 精确匹配当前已应用方案。任意其他
  `continuation_eligible=false` lane 仍不得成为续接源；未来 revision 创建时直接写入显式
  `continuation_eligible=true`。
- 发布 staging 与发布输入摘要显式包含拆分后的
  `intent_guardian_parts/intervention_control.py`，避免源码测试通过但制品缺模块。
- 工作区 proposal capsule 带有来源 provider/session。当前 `bound` lane 只抑制明确属于
  另一 session 的待决 capsule；来源缺失、摘要无效或 lane 尚未绑定时继续 fail closed。
- Codex 统一执行器的外层解析只在能静态证明唯一字面量 `exec_command` 或 `apply_patch` 时投影精确
  capability、target、path 与命令摘要；单一 Git 动作继续透传。动态参数、复合物质动作或
  未识别写入统一归类为 `unresolved_orchestrator_effect` 并在执行前硬拒绝，但该解析不是
  内层 Hook 的实机验收替代品，也不触发 destructive pause。

## 自动化证据

- Guardian 核心：223 项通过，18 项跳过。
- Native decision journal：65 项通过。
- 新增正反例覆盖：Allow 前写入拒绝、跨会话回执拒绝、Allow 后范围内写入通过、范围外
  写入拒绝、lane 摘要篡改拒绝、卡片世界漂移拒绝、崩溃恢复后精确提交。
- 官方隔离完整回归：1670 项执行；除一项 Windows 原生 launcher 模拟用例和当前系统
  Python 缺少可选 `numpy` 外，无其他失败。`test_rerank` 随后用已安装 Sulde venv 补跑
  3/3 通过。
- 真实 Codex CLI 0.151 合同与 staging 制品链路：通过，staged 635 files、verified 380
  corpus documents。
- 非 Windows bootstrap/launcher 回归：3/3 通过。
- 静态 Windows artifact、descriptor、scheduler transaction 合同测试：通过；真实 Windows
  bootstrap：待 Windows 主机验收。
- 本轮最终 exact-dev 集成门：405 项通过，18 项跳过，耗时 220.525 秒；覆盖 Guardian、
  resource projection、native decision journal、operational readiness、session continuity、
  release inventory 与 Codex 原子安装，POSIX staged 产物为 636 files、380 篇知识文档。
- 新增统一执行器正反例覆盖：单一字面量命令精确投影、字面量 `apply_patch` 投影、Git
  passthrough、动态命令 fail closed，以及真实负向 canary 的 exact digest、`pre_denied` 与
  finalize 约束。
- 新增并发 proposal 正反例覆盖：proposal 所属 `review_required` lane 保持
  `unsettled=1`；带有效来源证明的外来 proposal 不再让当前 `bound` lane degraded，也不被
  当前 lane 消费或清除。

第一次安装 generation `0.2.5+codex.20260831051315` 后，独立生产 contract 回读发现升级前
已批准的当前源 lane 带有旧默认值 `continuation_eligible=false`。该 generation 的事务安装
本身通过，但没有被当作新会话续接验收通过；随后在独立修复 worktree 增加上述窄迁移规则、
任意旧 bound lane 反例与未来 revision 正例，再进入下一次发布。

## 发布与实机会话证据

实现与兼容修复已合入 `dev`：

- 首次实现：`2220996`，合入提交 `ad0a939`。
- 旧批准 lane 窄迁移修复：`577d2bb`，合入提交 `d717b17`。
- 最终发布输入提交：`47e0e62`。
- 最终版本：`0.2.5+codex.20260831052525`。
- 最终 generation：
  `0.2.5+codex.20260831052525:2cdc4aae828ad694a0e845d2674a1471d11b6db74fef9265f67dbbdd23bfa65e`。
- scheduler activation id：`747140e130d748acbd2a1468a5381865`。

上述 generation 是首次续接协议的已安装基线。本轮继续验收修复形成新的 exact-dev 候选：

- lane-scoped proposal/readiness 与统一执行器 Pre 投影：`49ef509`。
- 新投影模块纳入 staging 与 release digest：`96a22a2`。
- 对应 Dev 合入提交：`64464e9`、`e2ddd3a`。

安装事务必须在本文和所有发布输入合入后重新密封 cachebuster 与树摘要；因此本文不预写尚未
发生的 generation、activation id 或 Hook 结果。最终值以安装器的
`deployment-generation.json`、runtime owner、真实 canary proof receipt 和本任务交付回读
为准，不能由这份静态报告预测。

原子安装成功；source staging、artifact 与 installed runtime 的 generation 摘要一致。Codex
插件列表显示 `sulde@sulde-local` 为 `installed, enabled`。deployment 状态为
`generation_verified`，runtime owner 状态为 `active`，两者均
`operational_ready=true`。真实 `launchctl` 进程投影为 16/16 loaded，
`failed_labels={}`，scheduler 状态为 `ready`。

兼容修复后的 exact-dev 集成门运行 362 项、全部通过、19 项跳过，覆盖 Guardian、native
decision journal、release inventory、plugin staging 与 Codex plugin install。最终 POSIX 和
Windows 静态 staging 各包含 635 个文件并验证 380 篇知识文档；两者 generation 摘要相同。

稳定 MCP 入口完成真实 initialize 与 `kb_status` 调用，server 为 `sulde-kb 0.2.0`。验收时
发现既有派生 `kb.db` 指纹与当前 380 篇 manifest 不一致；使用稳定 `kb-index build` 原子重建
后，索引指纹已一致，结果为 380 docs、1761 chunks、196 edges。该问题不属于 scheduler
故障；当前会话早于本 generation，未产生本 generation 的真实
`SessionStart/UserPromptSubmit`，因此交互健康投影仍如实标记为
`host_interactive_fresh/host_supervision_fresh` 未观测，不把后台 ready 冒充新会话 ready。

真实生产 contract 同时存在另一个会话创建的 revision 175 Community 导出提案。旧实现把它
错误注入当前已绑定 lane，并拒绝当前任务继续；本轮修复后它只阻断提案所属 lane，当前任务
lane 可继续，且当前 lane 不会替另一会话批准、拒绝或清除提案。

旧已安装 generation 上已执行一次真实统一执行器负向探针：精确 marker 命令实际返回 0，
marker 确实产生，gap 计数随之增加。这是对旧 Pre/Post 分裂缺陷的正面复现，不是通过证据；
测试 marker 随后已删除。新 generation 安装后必须用同一真实入口证明整次外层调用在
PreToolUse 被拒绝、没有内层 completed、marker 不存在，再由 finalize 清除同 session 缺口。

本报告仍不宣称真人正向续接 canary 已完成。它必须在不同 `CODEX_THREAD_ID` 的真实新 Codex
会话中展示一次 `task-continuation` 原生卡片，由人点击 Allow，并回读新 lane 为 `bound`、
产生新的 continuation token，同时确认没有旧 grant、approval receipt、open event、pending
verification 或 effect debt 被复制。同一 thread 的进程重启不构成该证据。

`main@265c5473fac6caf823ff9882e302b589d93840b6` 始终仅作为回滚基线，未被本任务修改。

## “生命体”批次结果

- 生命周期状态 `ready`，L2/L3/L4 均为 `ready`，evolution 状态为 `ready`。
- 当前 runtime、deployment、launcher 与 scheduler owner 均绑定最终 generation；调度进程
  16/16 ready，无失败 label。
- effect debt、open intervention 与 pending verification 的权威阻断数均为 0。
- 当前旧会话缺少新 generation 的交互 Hook 观测，故“后台生命体 ready”已闭合，但“新会话
  交互 ready”必须与上面的真人续接 canary 一起验收，不能由安装器或 synthetic smoke 代替。
- 本轮统一执行器修复属于交互监督边界，不改变生命周期调度能力的定义；发布新 generation
  后仍须重新回读 deployment、launcher、scheduler owner、16 个 actor、MCP 与真实 Hook，
  不得沿用上一 generation 的 ready 结论。

## Windows 主机交接

Windows 主机必须从同一 `dev` 提交构建 Windows artifact，并至少验证：bootstrap、原生
venv Python 解析、`kb-index`/MCP launcher、UTF-8 参数、scheduler 注册与回滚、安装后
generation readback。当前状态为 `pending_windows_native`；未获得这些原生证据前不得改写
为通过。
