# Sulde 意图监督闭环

## 目标

意图监督器解决的不是“再写一条更强的提示词”，而是把人和 Agent 的共同理解变成一份
可修订、可暂停、可验收的运行时契约，并把可观察执行串成同一条谱系：

`intent → Skill → MCP/tool → side effect → evidence`

监督器只处理可观察边界，不声称读取模型隐藏思维。它会观察用户纠正、Skill 生命周期、
MCP/工具调用、文件或外部副作用和验证证据；无法观察或证据不足时明确记为
`inconclusive`，不伪造“已对齐”。

## 核心状态

每个工作区默认只有一份活动契约：

```text
$SULDE_KB_HOME/intent/workspaces/<workspace-key>.active.json
```

Claude Code 与 Codex 在同一工作区读写这份真值。宿主、原生会话 ID、事件参数摘要和
Skill 栈仍分别标记；跨进程写入使用同一排他锁与原子替换，避免两个宿主同时工作时丢失
事件或相互继承 Skill。

契约包含：

- 目标、原因和可观察完成标准；
- 必须保留、明确拒绝、冻结和允许修改的范围；
- 本地写入、外部写入与破坏性动作权限；
- Skill 与 MCP server/tool 的允许/拒绝范围；
- 当前修订、运行模式、暂停原因和连续纠正计数；
- 未完成调用、待验证副作用、已验证证据和审查器检查点。

意图契约状态只有 `active`、`paused`、`closed`。暂停是真实持久状态：只允许读取、澄清和
受控控制面动作，不能用一条新提示假装已经恢复。外部操作结果不确定不会复用这个全局
`paused`；它有独立的 effect/intervention 事实源，避免一次远端回调丢失冻结其他宿主或
污染意图修订。

每次意图 revision 都生成独立 `task_epoch`，每份已加载 Hook 代码都有
`runtime_generation`。旧 generation 发出的 PreToolUse 可以在同 provider/session、原生
`call_id` 与物质语义唯一匹配时由新 generation 的 PostToolUse 闭合；旧 task epoch 的 Skill、
read/open-event 不会恢复进新任务。历史 unknown 与验证债务仍保留在报告的 historical 区，
但只阻断同一目标或显式依赖链，不再冻结无关任务。

每份 contract 旁边还有可恢复工件：

```text
<contract-stem>.interventions.jsonl  # append-only 权威事实
<contract-stem>.interventions.json   # 可删除、可重放的投影
<contract-stem>.corrections.jsonl    # 用户/Agent 纠正的 append-only 状态机
<contract-stem>.approvals.jsonl      # 人工问题/决定的 append-only 配对事实
```

七类真值不得互相替代：

| 真值 | 回答的问题 |
|---|---|
| IntentContract | 人授权了什么、语义是否漂移 |
| EffectAttempt | 这一笔外部操作已派发、待验证、成功、失败还是 unknown |
| Effect Intervention | 哪个 unknown 正等待人裁决，裁决证据是什么 |
| Correction Intervention | 哪项纠正已提出、排队、到达安全边界或无法支持 |
| Approval Pair / DecisionRequest | 人工决定是否回答了唯一、先前可见且仍有效的工作区问题 |
| L3 task/run | provider 正运行、意图暂停、待人工、可恢复还是终止 |
| Observation | 上述事实的只读、脱敏公共投影 |

EffectAttempt 的正常路径是
`authorized → dispatched → accepted → verifying → system_verified`。失败回调、缺失回调、
进程崩溃窗口或回合结束仍未独立验证都会进入 `unknown`。人工证明成功记录为
`human_attested_success`，不会伪装成 `system_verified`；人工确认失败记录为
`confirmed_failed`。旧 attempt 永不改写成一次新执行。

## 三种模式

| 模式 | 行为 | 用途 |
|---|---|---|
| `off` | 记录最小状态，不阻断 | 故障隔离 |
| `shadow` | 可逆本地越界只记录 `would_action=deny`；破坏性、密钥外发和未确认主观意图仍硬阻断，普通未知能力降级观察 | 首轮标定误报率，同时保留安全底线 |
| `enforce` | 对确定性越界即时拒绝并按需暂停 | 人确认意图后的执行 |

默认先用 `shadow` 观察，再把经确认的主观任务或高风险任务切到 `enforce`；`shadow` 不是
外部副作用的放行开关。主观编辑任务在意图镜像获确认前只允许读取和澄清。确定性监督不
产生额外模型调用。语义审查是独立 opt-in：启用前必须说明它会在本地密钥扫描后，把改动
片段发送给当前 provider 并产生额外调用。启用后也只有
在命中明确约束、置信度达到契约门槛且给出具体证据时才暂停；单个异常或风格建议不能自动
改写计划。

## 运行闭环

1. `UserPromptSubmit` 为工作区建立影子契约，并注入当前目标、修订和契约路径。
2. Agent 用不超过七个字段生成自然语言决策卡：目标、原因、保护项、拒绝项、自由度、
   验收方式和未决点；hash、内部 JSON 和权限枚举不作为人工阅读界面。
