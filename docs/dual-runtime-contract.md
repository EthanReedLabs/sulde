# Claude Code / Codex 双宿主运行契约

## 目标

Sulde 只有一个生命真值，但允许两个可替换宿主：

- 只安装 Claude Code：感知、记忆、L2、L3、L4、治理与进化闭环可运行；
- 只安装 Codex：同一组闭环可运行；
- 两端共存：共享 `$SULDE_KB_HOME`、SELF、知识索引和 L2/L3/L4 状态，不复制人格；
- 未选中的宿主缺失、退出登录或损坏，不影响已选宿主，也不会触发静默回退。

这里的“独立”是指不依赖另一种 LLM 运行时。Python、Git 和知识索引模型仍是明确运行依赖；
主观选择、公开/新受众、破坏性、费用、权限扩大和 unknown 仍由人补充语义或事实。确定性
低风险本地任务，以及完全落入已登记、一次性、宿主本地、可回滚且可独立验证的机械续行链，
可走受限 `agent-policy`，不要求人复制命令充当执行按钮。会修改 Sulde 源码/knowledge 的 L3/L4
任务还需要一个可写的正典 Git checkout；发布缓存本身不是可合并的源码真值。

## 四个 Port

### 认知运行时 Port

所有需要模型判断的器官只调用 `scripts/kb/llm-runtime.py`，并通过 stdin 发送 prompt。
器官不再内嵌 `claude -p` 或 `codex exec`：

- Claude 适配器使用非持久、safe/plan、无工具的 print 模式；
- Codex 适配器使用 `codex exec --ephemeral` 和 read-only sandbox；
- `--llm-cmd` 仍保留，供测试或显式的受控替换使用。

提供方选择优先级：显式参数 → `SULDE_LLM_PROVIDER` → `SULDE_HOST_PROVIDER` → 明确的
当前宿主证据 → 机器上唯一可用的 CLI。两种 CLI 都存在但没有所有者时，系统拒绝猜测；
已指定提供方不可用时，系统失败并说明原因，绝不借用另一端。

### L3 任务执行 Port

`scripts/kb/agent-runtime.py` 是仓库自有执行与验收协议，不依赖
`~/.claude/skills/codex-agent`：

1. 人工批准后创建隔离 git worktree；
2. 执行前保存内容与权限基线；
3. 由 `SULDE_AGENT_PROVIDER` 选择 Claude Code 或 Codex 写入 worktree；
4. 流式监督 Skill、MCP、工具和副作用；语义/权限越界持久化 `paused`，外部结果无法证明则
   持久化 `awaiting_human`，两者不共用状态；
5. 原子写入 provider、exit code、耗时、意图摘要和终态；
6. 同一个验收器检查意图策略、未闭合事件、验证债务、改动边界、五段报告和逐项命令/exit 证据；
7. commit、分支内 merge 和任务合同已覆盖的 push 由监督 Agent 收尾；只有公开/新受众、
   破坏性历史改写、权限扩大或知识语义裁决停在人类原生决策闸门，Allow 后仍由 Agent 执行。

`.codex-agent/` 暂时保留为历史兼容的任务工件协议目录；目录名不再决定执行提供方。
Claude 适配器在 macOS/Linux/WSL2 强制启用原生 Bash sandbox、禁止 unsandboxed escape，
并加载 commit/push/破坏性 git deny 规则；原生 Windows 因 Claude sandbox 尚不可用而使用
官方 Auto 权限分类器。Codex 忽略用户配置与 exec rules，使用 workspace-write sandbox。
两端再共同依赖“隔离 worktree
+ 禁区 prompt + 基线差分 + 独立验收 + 人工合并门”形成纵深防御，不使用危险的权限
绕过参数。

### 交互能力 Port

Claude 发布件原生暴露完整 skills；正式 Codex staged 发布件在插件根暴露宿主中立的
`dispatch-task`、`intent-guardian`、`kb-search`、`memory-distill` 与 `sediment`，并在
`runtime/` 携带同一实现所需脚本和语料。裸 `integrations/codex/plugins/sulde` 只用于
adapter 开发，不作为独立运行发布件。

