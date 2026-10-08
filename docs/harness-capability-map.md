# Harness 能力全景 × sulde 实现对照（7 层模型）

> 2026-07-31 汇总。左列为 Claude Code 官方能力与术语(附官方文档路径),右列为
> sulde-cc 的实现落点与版本溯源。状态:✅ 已实现/在用 · 🚫 刻意不用(有决策记录) ·
> ⏸ 有意留白(等触发证据) · 📋 已知边界。

## ① 上下文组装(Context Assembly)

官方能力:Memory 分层(`~/.claude/CLAUDE.md` 用户级 → 项目级 → 子目录级逐层叠加)、
自动压缩(auto-compaction,上下文将满时摘要续航)、`/compact` 手动压缩。
官方文档:`docs/en/memory`、`docs/en/costs`(compaction)。

| 官方能力 | sulde 实现 | 状态 |
|---|---|---|
| CLAUDE.md 分层加载 | 全局规则(codex 委托协议)+ 项目 CLAUDE.md | ✅ |
| 压缩挂点 PreCompact | 压缩前清注入去重态,防"压缩后失忆且不可再注入"(v0.3.1, WP7) | ✅ |
| 每轮上下文注入 | kb_recall 三闸注入 + cognee 记忆召回共用这条通道 | ✅ |

## ② Hook 事件(Hooks)——官方 9 事件

官方事件全集:`PreToolUse` / `PostToolUse` / `UserPromptSubmit` / `Notification` /
`Stop` / `SubagentStop` / `PreCompact` / `SessionStart` / `SessionEnd`。
官方输出协议:退出码(0 放行 / 2 拦截)、结构化 JSON(`hookSpecificOutput.permissionDecision`
allow/deny/ask,比 exit 2 更细)。官方文档:`docs/en/hooks`、`docs/en/hooks-guide`。