3. Agent 负责机械建档：没有活动契约时直接用 `prepare-proposal` 自动创建不授予权限的
   shadow 占位契约并冻结提案，不再要求用户复制 `create`、`activate` 命令。提案不改变
   活动权限。命令同时输出给人的 `decision_card` 和仅供机器校验的
   `technical_binding`/`digest_bound_contract`；未来新增权限字段仍必须进入卡片或被明确
   标为技术详情，不能藏在 hash 后面。人工路由还会同时冻结一个 digest 绑定的续接包：
   最多保留小段可见用户/Agent 对话和原会话只读引用，不复制隐藏推理、工具结果、批准回执
   或权限。
4. 系统按两条通道分流：
   - **人工决断**：人只阅读自然语言卡片。Codex 由 Agent 在当前对话发起原生
     `PermissionRequest` Allow/Deny 确认框，人按一次 Enter/Allow 或 Deny；无需回复固定短语、
     复制摘要/指纹/命令或打开额外终端。其他提供方只有在存在可验证的宿主原生决策面时
     才能完成同类授权；否则提案保持 pending，聊天中的固定短语不产生权限。系统把选择
     绑定到工作区唯一的当前提案，64 位 digest 只在后台防篡改。
   - **Agent 决断**：允许确定性、低风险、仅本地读写、路径明确、可回滚、无持续费用、
     无未决项且不扩大权限的提案；也允许完全落入已登记、宿主本地、一次性、摘要绑定、
     可回滚并有专用独立验证器的中风险机械续行链。Agent 必须提交理由和证据，记录为
     `agent-policy`，不能伪装成 `human`。主观表达、公开/新受众、任意外部效果、破坏性、
     费用、语义 critic 或 unknown 自动转人工。
     CI/发布配置、宿主规则、Hook/Skill、Guardian 自身和密钥路径也固定转人工；L3 子 Agent
     不能创建这类授权。
   - **无人值守分流**：默认 `--unattended-policy agent-if-eligible` 会在展示人工框之前运行
     完整 Agent 门禁；通过则直接进入 `agent-policy`，不制造一个等人点击的
     `PermissionRequest`。一旦人工框已经展示，五分钟只表示“需要重新评估/提醒”，不能把
     沉默解释为同意，因为当前 Hook 没有可验证的最终 Deny/Timeout 回调。人工问题在卡片和
     world-state 仍匹配时保留 24 小时；超过 24 小时的点击返回 `approval_expired`，必须重建
     新问题。需要无条件等人的任务显式使用 `--unattended-policy wait`。
   初始意图镜像使用同一机制：Codex 继续使用原生 Allow/Deny；其他宿主若没有可验证的
   原生决策面则保持 pending，不回退到固定文本。原生确认后 shadow 才升级为 enforce，
   拒绝则暂停并要求新提案。
5. 人工通道的宿主控制入口先写入一次性批准回执，Agent 才能应用同一文件；Agent 通道在
   应用前重新运行资格门禁。内容、基线修订、工作区或当前提案变化即拒绝。Codex 使用两段式
   证明：`PermissionRequest` 先记录逐字匹配的可读问题并把最终选择留给宿主 UI；只有用户
   Allow 后，受保护的 `native-decision` 才会运行、消费同一 request 并直接完成状态迁移。
   用户 Deny 时命令不运行，也不产生批准回执。Agent 调用 `approve-proposal`、`resume` 或 `activate` 试图制造人工
   决定时仍会被当作自授权阻断；`approve-event` 已退役，旧的“批准事件 + 摘要”只记迁移
   提示，不产生权限。匹配回执已经存在后，应用提案、执行可读任务范围内的动作、执行已选择
   的干预状态迁移属于 Agent/Hook/监督器的机械职责。
6. 每个 Skill、MCP 和工具调用在开始/完成边界写入审计；Skill 指令文件可读时同时记录
   内容摘要。被禁止的 Skill、超范围写入、
   未知 MCP 副作用、外部写入和破坏性动作在执行前判定。普通 unknown 若没有越界、泄密或
   破坏性信号，按 `degraded_observe` 继续并记观察缺口；无法解析的写目标仍失败闭锁。
