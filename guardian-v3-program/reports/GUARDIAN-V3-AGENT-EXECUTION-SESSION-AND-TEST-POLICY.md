# Guardian V3 Agent Execution、会话隔离与测试策略验收

状态：IMPLEMENTATION_ACCEPTED

日期：2026-09-03

## 冻结结果

- 普通本地文件写入由 Agent、宿主沙盒和最终验收负责；Guardian 不再把任务提示路径当成执行权限白名单。
- Git 与 Figma 均属于执行直通域。Guardian 只保留审计事实，不授权、不阻断、不生成效果债务；历史 Figma attempt 也不得阻断新调用。
- 破坏性操作、外部写入和持久控制状态变更仍保留精确的人类决策边界。恢复提示只要求当前宿主 Allow/Deny，不再引导复制摘要或切换外部终端。
- 本地删除按风险分级：少量字面量、非递归普通文件删除和 `apply_patch` 删除/重命名属于 Agent/宿主本地写入；递归删除、目录删除、超过 16 个目标、动态目标、受保护控制路径及正式安全 canary 才进入高风险人工边界。
- 同一项目的 provider/session 使用独立合同和持久路由。新 session 不继承其他 session 的 objective、grant、授权事件、效果债务或暂停状态；只有显式 task-continuation/workspace-handoff 可以续接。
- Codex Hook payload 缺少 session 字段时回退到 `CODEX_THREAD_ID`，四个 Hook 入口使用同一规范化逻辑。
- lenient 放行采用静默 exit 0；只在真实拒绝时输出宿主支持的 deny JSON，消除 `unsupported permissionDecision:allow`。
- Pre-execution v2 使用预先存在 marker 的破坏性删除负例，且真实 denial 事件同时绑定 `loaded_module_generation` 与 `artifact_generation`。
- 官方 Codex 插件校验器可在 `python -S -B` 下运行，不依赖 PyYAML。源码测试入口在前后清理派生 `.pyc/.pyo`，安装与 staging 继续拒绝字节码污染。
- 测试策略按 small/medium/refactor 分级，证据绑定 HEAD、tree、index、工作区内容、运行器、解释器和平台；只有未过期的精确通过记录可复用。记录 30 天过期，每日 GC，容量上限 250，并保护最近全量通过和有界首个失败证据。

## 验证结果