交互派单同样经过宿主适配边界：task 只持久化 `capability_tier: light|balanced|deep`，
不持久化某个提供方的模型名或 thinking 语法。协调端在派单瞬间读取**目标 session**的
provider、当前模型和可观察推理档，再由 `scripts/kb/model-dispatch.py` 渲染原生控制：
Claude Code 可使用其 `/model <Claude 型号>` 与 `/assign`；Codex 保留已满足要求的当前模型，
不足时使用 `/model` 和 `/reasoning` 选择器，并直接执行任务文件。两种 CLI 同时安装不构成
当前宿主证据，Codex 路径不得出现 Claude 型号或 `/mode`。

### 意图监督 Port

`scripts/kb/intent_guardian.py` 是宿主中立的可观察执行监督器。普通交互通过
`UserPromptSubmit → PreToolUse → PostToolUse/PostToolUseFailure → Stop` 形成闭环；Codex
另有 `PermissionRequest` 作为当前会话的原生人工决断边界。L3
直接消费 provider 结构化 stream，不依赖用户级 hook 是否加载。两端共享工作区活动契约，
但 Skill 栈按 `provider + native session_id` 隔离，所有状态迁移使用跨进程排他锁与原子写。

普通交互的闭环状态必须由真实宿主事件证明，安装器直接调用 adapter 只记为
`synthetic_smoke`，不能替代 `live_host_hook`。Codex 人工通道先由 `PermissionRequest` 记录
逐字匹配的自然语言卡片，再把最终 Allow/Deny 留给当前对话的宿主 UI；Allow 后受保护命令
才消费同一问题并迁移状态，Deny 不产生权限。Agent 不得要求人复制摘要、固定短语、CLI
命令或打开额外终端；桥接异常时保留提案并按 `intent-guardian doctor` 修复或重装。
其他宿主只有在存在可验证的原生决策面时才绑定同一份可读卡片；否则保持 pending，
不得把聊天文字当成授权。内部 digest 只供防篡改。
统一观察面的可携带导出复用同一 live Hook 证据链，但使用独立且更窄的
宿主原生 Allow/Deny 决策；它只批准一份已冻结脱敏切面在指定本地新文件中落盘，不批准
网络发送，也不能被提案批准、事件批准、聊天固定短语或另一宿主/session 的回执替代。
诊断按 provider + native session 隔离，不能用另一 thread 的 live 事件证明当前 thread。
人工提案同时生成不携带权限的续接包；重启恢复原 thread 或在同一工作区新开 thread 时，
`SessionStart` 注入结构化任务上下文。续接包只恢复可观察信息，批准、旧事件票据和工具权限
仍由新会话重新建立。

### 单一宿主能力契约

两端发布件共享 `scripts/kb/host_capabilities.py`，而不是由 staging、安装器和诊断各写一份
必需能力清单。最小契约是 `session_context`、`prompt_control`、`tool_guard`、
`tool_result`、`turn_reconcile`、`mcp_initialize`。Claude Code 的工具失败使用
`PostToolUseFailure`；Codex 的失败仍从 `PostToolUse` payload 归一化，二者进入同一中立
事件语义。描述文件不得再显式声明标准路径已自动发现的 Hook，否则构建直接失败。

就绪证据分三层，不允许互相替代：

- `artifact_ready`：入口已打包、配置只有一条注册路径且命令指向正确 Adapter；
- `synthetic_only`：安装器已真实启动 Adapter/runtime 并覆盖完整能力面，但不产生人类授权；
- `live_verified`：当前 provider、native session 与 workspace 的真实宿主 Hook 已触发。

`intent-guardian doctor` 返回会话范围的 `host_readiness`，`sulde-status --json` 返回最近的
非授权观察投影。每条记录还绑定当前发布件 Hook/Adapter 内容摘要。Codex 安装器会把仍存在
的旧缓存 Hook 入口改为受保护稳定桥：桥接后的旧 thread 由当前 Adapter 产生新摘要，可形成
当前 live 证据；未桥接或摘要漂移的旧路径仍只计入 `stale_runtime_rows`，不能替新发布件
变绿。没有真实 Hook 证据保持 `unobserved`，不会仅因安装成功变绿。