7. 权限来自可读的任务级范围，不来自事件摘要。已经声明的可逆 MCP/外部效果由
   Agent/Hook/监督器直接派发并立即进入证据账本；范围扩大、公开/新受众、费用、密钥外发、
   破坏性或主观选择才要求人在对话中决断。专用 profile 可进一步密封确定性后置条件，不再
   要求人复制摘要、回车或充当执行按钮。当前有两条预先封闭的机械续行通道：
   - 本地 Sulde `memory_annotate` 仅在当前契约已有本地写权限、`extracted_by` 等于当前宿主、
     每批 1–3 条关系且最多 6 个实体、所有关系端点都在本批实体内、置信度有效并存在可独立
     证明的关系后置条件时按 `local_write` 走固定系统策略；每个意图 revision 最多消费 3 次。
     任一条件不满足都保持普通 MCP 写入分类，不能借“本机 server”名义降级。
   - 插件维护等已登记动作必须先作为自然语言“自动续行动作”出现在可读决策卡，并同时冻结
     验收项摘要、效果类型、精确目标、解释器/Codex/脚本/工作树摘要、artifact 与安装根、
     最大次数、回滚和机器验证器。当前仅支持同卡、各一次的官方 cachebuster helper 与事务化
     Codex 插件重装；安装 grant 预先绑定 helper 完成后的未来 manifest/工作树。整条链满足
     Agent 门禁时可由 `agent-policy` 决断；若它与源代码修改、公开传播或其他未密封效果混合，
     仍由人确认高层语义。顺序颠倒、摘要漂移或缺独立验证必须失败闭锁并生成新提案或修复，
     不能靠一次人工回车降级放行，也不得降级为一般本地写权限。
   意图、方案和真正未知事实的问题绑定工作区、revision 和不可变卡片；事件摘要只用于审计
   配对。批准或续行 grant 都只消费一次，不能复用到另一个参数。人工批准必须先有
   `approval.asked`，随后由
   同一 lane 的真实控制 prompt 写入唯一 `approval.decided`；没有问题、重复决定或跨宿主
   回答都会失败闭锁。公开传播、新受众、费用、密钥、破坏性、范围扩大和不可独立验真的效果
   永远不进入续行通道。
8. MCP/外部写入完成后产生验证债务。独立读取必须同时匹配 provider/session、目标和能力
   家族，并证明写前生成的具体后置条件：内容/关系使用稳定摘要精确匹配，create 需要读取
   返回非空对象证据；空列表、not-found 文本或仅 success 状态不能证明存在。无法表达后置
   条件的能力保持未验证。同目标有多个候选 attempt 时，
   必须显式携带 attempt identity，不能批量误消债。仅有“读取调用成功”不能清债。
   对可解析的单分支 Git push，守卫把远端身份摘要、目标 `refs/heads/*` 和推送前本地 OID
   冻结为类型化后置条件；完成回调仍只进入 verifying，随后独立 `git ls-remote` 必须返回
   同一 ref 与同一 OID 才能 system_verified。多 ref、删除、tag、无法解析 upstream 或读取
   结果不一致时继续保持 unknown，不用“命令退出 0”代替远端事实。
   本地 Sulde `memory_annotate` 按生产中的 `entities[] / edges[]` 契约冻结整批后置条件，审计只保留
   匿名摘要；PostToolUse 之后用独立只读 SQLite 连接核对每个实体的 name/type，以及每条关系的
   src/rel/dst、entry_id、extracted_by 和 confidence。全部吻合才自动标记 `system_verified`，
   数据库不可读、结构不符或任一字段不一致都保留验证债务。
   一次性 Codex 重装完成后也不采信退出码、安装器自报或 PostToolUse 是否带回 stdout：守卫
   从 grant 重新定位 artifact，通过绑定的 Codex 可执行文件读取已启用插件及安装路径，再计算
   artifact 与安装缓存整树摘要、读取插件版本与全局规则并验证稳定 launcher；全部一致才由
   专用 verifier 清债。Pre/Post 指纹因插件热更新而变化时，仅在 provider、session、原生
   `call_id`、能力、效果、目标及验证摘要唯一匹配时接续原 attempt；不能用同 ID 跨 lane 劫持。
   `memory_graph` 的生产返回字段 `src/rel/dst` 同样可生成关系证据，不再依赖测试专用的
   `subject/predicate/object` 形状。
   工具返回 `success` 只进入 `verifying`。失败、缺回调、回合终止或崩溃恢复进入
   `unknown`，创建持久 intervention inbox 和尽力而为的系统通知。下一安全边界先重跑已登记
   的本地 verifier；能证明就由系统自动清债，仍不能证明才请人提供外部事实，不请人批准一条
   系统已经决定要执行的命令。
9. 同一目标或显式依赖链存在已派发、待验证或 unknown attempt 时，读取仍允许，依赖它的
   新物质写入在下一个安全边界被阻断；无关目标可继续。这不是语义暂停，不增加 intent
   revision，也不干扰其他 provider/session 或新 task epoch。系统在宿主对话中呈现可读
   干预卡，人选择：人工证明成功、确认失败、
   仅复查、授权一次重试或终止；Hook 原子记录回执并执行状态迁移。重试授权只消费一次，
   并创建链接旧证据的新 attempt。外部 CLI 仅作宿主内通道失效时的 break-glass。
   一个历史兼容边界是：已 `abort` 的 keyless Figma `use_figma` attempt（以及同一来源后来
   使用的精确 `[unresolved-figma-target]` 合成身份）仍保留为 unknown/quarantine，但较晚
   intent revision 中具有不同 sealed operation fingerprint、且未显式依赖旧 attempt 的
   `use_figma` 不再把该占位记录当成整个 Figma 域的通配 blocker。缺少 lineage、复用旧
   operation、未 abort、同 revision 或任何真实 file/node typed identity 仍按同资源 fail closed。
   有一个更窄的机器补偿例外：新的 `codex-plugin-install-v1` 必须来自当前契约的一次性、
   摘要绑定 grant，旧 attempt 必须是同 provider/session、同目标、同 profile 且仍有开放
   intervention 的 `unknown`。新 attempt 会显式记录 `compensates_attempt_id`；只有它自己的
   专用 verifier 独立读回精确安装后，旧 intervention 才追加 `system_compensated`，旧
   attempt 本身仍保持 `unknown`。新安装失败、回调丢失、摘要漂移或证据不完整时，两笔债务
   都保持开放；不同目标、普通外部写入或人工 retry 不能借用该通道。
