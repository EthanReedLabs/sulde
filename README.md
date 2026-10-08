# Sulde — Claude Code / Codex 双宿主工程生命系统

> **Sulde** (Mongolian: ᠰᠦᠯᠳᠡ, the rallying banner) — 面向移动工程的知识、记忆与受约束自治框架。Claude Code 或 Codex 任一宿主都可独立完成感知、召回、L2 起草、L3 隔离执行、治理与器官进化；两端共存时共享同一生命真值，但只允许一个定时调度所有者。

**Status**: v0.8.0 — dual-host engineering life system **+ 意图监督 + 知识库 + 自有记忆栈**:

- **KB 检索层**:354 篇知识(反模式/平台库/案例研究/工作模型),BM25+向量混合检索,
  自动注入 hooks,/sediment 沉淀流,确定性关系图,MCP server,质量飞轮 + CI 门禁
- **sulde-mem 会话记忆**(零 LLM、零 API 成本):CC/codex 三端自动捕获(当轮+滞后+
  压缩摘要收割+rollout 收割),`[sulde-mem]` 独立召回通道(口头禅/内容/跨项目三重门+
  绝对余弦资格门),/memory-distill 蒸馏建图,mem-prune 卫生清理
- **设备漫游**:`mem-sync` 按项目分区经私有 git 仓同步(允许清单制出境+密钥闸门
  mem-secret-scan 前置+每设备独立追加文件零冲突)
- **三端状态灯**:CC 底栏 ANSI 圆点 / codex 启动行 / 桌面异常通知,同一状态核心
- **意图监督闭环**:工作区共享意图契约,持续观察用户纠正、Skill、MCP、工具与副作用；
  可读任务级范围授权、证据门禁的计划内动作自动续行、写后独立验证、高置信语义漂移暂停,
  L3 可在执行中熔断并原地恢复
- **外部副作用证据闭环**:每次写入使用不可变 attempt identity；success 只进入待验证，
  独立读回还必须匹配内容/关系摘要或对象存在性；缺回调/失败/崩溃保持 unknown 并写入
  durable inbox；仅同目标或显式依赖写入阻断，宿主内可读卡片让人证明成功、确认失败、仅复查、
  授权一次新 attempt 或终止，Hook 执行已选迁移；独立 CLI 仅作 break-glass，L3 不会盲重跑，
  worktree 清理前会保留可重放归档
- **事件观察隐私面**:统一脱敏投影支持 `local / approved-export / disabled`；可携带文件绑定
  精确冻结切面与当前宿主一次可读批准，永不隐含网络发送授权，关闭时不扫描事件源且不制造假 0

能力全景见 [`docs/harness-capability-map.md`](docs/harness-capability-map.md),
记忆设计定稿见 [`docs/sulde-memory-design.md`](docs/sulde-memory-design.md),
检索契约见 [`docs/kb-retrieval-contract.md`](docs/kb-retrieval-contract.md)。
意图监督协议见 [`docs/intent-guardian.md`](docs/intent-guardian.md)，统一事件契约与只读
观察面见 [`docs/event-observability.md`](docs/event-observability.md)。

> Earlier v0.1.x releases (MIT) targeted any N-end split. v0.2.0 narrows scope to mobile to honestly reflect what's been battle-tested. Non-mobile users: stay on v0.1.x (`/plugin install skills@sulde-cc@0.1.0`) or wait for v0.3+ N-end re-entry.

---

## What you get