确定性、低风险、明确范围、可回滚且无未知项时可由 `agent-policy` 决断；已在人类可读任务
范围中声明的可逆外部效果可由 Agent 执行并进入证据账本。主观、公开/新受众、破坏性、
费用、密钥外发或权限扩大仍转人工。运行时超时、非零或空输出不得降级成“空上下文 +
成功”。机械的工作区建档由 `prepare-proposal` 自动完成，并保持未确认 shadow 权限。

工作区身份继续以规范化绝对路径隔离，防止同名目录继承权限。已删除路径形成的 orphan
contract 由 `doctor --scan` 显式列出；Agent 必须先取得当前宿主的一次性原生恢复授权，
再执行 `rebind-workspace`，且迁移后强制作废旧授权并重新审阅意图，不进行静默路径猜测；
无需迁移的 orphan 也由 Agent 在一次性原生授权后执行 `retire-workspace`，进入可审计的
closed 终态。没有原生恢复通道时保持 blocked，不让人复制 CLI 绕过。

监督范围固定为 `intent → Skill → MCP/tool → side effect → evidence`。权限绑定可读的任务
范围，事件 digest 仅作审计身份；范围内 MCP/外部写入由 Agent 机械执行并形成验证债务。
小批量、宿主归属明确的本地 `memory_annotate` 固定策略按 `local_write` 建模；只有固定
schema、限额和独立 SQLite 后置条件同时成立才进入该通道。其他 MCP 写入仍保持其原效果分类。
在意图卡中冻结验收项、类型化
效果、精确摘要/目标、单次预算、回滚与机器验证器的登记动作提供更强的机器证明。
当前登记链只有官方 cachebuster helper 和随后发生的事务化 Codex 插件重装，两步
同卡批准、各限一次，安装绑定 cachebuster 后的未来工作树；公开传播、新受众、费用、密钥、破坏性、
范围扩大和 unverifiable 效果不共享该授权。写后必须独立回读并匹配写前确定的内容/关系摘要或非空对象存在性；
读调用成功本身不是成功证据。每个外部操作由 provider/session 限定的
不可变 attempt 标识；两端共享工作区意图，但只有同一目标或显式依赖链的未决 attempt 会
阻断后续物质写入。每个 revision 的 `task_epoch` 隔离新旧任务；`runtime_generation` 让热
更新前后的 Hook 只在 provider/session、原生 call ID 与物质语义唯一匹配时闭合一次调用。
当前任务未闭合 Skill、开放调用、待验证写入、unknown effect 或开放 intervention
都会使 L3 验收失败，历史债务继续披露但不污染无关 task。Agent 只能在不可变提案通过门禁时
以明确的 `agent-policy` 身份决断；不能自批人工通道提案、裁决 intervention、恢复或
激活契约。工作区迁移和纠正风暴形成的暂停也不能由 Agent 决断解除。
L3 worktree 的 effect 日志在清理前必须可重放且没有阻断 attempt，随后归档到共享状态根；
`--force` 不能跳过这个事实闸门。

受管执行统一经过 `ExecutionBackend.start() → RunHandle`。`RunHandle.result` 记录 return code、
规范化 stop reason 和输出摘要；`dispose()` 独立、幂等地终止整个 POSIX process group 或
Windows Job，并产生 quiescence 证据。非 `completed` 结果即使留下完整报告也只是 partial；
provider 成功但清理未证实完全停稳同样不能发布为成功。请求、启动、interrupt、结果与
dispose 按顺序写入 `*.run.jsonl`，供 verifier 和统一事件观察面重放。POSIX provider 还由
同进程组 watchdog 持有父进程存活管道；父监督进程遭 `SIGKILL` 时 watchdog 会先终止整棵
进程树。下次运行只在进程组已证明消失且日志前缀可完整重放时追加 recovered
`result/disposed`；尾行损坏、旧进程仍可观察或旧格式缺少 watchdog 证据都保持
`unknown/inconclusive`、通知人工且绝不启动新 provider，也不截断原日志。