10. 本地产物按契约节奏交给只读语义审查器；出境前先做密钥扫描。高置信且有证据的漂移
   才暂停。审查器会本地检索结构化沉淀，只把 `applicability=apply` 且证据已确认的
   适用边界、路由正反例和执行正反例加入审查上下文；`skip/inconclusive` 不作为建议，
   意图契约始终高于知识样本。
11. 连续纠正达到阈值时停止盲改，保留最近认可结果，输出“已确认／已拒绝／当前误解／下一
   决策”。这类暂停不能只说“继续”恢复，必须由人批准并应用新的意图提案。
12. 每项真实用户纠正按
   `proposed → queued → applied | rejected | unsupported | cancelled` 落入独立账本。
   `queued` 在真正出现同一 provider/session 的 PreToolUse、Stop 或受管运行中断边界前不
   会消失；另一宿主或会话不能代为消费。`applied` 只证明控制动作到达可观察边界，不证明
   模型已理解，也不证明结果符合预期，语义验收始终保持 `unknown` 直到后续可见结果由人
   或确定性验收判断。受管 L3 收到纠正后先持久化暂停，再终止完整进程树并闭合 RunHandle。

## Skill 与 MCP 监督边界

| 场景 | Skill | MCP / 工具 | 失败闭合 |
|---|---|---|---|
| Claude 交互 | 原生 `Skill` 工具的 Pre/Post 事件 | 全匹配 Pre/Post hook | `PostToolUseFailure` + `Stop` |
| Codex 交互 | `skill-start` / `skill-end` 显式登记 | 插件 Pre/Post hook；宿主实际支持的工具均接入 | `Stop` 回收缺失完成事件 |
| Claude L3 | provider stream 中的原生 Skill 事件 | provider stream + worktree 基线 | stream 完成/失败事件；终态仍有开放事件即失败 |
| Codex L3 | 执行 prompt 强制显式登记，由父监督进程从 provider stream 裁决；子进程不能改权威契约 | provider JSON stream + worktree 基线 | 同上 |

Codex 的原生 Skill 生命周期目前不能作为稳定插件事件依赖，因此不伪称“自动看见所有
Skill”；每轮注入会给出带契约和会话 ID 的登记命令。Codex 对部分内置工具的 hook 覆盖
也由宿主实现决定，L3 以 provider stream、文件快照和终态验收补强。监督器永远不声称
观察隐藏推理。

## 批准回执与宿主健康

聊天里的批准文字不是授权真值，持久化且成对的问题/决定与一次性回执才是。配对账本只保留
`request_id`、intent/target/card/workspace/proposal/lane 摘要、route、状态、过期时间和
回执摘要，不保存用户 prompt、目标原文、卡片正文或 session 原文；回执绑定 `intent_id`、revision、
workspace、provider、native session、action 和 target；应用提案时消费一次，不能跨
工作区或修订复用。审计只保留控制摘要和回执，不保存原始 prompt。

SessionStart 从当前契约或不可变提案重新渲染卡片，并核对其摘要后恢复同一个开放
DecisionRequest；`authority_transferred=false` 是硬不变量。`current` 别名只有在恰好一个
有效问题与当前工作区/提案相符时才可解析。零个问题时系统先重建问题并展示卡片，本次回复
不产生权限；多个、过期、已被新方案取代或串工作区的问题均拒绝。网络抖动导致同一答案
重复送达时返回原决定，不追加第二份回执/提案裁决；与既有结果相反的重复答案仍失败闭锁。

人工确认使用两套独立时钟：`reassess_at=asked_at+5m` 只驱动可观测性和重新评估，
`expires_at=asked_at+24h` 才终止这一次可决断问题。五分钟后没有回调时状态为
`host_outcome_unobserved`，绝不产生 receipt、权限或状态迁移；仍在 24 小时内的晚到 Allow
可在重新校验 card、revision、workspace 和效果债务后幂等执行。若方案已被 Agent 完成、
已经被新提案替代或世界状态漂移，晚到点击分别返回 `already_agent_decided` 或
`superseded`，不会复用旧权限。若 proposal 已被替代，或 effect-intervention 已由权威效果
账本结算，下一次 Guardian/UserPrompt/SessionStart 边界会把对应的未决问题精确记为
`cancelled`；仍有开放权威目标的问题保持不变。清理器先读取问题快照、再读取权威目标，
并发到达的真实人工决定优先，绝不会被 `cancelled` 覆盖。