- A **plugin** (`/plugin install ...`) that adds:
  - **意图与执行 skills**:
    - `intent-guardian` — 镜像并确认人的真实意图，把 Skill/MCP/tool/副作用保持在一条可审计谱系
    - `coordinator/writing-task-md` — gates task dispatch through a structured task-md contract (5-step baseline verification enforced by hook)
    - `coordinator/configure-sulde` — 8-mode setup / migration / team-management dispatcher (`init`, `migrate-from-v0.1.0`, `add-frontend`, `add-team-member`, `add-sensitive-file`, `add-scaffold`, `add-skill-trigger`, `end-grace`)
    - `coordinator/multi-source-review` — major-review 4-class triage to prevent single-source misjudgement
    - `dev/assign` — executes a task-md (baseline verify → run → verify-strict → handoff)
    - `dev/handoff` — formalises the 5-section handoff format
  - **11 enforcement hooks** (Python entrypoints + git pre-commit bash):
    - PreToolUse Write/Edit — task-md baseline section, handoff 5-section format
    - PreToolUse Bash — block `cd` into frontend dirs (context-pollution prevention), require `git as-<alias>` commits
    - UserPromptSubmit — skill-trigger reminders, perf-gate (no fixes without measurements)
    - SessionStart — inject CLAUDE.md head + optional baseline / health scripts via `additionalContext`
    - git pre-commit — branch protect, branch format, commit-alias, AI-traces (4 bash hooks)
  - **知识与记忆 skills**:`kb-search`(混合检索)、`sediment`(引导式沉淀)、
    `memory-distill`(会话记忆蒸馏建图)、`import-codex-session`(codex 会话导入)
  - **8 user commands** — `/sulde-init`, `/sulde-migrate-from-v0.1.0`, `/sulde-add-*` (×5), `/sulde-end-grace`
- A **project template** (`template/_project/` + `template/{android,ios,flutter,harmony}/`) — root skeleton + 4 stack skeletons, `/sulde-init` copies them into a new project ~5 minutes.
- A **methodology document** (`docs/METHODOLOGY.md`) explaining the layers the skills sit on.

## What you don't get (by design)

Sulde is **factory-state mechanism**, not populated content. You bring:

- Your design source (Pencil / Figma / Sketch / custom MCP)
- Your anti-pattern catalog (3 mobile examples ship; you accumulate the rest from actual incidents)
- Your team identities (`git as-X` aliases configured via `/sulde-add-team-member`)
- Your domain rules (which files are sensitive, model-selection thresholds, language conventions)

## Prerequisites

- **Claude Code 或 Codex CLI**（至少安装并登录一个；另一端不是依赖）
- **Python 3.10+** with `pyyaml>=6.0` — bootstrap 会在共享 venv 中安装运行依赖；需要手工
  补 hook 依赖时，从当前源码根或 staged `runtime/` 执行:
  ```sh
  python3 -m pip install -r /path/to/sulde-runtime/hooks/requirements.txt
  ```
  Without pyyaml the hooks gracefully degrade to no-op + a stderr warning (your workflow does not break)
- **Git** with bash available (Windows: Git Bash or WSL2)
- **Stack-specific build tools** per frontend (Gradle / Xcode / Flutter SDK / DevEco Studio)

If Python 3.10+ is unavailable in your environment, install v0.1.x instead (MIT, no Python dependency).

---

## Install / 新设备接入指南

> 本仓库(sulde-pro)为**私有仓**。新设备接入的前提:该设备的 git 能访问本仓库——
> 用你自己的 GitHub 账号完成 `gh auth login`(或配好 SSH key),协作者需先被仓库邀请。

### 第 1 步:选择一个独立宿主

Claude Code：

```sh
claude plugin marketplace add EthanReedLabs/sulde-pro   # marketplace 名为 "sulde"
claude plugin install sulde-cc@sulde
```

Codex：

```sh
# 推荐：先只预览，再执行一体化安装/升级
python3 /path/to/sulde-pro/scripts/release/install_codex_plugin.py --dry-run
python3 /path/to/sulde-pro/scripts/release/install_codex_plugin.py --json
```

