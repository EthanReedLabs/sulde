# Guardian V3 性能与运行闭环

状态：性能批次 `ACCEPTED`；其中 PreToolUse 实机证据已被 2026-09-01 的新失败样本取代，
当前控制面验收见 `guardian-v3-pretool-fail-closed-report.md`。

基线：`dev@fe175c12affbc581a0aa7fc5c4a541ae6bd4f0c7`

任务分支：`task/guardian-v3-performance-closure`

## 目标

在不放松物质写入、原生人工决定、generation、一次性 grant 和恢复安全边界的前提下，
把可重探测诊断与非授权遥测移出成功热路径，并让状态、MCP、记忆、调度和“生命体”恢复
使用同一中立运行时与可验证数据面。

## 冻结验收矩阵

| ID | 验收项 | 完成证据 | Stop line |
|---|---|---|---|
| G3-P01 | 稳定 Hook 不为每次事件重复整套 adapter surface 摘要或启动第二个 Python 解释器 | 真实桥接测试、篡改反例、完整链路延迟样本 | 当前 generation 的密封入口仍拒绝 adapter 漂移 |
| G3-P02 | 只读与 Git 直通不执行逐事件 durable `fsync`；物质控制账本仍保持 durable | 热路径测试、落盘聚合读回、崩溃/安全回归 | 不允许异步化授权、dispatch、effect 或 terminal receipt |
| G3-P03 | 普通状态、幂等查询和 readiness 不随完整历史日志线性扫描或创建写锁 | 只读文件系统测试、历史规模反例、状态性能测试 | 深度完整性扫描保留为显式失败诊断 |
| G3-P04 | MCP 常驻进程内复用 KB/记忆读取依赖；失败时可显式降级 CLI | MCP 协议测试、模块复用计数、CLI 降级反例 | 构建、迁移及写事务继续使用单写者边界 |
| G3-P05 | Prompt 热路径不做 pending embedding 或重复记忆写入 | Hook 单测、数据库写者检查、积压 actor 读回 | 当前 prompt 必需的有界上下文召回可同步 |
| G3-P06 | readiness 使用真正只读 journal 投影；scheduler 的 observed/unobserved 不伪装 missing | 只读宿主测试、注入 probe 矩阵、doctor 读回 | 无可靠宿主进程证据时仍不得宣称 ready |
| G3-P07 | 输出、诊断与测试证据有界；失败才触发深诊断 | doctor/status 摘要测试、完整扫描入口测试 | 安全失败证据不得丢失或只记录成功文案 |
| G3-L01 | “生命体”升级当前代码、恢复监督器、恢复 lane、scheduler 与安装 generation 分层验收 | 当前 HEAD 测试、真实 actor/owner、安装读回、最终报告 | 历史 H03/H06 报告不得代替当前 generation 事实 |
| G3-R01 | 专项、交叉平面、全量、stage/release、真实新旧会话 canary 全部通过 | exact-HEAD 机器记录与最终报告 | 任一物质失败不允许合入或安装 |

## 明确保留

- Git 由 Agent、人和宿主原生授权处理，不进入 Guardian 策略、暂停或效果债务。
- 物质写入在执行前同步判定；外部和破坏性动作保持 fail-closed。
- 原生决定绑定 provider、session、task epoch、revision、目标、效果和一次性消费。
- `main` 不承载本次修改，仅作为已知回滚基线。

## 明确排除

- 不用降低模型推理档冒充控制面性能修复。
- 不以删除审计、关闭守卫、全局 bypass 或永久白名单换取速度。
- 不把历史合格报告、synthetic Hook 或安装器自报成功当作当前真实验收。
- 新发现仅在安全、数据损坏或本矩阵 blocker 时进入当前批次；其余登记为后继项。

## 验收状态

当前状态：性能目标保持 `ACCEPTED`；本节记录的是历史 generation 证据，不得继续作为当前
PreToolUse fail-closed 或新会话续接的验收凭据。

代码候选已完成以下机器验收：

- 最终全量：`Ran 1670 tests in 405.202s`，`OK (skipped=23)`；跳过项均为当前宿主不可执行的
  平台条件，不含本批次能力。
- Codex Hook 协议修复后的桥接、启动器、Windows、stage 与安装器回归：
  `Ran 114 tests in 188.631s`，`OK (skipped=2)`。
- 定向回归：`Ran 240 tests in 44.235s`，`OK (skipped=18)`。
- “生命体”独立矩阵：`Ran 205 tests in 55.328s`，`OK`。
- Codex POSIX 与 Windows 制品均完成确定性 staging：各 634 个文件、380 篇知识文档，
  runtime tree SHA-256 均为
  `58cdc18e37db5d2d4be3d5b0568904954292ae09d006686669133c8e660d7fcb`。
- 真实稳定 Hook 链路 40 次只读样本：中位数 `245.696 ms`、P95 `248.923 ms`、最大值
  `250.959 ms`；旧 Dev 制品中位数 `480.505 ms`、P95 `483.745 ms`，中位数/P95 均降低
  约 49%。
- MCP 同一常驻 server 的知识查询：首次 `559.861 ms`，随后为 `9.013 ms`、`8.755 ms`；
  旧实现连续调用为 `606.299 ms`、`552.949 ms`、`553.090 ms`，暖调用降低约 98%。