Codex adapter 新增独立 `PermissionRequest` 边界。它只处理结构完整的 `native-decision`；
普通工具批准保持 Codex 默认行为。说明文字、provider、native session、contract、决策类型
或目标不匹配时失败闭合；匹配时 Hook 不返回 allow，而是保持静默，让 Codex 自己展示
Allow/Deny。`dontAsk`、`bypassPermissions` 与 plan 模式不能证明交互选择，因此固定拒绝。
安装器只能证明 `synthetic_smoke` 接线，不能制造真人批准；synthetic receipt 会被保留用于
诊断，但 `apply-proposal` 明确拒绝消费它。

新 Codex 会话默认建立独立合同，不因工作区相同就加入旧任务。续接旧任务时，Agent 显式执行
`prepare-task-continuation <source-contract> --contract <current-contract> --provider codex
--session-id <current-session>`，在当前合同保存只读审查引用，源合同和路由保持不变。
来源必须是同一物理工作区的精确合同；当前已确认任务或未决物质状态不能被静默替换。
已有同合同 `review_required` lane 的旧入口保持兼容。
随后 Agent 使用 `native-decision-preview task-continuation --decision approve` 展示选定的
任务目标、约束、验收标准、目标 session、revision 与 `task_epoch`。Allow 只把该新 session
绑定到这一任务世界；Deny 保持只读。该事务不会复制旧 session 的 grant、批准回执、open
event、pending verification、effect debt、continuation token 或其他执行权限；工作区级未决
效果仍由原账本独立阻断。卡片目标同时绑定政策摘要、material sequence、授权状态摘要和源/目标
lane 摘要，所以跨 session 冒用、重放、revision/task epoch 漂移或审批期间的任务世界变化都会
失败闭合。跨合同 v2 还绑定当前合同、源合同及 session 路由前驱；原生命令仍指向当前合同，
不放宽 PermissionRequest 的当前会话匹配。事务复用 native decision journal，按合同路径
排序加锁、再对路由 CAS。源 lane 在准备阶段只读；路由暂存后仍解析到原合同，直到源合同
原子提交 bound lane 才生效。中断由既有恢复器续接内部事务，不重做外部动作。
若是新任务，必须应用新 proposal，不能借续接入口扩大旧任务。

```sh
intent-guardian doctor --workspace /path/to/project --provider codex
```

除面向批准通道的 `approval_capture` 外，结果还包含 `host_readiness`：它分别展示
SessionStart、UserPromptSubmit、Pre/PostToolUse、Stop 和 MCP initialize 的观察状态。
`artifact_ready` 与 `synthetic_only` 只证明发布件及运行时接线可运行；只有匹配当前
provider + native session + workspace 的 `live_verified` 才能证明真实交互边界已加载。
该字段是诊断证据，不参与授权判定，也不会把未知外部写入改成成功。

若当前 session 的 `PermissionRequest` 能力不是 `live_verified`，不得让用户重复发送人工决断，
也不得改给一条 `approve-proposal` CLI 命令或要求另开终端；应保留提案并修复/重装桥接。
`approve-event` 已退役：复制摘要命令既不能证明用户看过内容，也不能区分人和 Agent。
`doctor` 会按当前 native session 诊断，另一会话曾经 `live_verified` 不能替当前会话背书。
只有进程真正中断时才使用 continuation；`SessionStart` 会自动注入冻结的目标、保护/拒绝边界、
验收和有限可见对话，因此不要求人重新讲述整个任务。正常批准不要求重启当前会话。该故障只
阻断人工通道；满足严格资格条件的 Agent 决断仍可运行。没有活动 contract 时，`doctor`
也必须返回 `unobserved`，而不是把“没有状态”解释为健康；Agent 可自动运行
`prepare-proposal` 建立最小权限占位契约。

工作区绝对路径是授权边界，目录删除或临时 worktree 消失后，旧契约不会自动匹配同名的
新目录。先扫描：

```sh
intent-guardian doctor --scan --provider codex
```

扫描结果把根目录不存在的活动契约标为 orphan。确需迁移时，Agent 先通过当前宿主原生
Allow/Deny 获取一次性恢复授权，再执行精确的迁移事务；没有可验证的原生恢复通道时保持
blocked，不把 CLI 命令交给人复制。

`rebind-workspace` 只接受已消失且没有开放事件、待验证写入或活动 Skill 的源工作区；目标已
有契约时拒绝覆盖。迁移会归档旧契约、留下重定向标记、清空遗留事件票据、作废未消费回执，并把
新契约置为 paused。必须在新路径重新生成、人工批准并应用意图提案，旧授权不会随路径复制。
若旧任务已放弃且不需要迁移，同样由 Agent 在一次性原生授权后执行 retire 事务；它要求
源目录已消失且没有未闭合执行，随后将契约以 `closed` 终态归档并作废剩余授权。无法取得
原生授权时保持 blocked，不通过人工复制命令绕过。

## 审阅与控制命令