安装器把自包含 marketplace 写入新的持久版本目录，验证 Skill/hook/runtime 后才切换注册，
随后刷新带规格版本与摘要的六个稳定 launcher，事务性同步 Codex 全局派单纪律，并以
`synthetic_smoke` 验证原生模型档位渲染、意图建立、`PermissionRequest` Adapter 协议和
未批准 MCP 写阻断；合成烟测不冒充真实宿主证据。安装同时在工作区外生成权限受限、
与 launcher manifest 交叉绑定的本机脚本效果快照；只有解释器、脚本内容和 argv 契约都
精确匹配时，已声明的验证脚本或限定本地写脚本才获得确定效果分类；不透明执行只记审计，
无法解析的本地/外部写入仍受监督；同名伪造维护脚本、密钥外发和破坏性漂移继续失败闭锁。
Git 属于 Agent、人和宿主安全共同负责的执行域，Guardian 不解析子命令、不授权、不阻断也不
产生验证债务，只记录调用发生。
安装器还会扫描仍可能被恢复会话持有的旧 Codex 缓存，只把其中两个平台 Hook 启动入口
替换为稳定桥；旧 Skill、文档和 runtime 字节保持不变。稳定桥在每次调用前校验当前 runtime
及 Codex Adapter 表面摘要，再转发到当前安装版本。切换前先为每个真实旧缓存做整树快照；
Codex 清理缓存后先恢复静态树，再仅覆盖两个 Hook 入口，安装失败则恢复安装前整树。此前
中断遗留的部分目录只有在持久 artifact 完整、无符号链接且版本描述符精确匹配时才自动修复。
任一步失败会恢复旧 marketplace/plugin、launcher、scheduler owner/runner、actor 文件和加载
状态；旧 artifact 不删除。安装成功固定输出 `status=generation_verified`：source、artifact、
installed runtime、launcher、scheduler owner 和已加载 actor 已在同一事务中切到同一代，
`scheduler_reconciliation_command` 为空。结果中的整体 `operational_ready=false` 仅表示真实
宿主 Hook 尚未验证；若 `kb_initialization_command` 非空先完成模型、索引与记忆库初始化，
最后在当前或新 Codex 会话产生真实 Hook 证据并运行 doctor，才可由组合门禁得到整体 ready。
`interactive_supervision.status=live_unverified`
会一直保留到该过程完成。升级前已打开的会话在下一次 Hook 即使用新控制运行时；只有新增或
修改过的静态 Skill 发现目录仍需新开会话加载。产生真实提示后可运行
`intent-guardian doctor --workspace /path/to/project --provider codex`，只有
当前 session 的原生批准边界为 `live_verified` 才能依赖人工决断；否则保留提案并修复/重载 hook，
不要反复发送批准文本，也不要用复制 `approve-proposal` 命令冒充人工审阅。Codex 人工提案会
在当前对话显示可读的原生 Allow/Deny 确认框；人只需审阅并按一次 Enter/Allow 或 Deny，
无需回复固定短语、复制摘要/指纹/命令，也无需打开额外终端。提案预览不产生权限，
直接运行受保护命令也会因缺少配对的 `PermissionRequest` 而拒绝。
人工提案仍会
冻结一个不含任何批准或工具权限的续接包；重启恢复原 thread 或在同一工作区新开 thread
时由 `SessionStart` 自动恢复结构化任务上下文；这只是进程真正中断后的恢复手段，不是
Codex 正常批准所必需的步骤。人工只阅读自然语言 `decision_card`，digest 仅在后台绑定。
卡片对应的 DecisionRequest 持久保存 request、工作区、revision、卡片/提案摘要、路由与
过期时间；SessionStart 在新 thread 恢复的是同一问题而不是批准权。Codex 的初始意图、
修订方案、暂停恢复和外部效果选择都复用当前对话的 Allow/Deny 表面；固定文字只会提示使用
原生卡片，不会落授权。缺失问题只会先恢复卡片，不能补造授权，
同一决定重放幂等，相反决定、过期请求或串工作区回复失败闭锁。
确定性、低风险、仅本地、范围明确、可回滚且无未知项的提案可走独立 `agent-policy`
决断；完全落入已登记、一次性、宿主本地、摘要绑定且可独立验证的中风险机械链也可走同一
通道。已在可读任务范围声明的可逆外部效果由 Agent 执行并保留验证债务；主观、公开/新受众、
破坏性、有费用、密钥外发、范围不明或无法验证的事实/选择转人工。缺少活动契约时 Agent
可用 `prepare-proposal` 自动建立不授予权限的 shadow 契约。
可读卡片还可冻结少量登记过的“一次性自动续行动作”。它不是宽泛 auto-approve：当前
仅支持一条插件维护链——官方 helper 生成唯一 cachebuster 后，事务化重装当前工作区的 Codex
Sulde 插件；两步在同一张卡中各限一次，后一步绑定前一步完成后的未来工作树，并固定解释器、
helper/Codex/安装脚本摘要、manifest、artifact 与安装根、回滚和专用独立验证器。另有一条更窄的系统策略允许当前
宿主写入 1–3 条、最多 6 个实体的本地 `memory_annotate`，写后逐字段读取 SQLite；超限、
归属不符或无法证明时保持 unknown 并通知人补充事实。已密封且可证明的机械步骤由监督器执行，
不再要求人工复制摘要或回车；公开发布、费用、密钥、破坏性和范围扩大永不继承该授权。
临时 worktree 删除后可用 `intent-guardian doctor --scan --provider codex` 找出 orphan
契约；路径迁移必须由人执行 `rebind-workspace`，迁移后的契约保持暂停并要求重新批准意图，
不会把旧授权静默带到新目录；已放弃的 orphan 使用人类 `retire-workspace` 归档关闭。
staged plugin 的 `.codex-plugin/generation.json` 固定 runtime 全树摘要；安装后的
`deployment-generation.json`、稳定 launcher manifest 与 scheduler owner 必须逐字段指向同一
generation。调度入口每次执行前都会拒绝 `.git`、`__pycache__/*.pyc`、runtime 根或树内
symlink、摘要漂移和 authority 分叉；稳定 POSIX/Windows runner 自身的精确摘要也同时写入
descriptor、owner 与任务 action，并只向子进程传递环境白名单。切换前会同时枚举已加载和已安装的 `com.sulde.*` actor；
只有精确退役清单可归档并写入幂等 tombstone，任何未知 actor 都会在注册切换前失败闭锁。
历史整树 symlink 只可由同版本、无 symlink 的持久 artifact 物化为真实目录；回滚不会重新创建
这些链接，也不会让旧 repair actor 复活。
升级事务会在切换注册表前复制旧 runtime 和每个真实旧缓存整树，并把旧缓存绝对路径固定到
切换前的字节；验证新版本后只把旧路径的 Hook 入口切成摘要绑定的稳定桥，不把整棵旧路径
软链到新 runtime。
安装结果分别披露 Hook 与静态 Skill 生命周期。旧入口的摘要绑定稳定桥只能更新宿主仍在
调用的 Hook 代码，不能重建已经丢失的 PreToolUse 订阅；因此安装默认报告
`hook_restart_required=true`，直到重启后的真实负向 canary 同时证明执行前拒绝和 marker
未产生。任何 Post-only 物化拒绝都会锁存为监督缺口，使 doctor 保持 degraded；静态 Skill
清单更新同样需要新开 Codex 会话。SessionStart 本身不再清除该缺口；只有同 provider、
session 和 runtime generation 的精确负向 canary 先产生可信 Pre 拒绝、随后确认没有 Post
执行且 marker 不存在，才能生成一次 proof receipt 并复位该会话。