人工授权除一次性控制回执外，还必须满足独立的 append-only `approval.asked →
approval.decided` 配对不变量。提案、语义确认或真正未知事实只能回答唯一开放
问题；未提问、重复回答或跨 lane 回答都不能产生权限。受管 provider 不能改写 approval
账本；父监督器检测到伪造会恢复最后接受的前缀并暂停。L3 的成功与 verifier 共用同一个终态
闸门：Intent、Effect、Correction、Approval、RunResult 和 process-tree quiescence 任一仍有
债务，整体都不可发布。

统一观察面使用版本化派生投影而不是第二份事实源。snapshot 明示 `stateVersion`、零基
`asOfSeq` 和来源内容绑定的 `sourceRevision`；健康来源可从精确 SHA-256 字节前缀检查点只
重放新增 tail。版本变化、来源重写/截短、缓存损坏或未知 schema 一律退回全量领域日志，
不迁移、不猜测、不隐藏违规。缓存写失败只影响性能，不能改变状态或授权。

发布验收不能只导入源码模块。`tests/test_supervision_lifecycle_e2e.py` 每次先生成 Claude 与
Codex staged artifact，再从发布件真实入口串行覆盖：managed correction 中断及后代清理、
同 task/contract 的可读批准与 revision 恢复、统一 terminal gate、另一宿主读取同一真值、
投影 cache 冷读/命中/tail replay、批准导出、disabled MCP 以及重新启用。完整日志仍由
unittest/CI 保存，成功只输出用例结论；任何一段的来源、回执、终态或发布文件缺失都会让整条
旅程失败。

交互式 Claude/Codex 和受管 L3 共享 `Correction Intervention` 状态机。纠正原文与 native
session 不写入账本，只保留摘要；同一 provider/session 的下一 PreTool/Stop 才能把排队项
标成 `applied`。受管 L3 则由父监控器先持久化 policy pause，再通过 RunHandle 中断完整进程
树。这里的 `applied` 是控制面事实，不是模型理解或结果验收事实。

受管 provider 环境没有 effect/intervention 写者权限；父监督进程持续绑定最后验证的日志
字节，检测到子进程伪造后恢复权威版本并暂停。
人工裁决后的恢复上下文只传递 provider、能力、稳定 ID 与目标/证据摘要，不携带原始目标；
运行时拒绝跨 provider 恢复，避免把一次授权迁移到另一宿主或另一语义动作。

Claude 的原生 `Skill` 工具事件直接进入 hook/stream；Codex 当前采用显式
`skill-start`/`skill-end` 登记。受管 L3 由父进程从 provider stream 裁决登记，子进程不能
修改权威契约；登记必须携带实际 `SKILL.md` 路径并记录内容摘要，再由终态未闭合检查约束。两端都不声称读取隐藏
推理，宿主没有发出的事件也不能被虚构为已观察。详细协议见
[`intent-guardian.md`](intent-guardian.md)。

## 单生命、单写者

- 数据真值由 `SULDE_KB_HOME` 唯一标识；历史默认路径包含 `.claude` 是早期 Sulde 先接入
  Claude Code 时留下的共享状态根，仅为兼容，不构成 Claude Code 运行依赖，Codex 可完全
  独立读取同一目录。本阶段不边运行边复制到 `~/.sulde`，避免双写/双库；未来迁移必须停写、
  校验完整摘要、原子切换 `SULDE_KB_HOME`，旧路径只保留兼容指针并禁止双写。
- 共享记忆使用宿主限定会话 ID：`claude:<native-id>` / `codex:<native-id>`；
  `mem_entries.source_host` 独立记录来源。Codex 实时 hook 与 rollout 收割必须生成同一
  业务键，数据库继续以 `(session_id, content_hash)` 幂等去重。
- 宿主适配器是来源标签的信任边界：Claude 原生 hook 默认标记 `claude`，Codex
  adapter 强制覆盖为 `codex`，不信任外部 payload 自报的 client。无法可靠判定的历史
  数据标记 `unknown`，不得猜测归属。