稳定入口由一体化 Codex 安装器或 bootstrap 生成在
`$SULDE_KB_HOME/bin/intent-guardian`。launcher 安装清单同时绑定规格版本、入口摘要、
整个 `scripts/kb` 运行时摘要、Codex Adapter 表面摘要和生成文件摘要；缺失或不一致时状态灯显示
`🔴 接线未同步`，写控制面拒绝继续猜测。可用
`bootstrap.sh --launchers-only --host codex` 快速刷新，它不创建 venv、不下载模型、
不重建索引，也不修改宿主设置。已安装 runtime 仅被生成的
`__pycache__/*.pyc` 污染时，可增加 `--repair-generated-bytecode`；它先验证排除字节码
后的树与 sealed generation 完全一致，否则拒绝任何删除。

安装升级时，当前版本通过完整 smoke 后，安装器扫描旧 Codex 版本缓存并只更新
`scripts/run-hook.sh` 与 `scripts/run-hook.ps1`。旧入口调用稳定
`intent-guardian codex-hook`，稳定 launcher 先校验当前 runtime，桥接器再对照权限受限的
manifest 校验 Adapter 表面摘要，然后才转发原 stdin/stdout/stderr。旧 runtime、Skill 和
文档不被软链或覆写；安装前为每个真实旧缓存做整树快照，Codex 清理后先恢复静态树再替换
入口，失败也恢复安装前整树。部分缓存只有在持久 artifact 完整、无符号链接且版本描述符
精确匹配时才可自动修复。因而恢复同一 thread 时 Hook
策略可立即更新，而 Codex 在会话开始时快照的静态 Skill 清单仍只在新会话刷新。

Guardian 控制命令只在“首个可执行文件是可信稳定 launcher 或与当前运行时摘要一致的源码
入口”时识别；命令参数、被搜索文件名或引号内的正则字符不会升级成控制动作。
`show/report/doctor/prepare-proposal/apply-proposal` 等 Agent 安全动作走独立控制审计，不创建
普通工具 open-event，因而不会在应用提案时自锁；`approve/resume/activate/rebind/retire`
等 CLI 不得被 Agent 用来伪造人的决定。正常路径中，人只在宿主可读卡片作决定，Hook、
Agent 或监督器负责执行已授权动作；`rebind/retire` 等外部入口明确标为 break-glass，拒绝
本身也不会把业务意图额外暂停。

Shell 分类先解析未组合的可执行结构，再判断参数文本；因此 `rg "git push"` 仍是读取，
真正的 `git push` 才是外部写入。确定性的 `kb-index search`、`git ls-remote` 和受控测试/
语法检查以及每段都可证明只读的 `|`、`;`、`&&` 组合进入已知只读集合；无法识别的普通
命令在没有硬风险信号时进入 `degraded_observe`，保留审计和验证债务而不要求事件摘要。
`apply_patch` 只有从原始或嵌套宿主载荷解析出全部目标后才按
本地写入检查 scope，无法解析时以 unknown 失败闭锁。

本地 Python 脚本不能按文件名、扩展名或可写工作区中的声明获得信任。Codex 安装器会在
`$SULDE_KB_HOME/bin/.sulde-command-effects.json` 生成权限为 `0600` 的本机快照，并由
`.sulde-launchers.json` 绑定其完整摘要和同一运行时摘要。每条声明同时固定解释器文件摘要、
脚本绝对路径与内容摘要、效果类型和 argv 语法；运行时还会重新解析精确目标。当前只声明
`plugin-creator` 的验证脚本为 `read`，cachebuster 脚本为仅写目标插件
`.codex-plugin/plugin.json` 的 `local_write`。脚本升级、解释器变化、同名异路径、额外参数、
shell 串联、manifest 缺失/损坏/权限放宽或目标 symlink 都回到 `unknown`，需要重装刷新证据，
不会因历史信任自动放行。插件安装、网络、发布和未声明脚本不共享此契约。

宿主自己的目标/计划记录、询问人工、等待/列举协作者和中止协作者属于窄控制面：暂停时仍
可用于报告阻塞、等待决定或收缩执行，而且不进入业务 open-event。创建 Agent、发送继续
消息和 follow-up 会扩大执行，暂停时仍拒绝。Git 元数据也不作为普通文件权限的后门：单条
`git add -- <明确文件>...` 只有在每个 operand 都被证明为当前工作树内现存普通文件时，才按
这些文件的结构化目标逐项检查路径权限；内部 index 更新不产生通用 `.git` 权限。省略 `--`、
`-A/-u`、目录、glob、pathspec magic、交互/复合暂存继续拒绝，即使契约授权仓库根也不共享
例外。非 `--amend` 的 `git commit`，以及只合并一个已知 ref 且仅使用安全快进/提交选项的
普通 `git merge` 仍要求明确仓库级授权；子路径授权、直接 `.git/*` 写入、自定义 merge
strategy、merge 恢复控制、历史改写、强推继续拒绝。