如需手工构建，仍可使用 `stage_plugin.py --target codex --platform posix --output <空目录>`，
再自行注册 marketplace 和插件；Windows 把 `posix` 换为 `windows`。裸
`integrations/codex/plugins/sulde` 只是开发期 hook adapter，不是完整发布件；独立运行必须
安装 staged marketplace，才能同时获得 runtime、三项知识/记忆 skill 与 358 篇语料。

双端可以同时安装。它们读写同一个 `$SULDE_KB_HOME`，不各自复制记忆、SELF 或
L2/L3/L4 状态。完整协议见
[`docs/dual-runtime-contract.md`](docs/dual-runtime-contract.md)。

> 开发机例外:开发机直接把本地克隆目录加为 marketplace
> (`claude plugin marketplace add /path/to/sulde-pro`),改代码即时生效;
> 使用机一律走上面的 GitHub 源。

### 第 2 步:初始化 T1.5 检索索引(一条命令,仅首次)

```sh
# Claude Code 安装件
bash ~/.claude/plugins/cache/sulde/sulde-cc/*/scripts/kb/bootstrap.sh --host claude

# Codex：安装事务已原子完成 scheduler generation；若命令非空，执行其
# kb_initialization_command，再在当前或新会话用 doctor 验证真实 Hook。
# 开发源码也可显式执行：
bash /path/to/sulde-pro/scripts/kb/bootstrap.sh --host codex
```