- exact code tree 为 `71f8c6ba830e29e741ac0f6f4b065f1288965ed5`；任务协议修复提交为
  `c16bb36`，Dev 代码合并提交为 `49dce0c2`，两者 tree 完全一致。
- 官方原子安装为 `0.2.5+codex.20260831025657`；generation 为
  `0.2.5+codex.20260831025657:58cdc18e37db5d2d4be3d5b0568904954292ae09d006686669133c8e660d7fcb`，
  activation ID 为 `80a8805c1a3b49ff832beba8f4da8d8b`。artifact 与 installed plugin
  逐文件一致，stable launcher spec 12 指向同一 runtime。
- Scheduler owner 为 active，16/16 managed actor loaded，failed/missing/retired labels 均为空。
- 已安装 MCP 的真实常驻协议调用：initialize `224.588 ms`，`kb_status` `0.193 ms`，首次
  `kb_search` `556.165 ms`，同进程暖查询 `12.872 ms`，均返回非错误结果。
- 新会话 `01a055c3-d569-7072-983e-3fb3ebe64838` 与安装前旧会话
  `01a055a4-5759-7d43-9c0d-dc1bce04f5ea` 的真实 canary 均为：Git exit 0；越界
  `touch` 在执行前被 PreToolUse 拒绝；marker 不存在；审计只有 started deny，没有对应
  PostToolUse 完成事件。
- canary session 在旧任务 contract 中保持 `workspace_discovery/review_required`，因此其
  per-task interactive doctor 不宣称 task-lane ready；这是禁止新会话隐式继承旧 objective
  的预期边界。宿主 supervision 已 `live_verified`，artifact/scheduler ready，effect debt、
  open event 和 pending verification 均为空。
- `main@265c5473fac6caf823ff9882e302b589d93840b6b` 未参与本次修改，既有 `.ua` 用户修改保留。

安装期间真实 canary 还发现并闭合了一项跨层缺陷：适配器虽然输出了正确的结构化 deny，
却同时返回 exit 2；Codex 将其视为 Hook 失败并继续执行工具。最终实现统一为“结构化 JSON
决策经 stdout 返回且进程成功退出”，并仅保留 exit 2 的 stderr-only 兼容语义。安装器、
POSIX/PowerShell 桥和测试契约均已同步。

## 沉淀候选

### 控制面成功热路径重复建立解释器与摘要面

证据状态：`verified`。

- 问题语境：每个 Hook 事件由稳定 launcher 启动 Python 后，再以 subprocess 启动 adapter，
  adapter 又启动 runtime，同时每次摘要整个 Hook surface，固定成本接近半秒。
- 路由正例：安装时密封完整 surface，事件时只校验 common、选中 adapter 与选中 runtime hook；
  同一受控解释器内执行 adapter/runtime。
- 路由反例：事件 A 的无关 adapter 漂移不得阻断事件 B；选中事件的任一密封文件漂移必须阻断。
- 执行正例：保留 stdio、argv、环境与超时语义，异常转换为原子 Hook 结果并恢复进程状态。
- 执行反例：删除完整安装校验、跳过选中文件摘要，或让异常污染后续常驻调用。

### 非物质观察与物质账本使用同一 durable 写策略

证据状态：`verified`。

- 问题语境：只读与 Git 直通观察也逐事件取锁、flush、fsync，成功热路径承担授权账本级成本。
- 路由正例：非授权、可丢失且可重探测的观察采用单次 O_APPEND；授权、dispatch、effect 与
  terminal receipt 继续 durable。
- 路由反例：不能因“都是日志”而把权限或效果真相异步化，也不能因审计存在就要求每条遥测 fsync。
- 执行正例：测试分别证明只读/Git 不取 durable lock、不 fsync，物质边界仍 fsync。
- 执行反例：全局关闭 fsync、删除账本，或将两类记录继续绑定同一热路径。

### 不可观察的 scheduler 被投影为全部缺失

证据状态：`verified`。

- 问题语境：受限宿主不能运行进程 probe 时，旧 doctor 把 unobserved 投影为 0 loaded 和全部 missing，
  产生确定性误报。
- 路由正例：unobserved 保持 degraded，但 `loaded=null`、`missing_labels=[]`、
  `missing_observed=false`；只有成功 probe 才计算 missing。
- 路由反例：不可观察不等于健康，也不等于全部丢失。
- 执行正例：只读 journal 不创建 recovery lock，现场进程证据由可观察宿主补全。
- 执行反例：doctor 为了读取而修复 journal，或用 Python 子进程失败覆盖真实 launchctl 状态。

### 结构化 Hook deny 与进程失败状态混用

证据状态：`verified`。

- 问题语境：策略与审计均给出 deny，但适配器同时输出结构化 JSON 并返回 exit 2；Codex
  把它视为 Hook 执行失败而继续运行原工具，造成“账本说拒绝、效果已经发生”。
- 路由正例：宿主支持结构化决策时，以 stdout JSON 和成功退出交付 allow/deny；仅在
  stderr-only 的非结构化兼容路径使用 exit 2。
- 路由反例：不能把策略判定的 deny 等同于 Hook 进程失败，也不能只看审计 action 判断
  宿主是否实际消费了决定。
- 执行正例：安装器与真实新旧会话同时验证 Git 正例、越界写反例、marker 不存在及无
  PostToolUse 完成事件。
- 执行反例：只测 adapter 返回内容、只测 exit code、只看 ledger deny，或用 synthetic
  Hook 替代真实宿主 canary。