```sh
# 查看状态与覆盖范围
intent-guardian report --workspace /path/to/project
intent-guardian doctor --workspace /path/to/project --provider codex
intent-guardian doctor --scan --provider codex

# 当前会话未加载审批 hook 时由 Agent 机械生成；不产生任何批准或工具授权
intent-guardian prepare-continuation --workspace /path/to/project --provider codex

# 没有契约时 Agent 一步完成安全建档 + 冻结提案，并输出完整审阅内容
intent-guardian prepare-proposal --workspace /path/to/project \
  --intent-id "task-id" \
  --objective "..." --accept "..." --preserve "..." --reject "..." \
  --allow-path "resume.md" \
  --decision-route auto --intent-kind subjective --risk medium \
  --unattended-policy agent-if-eligible \
  --effect local_write --reversibility reversible --cost none \
  --rollback "恢复最近一次已接受版本" --mode enforce

# 已有契约也可直接生成修订提案；同样输出完整审阅内容
intent-guardian propose-revision /path/to/active.json \
  --objective "..." --accept "..." --preserve "..." --reject "..." \
  --allow-path "resume.md" --mode enforce

# 技术审计时按 digest 重新显示后台绑定内容（普通人工决策无需使用）
intent-guardian proposal-show <digest> --contract /path/to/active.json --provider codex

# 用户明确接受额外模型调用与改动片段出境时，才追加：--semantic-critic

# Codex：Agent 先运行 native-decision-preview，再用返回的 command_argv 与 description
# 原样发起一次性原生升级（不得请求持久 prefix 放行）；用户无需复制下列命令。
# Allow 后受保护命令自动应用同一不可变提案。
intent-guardian native-decision-preview proposal --decision approve \
  --target current --provider codex --session-id "$CODEX_THREAD_ID" \
  --contract /path/to/active.json

# 新会话确认续接同一任务：Allow 只绑定当前 session，不转移旧 session 的执行授权
intent-guardian native-decision-preview task-continuation --decision approve \
  --target current --provider codex --session-id "$CODEX_THREAD_ID" \
  --contract /path/to/active.json

# 没有原生决策面的宿主保持 pending；不得用聊天固定短语生成授权。
# 原生决策回执形成后，机械应用由 Agent 完成。Codex native-decision 已自动应用。
intent-guardian apply-proposal /path/to/proposal.json --contract /path/to/active.json

# 仅当 decision_route=agent 时，Agent 提交可审计理由和证据后决断
intent-guardian agent-decide-proposal <digest> --contract /path/to/active.json \
  --provider codex --rationale "满足确定性低风险门禁" \
  --evidence "仅修改明确允许的本地文件" --evidence "有可执行回滚方法"
intent-guardian apply-proposal /path/to/proposal.json --contract /path/to/active.json

# 事件摘要批准已退役；范围内动作由监督器执行，范围扩大只展示可读卡片
# 非交互 approve-proposal CLI 不能代替审阅；hook 不可用时修复接线

# 人工暂停
intent-guardian pause "需要重建共同理解" --workspace /path/to/project

# Codex 恢复：Agent 展示当前暂停卡，再以返回内容发起一次当前会话 PermissionRequest；
# 人只按 Allow/Deny。直接运行 resume CLI 仅保留为宿主控制面损坏时的 break-glass。
intent-guardian native-decision-preview resume --decision resume \
  --target current --provider codex --session-id "$CODEX_THREAD_ID" \
  --contract /path/to/active.json

# 查看 durable intervention inbox
intent-guardian interventions --contract /path/to/active.json
intent-guardian intervention-show int-<24hex> --contract /path/to/active.json

# 查看纠正状态；Agent 可在用户明确纠正受管任务时自动把原话排入对应 lane
intent-guardian corrections --contract /path/to/active.json
intent-guardian correction-propose "不是这个方向，请保留已确认内容" \
  --provider codex --session-id managed:l3:<slug> \
  --contract /worktree/.codex-agent/<slug>.intent.json

# 正常路径：Codex 在当前对话显示原生确认卡；人只按 Allow/Deny，不复制 CLI。
# 重查、重试、终止和观察导出均走 native-decision-preview；只有系统确实无法独立取得
# 外部事实时，人才在对话中提供“操作成功/失败 + 自己看到的证据”。

# break-glass：仅当 Hook、审批账本或宿主控制通道损坏时，由 Agent 展示精确风险与原生
# Allow/Deny；Allow 后 Agent 在独立恢复通道执行，人不复制命令或摘要
intent-guardian intervention-resolve int-<24hex> \
  --decision human_attested_success \
  --evidence "remote record 42 was inspected at 2026-08-14T..." \
  --contract /path/to/active.json
```

可用 decision 为 `human_attested_success`、`confirmed_failed`、`reprobe_authorized`、
`retry_authorized`、`abort`。`intervention-resolve` 不接受空证据；Agent 通过 CLI 代替人作
决定会被拒绝，但 Hook 在匹配可读选择与成对问题后执行同一状态迁移是正常路径。受管
Agent/自动修复环境中的 break-glass CLI 仍二次拒绝。精确控制 prompt 不进入记忆捕获、
召回、Skill 触发或性能建议，只作为控制面事件注入当前对话上下文。