- 两份全局规则都声明当前宿主是完整宿主；Claude 规则不得要求 Codex 委托，Codex
  规则不得要求 Claude skill。
- 同一项目的交互意图由工作区 key 唯一寻址；Claude 与 Codex 不再各建一份互相竞争的
  会话契约。宿主和会话 ID 只用于事件归属、一次性批准和 Skill 栈隔离。
- macOS 两端共用相同 `com.sulde.*` LaunchAgent 标签。安装时必须传
  `--provider claude|codex`，后一次安装原位接管调度，不新增第二套标签。
- 安装器把同一 provider 同时写为 `SULDE_HOST_PROVIDER`、`SULDE_LLM_PROVIDER` 和
  `SULDE_AGENT_PROVIDER`；同一轮心智与行动不会跨宿主拼接。
- 现有数据库锁、器官锁和 worktree/branch 冲突检查继续作为进程级单写者防线。

## 操作矩阵

| 场景 | Bootstrap | 后台调度 | L3 手动执行 |
|---|---|---|---|
| Claude-only | `bootstrap.sh --host claude` | `install-agents.sh --provider claude --accept-llm-data-egress` | `SULDE_AGENT_PROVIDER=claude self-repair.py --execute` |
| Codex-only | `bootstrap.sh --host codex` | `install-agents.sh --provider codex --accept-llm-data-egress` | `SULDE_AGENT_PROVIDER=codex self-repair.py --execute` |
| 共存、Codex 主控 | 两端插件均可装，bootstrap 一次 | 只装/最后装 Codex provider | 默认跟随已配置 Codex；可逐次显式选择 |
| 共存、Claude 主控 | 两端插件均可装，bootstrap 一次 | 只装/最后装 Claude provider | 默认跟随已配置 Claude；可逐次显式选择 |

Codex 安装/升级优先使用 `scripts/release/install_codex_plugin.py`：只有 staged artifact、
Codex 注册、缓存树摘要、稳定 launcher 契约、scheduler generation、意图建立、`PermissionRequest`
Adapter 和未批准 MCP 写阻断的合成验证全部通过后才返回成功；失败恢复原 marketplace/plugin、
launcher 与 scheduler 全部状态。成功状态固定为 `generation_verified`；整体
`operational_ready=false` 仅表示真实宿主 Hook 尚未验证。共享 KB 尚未初始化时返回精确的
`kb_initialization_command`；`scheduler_reconciliation_command` 为空，当前或新会话的真实
Hook/批准边界仍由 doctor 复核。组合通过前不得报告整体 ready。launcher-only 修复不得触发模型
下载、索引、记忆库或宿主设置写入。切换前复制当前插件缓存；新安装通过 smoke 后，将旧
版本绝对路径恢复为切换前字节的固定副本，再只替换 POSIX/Windows Hook 启动入口。入口经
稳定 `intent-guardian codex-hook` 校验 launcher manifest、当前 runtime 与 Adapter 表面摘要
后转发；禁止把旧路径整体指向新 runtime。每个真实旧缓存都在切换前做整树快照，回滚恢复
descriptor、runtime、Skill、文档和入口的全部原字节；只剩 Hook 文件的部分缓存仅可从版本
描述符精确匹配且无符号链接的持久 artifact 恢复。旧 thread 因而无需
重启即可获得新 Hook 控制逻辑，静态 Skill 清单仍需新会话加载。
Codex staged artifact 还携带 `.codex-plugin/generation.json`。其 runtime 全树摘要和 generation
必须与 installed deployment descriptor、六入口 launcher manifest、POSIX `runtime-owner.json`
或 Windows Task Scheduler owner 完全一致；任何一层缺失或分叉都保持 degraded。后台 wrapper
拒绝 `.git`、`__pycache__/*.pyc`、根/树内 symlink 和运行中字节漂移；实际先执行的稳定
POSIX/Windows runner 摘要同时绑定到 descriptor、owner 与 action，并以环境白名单启动任务，
不能继承宿主 session 或 provider secrets。安装/接管前同时枚举 loaded 与 installed `com.sulde.*` actor：精确退役
清单归档到确定路径并写幂等 tombstone；未知标签失败闭锁，名称中含 cache/repair 也不构成授权。
历史整树 symlink 只有同版本 immutable artifact 可物化，rollback 永不重新创建旧链接。
POSIX 一体化安装在同一事务中写入
`installation_status=generation_verified`、`operational_ready=true` 的 scheduler owner，并要求
deployment 和加载 actor 同代；这只表示 scheduler generation 就绪，不冒充真实宿主 Hook truth。
Windows 仍按下文的独立 Task Scheduler 现场门禁保持 degraded，直到真实任务回读完成。
若安装作为已批准计划的自动续行动作，同一张卡先冻结官方 cachebuster helper 对唯一 manifest
的一次修改及修改后整树摘要，再把安装 grant 绑定到该未来版本、Python/Codex/安装器摘要、
artifact、Codex/KB 根目录与一次执行预算；两步完成后分别独立验证 manifest/整树及两棵插件树、launcher、
全局规则和 `codex plugin list`，安装器返回 `success` 或零退出码本身不构成证明。