建 venv、预下载中文嵌入模型 bge-small-zh-v1.5(~100MB)、构建混合索引到
`~/.sulde/data/kb`(与宿主及版本缓存解耦,插件升级零手工)。公共稳定启动器位于
`~/.sulde/bin`；`SULDE_HOME` 可整体迁移该中性目录。`SULDE_KB_HOME` 仅保留给显式
portable/test home，旧 Claude 数据目录只作为一次性迁移源，不再承担运行时职责。

### 第 3 步:选择唯一后台调度宿主(macOS)

```sh
# 二选一；先 dry-run，再安装
scripts/kb/install-agents.sh --dry-run --provider codex --runtime-root /path/to/installed/plugin/runtime
scripts/kb/install-agents.sh --provider codex --runtime-root /path/to/installed/plugin/runtime --accept-llm-data-egress

# 若由 Claude Code 独立承担后台认知，则把 codex 换成 claude
```

安装器会把认知提供方与 L3 执行提供方同时写入全部 LaunchAgent。两端使用相同的
`com.sulde.*` 标签；确认 dry-run 的出境边界后还须显式传
`--accept-llm-data-egress`。后一次安装会原位接管，不会生成两套并发任务。选定提供方
缺失时任务明确失败，绝不静默调用另一端。

### 到此即得(零服务依赖)

- **T0/T1**:354 篇知识(反模式/平台库/案例研究/工作模型)随插件分发,frontmatter 自描述 + INDEX.md
- **T1.5**:BM25+向量混合检索(`kb-search` skill)+ 每轮对话自动注入(三闸控噪)
- **sulde-mem**:会话记忆自动捕获+召回(memory.db,原文直存零 LLM;压缩/清屏/换会话
  不丢上下文),状态灯常驻底栏
- **多层 hook**:意图镜像 / Skill-MCP-tool 监督 / 注入 / 索引保鲜 / 写守卫 / 采纳反馈 /
  失败与轮次闭合 / 压缩防失忆 / 桌面通知
- **意图守护**:同工作区 Claude/Codex 共用一份契约；Skill/MCP/tool 调用进入审计，
  `shadow` 标定后可切 `enforce`；物质写入按可读任务范围执行，事件摘要不再授权；小批量
  本地记忆和登记 continuation profile 提供更强机器证明，全部仍要求独立回读验证

### 全局纪律接线(一次)

把仓库正典中的 Sulde 纪律以幂等标记块接入 Claude Code 与 Codex 的全局规则文件:

```sh
# 二选一；双端共存时可分别执行
python3 /path/to/sulde/scripts/kb/configure-global.py --install --target claude
python3 /path/to/sulde/scripts/kb/configure-global.py --install --target codex
```

命令只管理 `<!-- sulde:rules:begin -->` 到 `<!-- sulde:rules:end -->` 标记块,
不会改动块外用户内容。升级后可重复运行;检查状态用 `--check`,移除接线用
`--uninstall`。

### 底栏状态灯接线(一次,推荐)

bootstrap 会在 `${SULDE_HOME:-$HOME/.sulde}/bin/` 生成**稳定路径启动器**(自动解析最新插件
版本)。每个启动器携带 spec、入口和 sealed generation 摘要；正常成功路径只核验目标与
交付 seal，完整运行时摘要留给显式 deep probe，摘要不匹配时明确红灯并拒绝猜测。
只需修复接线而不安装依赖、下载模型或重建索引时运行：

```sh
bash /path/to/current/runtime/scripts/kb/bootstrap.sh --launchers-only --host codex
```