- 失败基线：`20260903T031948.483963-798077737803`，1757 项中 11 failures、1 error、25 skipped；耗时 514.245 秒。失败原文和 SHA-256 保留，没有被后续通过记录覆盖。
- 修复后全量：`20260903T034411.342707-5d85f37a0fcc`，1757 passed、25 skipped；exit 0，耗时 510.170 秒。
- 通过日志 SHA-256：`a055ce821594a4b363306f311294bd9378784d92bd36db46f6a944cc618c0b90`。
- 真实宿主名补充后，`f42f032` 的两次全量均稳定发现 Claude 外部 MCP 写入后的 read verifier 被错误送入无锁热路径：`20260903T081244.925783-bac93aac16e6` 与 `20260903T081354.245244-bac93aac16e6`，均为 1762 项中 1 failure、23 skipped。失败记录保留，未作为可复用基线。
- 修复后精确全量：`20260903T083647.836765-5dfc41e14c01`，绑定 `31b06c66cfdeb25471bdd749a5016c6ddabeafb5`，1763 passed、23 skipped；exit 0，耗时 499.217 秒，证据键 `5dfc41e14c011a15686ce460e44bea40d9275c4a2cde79a86a2f74548c10f966`，日志 SHA-256 `c342a45e645bb7ff46487d47f73930f10f04531b086f8a9dccce94d532a74732`。
- 本地删除风险分级全量：`20260903T085941.313055-81652f56e044`，1764 项中 1763 通过，仅旧 post-only fixture 仍使用普通文件而失败；实现无其他回归。将 fixture 改为正式高风险 canary 后，按 small 映射运行完整 `tests.test_intent_guardian`：`20260903T091034.041081-ea848c8b604a`，exit 0，耗时 49.756 秒，证据键 `ea848c8b604a6957796162fd28ac035ec93924ab20d877b893aa42f70fe5ddaa`。
- 测试期间清理旧派生字节码 5 个、空 `__pycache__` 目录 2 个；通过轮开始和结束均为 0。
- `python3 -S -B scripts/release/validate_codex_plugin.py integrations/codex/plugins/sulde`：valid，`pyyaml_required=false`。
- 组件边界：`state.py` 与 `recovery.py` 均不超过 3000 行，组件依赖图无延迟 import 或环。
- L3 runtime 定点复验：75/75；越界交付由最终报告/工作树快照判失败，但不再把普通写入变成 Guardian 暂停。
- Figma 分类正反例：`p.name === value` 为只读审计，`p.name = value` 为写入审计；二者执行层均直通。
- 真实 Codex Apps 扁平名 `mcp__codex_apps__figma_use_figma` 与原生 `mcp__figma__*` 均在合同解析和账本锁之前直通；Guardian 不创建 grant、intervention 或 effect debt。
- 精确 Sulde 只读 MCP 走可重入的无锁热路径；其他外部 MCP read 保留验证语义，可结算同资源前序 write，避免为解除自锁而破坏 effect 闭环。
- 候选 promotion 同时识别历史 v1 与 `python -B` 的 v2 密封调用；v2 绑定 `PYTHONDONTWRITEBYTECODE=1`/`-B`，并复用一次性候选 receipt，不重新构建未经候选验收的发布树。
- 本地清理正反例：`rm -- <single-regular-file>` 与精确 `apply_patch` 删除由 Agent 执行；`rm -rf <directory>` 和 `sulde-pre-execution-canary-*` 保持执行前拒绝。Post-only latch 只服务需要 Guardian 前置监督的高风险动作，不再把普通本地写入计为控制面缺口。
- 会话正反例：同项目新 session 获得独立 shadow 合同；同 session 原生决策、观察导出和 workspace handoff 保持精确绑定。

## 发布边界

本报告只接受已经提交的实现和测试证据，不预先宣称 production 已安装。候选代际必须在隔离的 Sulde/Codex/KB/launcher 根完成真实 CLI → Hook → unified exec 链；候选通过后才允许一次性 promotion。最终 production generation、scheduler、launcher、MCP 和真实 Hook 结果由安装事务回执追加证明，候选失败时旧 production 保持可用。

Windows bootstrap 依照既定决策由 Windows 环境独立验收，本次 macOS 交付不代替该平台结论。

## Production 最终验收

- 发布源提交为 `f5570ddbd96ba4faf46c8fc1b1604a5579a0d3c2`，版本 `0.2.5+codex.20260903091235-9c92ea3946`，generation 为 `0.2.5+codex.20260903091235-9c92ea3946:bf528b2247e35b7487c6a4d47ce8e4b86c441f513eeb3b081ca29893d4d7ec7d`。
- 候选 `guardian-v3-agent-policy-f5570dd` 在隔离 Codex/Sulde/KB 根完成真实新进程 CLI → PreToolUse → unified exec 拒绝链、MCP initialize 和 scheduler entrypoint 验证；receipt `83f69acd89c92fdaf6444af75d4ad55b9507c163768f79aa2cea11b4b23b3e3d` 已一次性直接 promotion，状态为 `promoted`、`promotion_consumed=true`，没有重新构建发布树。
- 正式安装耗时 19.234 秒，其中安装锁内 13.826 秒；artifact、installed runtime、deployment、launcher 和 scheduler owner 指向同一 generation。Scheduler 16/16 loaded，`failed_labels={}`；6 个 Codex Hook 均唯一、enabled、trusted。
- 正式环境真实正例：`sulde_kb.kb_status` 返回 ready；Codex Apps 扁平 Figma `figma_whoami` 成功且没有产生 Guardian 债务；普通单文件 `touch`/`rm` 均由 Agent 完成。
- 正式环境真实负例：高风险 `sulde-pre-execution-canary-*` 删除在执行前被拒绝，marker 未执行并已收尾；proof `22954a7be2cc151a15fb54663cdfeb9d42ddbdac49e254e8fea88aa63650bcba` 同时绑定实际 denial 的 `loaded_module_generation` 和 `artifact_generation`。
- Revision 13 的 cachebuster 与 install 效果均为 `system_verified`；effect debt、pending verification、open intervention 和未消费 approval request 均为 0。
- 同一项目双新会话验收：session `01a06696-4125-7e41-ba54-ec64d5c21df9` 与 `01a06696-e048-7593-ab07-009b1ceb2439` 分别解析到独立 session contract、独立 `task_epoch`、独立 continuation token 和独立 mapping digest；两边授权/grant/effect debt 均为 0。第二个会话的原始宿主账本完整记录 `SessionStart → UserPromptSubmit → PreToolUse → PostToolUse → Stop`，全部绑定同一 session/workspace/runtime；第一个无工具会话仅记录 session/prompt/stop，符合实际动作。
- 从旧 root session 运行 doctor 仍显示交互域 degraded，是因为 session-scoped 新代际观测不允许从其他新会话借用；artifact、scheduler、recovery、effect 和 pre-execution 域均 ready/clear。这是隔离预期，不是生产故障，也不要求为了 Hook 热更新重启旧会话。
- 验收后 task worktree 与 dev worktree 均 clean，`dev == origin/dev == f5570ddbd96ba4faf46c8fc1b1604a5579a0d3c2`；main 未被本任务修改，原有 `.ua` 用户修改保持不动。