| 官方事件 | sulde 实现 | 状态 |
|---|---|---|
| UserPromptSubmit | intent mirror/纠正风暴 + kb_recall(三闸注入+平台探测+会话去重)+ skill_trigger | ✅ |
| SessionStart | kb_freshness(INDEX sha256 比对后台重建)+ 预热 + kb_stale_session(闲置>4h 提醒,防 ap-0181) | ✅ |
| PreToolUse | intent guardian 全工具前置裁决 + kb_guard(dev 写 knowledge/ 硬拦)+ postmortem 提醒 | ✅ |
| PostToolUse | intent guardian 完成/验证债务 + kb_feedback(Read-after-inject 采纳信号) | ✅ |
| PostToolUseFailure | intent guardian 失败闭合并保留 inconclusive/验证债务 | ✅ |
| PreCompact | 注入去重态清理(见①) | ✅ |
| Notification | kb_notify(osascript 桌面通知,60s 去重,SULDE_NOTIFY=off 可关)(v0.3.6, `310dfaa`) | ✅ |
| Stop | 只回收缺失完成回调与未闭合 Skill；不承担生产写入 | ✅(轻量闭合) |
| SubagentStop | 委托产物已由主流程验收,重复挂钩是噪音 | 🚫 |
| SessionEnd | 末端生命周期执行不可靠(3s 钳制;cognee #303 的根因层)。原则:必须发生的事不押末端 hook | 🚫 |
| 结构化裁决 JSON | kb_guard deny 从 exit 2 升级为带理由的 permissionDecision(v0.3.7 四件套, `978238f`) | ✅ |

## ③ 权限与沙箱(Permissions & Sandboxing)

官方能力:`settings.json` 三层(user/project/local)allow/deny 规则表、权限模式
(default / acceptEdits / plan / bypassPermissions)、bash 沙箱。
官方文档:`docs/en/iam`、`docs/en/settings`。

| 官方能力 | sulde 实现 | 状态 |
|---|---|---|
| permissions.deny 规则 | sulde-add-sensitive-file skill:register.py 合并写入项目 settings.json,幂等+首写备份(v0.3.7) | ✅ |
| 权限模式/沙箱 | 使用默认形态,未定制 | ✅ |

## ④ 子代理与编排(Subagents & Orchestration)

官方能力:Task/Agent 工具、自定义 agent 类型(`.claude/agents/*.md`)、后台代理、
Workflow 确定性编排。官方文档:`docs/en/sub-agents`。

| 官方能力 | sulde 实现 | 状态 |
|---|---|---|
| 多代理编排 | 等价替代:codex 委托协议(任务书 brief + launch/verify/active-update 脚本,冷启动规则 ap-0180) | ✅ |
| plugin 自带 agents | bug-hunt"三人排查团队"仍是 skill 文字版;做成真 agent 可真并行 | ⏸ |

## ⑤ 会话管理(Session Management)

官方能力:`--resume`/`--continue`、会话记录(transcripts)、文件编辑检查点(rewind)、
headless(`claude -p`,`--bare` 跳过 hook 发现)。官方文档:`docs/en/headless`。

| 官方能力 | sulde 实现 | 状态 |
|---|---|---|
| resume 长会话 | kb_stale_session:resume 闲置>4h 提醒重启(ap-0181 预警)(v0.3.7) | ✅ |
| 跨工具会话导入 | /import-codex-session:定位 codex rollout 文件只读引入(v0.3.7) | ✅ |
| headless 插件 hook | 实测 `claude -p` 不触发插件 hook(与文档相悖,稳定复现)→ 边界文档在册;补偿:CLAUDE.md 引导主动 kb-search | 📋 |

## ⑥ 插件系统(Plugins)

官方能力:marketplace 分发、插件组件(skills / commands / hooks / agents / MCP)、
版本管理、`claude plugin eval` 评测框架。官方文档:`docs/en/plugins`、`docs/en/plugins-reference`。

| 官方能力 | sulde 实现 | 状态 |
|---|---|---|
| marketplace + 版本管理 | sulde-cc 本体,v0.3.x 系列迭代;运行时状态与版本缓存解耦(SULDE_KB_HOME, WP7) | ✅ |
| skills/hooks/MCP 打包 | kb-search/sediment/import-codex-session 等 skills + 6 hook 层 + sulde-kb MCP server | ✅ |
| 插件热更新悬空路径 | 修复器 fix-plugin-cache-dirs.sh + LaunchAgent(WatchPaths),旧版本目录复活为符号链接;1.3.1 升级实战验证 | ✅ |
| claude plugin eval | 触发消歧话术可做成回归评测;纯优先级排后 | ⏸ |

## ⑦ 界面与自动化(UI & Automation)

官方能力:statusline 定制(`docs/en/statusline`)、定时任务(schedule/cron)、
MCP 客户端、LSP、IDE 集成、`gh` 集成。

| 官方能力 | sulde 实现 | 状态 |
|---|---|---|
| 桌面通知 | Notification 层(见②) | ✅ |
| 定时任务 | com.sulde.kb-weekly-calibrate LaunchAgent:每周日 10:00 自动跑 calibrate.py + 运营统计 → calibrate-weekly.md + 桌面通知(2026-07-31 落地,首报已生成) | ✅ |
| statusline 段 | KB 健康度显示(索引新鲜度/注入命中数);锦上添花 | ⏸ |
| MCP 客户端 | codex 侧消费 sulde-kb MCP(protocolVersion 回显修复 `b4b330a`) | ✅ |

## 决策原则备忘

1. **末端不可靠**:关键动作永不押在会话生命周期末端(cognee #303 的教训)。Stop 只把
   缺失完成回调的已观察事件记为 `inconclusive` 并回收 Skill 栈；SubagentStop/SessionEnd
   仍不承载必须发生的动作。
2. **留白要有触发条件**:⏸ 三项(真并行 agents / plugin eval / statusline)不欠数据
   不欠依赖,只欠"值得做"的证据,出现即启动。
3. **数据驱动调参**:三闸参数(SCORE_MIN 0.55/MARGIN 0.10)维持现值,由周校准报告
   积累真实开发场景样本后按证据调整(元工作会话样本偏置,不作数)。