Windows 使用
`install-agents.ps1 -Provider Codex -RuntimeRoot <installed-plugin/runtime> -AcceptDailyLlmInvocation`；
它使用与 POSIX 相同的 deployment/launcher/generation 三方栅栏、共享 deployment lock 和
完整事务快照。Task Scheduler 回读必须逐项绑定 action、runtime root、generation、runner
摘要与 `LastTaskResult`；注册完成只能把 owner 从 `reconciling` 提升为
`active/installed_degraded/operational_ready=false`，真实 task 成功运行并被独立现场门禁回读前
不得提升 operational truth。第二个任务注册失败会恢复旧 runner、owner、authority 与全部旧
task XML/action。旧参数
`-AcceptDailyClaudeInvocation` 只作为兼容别名保留。原生 Windows 上 Claude L3 依赖
账号可用的 Auto permission mode，且没有 Claude Bash sandbox 的 OS 级隔离；需要同等
隔离保证时应在 WSL2 中运行 Claude provider。Codex provider 仍使用 workspace-write
sandbox。

## 验收不变量

- 源码中没有认知器官直接默认到某一 provider；
- 全局规则与 SELF 不把另一宿主列为任务执行前置依赖；
- Claude-only 与 Codex-only 都能完成 prompt stdin、L3 执行、终态和统一验收；
- 配置的 provider 缺失时产生可观察失败，另一 provider 的假程序不会被调用；
- Codex bootstrap 不写 Claude `settings.json`；
- 两种发布件都携带运行时端口、L3 执行器、SELF、任务书、沉淀 skill 与调度模板；
- Codex staged 发布件在插件根声明并携带派单适配、意图监督与三个知识/记忆 skills；
- Codex 安装成功证据包含 marketplace/plugin 注册、artifact→缓存整树摘要一致、六个
  launcher 的 spec/入口/运行时/生成文件摘要、当前会话原生批准桥、全局派单纪律和真实
  dispatch/guardian smoke；
- Codex 升级后，切换前存在的插件缓存绝对路径仍能解析到完整 Hook 运行时；
- 两端共存只有一组调度标签和一个共享状态根。
- 新 task 只记录宿主无关能力档；给 Codex 的派单不会出现 Claude model/command，给 Claude
  Code 的派单不会出现伪造的 Codex model ID。当前模型高于最低能力档时允许保留。
- 两端在同一工作区解析到同一活动意图契约；Skill 栈不跨宿主/会话串线，task-level 范围、
  effect attempt 与验证证据不能跨宿主、会话或参数误配。
- L3 终态要求活动契约、策略未变、零未闭合 Skill/事件、零待验证副作用、零 unknown
  effect 和零开放 intervention；`awaiting_human` 不得被生命周期投影为 ready 或自动重试；语义审查必须
  显式 opt-in，不能隐藏额外调用或数据边界。
- 同一原生会话经实时 hook 与后台收割后只有一个规范会话 ID，召回日志显式携带
  `source_host`，混合宿主统计不依赖路径名或会话 ID 猜来源。