如果报错明确包含 `runtime digest changed` 或发现 `__pycache__/*.pyc`，使用受限恢复模式：

```sh
bash /path/to/current/runtime/scripts/kb/bootstrap.sh --launchers-only --repair-generated-bytecode --host codex
```

它只会在删除字节码后的其余运行时树与 sealed generation 完全一致时执行；
任何源码、软链接或其他文件漂移都会拒绝修复。

`~/.claude/settings.json` 加:

```json
"statusLine": {
  "type": "command",
  "command": "~/.sulde/data/kb/venv/bin/python ~/.sulde/bin/sulde-statusline.py"
}
```

Windows 把 `python3` 换成 `python`,路径用实际家目录绝对路径。statusLine 是
用户级设置,插件无权自动接管——这一条是全套接入里唯一需要手写 settings 的。

### Windows 后台任务接线(一次)

Windows 原生环境用 PowerShell 安装等价的用户级计划任务。安装器会创建:

- `Sulde-Codex-Harvest`:每 30 分钟增量收割 Codex rollout,纯本地、零 LLM;
- `Sulde-Daily-Distill`:每天 09:30 先运行密钥扫描闸门,通过后调用一次选定的
  Claude Code 或 Codex,最多发送约 40,000 字符的本地记忆做蒸馏;发现密钥即阻断外发。

Distill 涉及每日 LLM 调用与数据出境,因此必须显式传
`-AcceptDailyLlmInvocation` 并选择宿主。先 dry-run,确认后再安装:

```powershell
$plugin = Get-ChildItem "$HOME\.claude\plugins\cache\sulde\sulde-cc" -Directory |
  Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
& "$($plugin.FullName)\scripts\kb\install-agents.ps1" `
  -DryRun -Provider Codex -AcceptDailyLlmInvocation
& "$($plugin.FullName)\scripts\kb\install-agents.ps1" `
  -Provider Codex -AcceptDailyLlmInvocation
```

两项任务仅在当前用户登录时运行(不存 Windows 密码),分别使用 20 分钟/2 小时
执行上限并禁止并发重复实例。卸载:`install-agents.ps1 -Uninstall`。

### 可选增强

- **codex 侧**:按第 1 步安装 staged Sulde marketplace——启动状态灯 + 每轮 kb+mem 自动
  注入 + `kb-search`/`memory-distill`/`sediment` 三项 skill；或仅配
  `[mcp_servers.sulde-kb]` MCP 按需查询。插件 manifest 会声明 MCP；手工注册时也只走
  中性稳定入口:`codex mcp add sulde-kb -- "$HOME/.sulde/bin/sulde-kb-mcp"`。rollout 收割等
  LaunchAgent 可先运行 `scripts/kb/install-agents.sh --dry-run` 核对，再去掉参数安装
- **项目记忆设备漫游**(运输层 Fernet 加密):新设备三步曲——
  ① `git clone git@github.com:EthanReedLabs/sulde-mem-sync.git` 到
  `$SULDE_KB_HOME/mem-sync-repo`;② 从旧设备拷 `~/.config/sulde/mem-sync.key`
  (chmod 600,唯一需要人搬的东西);③ 写 mem-sync.json(repo_path/device_id/
  encrypt:true/允许清单)后 `mem-sync import`。设计约束见
  [`docs/sulde-memory-design.md`](docs/sulde-memory-design.md) §4.2;
  定时导入模板 `templates/launchagents/com.sulde.mem-sync-import.plist`
- **cognee(已退役,2026-08)**:记忆能力已由 sulde-mem 全量自有化,API 成本归零;
  历史 runbook 与回退路径存档于 [`docs/cognee-selfhost/deploy-plan.md`](docs/cognee-selfhost/deploy-plan.md)

### 日常同步

- 拉取知识更新:`claude plugin update sulde-cc@sulde` → INDEX sha256 保鲜 hook 自动重建本地索引
- 反向沉淀:一律走 git(PR 到本仓库,过 SEDIMENTATION-STANDARD + CI 门禁)——git 真源 + 单写者模型即多设备协同方案

### 已知边界