Codex 采用 Skill 时必须按注入的完整命令调用 `skill-start` 和 `skill-end`；不要手工省略
或替换 `--skill-path <absolute-SKILL.md>`、`--contract`、`--provider`、`--session-id`，否则
登记本身会被拒绝。监督器在生命周期边界记录可读 `SKILL.md` 的内容摘要。L3 中子命令
只发出可观察登记信号，唯一权威状态由父监督进程维护。

## 交互任务 worktree 收尾

任务分支的精确 HEAD 已进入同仓库 `dev`、源 worktree 干净且所有效果状态已结算后，Agent
调用 `release-completed-workspace`。该操作只做 Git 身份、洁净度和祖先关系读取，把当前
session 原子降权到 session 专属的只读 completion anchor，并保留带摘要的 cleanup
`pending` 记录；它不执行合并、删除、移动或分支修改，也不复用其他 session 的 dev 合同。

随后 Agent 从 dev worktree 运行普通 `git worktree remove` 与 `git branch -d`，再调用
`finalize-workspace-cleanup`。finalize 只有在源目录不存在、worktree 不再注册且本地任务
分支不存在时才写入 `complete` 回执。中断时 `doctor` 与下一次 Hook 上下文持续暴露
`WORKTREE_CLEANUP_PENDING`，由 Agent 自动续完；无需关闭当前会话，也不得让用户复制命令。
脏树、未合并 HEAD、不同 Git common-dir、保护分支、未决事件/验证、真实效果债务或活动
Skill 均拒绝 release，并保留原任务环境供修复。

## L3 持续监督

`agent-runtime.py` 不再等 Agent 退出后才检查结果。它逐行读取 Claude/Codex 结构化输出，
将 Skill、MCP、命令和文件事件送入同一状态机；确定性越界立即终止 provider，契约和
隔离 worktree 保持 `paused`。若问题是外部结果 unknown，终态改为 `awaiting_human`，保留
worktree、attempt 和 intervention identity，禁止被普通失败重试逻辑重新发射。人先用
`intervention-resolve` 裁决，再执行 `self-repair.py --resume-guarded`；新 provider session
会读取持久化 resume context：已证明成功的动作禁止重做，`reprobe_authorized` 只允许读，
`retry_authorized` 只允许原指纹重试一次。resume context 只携带 provider、能力、稳定 ID 与
目标/证据摘要，不复制原始目标；恢复时若所选 provider 与原 attempt 不同则拒绝执行。旧
attempt 仍不可变。
受管 provider 子进程只产生可观察事件，不能直接调用 effect 状态迁移 API；父监督进程持有
权威写者身份并校验 effect 与 approval event store 字节。子进程直接伪造或改写日志会恢复
到父进程最后验证的版本、记录 integrity breach 并暂停任务。

POSIX 受管运行由父进程存活管道和同 process group watchdog 组成；即使父监督进程被硬杀，
watchdog 仍会终止 provider 及其后代。下一次启动先重放 `*.run.jsonl`：只有完整前缀、可证明
进程树消失且具备 watchdog 证据时才能追加 recovered 终态。损坏尾行或仍存活的旧进程保持
`awaiting_human`，原字节不截断，也不会再启动一个并行 provider。

清理 L3 worktree 前会先重放 effect/intervention 日志。仍有开放、待验证、待复查或未消费
重试的 attempt 时，即使指定 `--force` 也拒绝清理；全部裁决完成后，append-only 日志及其
摘要清单先归档到 `$SULDE_KB_HOME/interventions/archive/`，再允许删除 worktree。归档日志
继续进入状态统计和统一观察面，且与清理前使用相同的逻辑来源 identity，避免重复事件。

L3 成功还要求：策略未被执行者修改、零拒绝、零未闭合 Skill、零当前 task epoch 开放事件、
零当前任务待验证副作用、零当前任务 unknown effect、零当前任务开放 effect/correction
intervention、零开放 approval，并且 RunResult 成功、process tree 已 quiescent、改动范围符合基线、五段报告完整且每个
完成项有命令与退出码证据。运行端与独立 verifier 调用同一个终态不变量函数，避免一边绿一边
红。生命周期不再把 `paused`、`awaiting_human`、timeout 或陈旧
executing 报成 ready。失败、缺回调或语义证据不足会保留 `inconclusive` 记录，不能被
报告成已验证事实。commit、push 和普通 merge 只有在可读任务范围明确声明、目标可验证且无
历史改写时才可由 Agent 机械执行；发布、新受众、知识语义裁决或破坏性 Git 操作仍由人决定。

## 明确限制

- 这是可观察执行监督，不是读心，也不能证明未发出事件的宿主内部动作不存在。
- 主观偏好必须由人确认；审查器不能替代人的最终审美或表达选择。
- 外部系统若没有可读回查能力，写入会一直保持未验证，不能宣称闭环完成。
- `shadow` 发现只是候选信号；没有积累证据前不能直接升级为硬阻断。
- 宿主 hook 自身异常在普通交互中会显式降级，避免整台宿主不可用；受管 L3 的终态验收
  独立 fail-closed。