## 沉淀候选

### 候选 1：持久 session 路由必须按数据根隔离

- 问题语境：provider/session 映射是持久状态；测试或宿主若复用全局 KB home，会把已删除临时合同留给下一会话。
- 证据状态：conclusive。
- 路由正例：每个真实 session 只解析自身映射；测试为每个 fixture 提供独立 `SULDE_KB_HOME`。
- 路由反例：不同 session 因同一 workspace anchor 自动继承 objective 或 authority。
- 执行正例：显式 continuation/handoff 原子绑定新 lane，且不复制 grant/debt。
- 执行反例：启动环境中的旧合同路径永久覆盖当前 session 路由。

### 候选 2：测试结果复用必须绑定完整可执行世界

- 问题语境：仅记“测试跑过”无法安全复用，也会导致每次小改无差别重复全量。
- 证据状态：conclusive。
- 路由正例：small 走直接映射，medium 走影响集，Guardian/runtime/refactor 走全量。
- 路由反例：按文件数或人工印象跳过核心测试。
- 执行正例：复用前精确匹配 HEAD、工作树、runner、Python、platform 和未过期 pass。
- 执行反例：复用失败记录、过期记录或不同 working tree 的结果。

### 候选 3：恢复来源不应抹掉原始审批语义

- 问题语境：观察导出问题在 SessionStart 恢复后，审批事件来源会变为恢复来源，但仍绑定同一 proposal 和真实宿主回执。
- 证据状态：conclusive。
- 路由正例：开放问题只从原始 prepare 路由；已决定问题接受受限 restore 来源并继续核验 actor、lane、receipt。
- 路由反例：把任意恢复事件视为新的导出授权。
- 执行正例：唯一 proposal、唯一 live receipt、一次性消费全部成立后才导出。
- 执行反例：只凭聊天文本、digest 或恢复事件直接执行导出。

### 候选 4：无锁只读热路径必须保留资源验证语义

- 问题语境：为避免嵌套 Sulde MCP 与外层 Hook 争用同一账本锁，不能把所有 MCP read 一概绕过 Guardian；业务资源 read 可能正是前序 write 的独立 verifier。
- 证据状态：conclusive。
- 路由正例：精确 `sulde_kb` 诊断 read 走无锁热路径；Docs 等资源 read 进入对应资源适配器。
- 路由反例：仅按 `effect=read` 将全部 MCP 调用送入无锁热路径。
- 执行正例：外部 write 完成后，同资源 read 结算 pending verification；诊断 MCP 可在外层 tool 尚未收尾时重入。
- 执行反例：为修复自锁而跳过全部 read verification，留下永久效果债务。