- **Windows**:`bootstrap.sh` 未实测(bash 脚本,建议 Git Bash / WSL2;首装留排雷时间窗)
- **headless**:Claude Code/Codex 的非交互子进程都不依赖宿主 hook 注入；Sulde 器官会把
  所需上下文放进显式 prompt。普通项目任务仍应主动 `kb-search` 并读取命中原文。
- **Skill 观察**:Claude 的原生 Skill 工具可由 hook 直接观察；Codex 当前使用
  `skill-start`/`skill-end` 显式登记。两端都只监督可观察执行边界，不读取隐藏推理。

### Bootstrap a new project

```sh
cd your-mobile-project
/sulde-init
```

The init wizard asks ~8 questions (project name, role, stacks, design source, team, enforcement level, language, OS target), writes `.sulde-config.yaml`, copies the matching templates, installs git pre-commit hooks, and drops a 7-day grace marker so the first week of enforcement runs in lenient mode.

### Migrate from v0.1.x

```sh
/sulde-migrate-from-v0.1.0
```

Reads existing `.sulde-config.yaml`, dry-runs the schema upgrade to `.sulde-config.yaml.v2-preview`, backs up the original as `.sulde-config.yaml.v0.1.0-backup` once you confirm, and drops a 7-day grace marker for re-acclimation.

### Opt-in per project

Installing the plugin enables the local intent guardian in workspace-scoped `shadow` mode, including in non-code writing or résumé folders. It stores the contract under `SULDE_KB_HOME` and makes no extra model call unless semantic critic is explicitly enabled. Mobile engineering gates, KB auto-recall, skill triggers and project-specific enforcement remain opt-in: they activate only after `.sulde-config.yaml` is placed in the project root.

---

## 4 supported stacks (v0.2.0)

| Stack | Template | Notes |
|---|---|---|
| Android | `template/android/` | Kotlin + Compose / View; Gradle wrapper; `adb` |
| iOS | `template/ios/` | Swift + SwiftUI / UIKit / TCA; xcodebuild + `ios-deploy` / `xcrun devicectl`; **macOS only** |
| Flutter | `template/flutter/` | Dart + Widgets; `flutter` CLI; targets Android + iOS |
| HarmonyOS NEXT | `template/harmony/` | ArkTS + ArkUI; DevEco Studio + `hvigorw`; `hdc` |

React Native demoted to v0.2.1+ (see `docs/V0.2.0-DESIGN-v2.md §0.2 #15`).

---

## 5-minute walkthrough

See [`docs/GETTING_STARTED.md`](docs/GETTING_STARTED.md).

## Why a coordinator + N Devs

See [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) — the 7-layer pyramid (project meta → docs hub → design-truth → tasks → handoff → ADR → cross-session memory).

## OS compatibility

- **macOS** — full support across all 4 stacks
- **Linux** — full support for android / flutter / harmony; iOS requires macOS for Xcode
- **Windows** — Git Bash or WSL2 required for git pre-commit hooks; iOS not supported; Harmony fully supported via DevEco; android / flutter work via WSL2 or PowerShell + Gradle wrapper

## Contribute

See [`CONTRIBUTING.md`](CONTRIBUTING.md). The maintainer accepts PRs in bounded areas: anti-pattern ADR additions, stack-specific examples, docs corrections, i18n. Plugin internals (skill structure, hook protocol, template top-level shape) are author-controlled. PRs require a CLA in line with the Business Source License.

---

## License

**v0.2.0 onward**: [Business Source License 1.1](LICENSE) — Change Date 2030-05-25, Change License MIT.

**v0.1.x and earlier**: MIT — preserved in [`LICENSE-v0.1.0-MIT-archive`](LICENSE-v0.1.0-MIT-archive) for the lifetime of the repository.

## Acknowledgements

Sulde grew out of a real multi-end mobile project (one coordinator + two Dev sessions running for 6+ months). The methodology was distilled from ~100 anti-pattern ADRs accumulated during that work. v0.2.0 ships the structural mechanism and three mobile-generic ADR examples; your project supplies its own incident catalog over time.
