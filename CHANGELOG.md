# Changelog

- **Codex 当前会话原生批准桥** — 新增 `PermissionRequest` Hook 与来源隔离的成对审批账本。
  `PreToolUse` 只预检绑定了 provider/session/contract/选择的 `native-decision`，Codex 随后在
  当前对话展示可读 Allow/Deny 卡；Hook 不替人选择，Allow 后命令才消费同一问题并应用提案、
  意图选择或一次性外部效果重试/复查/终止。直接调用、改写说明、跨 session、`dontAsk`、
  `bypassPermissions`、plan 模式和普通聊天回执均不能替代原生批准；人不再复制摘要、指纹、
  固定短语或外部终端命令。安装/launcher/宿主能力契约同时纳入该 Hook。

All notable changes to sulde-cc are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) loosely; versions follow [SemVer](https://semver.org/).

## [Unreleased]

## [0.8.6] - 2026-09-27

- **编排迭代 A(R1–R3 closeout)**:统一受管启动描述与幂等派发注册、行级用量核算、
  代际护栏与准入 fence(observe/block 分档、配额等待移出共享 fence 锁)、
  恢复生命周期与验收真实性修复。
- **预测式执行 B(B0–B5)**:版本化影响预测工件(`sulde-impact-prediction-event-v1`,
  只增不改、修订带证据与理由)、执行中增量事实与冻结触发点判断、纠偏生命周期 v2
  (applied→acknowledged→verified→closed,执行者不可自结算)、经验 TTL 与
  verified 召回驱动预测形成。协议测试 78 项 + 真实会话 dogfood 证据。
  详见 `docs/predictive-execution/`。

## [0.8.5] - 2026-09-27

- **命令效果分类修复（executable/argument 区分）** — `_command_effect` 不再把命令参数/
  路径中的 `deploy` 等关键词当作调用（如 unittest 的 `vpn-deploy/...` 测试路径不再被误判
  external_write 并产生错误验证债）；真实 deploy/scp/HTTP 写入与破坏性组合保持原保护，
  未证明的脚本保留 unknown。经 53 项源码测试、真实/隔离 Hook 链双向对照、打包门禁及
  真实宿主 enforce 正例终验（12/12、exit 0、无新债）验证；已装 Codex runtime
  代际 `0.2.5+codex.20260927061338-6d56455282`。详见
  `docs/command-effect-path-repair-20260926.md`。

- 新增脱敏知识：Docker 平台限定导出与管道、归档完整性验证；微信支付产品、凭据、渠道启停与历史结算。明确自动化和真实交易证据边界，并补充相关互链。

- **mem-sync 重试包络覆盖真实对相运行** — export 与 import 共用 6 小时节拍与同一把事务
  锁,原 `3 次 × 0.1s`(总退避 0.3s)远短于一次真实导出的秒级耗时(数千条 + 加密 +
  git commit),相位一撞 follower 必死;现场观察到输家在 export/import 间轮流出现。
  现改为 `6 次 × 2s` 起步指数退避(总退避 62s),并新增下限测试把「总退避 ≥ 30s、
  尝试 ≥ 5」钉为不变量,防止再次收缩到毫秒量级。调度错开不采纳:它只能避开同时启动,
  管不住慢导出拖进下一窗口;加宽包络对所有碰撞成因成立。

- **被拒标注样本不再卡死蒸馏管线** — `mem-annotate` 的实体类型冲突原本与超时、后端不可用
  一起被压成退出码 `2`，`auto-distill` 遂以 `DistillError` 收场且不推进水位，同一坏窗口被
  无限重放；冲突又排在 `append_candidates` 之前，图谱失败会连坐掉整窗沉淀候选。现在
  `memory_annotation.CONFLICT_EXIT_CODE` 作为唯一协议常量被三方共享，CLI 以该退出码并在
  stderr 输出 `{"code":"memory_annotation_conflict"}` 保留冲突身份；`auto-distill` 将其降级为
  样本级 `AnnotationRejected`，落 `distill-rejected.jsonl` 待人工复核、照常产出 lessons、并让
  水位继续前进。蒸馏 prompt 的 `entities[].type` 同时收敛为固定枚举，与既有
  `lessons[].problem_type` 对齐。后端故障仍按 `DistillError` 保持水位不动。
  本条不改 `sulde-memory-annotation-v2`：`normalize()` 不强制枚举、存量实体类型不归一，
  因为二者都会追溯性作废已存回执的 `rows_sha256`，需单独的 schema 升级承载。

- **Guardian 修复经验沉淀** — 新增反模式 `0250–0252`，覆盖同名方法对象证明、
  可选记忆依赖投影和实际测试解释器前置预检；新增幂等登记、显式会话续接和
  多对象回执锁三个工作模型。发布证据复用、独立结算与真实事件双代际证明并入
  既有工作模型，保留失败历史、隔离/生产证据分层及未知根因；本批不修改运行逻辑。

- **悬浮 UI 迁移的四项可验证经验** — 新增反模式 0253，约束动画重定向的当前帧续接与尺寸包络；
  将透明后代抢滚动变体并入 0151、内容槽迁移变体并入 0248，并升级 ArkUI 滚动壳条目，
  增加安全区只计一次、滚动尾部和固定按钮分别消费的浮层避让规则。旧规则与证据边界保留，
  不将未验证的系统材质或参考光学效果写成成功结论。
  合并保留悬浮底栏窄版的原始证据限制、正反样本和四条独立改写用例。

- **手动全量任务不能继承定时 opt-in 过滤** — 新增反模式 `0249`：同一执行器可以复用，
  但手动与定时入口必须显式拆分选择范围、副作用权限和节流策略；异步调用方只展示终态摘要，
  并把“候选非空但检查数为零”视为待诊断信号，避免空跑成功伪装成没有变化。
- **新 Codex 会话可显式续接同一任务** — `TASK_REVIEW_REQUIRED` lane 新增
  `task-continuation` 原生 Allow/Deny 路由。Allow 通过既有可恢复 native transaction 只绑定
  当前 provider/session 与精确 revision/task epoch；目标同时摘要政策、material sequence、
  授权状态和源/目标 lane。旧 grant、批准回执、open event、pending verification、effect debt、
  continuation token 与其他执行权限均不复制；Deny、跨 session、重放和任务世界漂移保持只读
  失败闭合。不同任务仍必须走新 proposal。
- **Codex 插件 MCP 与 Guardian 稳定入口闭环** — 插件 stdio 声明不再把
  `${PLUGIN_ROOT}` 当作可执行文件名，而是使用 Codex 可解析的插件内 `./` 命令，并按官方
  插件清单约定把 stdio cwd 设为 `.`；Windows staging 生成对应的 PowerShell 路由。安装
  验收现在还会读取 `codex mcp get --json` 的宿主归一化结果，并以该 command/cwd 完成
  initialize，避免自行解释清单或绝对路径手工 smoke 掩盖宿主启动失败。Canonical
  `SULDE_HOME/data/kb` 的 Skill 登记提示也统一投影到 `SULDE_HOME/bin` 稳定 launcher，旧的
  `data/kb/bin` 不再进入新会话上下文。
- **Post-only 物化缺口不再伪装成绿色 Hook** — 未匹配 PreToolUse 的本地/外部物化完成若按
  当前契约本应拒绝，会锁存到对应 provider/session 的 `pre_execution_gaps`；普通 Pre/Post
  配对或 SessionStart 不能覆盖该证据，doctor 保持 degraded，直到同 session/generation 的
  精确负向 canary 被可信 Pre 拒绝、无 Post 且 marker 不存在，并生成 proof receipt。安装器同时区分
  “旧入口可热重绑定”与“宿主订阅仍存在”，默认要求 Hook 重启并以真实负向 canary 收口。
- **MCP 状态查询退出深诊断热路径** — `kb_status` 改读后台原子发布、带 TTL 的 owner-only
  有界快照并显式返回年龄与证据权威；109k 级事件投影和效果债务扫描只留在 doctor/维护路径，
  不再用 2 秒超时把可用状态误报为 backend unavailable。
- **共享消耗型 SKU 的未完成交易恢复边界** — 新增反模式 `0246`：消耗型 IAP 必须把商店
  交易建模为可跨中断恢复的状态机；多个业务权益共用 SKU 时，必须以平台订单标识和持久
  purchase intent 还原原始权益，禁止把历史 owned receipt 认领给当前点击内容。当前现场只
  证明 `ALREADY_OWNED` 与客户端恢复缺口，遗留回执归属和端服修复仍标为 inconclusive。
- **后台交付代际不可变且跨平台可回滚** — staged、installed、launcher 与 scheduler owner
  统一使用一个 runtime generation；`.git`、symlink 与 `__pycache__/*.pyc` 在 stage/install/run
  边界硬失败。POSIX `sulde-scheduled-run` 和 Windows `sulde-windows-task.py` 的精确摘要进入
  descriptor/owner/action 并在每次运行前回验。两端在共享 deployment lock 内先枚举未知/退役
  actor，再冻结 runner、owner 与任务定义；失败恢复完整上一代。Windows 回读同时固定 action、
  runtime、generation、runner 和 `LastTaskResult`，注册完成仍只报告
  `installed_degraded/operational_ready=false`。
- **无人值守人工确认不再卡死，也不把沉默当批准** — 提案新增独立的五分钟重评时钟与
  24 小时人工决断 TTL。完整确定性/低风险/可回滚 Agent 门禁改在展示
  `PermissionRequest` 前执行，通过的任务直接记录 `agent-policy`，无需制造人工点击；人工框
  一旦展示，五分钟后只报告 `host_outcome_unobserved`，不会覆盖可能的 Deny、生成 receipt 或
  扩大权限。24 小时内的晚到 Allow 会重新校验当前卡片和 world-state，过期、已由 Agent
  完成或已被新方案替代则分别返回结构化 `approval_expired`、`already_agent_decided` 或
  `superseded`。已结算 effect-intervention 与已替代 proposal 的开放问题会在安全边界精确
  取消，仍有效的问题和并发到达的真实人工决定保持不变，不再长期假报 `approval_open`。
  `--unattended-policy wait` 可固定为始终等待人工。
- **可信控制命令组合不再制造安全自锁** — 摘要匹配的 Guardian 控制入口若携带管道、
  顺序/条件执行、重定向或替换语法，统一保留为 `invalid-composition` 控制事件：整个 shell
  在启动前拒绝，但不再伪报 destructive、暂停当前 lane 或创建效果债务；独立的真实删除、
  强推、伪造 Hook 与无效 native decision 仍保持 fail-closed。shell 词法与递归只读分类已从
  Guardian 主文件抽到已跟踪的纯 `command_template.py`；lane 级 critic batch 状态并入同样
  无 I/O 的 `task_ownership.py`，避免发布制品消费旧批准摘要未覆盖的未跟踪模块。新增反模式
  `0243` 记录“可执行性违规”和“副作用语义”必须分层建模。
- **精确 Git 暂存不再要求仓库根权限** — 仅单条 `git add -- <明确文件>...` 可生成逐文件
  `write_targets`；每个目标都必须是当前工作树内现存的普通非 symlink 文件，并逐项经过
  allowed/frozen 路径判断。`-A/-u`、省略 `--`、目录、glob、pathspec magic、复合/交互命令
  继续落到受保护的 `.git` 目标，即使契约允许仓库根也不能借此扩大暂存范围。新增反模式
  `0244` 记录 index 串行化和内容授权必须分层，以及旧运行时发布摘要的 bootstrap 边界。
- **真实运行闭环第一轮 P0 稳定化** — workspace 内的任务权限改由 provider/session lane
  显式接管，新 prompt 不再继承旧任务的实质写权限；同一规范化资源的 unknown 效果跨 session
  阻断，retry/reprobe 只向明确接管 lane 发放一次性权限。Hook 观察新增稳定桥签发、短 TTL、
  runtime 代际和精确会话绑定，合成/直接调用不能自称 live；状态页和生命周期改用 active contract、
  新鲜完整 Hook 链、条件式 `PermissionRequest` 与当前效果债务的组合真值。测试统一进入临时
  HOME/CODEX_HOME/KB，并在 test mode 拒绝写生产 KB。Codex 安装结果不再返回含混的 ready，
  后台 actor 只执行摘要匹配的不可变代际、以白名单环境 `execve` 启动，已知退役 cache actor
  在注册切换前停用并归档；旧整树重链脚本退役为不可变 tombstone。效果 dispatch 改成单条
  权威事件，消除 `authorized → dispatched` 两行之间崩溃后既不阻断也不追债的窗口。
- **Codex 固定文字授权退役与同边界结算** — `批准当前方案`、意图确认、暂停恢复、观察导出和外部效果
  选择在 Codex 的 `UserPromptSubmit` 中不再产生任何权限；方案/续接输出也不再向 Codex
  展示这些文字选项，统一由当前对话一次性 `PermissionRequest` 的 Allow/Deny 完成。安装
  smoke 反向验证文字与预览都不能授权。Stop 新建机器可验证债务后会在同一安全边界立即运行
  独立 verifier，已有本机证据不再靠下一条“继续”消息触发结算。Claude 的真实 prompt 回执
  兼容路径，以及越界、泄密、破坏性和不可证明外部效果的人类边界保持不变。
- **已验证的同目标补偿不会再被历史 unknown 自锁** — 历史插件安装若产生部分效果但无法
  证明终态，原 attempt 继续保持 `unknown`；当前契约中新生成、一次性、摘要绑定的
  `codex-plugin-install-v1` 可显式链接同 provider/session、同目标、同 profile 的旧债务。
  只有新安装经专用本机 verifier 成为 `system_verified` 后，旧 intervention 才以追加式
  `system_compensated` 关闭。失败或证据不足时新旧债务均保持开放，未密封写入、不同目标、
  破坏性动作和秘密外发不共享该补偿通道。
- **Codex 长会话当前运行时桥与本机记忆效果收窄** — 插件升级验证完成后，安装器会扫描所有
  旧 Sulde 缓存，只把 POSIX/Windows Hook 启动入口替换为可回滚的稳定桥；稳定 launcher
  校验当前 runtime，桥接器再校验 Adapter 表面摘要后才转发，使恢复中的同一 thread 无需
  丢弃上下文即可使用新 Hook 规则。静态 Skill 快照仍明确要求新会话刷新，安装结果分别披露
  两种 restart 状态。固定 schema、当前宿主归属、1–3 条边、最多 6 个实体且可由独立 SQLite
  逐字段证明的 `memory_annotate` 现在按 `local_write` 建模；超限、归属不符或其他 MCP 写入
  不降级。旧缓存改为切换前整树快照，成功后恢复静态树再仅覆盖 Hook 入口；失败恢复整树，
  遗留部分缓存仅从无符号链接且版本精确匹配的持久 artifact 修复。
- **只读 MCP 中断与外部效果账本分离** — 新增反模式 `0242`：调用完成状态与副作用类型必须
  分开建模，明确为 read 的 MCP 即使缺少完成回调也只保留未完成审计，不得生成外部效果
  attempt、pending 或人工干预；历史误判通过追加式 `abort` 对账关闭并保留原事件。真实写入
  缺少独立读回时仍保持 unknown，并与长寿命会话运行时快照、错误分类塌缩两类相邻根因互链。
- **意图监督 P0/P1/P2 去仪式化与代际隔离** — 权限从不可读的事件 digest 迁移到可读任务级
  scope；旧 `批准事件 <digest>` 只产生迁移提示，不再授权或阻断，PreToolUse 也不再把
  contract 路径和 fingerprint 当成人工操作界面。范围内可逆 MCP/外部效果由 Agent 执行并
  进入证据账本，普通 unknown 降级观察；范围扩大、公开/新受众、密钥外发和破坏性动作保持
  硬门禁。新增 `runtime_generation` 与 `task_epoch`，热更新回调只按唯一 host call/语义配对，
  历史 Skill/read/open-event 自动迁移，历史 unknown 仅阻断同目标或显式依赖链。`report`
  同时披露 current/historical 债务、allowed/denied/degraded/scope-review/hard-safety 指标和
  旧权限迁移计数；只读 `|`、`;`、`&&` 组合及 web read 不再触发人工确认。
- **监督式自动决断与热更新闭环** — 已登记、一次性、宿主本地、摘要绑定、可回滚且有专用
  verifier 的机械续行链现在可由 `agent-policy` 决断，人工只处理主观语义、公开/破坏性/
  费用边界或机器仍无法证明的事实，不再复制 digest、确认 stdout 或按回车充当执行按钮。
  Codex Pre/PostToolUse 在指纹因插件升级变化时，可用同 provider/session 的唯一原生 `call_id`
  加能力、效果、目标和验证摘要继续同一 attempt，跨 session 或语义漂移仍拒绝。安装验证不再
  依赖 PostToolUse 回传 stdout，而是重新读取 artifact、注册表安装路径、两侧整树摘要、版本、
  launcher 与全局规则；遗留 verifying/unknown 在下一安全边界先由系统 verifier 自动复核。
  安装器切换注册表前复制旧 runtime，并将旧版本绝对路径固定为旧字节副本，彻底取消“旧路径
  软链到新代码”造成的同一次调用跨运行时执行。`codex plugin list/help` 与受信稳定 launcher
  的精确健康 probe 同步纳入只读分类，同名伪造脚本仍拒绝。
- **证据门禁的必要步骤自动续行 P2** — 可读自然语言方案现在可显式冻结登记动作的一次性
  continuation grant，绑定验收项、类型化效果、精确目标、解释器/Codex/脚本/最终工作树
  摘要、artifact 与安装根、执行次数、回滚和专用机器验证器；Agent 的“必要/正收益”自述
  不产生权限。首个登记链把官方 cachebuster helper 与事务化 Codex 插件重装冻结在同一张
  可读卡中，各限一次；安装预先绑定 cachebuster 完成后的未来工作树，不能颠倒顺序或降级为
  普通本地写权限。两步分别独立验证 manifest/整树，以及 artifact/安装缓存整树、插件版本、
  稳定 launcher、全局规则与 `codex plugin list`，任一漂移保留 unknown。本地
  `memory_annotate` 增加更窄的固定策略：当前宿主归属、1–3 条边、最多 6 个实体、每 revision
  最多 3 次，并由只读 SQLite 逐字段验真；其他范围内 MCP/外部写入进入通用证据账本。事件级确认或未知分类
  不再暂停整个语义意图，`git blame` 和安全 stderr 丢弃按只读处理，多行人工证据可作为一条
  精确回执解析。
- **可信本地脚本效果契约 P1** — Codex 安装器现在生成工作区外、`0600`、与 launcher
  manifest 交叉绑定的本机快照，逐条固定 Python 解释器摘要、脚本绝对路径与内容 SHA-256、
  声明效果和 argv 语法。只有全部匹配时，`plugin-creator` validator 才按 `read` 处理，
  cachebuster 才按精确 `.codex-plugin/plugin.json` 目标受 `local_write` scope 约束；同名
  异路径、内容/解释器升级、额外或非法参数、shell 串联、manifest 篡改/损坏/宽权限和目标
  symlink 全部按高风险维护边界拒绝。快照纳入安装事务与回滚，外部安装、网络、发布、破坏性和
  未声明脚本不共享信任，消除已知安全脚本执行前批准与执行后人工确认的重复环节。
- **意图守卫决策权/执行权 P0 解耦** — 人只在宿主内阅读卡片并作决定，Hook、Agent 或监督器
  机械执行已授权状态迁移；外部 CLI 明确降为 Hook/账本/宿主通道故障时的 break-glass。
  external-effect unknown 可在当前对话选择证明成功、确认失败、仅复查、一次重试或终止，
  回执在精确事件/控制/观察导出开始时消费，意图 revision 会作废旧回执。命令分类改为先看
  可执行结构，搜索参数中的外部写入字样不再反向暂停；`kb-index search`、`git ls-remote` 与
  确定性 Python 验证命令按只读处理，普通 unknown 在 enforce 下进入降级观察。`apply_patch` 支持
  嵌套宿主载荷且无法解析目标时拒绝；可解析的 Git branch push 生成 remote-ref/OID 后置条件，
  只有独立 `ls-remote` 精确对拍才标记 system_verified。生产 `memory_annotate` 的
  `entities/edges` 批量契约现在冻结为匿名后置条件，并由独立只读 SQLite 逐行核对；缺任一实体或
  关系保持待验证。`memory_graph`、`kb_related`、`event_observe` 与 `kb-index mem-graph` 按真实
  只读能力分类，测试夹具不再用已过时的 `subject/predicate/object` 入参制造假绿。
- **Windows/WSL migration 字节兼容门禁** — 新增反模式 `0241`：SQLx 校验的是已发布 migration 的原始字节而非 SQL 语义；Windows 既有数据库与 WSL/Linux 交叉构建之间必须逐条对照 LF/CRLF checksum，修构建输入而非篡改 migration 表，并用上一稳定 Windows 数据库夹具跑真实升级链。与 `ap-0226` 双向关联，区分“文件被筛选漏处理”和“已选中资源被跨平台改写”两类行尾根因。
- **持久化 DecisionRequest 与控制面自锁修复** — 人工意图/方案问题不再只依赖某次 Hook 的瞬时上下文：append-only 请求现在绑定 `request_id`、意图 revision、可读卡片摘要、工作区摘要、提案摘要、决断路由、状态和过期时间；SessionStart 可跨 Claude Code/Codex 会话恢复同一张卡，但不恢复任何授权。`确认当前意图`、`批准当前方案` 等当前别名只能解析唯一开放问题；请求缺失时先重建并要求重新审阅，过期、被取代、串工作区和相反的重复决定均拒绝，同一决定重放则幂等。Guardian CLI 识别也从“整条命令正则命中”收紧为可信 launcher 摘要与首个可执行参数解析，引用源码名或引号内 `|` 的只读搜索不再被误判成破坏性自授权；Agent 安全控制命令独立审计且不进入普通 open-event 队列，人类控制命令仍不能由 Agent 代跑。
- **仓库终态与暂停控制面不再自锁** — 明确授权整个仓库后，单条 `git add`、非历史改写的 `git commit`，以及只合并一个已知 ref、仅含安全快进/提交选项的普通 `git merge` 作为仓库级本地写入接受监督，不再因内部写 `.git/index`/objects 被误判越界；子路径授权、直接 `.git/*` 写入、复合命令、自定义 merge strategy、merge 恢复控制、`--amend`、hard reset/clean 和 force push 不共享例外。暂停期仅保留目标/计划记录、人工提问、等待/列举/中止协作者等收缩型宿主控制，创建或继续 Agent 与业务副作用仍阻断。
- 修复 Codex 插件只加载 Skills/MCP、`/hooks` 却显示 Sulde `Installed 0 / Active 0`：平台化 Hook 现在打包到宿主约定的 `hooks/hooks.json`，安装与能力契约同步校验该唯一发现路径，避免根目录 `hooks.json` 静默漏载。

- **真实项目验证修复 Agent 决断极性与审计身份** — 本地双宿主重装后的真实仓库旅程发现两处单体测试未覆盖的口径漂移：只读理由中的名词“发布件”被词法后备门误判为外部发布动作，合法低风险提案错误转人工；Agent-policy 提案虽然权威字段正确，`applied_by/consumed_by` 仍沿用 `agent-after-human-approval`。外部动作门现只排除确定的“发布件”复合名词，真实发布仍转人工；提案消费方按实际 human/agent-policy authority 写入执行身份，并由正反回归锁定。
- **统一宿主能力契约与受管运行句柄** — Claude Code、Codex 和受管 L3 不再依赖各自维护的“必需 Hook”清单：staging、安装校验、合成烟测、`doctor` 和状态 JSON 共享 `host_capabilities.py`。契约覆盖 SessionStart、UserPromptSubmit、Pre/PostToolUse、Stop 与 MCP initialize，拒绝双重 Hook 注册；观察结果严格区分 `artifact_ready`、`synthetic_only` 和当前 provider/session/workspace 的 `live_verified`，合成调用永远不能冒充真实会话授权。新增 Adapter conformance matrix，证明 Claude、Codex 和 L3 provider stream 对同一工具生命周期产生一致身份并正确闭合。L3 同时改由 `ExecutionBackend → RunHandle` 持有进程树：provider result、规范化 stop reason 与幂等 dispose 分开落盘，部分输出不能把失败变成成功，只有子进程完全停稳后任务才能成功。
- **持久纠正 InterventionEvent** — 用户或 Agent 纠正现在沿 `proposed → queued → applied/rejected/unsupported/cancelled` 写入脱敏 append-only 账本；只有匹配 provider/session 的真实 PreTool、Stop 或受管 L3 中断边界才能消费排队项。受管纠正会暂停契约并终止完整进程树；`applied` 始终只代表控制动作完成，统一观察面固定保留 `semantic_acceptance=unknown`，不会伪报模型已理解。
- **硬崩溃恢复、审批配对与统一终态闸门** — POSIX 受管进程新增 parent-death watchdog，父监督进程遭硬杀后仍会清理 provider 全树；下次运行只在 append-only 前缀可重放且进程树已证明消失时追加 recovered 终态，损坏尾行保持原样转人工且不启动新 provider。人工提案/事件授权新增脱敏 `asked → decided` 配对账本，拒绝未提问、重复或跨 lane 决定，并由父监督器恢复子进程伪造。运行端和 verifier 现在共用同一 full-quiescence 不变量，Intent、Effect、Correction、Approval、RunResult 或进程清理任一有债务都不能发布成功。
- **版本化观察投影与有界 tail replay** — 统一观察 snapshot 新增 `stateVersion/asOfSeq/sourceRevision`，消费者可区分折叠语义、读取水位和实际来源切面。健康来源按精确逻辑身份、byte offset 与 prefix SHA-256 写入可删除的脱敏缓存；冷读只适配新增 tail。来源重写/截短、撕裂尾部、版本不匹配、缓存 payload 篡改或 symlink 越界均回退权威日志并保留可见违规，不产生幽灵事件。缓存使用 0600 原子整记录替换、64 MiB 上限与 fail-soft 写入，失败只增加重放成本。
- **观察隐私模式与可读一次性导出** — 派生观察面新增 `local / approved-export / disabled` 三态策略；disabled 不发现来源、不读写 cache，并把健康/计数保持 unavailable，而不是伪装成 0，同时不关闭 Guardian 或删除权威事实。可携带导出先冻结同一脱敏投影的精确版本切面，再展示包含范围、数量、目标与排除项的决策卡；Claude Code/Codex 当前 live 会话用“批准观察导出/拒绝观察导出”绑定唯一 asked/decided、session 与回执。批准先消费再原子创建不覆盖文件，失败不可盲重试且从不包含网络发送授权；伪造内部 decision、策略切换、拒绝和完成后的派生 payload 均有回归清理。
- **全发布形态监督纵向验收** — 新增一条从 Claude/Codex staged artifact 出发的真实进程旅程：受管 Codex 进程及后代被纠正中断并证明 quiescent，经当前 Codex Hook 的可读方案批准后在同一 task/contract 新 revision 恢复成功，统一 verifier 接受；随后由 Claude Hook 读取同一真值，并依次验证事件投影冷重放/命中/tail replay、可读一次性导出、disabled MCP 与重新启用后的事实恢复。该旅程发现并补齐 `sulde-correction-pause-v1` Adapter，避免单体账本健康但整体观察误红。
- **长寿命会话审批续接** — `doctor` 现在按当前 provider + native session 判定 Hook 健康，不再用另一 thread 的历史 live 事件误报可批准；人工提案自动冻结 digest 绑定、脱敏、限长且不携带任何授权的续接包。Claude Code/Codex 的 `SessionStart` 在重启恢复原 thread 或同工作区新建 thread 时注入目标、保护/拒绝边界、验收与有限可见对话，新会话再独立取得批准回执，避免“重复批准无效”和“新开会话丢上下文”二选一。
- **Codex 派单档位强制适配** — 新增可发现的 `dispatch-task` skill 与稳定 `model-dispatch` launcher；“给 Dev 发送”、任务返修和继续原任务必须经目标宿主渲染，Codex 默认得到 `gpt-5.6-sol/terra/luna + high/medium/low`，当前更高档位则保留。渲染器机械拒绝 Claude 型号、thinking 与 `/mode`/`/assign` 泄漏；Codex 安装器事务性同步并校验全局 AGENTS 门禁，以真实安装态 dispatch smoke 防止只改源码或模板的假修复。
- **Codex 意图批准接线与孤儿契约闭环** — 精确批准、暂停和恢复 prompt 在运行时失败、超时或缺少匹配回执时失败闭锁；批准回执绑定 intent revision、workspace、provider、native session 和事件来源，提案应用后一次性消费。安装 smoke 明确标记为 `synthetic_smoke`，`doctor --provider` 按 Claude/Codex 分别证明真实 UserPromptSubmit，不再把另一宿主或直接 adapter 调用算作当前宿主健康。`doctor --scan` 可发现已删除临时 worktree 留下的 orphan contract；仅人可执行的 `rebind-workspace` 会归档旧绑定、作废旧授权并强制在新路径重新批准意图，放弃的 orphan 则由 `retire-workspace` 进入 closed 终态。
- **Codex MCP 发布件闭环修复** — Codex staged runtime 现在携带 `tools/kb-mcp/server.py`；发布校验不仅检查 launcher 自身摘要和 MCP 写入监督，还真实发送 JSON-RPC `initialize`，分别验证发布件 server 与已初始化机器上的稳定 launcher。launcher spec v3 的 runtime 摘要同时覆盖 `scripts/kb`、`hooks/lib`、`tools/kb-index` 与 `tools/kb-mcp`，避免“入口健康但传递目标漏打包或已损坏”的假绿。
- **结构化沉淀 v2 可执行检索闭环** — 五类知识模板统一问题语境、证据状态、适用边界及 apply/skip/pass/fail 四类样本，lint、索引和意图监督器按语义角色消费；自动消费者使用严格 `route` 目的，排除混合边界说明和辅助正文的极性干扰。新增 16 条独立改写 top-1 回归集及真实混合索引 canary，分别报告文档与语义准确率。
- **跨进程会话恢复门禁** — 新增反模式 `0240`：主应用与 Extension/Widget 必须复用同一凭据恢复器，区分密文失效、基础设施错误、断网和真实鉴权失效；可信回退写回后 read-back，并用保留数据覆盖安装验证迁移路径。
- **第三方 SDK 最终产物合规闭环** — 扩展端侧隐私与商店声明方法：依赖锁、传递字节码、最终签名包权限、SDK opt-out、运行时同意、隐私政策和商店表单必须使用同一事实；opt-out 后还要验证 token/别名/标签等核心能力，构建成功或业务未直接调用不再视为合规证据。
- **端侧文本推理请求状态边界** — 新增模型权重、会话 KV、单次生成和 UTF-8 流式缓冲的分层所有权；要求 native context 的拥有者串行化完整生成事务，并覆盖连续请求、并发、取消和跨 token 多字节字符。
- **视觉方向输入契约** — 新增 CameraX 预览、ImageAnalysis 像素、rotation metadata、视觉模型和 landmark 映射的五层校验；API 接收旋转参数不再作为像素已归一化的证据。
- **反模式 `0237`** — 收编异步 native 推理提交与 runner 关闭并发导致 use-after-free；协程取消、布尔关闭标记和异常捕获不能替代提交/关闭的所有权序列化。
- **反模式 `0238`** — 收编 KMP 公共 resources 被误认为自动进入 Android assets；资源可用性必须通过 APK/AAB 内容与安装包环境真实读取验收。

## [0.8.4] — 2026-08-14

- **Windows Codex stdin 转发修复** — `llm-runtime.py` 不再让原生 Codex 继承中间 `pythonw.exe` 的 stdin 句柄，而是在 Windows 上先读取提示词，再通过 `subprocess.run(input=...)` 建立并关闭专用管道；保留 `CREATE_NO_WINDOW`，消除计划任务进入 Codex 后无输出、长期不退出并遗留进程树的问题。回归测试同时锁定无窗口标志和输入显式转发。

## [0.8.3] — 2026-08-14

- **Windows Daily Distill 最后一跳无窗口修复** — `auto-distill.py` 虽已用 `CREATE_NO_WINDOW` 启动中间 `pythonw`，但 `llm-runtime.py` 随后仍以普通 `subprocess.call` 派生 `claude.exe`/`codex.exe`，导致计划任务弹出短暂终端。Windows provider 子进程现在也显式传入 `CREATE_NO_WINDOW`，并在真实 runtime Port 调用层增加回归测试，避免只覆盖中间包装器的假绿。
- **Windows 调度 provider 路径去陈旧化** — PowerShell 当前 `codex` 解析到 npm 的 `codex.ps1` 时，安装器从同一 npm 包的 `codex-win32-*` vendor 中选择原生 `codex.exe`；不再命中 PATH 后方遗留的旧 Scoop 二进制，也不经过会派生 `cmd.exe`/`conhost.exe` 且可能卡住的 `.cmd` wrapper。回归夹具同时放置当前 wrapper、当前原生 binary 与陈旧 exe，锁定后台任务必须使用当前包的可执行体。

## [0.8.0] — 2026-08-12

- **安装态闭环与假同步门禁** — 新增一体化 Codex 安装/升级器：构建新的持久 staged artifact，验证后切换 marketplace/plugin，校验 artifact→缓存整树摘要，再刷新稳定 launcher 并真实 smoke 意图建立与未批准 MCP 写阻断；任一步失败恢复旧注册与 launcher，成功后保留或修复旧缓存绝对路径供长寿命会话续用。六个 launcher 记录 spec、入口、运行时和生成文件摘要，SessionStart 遇缺失或陈旧接线显示红灯；`--launchers-only` 可无模型/索引副作用地快速修复。
- **意图监督闭环** — 新增工作区共享、跨进程原子的 revisioned intent contract；Claude/Codex 混用时保持同一目标真值并按宿主会话隔离 Skill 栈。用户纠正、Skill、MCP、工具、副作用和证据进入统一审计谱系；连续纠正停止盲改，高置信且有证据的语义漂移可暂停。
- **Skill / MCP 运行时监督** — Claude 原生 Skill 与 Pre/Post/Failure/Stop hooks、Codex 插件工具 hooks 与显式 Skill 生命周期登记、L3 provider stream 共同接入。所有 MCP 写入与外部写入按宿主、会话、能力、目标和参数形成一次性事件批准，写后必须独立回读；失败或缺失完成回调保留结果未知的验证债务。
- **不可自授权的人类门禁** — Agent 只能生成绑定基线 revision 和全量候选内容摘要的不可变意图提案；人批准同一 digest 后方可应用。Agent 自行调用批准事件、批准提案、恢复或激活契约按破坏性自授权阻断。L3 逐行监控并能中止 provider，恢复沿用原 worktree 且归档旧终态。

## [0.7.1] — 2026-08-12

- **Claude Code / Codex 混合会话数据身份收敛** — 共享记忆新增宿主限定会话 ID 与独立 `source_host`；Codex adapter 强制标记来源，实时 hook 和 rollout harvest 使用同一业务键，避免双采集重复。新增可审计迁移器，在备份后事务合并历史重复并保留向量、FTS 与关系边；无法证明来源的旧记录明确保留 `unknown`。

## [0.7.0] — 2026-08-12

- **Claude Code / Codex 双宿主独立闭环** — 八个认知器官统一改走仓库自有 `llm-runtime.py` Port，L3 改走仓库自有 `agent-runtime.py`，删除对 `claude -p` 默认值和 `~/.claude/skills/codex-agent` 的硬依赖。两端都有只读认知、隔离 worktree 执行、统一快照验收和可观察失败；显式选中的宿主不可用时禁止跨宿主静默回退。
- **单生命、单调度所有者** — macOS/Windows 安装器把认知与行动 provider 作为同一所有者写入调度环境及 `runtime-owner.json`；两端共存仍共享一个 `SULDE_KB_HOME` 和同一组任务标签，后安装者原位接管。定时认知的数据出境改为显式确认。
- **双发布件自包含** — Claude 与 Codex 发布件都携带运行时 Port、L3 执行器、SELF、任务书、知识语料和调度模板；Codex staged 插件在可发现的根 `skills/` 暴露宿主中立的 `kb-search`、`memory-distill`、`sediment`。bootstrap 可显式选择宿主，Codex 模式不再改写 Claude Code `settings.json`。全局规则与 SELF 同步面也改为宿主中立，Claude-only 不再被旧规则强制委托 Codex。

- **并行长提示 KB 召回稳定性** — 自动召回识别并跳过 harness 生成的委托任务 envelope；未知长提示的检索参数固定保留首尾并限制为 2,000 字符，避免全文 Jieba/FTS/ONNX 开销及 Windows 命令行边界。CLI 失败日志披露原提示与实际检索长度，便于区分输入膨胀和机器负载。
- **KB / memory 召回日志通道契约收敛** — 新增轻量共享 writer/classifier，新写入固定 `source` 并执行严格字段契约；历史读取兼容无 `source` 的旧 KB 行和缺少采纳 envelope 的 mem v0 行，不迁移、不回填。状态、golden、阈值校准、memory replay 与治理采纳统一通道分类，采纳资格对部分或伪造 envelope 保持拒绝并披露未分类行，避免跨通道污染。新增直接写入漂移守卫，覆盖运行时代码中的 Path/open 写入与常见文件名别名传播，防止生产 writer 再次分叉。
- **Memory golden 红例闭环** — 扩展集由 25/28 提升到 28/28（100%）：memory 与 KB 召回入口共用结构化噪声门，阻断固定 headless 系统提示自回声与纯延迟探针，同时保留真实延迟诊断问题；`gm-07` 经复核是多套“三层”概念造成的真值歧义，补齐记忆蒸馏 L1/L2/L3 语义且不放宽阈值。golden 搜索改用只读冻结向量快照，不再因其他 Codex 会话新增待嵌入条目触发 `readonly database`；生产懒嵌入将 SQLite 写锁等待由 100ms 提升至 5s，避免并发会话瞬时 `database is locked`。
- **Memory golden 审核积压清零** — `golden-review` 完成剩余 32 条候选审计：接受 5 条代表性边界/红例、拒绝 27 条通道错配、重复、错误断言或含环境敏感事实的候选；L2 `golden_case.pending` 降至 0，L4 活动目标自动结案。审核完成时完整 golden 为 25/28（89.3%），失败集合固定为既有 `gm-07` 与两条新质量缺口，随后已由召回闭环修复为 28/28。生产端停止把 KB 通道告警写入 memory golden 队列，复用旧报告与结构化 skip cache 避免重复 LLM 付费，并读取追加式人工审计防止已消费候选复活；消费端要求最多 40 字的日志片段必须通过完整 case override 才能接受。
- **Windows 后台任务不再闪现终端** — `Sulde-Codex-Harvest` 与 `Sulde-Daily-Distill` 改由虚拟环境的 `pythonw.exe` 启动，Daily Distill 派生的 `claude.exe` 也显式使用 `CREATE_NO_WINDOW`；保留交互用户权限、原有调度频率、日志和退出码，并新增安装器动作、无标准流及无控制台子进程回归。
- **第八批 L4 沉淀积压清零** — 收编最后 4 条早期存疑项：新增跨设备发布产物架构/版本目录契约与 Android 构建首失败诊断规则；adb 沙箱项归入 `ap-0201`，启动崩溃验收项归入 `verify-build`。
- **第七批 L4 沉淀积压收编** — 新增 AVFoundation 像素缓冲跨协程所有权反模式与证据门禁来源/格式/时序契约；把独立 worktree 扩展为验收归属边界，并补齐治理规则的结构识别、存量迁移和授权重试闭环。
- **第六批 L4 沉淀积压收编** — iOS 真机 probe 参数改用受控 sandbox flag 文件并要求 App acknowledgment；`ap-0048` 补齐 KMP framework link 后必须重打 App 包的产物同源检查；`ap-0161` 增加原生可失败初始化的 Debug 异常取证；`ap-0214` 收敛 `-force_load`/`-u` 与单一链接所有权选择。
- **第五批 L4 沉淀积压收编** — `verify-build` 收敛 iOS 真机枚举交叉验证、安装/持进程启动分工、safequit/PID -1、调试器 signal 9 与 crash grep 非空语义；`ap-0233` 增加 Compose ViewModel 注入路径的诊断隔离边界。
- **第四批 L4 沉淀积压收编** — 新增无损知识判重合并流程，强制双向差集、治理元数据并集与 tombstone 追溯；新增治理观察契约，统一绝对基线、逐搏分辨率、证据范围和暂态到期默认动作。
- **第三批 L4 沉淀积压收编** — `ap-0229` 补齐“采样失败必须是缺失值而非 0”的三态度量；新增历史证据/当前状态时态隔离和 launcher spec/已生成包装器同步两条反模式，并收编双平台进程分支测试守卫。
- **第二批 L4 沉淀积压收编** — `verify-build` 补齐验证脚本 summary/退出码双通道契约与昂贵构建前轻量 preflight；`ap-0201` 收编 adb daemon 沙箱边界、全 UNKNOWN 假产物和设备端参数 quoting；新增端侧小模型结构化输出分层治理。
- **首批 L4 沉淀积压收编** — 新增消息持久化身份收敛与 Kotlin 多模块版本漂移两条反模式；把 KMP/CocoaPods 双重原生依赖所有权并入 `ap-0212`，把受控真机数据夹具和 iOS 真机恢复入口纪律并入 `work-model/verify-build`。
- **Dev git 身份反模式归并** — `ap-0030` 退役为指向 `ap-0028` 的 tombstone；canonical 统一单模块身份错配与跨多个 Dev 模块未拆分提交两个粒度，并补充 handoff/git-log 责任追溯和提交门禁候选。
- **静态 Pod 重复知识完整归并** — `ap-0215` 退役为指向 `ap-0214` 的可追溯 tombstone；canonical 补回旧合并遗漏的运行时注册 archive、`-force_load`、library search path、最终二进制符号断言与依赖升级清单，并明确区分链接输入和 App bundle 资源。
- **器官机会映射修正** — `golden_case` 与 `threshold_proposal` 积压不再错误指向生产器，分别改由 `golden-review` 与 `governance-review` 消费器负责人工审核、真值写入与终态登记；`wp_brief.pending` 明确为等待人工而非器官失败，不再自指触发 self-repair，只有 L3 `failed` 会触发修复升级；错误实验保留为 `inconclusive/rejected` 证据。
- **器官进化闭环** — 生命周期从 L2 积压与 L3 失败发现器官升级机会，冻结基线后一次只起草一个 L3 隔离实验；至少两次独立观察才建议保留或回滚，最终裁决必须由人携证据写入，实验不得自行合并或扩大权限。
- **L2-L4 生命周期闭环** — L2 候选改用稳定 ID、可审计状态迁移并在刷新后保留终态；新增 L3 执行/验收投影与证据驱动的 L4 目标 registry，由心跳及独立六小时 LaunchAgent 驱动。`sulde-status` 读取统一生命周期真值，但不放宽保护动作的人类闸门。
- **L3 验收环境自适应** — worktree 优先使用 pytest；运行环境未安装 pytest 时自动降级到标准库 unittest discovery，避免把测试运行器缺失误判成修复失败。
- **L3 外部修复结案** — 带人工证据的 `self-repair --resolve SLUG EVIDENCE` 允许由主线或独立任务完成并验收后，关闭历史失败项或已批准但由主线完成的任务，同时保留原现场和追加式审计记录。
- **治理绿灯显示分级与知识去重** — 周报把合格项区分为余量充裕、踩线和高位退化并披露真正健康绿灯数；dedup 簇 10 将滚动页壳真值收敛到 Harmony 平台文档，`ap-0147` 保留为可追溯 tombstone。
- **运行时 SELF 受控同步** — 新增 `sync-self.py`，只同步模板中的能力阶梯与真值声明，原子写入前备份，保留心跳生成的目标栈、观察和自评。
- **macOS 本地 Codex 插件缓存修复** — 裸 local-marketplace 插件被复制到 `~/.codex/plugins/cache` 后缺少 staged `runtime/`，adapter 现在从 Codex 配置中的 local marketplace source 反查并验证仓库运行时；新增真实 raw-cache SessionStart 回归，manifest 改用 cachebuster 版本并移除不再接受的旧式 `hooks` 字段。
- **L2 四路起草能力闭环** — 新增 `l2-draft.py`，统一登记 WP 任务书、golden 用例、沉淀草稿与阈值提案；心跳每轮刷新 `$SULDE_KB_HOME/l2/registry.json`。任一路产物源缺失即标记 `degraded`，SELF 不再作为 L2 完成真值。
- **L3 诊断任务与实施任务分层验收** — 人工批准时显式记录任务类型；诊断可归档为 `conclusive`、`conclusive_with_gaps` 或 `inconclusive`，状态使用 `diagnosed` 而非修复成功。带缺口结论必须有完整五段报告和明确证据缺口。
- **记忆采纳率观测链补强** — recall 新增 `opportunity_id/session_id/channel`；采纳检测记录 `classified/skipped/write_failed` 终态及原因；noise prompt 不再阻断上一轮 assistant 回收。治理指标改为按 opportunity 聚合并披露 observation coverage，覆盖不完整时返回 `insufficient`，不再把缺测解释成低采纳。
- **Codex SessionStart 状态上下文 UTF-8 修复** — `sulde-status.py` 现在在入口强制标准流为 UTF-8；此前 Windows 子进程按 CP936 输出，Codex 适配器固定按 UTF-8 解码，中文在写入 `additionalContext` 前已被替换为 `U+FFFD`。新增真实 CP936 子进程与 staged artifact 全链路回归；Codex 适配器升至 `0.1.3`，避免同为 `0.1.2` 的旧缓存继续复用。
- **work-model Dev 侧技能补全** — 新增 `crash-fix` / `perf-diagnose` / `postmortem` / `ui-impl` 双平台合并版，统一通用流程并以 Android/iOS 分列平台差异。
- **原创动作动图与第三方训练数据隔离** — 新增第三方动作数据集的许可证分层方法：代码与结构化元数据可按其许可构建可追溯语料，图片、GIF 和视频必须单独取得训练与生产使用授权；Apollo 动图采用原创生成、逐帧动作规范、来源哈希和专家复核门禁，禁止把参考仓库媒体混入模型训练或产品资产。

- **动作肌群可视化方法** — 新增由生产动作目录驱动主力肌与协同肌组合图的方法，并补充以复合动作族覆盖器械、握法、站距和单双侧变体的全量策略；要求同底图蒙版组合、动作 ID 全覆盖、`catalog_pending` 隔离、深层结构局部展示，并禁止用跨人体投影制造虚假精确度。

- **生成式解剖图谱验证与修正方法** — 新增用权威 3D 解剖概念与网格分别校验分类对应和几何边界的方法；记录整个人体外接框映射导致肌肉标注错位、同源投影自验证产生假通过的失败案例；要求分区/非刚性注册、候选叠加审批和可回退 apply，自动指标不得替代视觉与专家门禁。

- **跨端/iOS 反模式 `0161`** — Objective-C failable initializer 在 KMP 中仍须按 nullable runtime boundary 处理；历史 sandbox 路径先验证，播放器只在用户点击后惰性创建，禁止放入 Compose 列表组合路径。

## [0.6.9] — 2026-08-10

- **WP48 阶段三(第二批):`kb-index` 改为纯 Python 入口,shell 形态 KB 入口归零** — `scripts/kb/kb-index` 由 `#!/bin/sh` 改写为 Python,launcher spec 由 `shell` 改为 `python`;`bootstrap.sh` 自身 2 处对源码 shell 入口的直接调用改经已解析的 venv 解释器。至此 `bootstrap.sh` 中 shell 形态的 launcher 计数为 0。
- **修正此前"阶段三剩余不必要"的判断** — 曾以"`shutil.which("bash")` 本机挑到 Git bash 是对的"为由判定为潜在风险而非现存故障。实测推翻:最小环境(PATH 无 bash,codex 即以此方式启动子进程)下 `<venv python> <KB_HOME>/bin/kb-index search ...` 报 `bash is required to run ...`。**`kb-index` 正是全局纪律模板下发给 agent 的命令主体**(`search` 查知识库、`mem-annotate` 落图谱),`[0.6.4]` 修命令形态、`[0.6.7]` 修 `kb-mcp` 之后,agent 最常用的这条一直不可用。本机有 bash 不等于 agent 运行环境有 bash。
- **单一真值** — 11 个子命令映射改写后与 `hooks/lib/kb_cli.py` 合并,不形成第二份。与 `[0.6.7]` 不同,本轮**未引入解释器选择变更**——`kb-index` 原本已用 venv 解释器,改写只换外壳。
- **回归** — 新增 `tests/test_kb_index_entry.py`(11 个映射逐条比对)、`tests/test_bootstrap_windows.py` 补最小环境 UTF-8 search 与 bootstrap venv 自调用用例。先红后绿。全套 141 passed / 2 skipped / 4 failed(4 项既有,零新增)。两道漂移守卫仍通过且白名单零改动。

> ⚠ **需 macOS/Linux 复验**(与 `[0.6.7]` 同):POSIX 侧仅有静态与参数化证据(shebang、`100755`、命令构造),直接执行 `./scripts/kb/kb-index` 未真机运行。

## [0.6.8] — 2026-08-10

- **子进程文本编码系统治理(同类边界第 8 次暴露后收口)** — 全仓库 58 处 `subprocess` 文本模式调用统一固定 `encoding="utf-8", errors="replace"`(生产 11 处 + 测试 47 处)。此前 `text=True` 不带 `encoding` 在 Windows 上按 locale(GBK) 编解码,遇非 GBK 字节即崩。
- **该缺陷的危险不在崩,在崩得不像编码问题** — 实证:`git show HEAD:scripts/kb/thresholds.json` 的输出含非 GBK 字节 → 读取线程抛 `UnicodeDecodeError` 并死掉 → `completed.stdout` **静默变为 `None`** → 下游 `json.loads(None)` 报毫不相干的 `TypeError`。查到根因需三步回溯。修复 `tests/test_governance_report.py:354`,该项由红转绿。
- **AST 漂移守卫(白名单为空)** — 新增 `tests/test_subprocess_text_encoding_guard.py`,用 AST 全仓解析识别文本模式子进程调用(含别名调用与条件参数),任何未固定编码的新调用即判红。**已实测真设防**:向 `codex-harvest.py` 植入一处 `text=True` 缺 `encoding`,守卫精确定位并判红;还原后转绿。
- **回归** — 全套 134 passed / 2 skipped / 4 failed。此前的 5 个既有失败中,`test_governance_report` 已修复转绿;其余 4 项(`test_golden_expand` ×2、`test_graph_audit`、`test_kb_dedup`)为另一工作线的判定语义问题,本轮未触碰。

> 同类编码边界今日累计 8 处:状态栏启动器、`configure-statusline --check`、`memory.py`、`search.py`/`build.py`/`fleet.py`、`auto-sediment` Git 边界,及本次。前 7 次均为逐处修补;本轮起由守卫兜底,不再依赖"撞上才发现"。

## [0.6.7] — 2026-08-10

- **WP48 阶段三(第一批):`kb-mcp` 改为纯 Python 入口** — `scripts/kb/kb-mcp` 由 `#!/bin/sh` 改写为 Python,`bootstrap.sh:217` 的 launcher spec 由 `shell` 改为 `python`,MCP 链路不再依赖 bash。触发动因是实证:codex 用**最小环境**启动 MCP(PATH 无 bash),稳定启动器报 `bash is required to run ...` 退出,codex 侧表现为 `connection closed: initialize response`,MCP 完全不可用。
- **解释器选择变更(POSIX 同受影响,非纯 Windows 移植)** — 原 sh 用 PATH 的 `python3`,现改用 KB venv 解释器(复用 `hooks/lib/kb_cli.py` 的集中解析),以固定依赖并保证最小环境可用。POSIX 上启动后经 `os.execve` 切换到 venv,保持原 `exec` 的进程替换语义;**Windows 改用 `subprocess.run`——`os.execve` 在 Windows 上稳定触发 `0xC0000005` 访问违例**(本次新发现)。
- **回归** — 新增 `tests/test_kb_mcp_entry.py`;`tests/test_bootstrap_windows.py` 补最小环境握手用例;`tests/test_stage_plugin.py` 的 staged shell `bash -n` 检查保留,`kb-mcp` 转入等价的 Python shebang/compile/模式检查(**未靠排除该文件了事**)。先红后绿:红 `8 failed, 5 passed`,绿 `13 passed`。全套 131 passed / 2 skipped / 5 failed(5 项既有,零新增)。

> ⚠ **需 macOS/Linux 复验**:本轮全部验证在 Windows 完成。POSIX 侧仅有静态证据(shebang、`100755`、命令构造),直接调用 `./scripts/kb/kb-mcp --status` / `--print-home`、稳定启动器握手、`os.execve` 分支均未真机运行。前例:`[0.5.6]` 的 macOS bash 3.2 多字节断词缺陷即 Windows 验证通过后由他机发现。
>
> 阶段三剩余:`bootstrap.sh` 另 2 处源码入口耦合;`shutil.which("bash")` 的通用别名风险;`configure-global.py`/`configure-statusline.py` 两处渲染类评估。

## [0.6.6] — 2026-08-10

- **WP48 阶段二:剩余调用点全部收敛** — `tools/kb-mcp/server.py` 五处(`kb_search`/`kb_related`/`memory_search`/`memory_annotate`/`memory_graph`)、`scripts/kb/mem-golden.py`、`tests/kb-golden-eval.py` 迁移至 `hooks/lib/kb_cli.py`;`mem_recall`/`auto-distill`/`auto-sediment` 三套已治理调用一并收敛。**codex 侧五个 MCP 工具此前在 Windows 上全军覆没**——`AGENTS.md` 里让 codex 用 `memory_annotate` 落图谱的规则一直是条断路,现已接通。
- **`mem-secret-scan` / `mem-sync` 解释器解析收敛** — 两处真正启动子进程的调用改用共享解析。`mem-sync.py:229` 的防重入守卫**行为原样保留**(pyenv 场景下 `venv/bin/python` 是基解释器符号链接,不能用路径 `resolve()` 比较,须用"当前是否已在 venv 内"本质检测——v0.5.9 实战坑),共享层只负责查找解释器,防重入判断留在调用方。新增 `tests/test_kb_venv_reentry.py` 为这条此前无测试保护的守卫补上回归。
- **漂移守卫(本次最有长期价值的改动)** — `tests/test_kb_cli_migration.py` 新增两条全仓库扫描:不得出现新的 CLI 子命令映射、不得出现新的 venv 双候选解析(白名单仅 `kb_cli.py` 与两个渲染类文件)。**已实测其真设防**:向 `codex-harvest.py` 植入一处伪造双候选解析,守卫立即判红。同一根因今日出现六次,靠的就是没有任何机制阻止第七次——补上这条,WP48 才算收口。
- **回归** — 全套 126 passed / 2 skipped / 5 failed(5 项为既有,零新增)。

> 阶段三待办:`scripts/kb/bootstrap.sh` 2 处源码入口耦合;`$KB_HOME/bin/kb-index` 用 `shutil.which("bash")` 会挑到 WSL bash 别名(与 `launch.sh` 曾踩的 WindowsApps 商店别名同类);`configure-global.py`/`configure-statusline.py` 两处仅渲染命令字符串、不启动进程,评估是否值得共享"查找解释器"这一小块。

## [0.6.5] — 2026-08-10

- **WP48 阶段一:KB CLI 共享调用模块** — 新增 `hooks/lib/kb_cli.py`,集中三件事:子命令 → Python 入口的映射、venv 解释器双候选解析、受监控的进程启动。`hooks/lib/kb_recall.py` 与 `hooks/lib/kb_freshness.py` 已迁移,各自的解析实现全部删除。此前仓库有 4 套独立的 venv 解析,映射散布在各调用点——漂移已在发生,不是假想风险。
- **自动 KB 注入在 Windows 上首次可用** — `kb_recall` 此前直启无扩展名的 `scripts/kb/kb-index`,原生 Windows `WinError 193`,且 `except` 把失败与"无结果"写成同一条空日志。UserPromptSubmit 的自动 KB 注入因此从未工作过。同理 `kb_freshness` 的索引重建与预热。
- **失败与无结果可区分(本次最有长期价值的改动)** — recall 日志新增 `cli_status` / `cli_detail`。此前 `recall-log.jsonl` 484 行 `top_scores: []` 无法分辨"搜了没结果"与"根本没搜成",正是该缺陷长期不可见的直接原因。实测新日志:`top_scores` 有分数、`injected: []`、`cli_status: "ok"`——真的是未过注入门槛,一眼可辨。
- **回归** — 新增 `tests/test_kb_cli_launch.py`,覆盖正常空结果、启动失败、非零退出、超时、运行环境缺失五种路径,跑真实 venv 与真实进程启动,先红后绿。全套 112 passed / 2 skipped / 5 failed(5 项为既有,零新增)。

> 阶段二待办:`tools/kb-mcp/server.py`(5 处)、`scripts/kb/mem-golden.py`、`tests/kb-golden-eval.py`、`scripts/kb/bootstrap.sh`(2 处源码入口耦合),以及把 `mem_recall`/`auto-distill`/`auto-sediment` 三处已治理调用收敛进 `kb_cli`。另:`$KB_HOME/bin/kb-index` 用 `shutil.which("bash")` 会挑到 WSL bash 别名,与 `launch.sh` 曾踩的 WindowsApps 商店别名同类,一并归阶段二。

## [0.6.4] — 2026-08-09

- **全局纪律下发的 KB CLI 命令跨平台修复** — `configure-global.py` 此前把 `{KB_BIN}` 渲染成 `$KB_HOME/bin`,两份模板据此写出 `<KB_BIN>/kb-index ...` 直接执行形式。该文件是无扩展名 Python 文本,原生 Windows `WinError 193`。**这两份模板是下发给 Claude 与 codex 的行为指令**——Windows 用户的 agent 照做必然失败,且失败发生在 agent 侧不会回流,规则形同虚设。改为集中渲染 `{KB_CLI}`:Windows 带显式解释器并正确加引号,POSIX 保持直接执行,命令形态单一真值不在模板里分叉。
- **KB 检索/构建/舰队入口 UTF-8 输出修复** — `tools/kb-index/{search,build}.py` 与 `scripts/kb/fleet.py` 在 GBK/cp936 下打印含中文或符号(`❌` U+274C、`•` U+2022)的结果即 `UnicodeEncodeError`。**这意味着 KB 检索在 Windows 上从未工作过**,不只是记忆召回。`[0.6.2]` 修 `memory.py` 时漏了三个兄弟入口;本次收敛为 `tools/kb-index/common.py` 单一实现,四处共用,不再各写一遍。
- **回归** — 新增 `tests/test_configure_global_cli.py`(渲染命令真实可执行,含空格路径);扩充 `tests/test_utf8_subprocess_boundaries.py` 覆盖三入口真实 cp936 子进程。均先红后绿。全套 102 passed / 2 skipped / 5 failed(5 项为既有,本轮未新增)。
- **端到端** — 按全局规则逐字执行 `"<venv python>" "<KB_HOME>/bin/kb-index" search "状态栏 乱码" -k 2 --json`:exit 0,输出合法 UTF-8 JSON、命中 2 条,内容含 `❌` 与中文——正是此前必崩的字符。

> 注:本次是同一根因(`scripts/kb/kb-index` 无扩展名入口 + 子进程 locale 输出)的第 5、6 处表现,治理方案见 §4.2.11(WP48)。

## [0.6.3] — 2026-08-09

- **`fcntl` 硬依赖消除** — `auto-sediment.py` 与 `heartbeat.py` 在模块顶层 `import fcntl`(POSIX 专有),Windows 上直接 `ModuleNotFoundError`,自动沉淀官与心跳两个器官完全不可用;`tests/test_auto_sediment.py` 同样顶层 import,导致 pytest **收集阶段即中断**、整个测试套件在 Windows 上跑不起来。新增 `scripts/kb/file_lock.py` 统一跨平台文件锁(`fcntl.flock` / `msvcrt.locking`),三处调用点共用一份实现,锁语义保持独占+非阻塞+可释放。
- **自动沉淀官 KB CLI 调用跨平台修复** — `auto-sediment.py` 此前默认以 `subprocess.run([scripts/kb/kb-index, ...])` 直启无扩展名 shell 脚本,Windows 上 `WinError 193`——即使 import 通了,一调 `kb_search`/`build` 就死。改为 venv Python 直调 `tools/kb-index/{search,build}.py`(子命令映射见 `scripts/kb/kb-index:35-36`),与 `[0.6.2]` 修 `mem_recall` 同一成方。注入点由 `--kb-index-cmd` 改为 `--kb-index-root` + `--kb-index-python`,生产与测试 mock 汇聚到同一命令生成器,mock 以生产启动真实 CLI 的同一种方式被启动。
- **回归** — 新增 `tests/test_file_lock.py`(真实跨进程文件锁,先红后绿);`test_auto_sediment.py` 由"从未被收集"变为 12 passed。全套 87 passed / 2 skipped / 4 failed,4 个失败为既有项(`test_golden_expand` ×2、`test_graph_audit`、`test_kb_dedup`),本轮未新增。

> 注:`scripts/kb/kb-index` 作为唯一 CLI 入口在 Windows 上不可直接启动,而仓库多处直接 exec 它。今日已在 `prewarm`、`mem-search`、`memory.py` 打印、`kb_search/build` 四处遇到同一根因。建议后续统一治理(给 `kb-index` 出 Windows 可启动入口,或全面改走 venv Python 直调),而非逐处修补。

## [0.6.2] — 2026-08-09

- **记忆召回全链路修复(三层)** — Windows 上记忆召回从未产出过一次注入,根因是同一个坑的三处表现:
  ① `hooks/lib/mem_recall.py` 的 `prewarm()` 用 `subprocess.Popen` 直启无扩展名 shell 脚本 `scripts/kb/kb-index`,Windows 报 `WinError 193`,而它是全仓库唯一的 `mem-embed` 调用点——嵌入批次从未跑过;
  ② 召回入口 `run()` 走同一个坏路径,搜索子进程根本起不来;
  ③ `tools/kb-index/memory.py` 打印结果时按 locale(GBK)编码,记忆内容含 `•` 即崩溃、子进程非零退出。
  三处均改为 venv Python 直调 `memory.py`(沿用 `[0.5.4]` 为 `mem-annotate` 定下的成方),`memory.py` 自身 stdout/stderr 强制 UTF-8。
- **失败不再静默** — 上述缺陷长期无人察觉,因为 `except OSError: pass` 叠加 `stderr=DEVNULL` 双重吞掉。现在预热与召回的异常、超时、非零退出、坏 JSON 一律留痕到 `kb/mem-recall.log`,但仍保证不抛异常、不阻塞 hook(调用方是 SessionStart 与 UserPromptSubmit)。
- **回归** — 新增 `tests/test_mem_recall_prewarm.py`,扩充 `tests/test_utf8_subprocess_boundaries.py`;两处缺陷均先红后绿验证,cp936 用例跑在真实子进程环境而非写 UTF-8 字节的 fixture。全套 52 passed / 2 skipped。
- **端到端验收** — 真实 `memory.db` 召回 `top_scores` 由恒空变为 `[0.735, 0.715, 0.694, 0.5, 0.484]`,注入 2 条并带出知识图谱关联边。

> 注:`0.5.6`–`0.5.8` 三个版本在他机发布,未留 CHANGELOG 条目;其内容见提交 `01b1c88`(bootstrap 多字节变量断词)、`10939ba`(WP31 全局纪律入仓+接线器)、`5371171`(召回组硬隔离)。

## [0.6.1] — 2026-08-09 — 生命体首轮自我改造

- **沉淀官两阶段可恢复(WP43)** — 判定逐条落盘+--resume 续跑+单条超时降级;已付费 LLM 判定不再因中断蒸发。
- **重排分参与召回门(WP44)** — 用 bge-reranker logit 0 绝对边界替代相对分数线(ap-0182 同族缺陷复发修复);golden 81.2%→93.8%。
- **候选积压清零** — 沉淀官消化 50 条候选,KB 295→330 篇,关系图 12→62 边。
- 采纳信号闭环首基线 0.296(阈值待红队评审,禁为凑数调参)。

## [0.6.0] — 2026-08-08 — 生命体里程碑(观察员形态)

- **器官一号·自动沉淀官** — 候选→/sediment 判定→审稿分支,七防线机械化;首刀 ap-0186~0188。
- **器官二号·简报官** — 开场先开口(上次结论/未完结/决策边/待办),35ms 确定性组装,安静原则。
- **器官三号·周质量委员会** — thresholds.json 真源+机器红绿灯+红队条款周报,双降级。
- **脑干·心跳+SELF** — 每 6h 一搏:感知→思考→亲手更新自我+观察日志;观察员模式,宪法守护防劫持。
- 治理层/生命体架构(L3 宪法生命体)设计定稿;法典一补边界声明;召回组硬隔离(v0.5.8)。

## [0.5.5] — 2026-08-07

- **statusLine 自动接线层** — 新增 `configure-statusline.py`(`--install`/`--check`/`--uninstall`/`--force`/`--dry-run`),由 bootstrap 在生成稳定启动器后显式调用:只合并 `statusLine` 键、备份 + 临时文件原子替换、幂等、已有非 Sulde 状态栏默认拒绝覆盖(`--force` 才替换),备份默认保留最近 5 份且只裁剪自身文件。此前 bootstrap 只 echo 一行接线提示,用户从未接线,状态栏一直不显示——缺的是接线层,不是状态采集。
- **Windows 状态栏中文乱码修复** — 强制状态子进程 `PYTHONIOENCODING=utf-8`。此前子进程按 locale(GBK)输出、父进程按 UTF-8 解码,得到一串 U+FFFD;只在父进程侧调编码无法解决,须修在子进程输出侧。
- **启动器 HINT 跨平台修复** — `SOURCE_ROOT` 改用 `pwd -W || pwd`。此前 Git Bash 下写入 MSYS 路径(`/d/GitHub/...`),Windows Python 恒解析失败,四个启动器全部静默回落到版本化插件缓存,导致对仓库源码的改动在 Windows 上不生效。
- **启动器降级加固** — 状态命令加 1 秒超时;超时、非零退出或空输出一律输出 `sulde ?` 并 exit 0,状态栏永不因 sulde 报错或卡住。
- **回归** — 新增 `tests/test_configure_statusline.py` 并扩充 `tests/test_bootstrap_windows.py`,覆盖含空格路径、JSON 转义、配置冲突、重复安装、卸载保留其余键、备份裁剪、子进程 cp936 编码边界与 MSYS HINT 解析(均先红后绿验证)。全套 43 passed / 2 skipped。
- **补丁记录** — 新增 `docs/codex-agent-windows-sandbox-patch.md`,记录 codex 原生 Windows 沙箱因商店别名 `pwsh.exe` 导致 `CreateProcessAsUserW failed: 5`、且失败伪装成 `status=success` 的坑与修法(该文件位于本机技能目录,无版本管理)。

## [0.5.4] — 2026-08-07

- **Windows 后台记忆任务** — 新增 `install-agents.ps1` 与稳定 `windows-task.py`，幂等注册每 30 分钟 Codex Harvest 和每日 Distill；任务仅在当前用户登录时运行，Distill 必须显式确认每日 Claude 调用与数据出境影响，并在每次外发前通过 `mem-secret-scan` 闸门。
- **Windows 原生蒸馏边界** — Claude stdin/stdout 强制 UTF-8，彻底修复 GBK 遇 emoji 失败；`mem-annotate` 改由 Sulde venv Python 直接执行 `memory.py`，不再依赖 Windows 无法可靠启动的无扩展名 shell 入口。
- **双端分发与回归** — Claude 插件升至 `0.5.4`，Codex 适配器升至 `0.1.2`；新增 Windows DryRun、UTF-8、原生注解及两类 staged artifact 资产测试。

## [0.5.3] — 2026-08-07

- **日蒸馏调度语义修复** — 正常增量恒先行,补蒸降为追加阶段(参数初始化/状态续跑);修复例行参数被拒导致的静默未跑。

## [0.5.2] — 2026-08-07

- **稳定入口层 bin 全套** — bootstrap 生成 `bin/{kb-index,sulde-kb-mcp,mem-sync,sulde-statusline}`(三级解析:env→源→最新缓存),外部接线免版本路径;`install-agents.sh` 一条命令按本机生成并装载全部 LaunchAgent。

## [0.5.1] — 2026-08-07

- **statusline 稳定启动器** — settings 一次接线终身有效;README 双平台接线文档。

## [0.5.0] — 2026-08-07

- **跨平台工件化整合** — 合并 Windows 支线(manifest-first KB/UTF-8 hook 边界/codex 双平台适配/发布 staging/24 测试)与本线(fleet/法典四/缓存钉扎);`runtime_root` 增加开发机回退。

## [0.4.12] — 2026-08-07

- **嵌入模型缓存钉持久目录** — fastembed 默认落系统临时目录被清理蒸发(实证 225 条积压),四加载点钉 `$KB_HOME/fastembed_cache` 并支持自动重下。

## [0.4.11] — 2026-08-07

- **fleet 舰队面板** — 跨项目任务/会话全局视图(自动发现+注册表),滞留>30min 桌面报警,状态灯追加 `任务:N滞`。

## [0.4.10] — 2026-08-06

### Changed

- **确定性 KB 语料清单** — 以 Git 跟踪文件生成可复验的 `knowledge/MANIFEST.json`，统一索引、指纹与新鲜度判断，并支持无 `.git` 的官方发布制品校验。
- **自包含 Codex 运行时** — Claude 与 Codex 制品均由受限 Git 路径确定性暂存；Codex 适配器只引用随包运行时，不再携带 Mac 绝对路径或用户数据。
- **UTF-8 Hook 协议** — Hook 输入、JSON stdout、诊断 stderr 与捕获子进程统一显式 UTF-8，兼容 Windows 原生代码页。
- **跨平台执行权限契约** — Git 索引模式作为发布真值；POSIX 校验实际执行位，Windows 使用 Git Bash 校验 shell 语法并选择 PowerShell launcher。
- **Windows 原生回归覆盖** — bootstrap 同时识别 `venv/bin/python` 与 `venv/Scripts/python.exe`，CI 新增无模型下载的 Windows 暂存制品 smoke，并让 Linux 从暂存入口完成 bootstrap 与质量评估。

## [0.4.0–0.4.9] — 2026-08-05 ~ 2026-08-06 — 自有记忆栈里程碑(补记)

- **0.4.0** 三端记忆捕获全覆盖:codex rollout 收割(WP19)+三面状态通知(WP20)+codex 插件(WP21)。
- **0.4.1** 召回三重门:口头禅提示词(≥6字)/口头禅条目(≥20字)/跨项目相对分数线 0.75。
- **0.4.2** 记忆卫生(WP24):图谱查询按项目过滤+共享边相关性门、捕获三类降噪、`mem-prune` 清理通道(真库清 1281 条)。
- **0.4.3** 跨项目绝对证据门:裸余弦≥0.68,堵归一化 top1 恒 1.0 的穿门漏洞(实测标定)。
- **0.4.4** SULDE 法典:跨项目每会话无条件注入的最高原则集(成本哲学/密钥纪律/真值纪律)。
- **0.4.5** 记忆栈加固(WP26):捕获侧密钥就地脱敏、memory.db 周备份轮转、通知补蒸馏/导出滞后报警。
- **0.4.6** mem-golden 回归集(15 用例含串场事故永久回归)+同项目门 0.55→0.50(双通道分歧标定修正)+积压补蒸模式(WP27)。
- **0.4.7** mem-sync 运输层 Fernet 加密(WP28):去重键明文哈希保免冲突语义,16341 条密文重导;`mem-graph --depth`。
- **0.4.8** 移除 plugin.json hooks 显式声明(与新版 CC 自动发现双重加载,2.1.220 拒载)。
- **0.4.9** venv 双布局解析:Windows `Scripts/python.exe` 与 Unix `bin/python` 全链兼容(五处)。
- 同期非版本化:mem-sync 设备漫游上线(WP23,私有 git 仓+允许清单+密钥闸门)、mem-secret-scan 出境闸门(WP22)、auto-distill 日蒸馏(WP25,headless 订阅通道)、蒸馏三层架构(L2 会话内里程碑标注)、法典第四条边界哲学(0.4.10 后补)。

## [0.3.0] — 2026-07-28 — KB 检索层:契约 + T1.5 本地混合索引 + 自动注入

### Why

知识库沉淀了 275 篇文档但检索全靠 grep/目录导航,"换个问法"即失效;且检索能力需要向其他消费项目分发并为未来 MCP 服务预留稳定接口。本次落地引擎无关的检索契约与四级渐进增强(T0 数据自描述 / T1 目录 / T1.5 本地混合索引 / T2 cognee 增强):**没有任何服务时功能完整,cognee 在场时白拿增强**。

### Added

- **检索标准契约**(`docs/kb-retrieval-contract.md`)与实施方案基线 — 文档 schema(frontmatter 受控词)、`kb.search`/`kb.get`/`kb.related` 查询契约、自动注入三闸、cognee 后端映射、MCP 只读预留;git 真源定案,索引永远是可重建衍生物。

- **frontmatter 全量迁移** — 281 个 tracked 文档补齐 `doc_id`/`container`/`platform`/`summary`;反模式正文平台字段回收(ios 29 / android 27 / harmonyos 11 / cross 51);纯格式 commit 已登记 `.git-blame-ignore-revs`;`scripts/kb/add-frontmatter.py` + `lint-frontmatter.py` 幂等可复跑,SEDIMENTATION-STANDARD 增补必带条款。

- **INDEX.md 目录层** — `scripts/kb/build-index-md.py` 从 frontmatter 确定性生成 275 条目录,`--check` 防陈旧。

- **T1.5 本地混合索引**(`tools/kb-index/`)— BM25(FTS5+jieba)+ 向量(fastembed `bge-small-zh-v1.5`,本地零外发)加权融合,sqlite 单文件索引(gitignored,每端本地构建),manifest 增量,契约 JSON 输出;golden set 症状式盲测 hit@5 = 10/12(`tests/kb-golden-eval.py` 可复跑)。

- **kb-search skill**(`skills/kb-search/`)— T1.5 → T1(INDEX.md)降级检索入口,强制"命中后必读 `source_path` 原文"。

- **KB 自动注入 hooks** — `kb_recall`(UserPromptSubmit:三闸控噪 + 会话去重 + 消费项目平台探测 + jsonl 校准日志)与 `kb_freshness`(SessionStart:索引落后 git HEAD 时后台增量重建);无 `.sulde-config.yaml`/无 pyyaml 的消费项目同样生效,现有 hook 行为零回归。

## [0.2.3] — 2026-07-20 — 多项目沉淀标准 + HarmonyOS/ArkUI 平台维度

### Why

知识库此前只有单一来源项目(Android/iOS)沉淀,结构与措辞都绑定该项目;且 `grep harmony|arkui|arkts = 0`,鸿蒙平台维度完全缺失。本次从第 2 个来源项目(HarmonyOS 原生 + Flutter→ArkUI 转译)沉淀,并把结构升级为**任一后续项目可复用的多项目标准**(加法为主、零破坏既有编号/域)。

### Added

- **跨平台工程基线补充** — tech-docs 补编码基线与设计模式两篇，platform-kb 增 Android/iOS 速查，work-model 补 Dev 侧 4 技能与团队配置模板。

- **work-model 协调端 skills 补全** — 新增 8 个通用化协调端 skill，保留 task md / handoff / pen-truth / worktree / baseline 等完整工作法，并清除来源项目、业务、内部页号、人名与内部路径语境。

- **来源项目 sediment 第二批** — 新增 9 条反模式(`0171`–`0179`，2 条并入既有条目)与 3 篇案例研究(流式连接终态闸门 / 流式快照单调合并 / 请求级单飞与多订阅者广播缓存)。

- **来源项目 sediment 批(案例补遗)** — 新增 2 篇案例研究:《用户已有资产复用与内容寻址分享缓存》(移动端缓存架构)/《异步媒体子页的播放所有权与可见性门控》(iOS 架构实践)。

- **来源项目 sediment 批** — 新增 9 条反模式(`0162`–`0170`，0 条并入)、2 篇案例研究(iOS TCA 条件依赖追踪 / 轮询守卫三值语义)，并为 `verify-build` 增补 iOS 真机 launch 持进程、禁止 CLI 全局 Bundle ID 覆盖、`idevicedebug` 输出优先于 exit code 三条铁律。

- **`knowledge/tech-docs/训练休息计时的暂停与有效时长.md`** — 为训练休息区分墙钟与有效时长，持久化当前暂停起点和累计暂停秒数；覆盖重启恢复、未闭合暂停、截止时间重建及 pause/resume 审计。

- **`knowledge/tech-docs/结构化建档与安全约束贯通训练计划.md`** — 将训练目标、时间预算、器械和疼痛/暂停建模为结构化事实，并贯通周计划、今日调整和手动编辑；要求显式安全确认与建档完成证据，禁止猜测重量或仅在执行阶段补救不安全计划。

- **跨端/iOS 反模式 `0160`** — KMP Kotlin/Native 不得把 Kotlin 值直接传入 `NSLog` 等 C/Objective-C variadic API；format string 不提供 ABI 装箱保证。先在 Kotlin 侧生成单字符串，复杂日志使用 typed native bridge，并以符号化真机报告区分 interop 崩溃与权限/UIKit 时序问题。

- **`knowledge/tech-docs/跨端大模型下载与平台能力门禁.md`** — 跨端共享模型界面的平台能力契约：生产 DI 禁止把可交互入口绑定到 Noop/Stub；iOS 数 GB 模型使用 URLSession 文件下载、`.part` 校验与原子激活，并把下载、校验、加载、推理和硬件加速拆成独立真机门禁。

- **`knowledge/tech-docs/端侧应用隐私政策与商店声明对齐方法.md`** — 区分本地敏感数据访问与 Play/App Store 的离设备收集定义，以统一数据路径驱动中英文政策、权限、Health Apps 声明、Data Safety/App Privacy 和读写删真机证据，并用自动门禁阻止上传路径与旧表单答案漂移。

- **`knowledge/tech-docs/端侧模型异构分层卸载验证方法.md`** — Android 端侧模型 OpenCL 优化的证据驱动方法：先证明真实 accelerator/层/缓冲区卸载，再用同线程冷态 smoke + thermal-aware soak 搜索部分卸载最佳点；配置按 SoC/GPU/系统画像隔离，并以两个不同画像的完整证据作为生产放量门槛。

- **Android 反模式 `0159`** — Compose 懒列表 item 禁止在组合期同步读取音频 metadata 或调用 `MediaPlayer.prepare()`;`remember` 不是异步边界,播放器应在显式点击后惰性创建并异步 prepare。来源按 Layer1→Layer2 标准完成去重与脱敏。

- **`knowledge/SEDIMENTATION-STANDARD.md`** — 项目无关的贡献标准:两层模型 / 脱敏铁律 / 反模式全局 append-only 编号 / 平台受控词 / `dedup-before-add` / curate-to-kb 三门 / 各项目留底约定。`ABSTRACTION-GUIDE.md` 降级为「首个来源项目案例」附录。
- **`knowledge/platform-kb/`**(新类)+ **`harmony/`** 子体系 — 13 篇脱敏 HarmonyOS/ArkUI/ArkTS 平台速查(arkts-language / arkui-components / -incompatibility / -layout-scroll-shell / arkweb / build-toolchain / network-api / real-device-verify / resources-system / routing-navigation ×2 / state-management / translate-rules)。填补 KB 鸿蒙空白。
- **`knowledge/anti-patterns/INDEX.md`** — 按平台 facet(Android/iOS/HarmonyOS/跨端/协调端方法论)导航;反模式 139 → **156**(新增 0142–0158,首批 8 条 HarmonyOS 平台机制)。
- **`knowledge/tech-docs/dart-to-arkts.md`** — Flutter→ArkTS 转译"how to think"层。
- **`knowledge/work-model/`** — `postmortem-generalization` / `cross-stack-parity-loop` / `single-session-task-execution`。
- **`skills/coordinator/`** ×3 — `codex-preflight-scaffold` / `handoff-code-review` / `reverse-source-completeness`。coordinator skills 8 → 11。
- **`knowledge/tech-docs/案例研究/06-HarmonyOS-ArkUI工程/`** — 2 篇 ⭐⭐⭐⭐+ 案例(SSE 流式生命周期与分帧;ArkUI 浮层响应式/宽度/键盘深水区)。案例研究 17 → 19。

### Changed

- **端侧隐私/商店声明方法** — 增加实现阶段与人工发布阶段分离规则；通用继续指令不得触发 GitLab/商店账号操作，外部门禁先记录并仅在负责人明确启动最终发布后执行。
- **反模式 dedup**(补充而非新建):`0141`(截图判布局,+HarmonyOS/+diff 分类)、`0097`(复用绕过,+双真值源静默 bug)、`0041`(规则未应用,+UI 编辑 preflight gate)。
- **案例研究 README** — 加 HarmonyOS 技术栈行 + 域 06;标题扩到 Android/iOS/HarmonyOS。
- **`plugin.json`** — skills 计数 17 → 20(11 coordinator + 9 dev)。

---

## [0.2.2] — 2026-06-30 — 知识库层：案例研究 KB + curate-to-kb + 沉淀回路闭环

### Why

工作模型一直有「修后沉淀」缺口：handoff 堆积、内部 bugbook 冻结、修复经验不复用。本次补齐【两层知识库 + 自维持活回路】，并把跨项目可复用的工程案例沉淀进 `knowledge/tech-docs/案例研究/`。

### Added

- **`knowledge/tech-docs/案例研究/`** — 17 篇脱敏工程案例研究（跨项目复用），5 域：Android 媒体与性能（4）/ iOS-TCA（4）/ 跨端一致性（2）/ 移动端缓存（4）/ 诊断方法论（3）。每篇五段式（场景架构 / 现象+实测 / 根因深挖平台机制 / 解决方案 why-not / 可迁移原则）+ 技术深问。含 README（两层系统 + 活回路说明）。
- **`skills/coordinator/curate-to-kb/`** — 新 coordinator skill：Layer1（bugbook + 反模式）→ Layer2（案例研究）的 curation 上浮流程，含脱敏铁律表 + 三道门质检（C 验真 / A 对齐标杆 / B 脱敏）。coordinator skills 7 → 8。

### Changed

- **`scripts/coordinator-baseline.sh`** — 新增 §7「沉淀欠债」forcing function：`沉淀欠债 = active handoff − 近30天新增 bugbook`，超阈值 SessionStart 告警，防 Layer1 知识库冻结。
- **`skills/coordinator/writing-task-md`** — §0 加 Step 0b「修前必查 Layer1」（review-similar 找前车之鉴）+ Gate1 判定线。
- **`skills/coordinator/coordinator-maintenance`** — §4.2「归档前必沉淀 Layer1」（add-bug 是归档前置）+ Gate2 判定线。
- **`knowledge/ABSTRACTION-GUIDE.md`** — 落点表加「案例研究」类 + 更严脱敏说明（全脱敏，区别于方法论文档保留通用词）。
- **`plugin.json`** — skills 计数 16 → 17（8 coordinator + 9 dev）。

### 活回路（4 门闭环）

baseline 沉淀欠债（让欠债可见）→ 修前必查 Layer1（Step 0b）→ 修后必沉淀 Layer1（§4.2）→ 定期上浮 Layer1→Layer2（curate-to-kb）。

---

## [0.2.1] — 2026-05-25 — Dev skill refactor (shared body + per-stack references)

### Why this release

v0.2.0 shipped 4 mobile stacks (android / ios / flutter / harmony) in template / hooks / build_verify config, but **7 dev skills still had duplicate Android + iOS copies** (`skills/dev-android/X/SKILL.md` + `skills/dev-ios/X/SKILL.md`). To make Harmony / Flutter actually usable from `/ui-impl`, `/crash-fix`, `/perf-diagnose` etc. — without duplicating the skill 4 times — we refactor to **single generic SKILL.md + per-stack references**.

### Breaking(micro)

- **Skill rename**:`ui-impl-android` / `ui-impl-ios`(v0.2.0 stack-suffixed names)→ `ui-impl`(v0.2.1 unified)。同理 `crash-fix-{android,ios}` → `crash-fix`,等 7 skills 改名。
  - **User-facing impact**:Claude 自动 invoke 通过 description trigger,不通过 name string,**绝大多数用户无感**。
  - **Affected**:若你脚本 / hook / config 显式引用 v0.2.0 stack-suffixed skill name(如 `/sulde-cc:ui-impl-android` 全名调用),需改成 `/sulde-cc:ui-impl`。
  - **Why micro**:hook / command / template / plugin.json / .sulde-config.yaml schema 全部 unchanged,仅 skill name string 改。
  - **Rollback**:`/plugin install skills@sulde-cc@0.2.0` 回退到 v0.2.0 名称。

### Changed

- **`skills/dev/<skill>/`** restructured for 7 skills:
  - `ui-impl` — UI restoration / design-truth alignment (deep split, 5 files / 2265 lines)
  - `crash-fix` — Crash diagnosis & repair (deep split, 5 files / 978 lines)
  - `perf-diagnose` — Performance diagnosis gate (deep split, 5 files / 1720 lines)
  - `bug-hunt` — 3-agent bug triage (light split, 5 files / 391 lines)
  - `code-review` — 2-agent code review (light split, 5 files / 546 lines)
  - `parallel-dev` — Worktree-based parallel dispatch (light split, 5 files / 430 lines)
  - `postmortem` — 4-question funnel + ADR (light split, 5 files / 552 lines)

- **New structure per skill**:
  - `SKILL.md` (stack-neutral workflow + decision tree)
  - `references/android.md` (Android-specific commands / patterns / lints)
  - `references/ios.md` (iOS-specific)
  - `references/flutter.md` (Flutter-specific; v0.2.1 placeholder where source unavailable)
  - `references/harmony.md` (Harmony-specific; same)

- **SKILL.md top of each file** has a stack-routing table directing readers to the appropriate `references/{stack}.md` based on `.sulde-config.yaml: frontends[].stack`. No more guessing which Compose vs SwiftUI vs Flutter Widgets vs ArkUI to apply.

### Removed

- **14 legacy duplicate SKILL.md files**:
  - `skills/dev-android/{ui-impl,crash-fix,perf-diagnose,bug-hunt,code-review,parallel-dev,postmortem}/SKILL.md`
  - `skills/dev-ios/{ui-impl,crash-fix,perf-diagnose,bug-hunt,code-review,parallel-dev,postmortem}/SKILL.md`

- The `skills/dev-android/` and `skills/dev-ios/` directory trees are fully removed. All dev skills now live under `skills/dev/<skill>/` with the new generic + references structure.

### Added (placeholders for new stacks)

- `references/flutter.md` and `references/harmony.md` for each of the 7 skills — these contain real commands and patterns where extractable from Freebeat's Android/iOS implementations + general framework knowledge, with explicit `占位说明:v0.2.1 初版` notes where content depends on project-specific stack-library choices.

### Migration

- v0.2.0 → v0.2.1 is **non-breaking for** hooks, commands, templates, plugin.json, manifests, .sulde-config.yaml schema, BSL license, Python dependency. Re-running `/plugin install sulde-cc@sulde-cc` picks up new layout.
- v0.2.0 → v0.2.1 has **one micro-breaking change**(see ### Breaking above):skill name string `ui-impl-android` → `ui-impl` etc. User-facing trigger words / descriptions unchanged — if you rely on Claude auto-invoke via description, no action needed. If you script against the skill name strings (rare), update to the new unified names.
- Same `BSL 1.1` license, same Python dependency, same template/_project + 4 stack templates.

### Notes

- **bug-hunt / code-review / parallel-dev / postmortem** are "light splits" — their workflow was already ~90% stack-neutral; the per-stack references mostly contain stack-specific commands and lint patterns.
- **ui-impl / crash-fix / perf-diagnose** are "deep splits" — the original SKILL.md had substantial stack-specific content (Compose vs XML, Profiler vs Instruments, Hang vs ANR) that genuinely deserves per-stack drilldown.
- Total skill content: 7180 lines across 37 files (vs. v0.2.0 ~5000 lines across 17 files with duplicates) — net more comprehensive, with shared workflow eliminating drift and per-stack references gaining Flutter + Harmony coverage.

---

## [0.2.0] — 2026-05-25 — Mobile-first + Python hooks + 4-stack template

### Scope change (read this first)

v0.2.0 **narrows** the framework's officially-supported scope to **mobile multi-end projects**:

- Supported stacks: `android`, `ios`, `flutter`, `harmony` (HarmonyOS NEXT)
- React Native demoted to v0.2.1+
- Generic / web / backend N-end use cases retire to v0.1.x line (MIT) or wait for v0.3+

If your project is not mobile or you cannot upgrade Python dependencies, **stay on v0.1.x**:

```
/plugin install skills@sulde-cc@0.1.0
```

### Breaking changes

- **Python 3.6+ required** with `pyyaml>=6.0`. Hooks are now Python-based for cross-OS support (Windows/Linux/macOS without bash/sed dependence). Hooks gracefully degrade to no-op + stderr warning when pyyaml is missing — your workflow doesn't break, but you lose enforcement.
  - Fallback path: `pip install -r ${CLAUDE_PLUGIN_ROOT}/hooks/requirements.txt`
- **License: MIT → Business Source License 1.1**. Change Date 2030-05-25, Change License MIT. v0.1.x and earlier remain MIT (preserved at `LICENSE-v0.1.0-MIT-archive`). See `LICENSE` for parameters + Additional Use Grant.
- **Template top-level layout changed**: `template/docs-hub/` and `template/.sulde-config.yaml.example` moved into `template/_project/` for clearer naming. `template/frontend-a/` (v0.1.0 placeholder) replaced by 4 stack skeletons (`template/{android,ios,flutter,harmony}/`).
- **`skills/dev-android/assign/` + `skills/dev-ios/assign/` removed**; replaced by single generic `skills/dev/assign/`. Other dev-android/dev-ios pairs (bug-hunt, code-review, crash-fix, parallel-dev, perf-diagnose, postmortem, ui-impl) preserved for now under name-suffixed identities (no namespace conflict).
- **plugin.json `license: "MIT"` → `"BUSL-1.1"`**. Tooling that filters plugins by SPDX license should be aware.

### Added

#### Hooks (11 total, all enforce v2 protocol)

- **3 Python entrypoints**: `pre_tool_use.py`, `user_prompt_submit.py`, `session_start.py`. Each wraps `import yaml` in a try/except for graceful degradation.
- **7 check modules** in `hooks/lib/`:
  - `check_task_md_baseline.py` — blocks Write of task-mds missing `§起草前 baseline 实证` (coordinator-side, hard severity)
  - `check_handoff_verify.py` — blocks Write of handoffs missing the 5 required sections (dev-side, hard severity)
  - `check_subdir_cd.py` — blocks Bash `cd <frontend>/` to prevent CLAUDE.md context-pollution (medium severity, coordinator only)
  - `check_git_commit_alias.py` — requires `git as-<alias>` commits (medium severity, dev only)
  - `skill_trigger.py` — UserPromptSubmit reminder on trigger regex match (soft severity)
  - `perf_gate.py` — UserPromptSubmit reminder on perf keyword match (soft severity)
  - `claude_md_inject.py` — SessionStart `additionalContext` JSON injection (CLAUDE.md head + optional baseline / health scripts)
- **4 git pre-commit bash hooks** in `hooks/git-precommit/`:
  - `check_branch_protect.sh` — block direct commits to main / develop
  - `check_branch_format.sh` — enforce `dev/<alias>/<slug>` pattern
  - `check_commit_alias.sh` — require `git as-<alias>` via `SULDE_COMMIT_ALIAS` env sentinel
  - `check_ai_traces.sh` — block AI traces in staged paths / diff

#### Skills (5)

- `coordinator/writing-task-md` (updated): §0.5 generalised to mobile-generic (removed Freebeat-specific case names + 双端 → 各 frontend)
- `coordinator/configure-sulde` (new): 8-mode dispatcher — init / migrate / 5×add-* / end-grace
- `coordinator/multi-source-review` (new in v0.1.1, retained): 4-class triage for major reviews
- `dev/assign` (new generic, replaces dev-android/+dev-ios/ pair): §0 baseline verify + §5 verify strict
- `dev/handoff` (new): 5-section handoff format formalised

#### Commands (8 new)

- `/sulde-init`
- `/sulde-migrate-from-v0.1.0`
- `/sulde-add-frontend`
- `/sulde-add-team-member`
- `/sulde-add-sensitive-file`
- `/sulde-add-scaffold`
- `/sulde-add-skill-trigger`
- `/sulde-end-grace`

#### Template (4 stacks + _project skeleton)

- `template/_project/` (14 files): README, `.gitignore.template`, `.sulde-config.yaml.example`, `scripts/{coordinator-baseline,health-check}.sh.template`, `docs-hub/` with `00_shared-rules/` (5 mobile-generic rule templates), `design-truth/` skeleton + example, `ADR/` with frontmatter schema + INDEX + 3 mobile-generic examples (`0001-0003`)
- `template/android/` (11 files): Kotlin / Compose / Gradle / adb workflow
- `template/ios/` (11 files): Swift / SwiftUI / TCA / xcodebuild / ios-deploy workflow
- `template/flutter/` (11 files): Dart / Widgets / flutter CLI workflow
- `template/harmony/` (11 files): ArkTS / ArkUI / hvigorw / hdc workflow

#### Docs-hub content (`template/_project/docs-hub/00_shared-rules/`)

- `data-sources.md.template` — priority of truth (user > design-truth > scaffold > PRD > existing)
- `verify-build.md.template` — 5-step verify gate + per-stack commands
- `self-fix-boundary.md.template` — auto-fix allowlist vs escalate list
- `perf-diagnosis.md.template` — perf-gate rules + per-stack profilers
- `model-strategy.md.template` — Claude model selection per task type

#### Anti-pattern ADR examples

- `0001-coordinator-impression-based-dispatch.md.template` — coordinator drafting from memory (enforced by `check_task_md_baseline.py`)
- `0002-scaffold-bypass.md.template` — features bypass scaffold contracts
- `0003-mobile-cold-flow-stateflow.md.template` — Cold Flow / Publisher used where Hot StateFlow / @Published needed

#### Cross-OS support

- All Python hooks tested on macOS / Linux; Windows native via Git Bash or WSL2 (CRLF handling documented in installer scripts)
- Per-stack `pre-commit-installer.sh` auto-detects `CLAUDE_PLUGIN_ROOT`, emits Windows CRLF hint when applicable
- `.sulde-config.yaml` schema adds `os_compatibility.{primary_target, windows_shell_hint}` for stack scripts

#### Onboarding grace period

- 7-day default grace window via `.sulde-grace-started` / `.sulde-grace-ended` marker files (not mtime — game-resistant). During grace, hooks force `lenient` regardless of config. `/sulde-end-grace` exits early.

#### Tests

- `tests/p1_hook_dryrun.py` — 13 assertions covering all hook entrypoints + protocol compliance + ImportError fallback
- `tests/p2_template_dryrun.py` — 76 assertions covering template structure + stack-specific signatures + copytree simulation

### Changed

- Hook stdout/exit protocol now strictly v2-compliant: PreToolUse Write/Edit uses `permissionDecision` JSON (exit 0); PreToolUse Bash uses exit 2 + stderr; UserPromptSubmit / SessionStart use stdout / `additionalContext` JSON respectively.
- `enforcement.py` introduces 3 severity levels (hard / medium / soft) × 3 enforcement levels (strict / balanced / lenient) matrix.
- `.sulde-config.yaml` schema extended with 14 new optional fields; all default to sensible values for mobile projects.
- `i18n` support added (en / zh / ja); error messages localised based on `lang:` config or `SULDE_LANG` env.

### Migration from v0.1.x

Use the wizard:

```
/sulde-migrate-from-v0.1.0
```

It reads existing `.sulde-config.yaml`, dry-runs schema upgrade to `.sulde-config.yaml.v2-preview`, on confirmation backs up the original as `.sulde-config.yaml.v0.1.0-backup`, and writes the upgraded file. Drops `.sulde-grace-started` so the first 7 days run at `lenient` for re-acclimation.

Manual steps after migration:

1. `pip install pyyaml>=6.0` (or `pip install -r ${CLAUDE_PLUGIN_ROOT}/hooks/requirements.txt`)
2. Run `bash <frontend>/scripts/pre-commit-installer.sh` per frontend to install v0.2.0 git hooks
3. Run `/sulde-add-team-member` per developer to install `git as-<alias>` aliases

### v0.1.0 fallback (no Python required)

```
/plugin install skills@sulde-cc@0.1.0
```

v0.1.0 remains MIT-licensed, pyyaml-free, and supported for environments where Python isn't available.

---

## [0.1.1] — 2026-05-24 — Private bundle + multi-source-review

- Bundled 21 project-private skills from Freebeat-derived deployment
- Added `multi-source-review` skill (generic, derived from session learnings)
- Public generic version remains at tag `v0.1.0`

## [0.1.0] — Initial release (MIT)

- Single coordinator + N Dev role split
- 3 core skills: `writing-task-md`, `assign`, `update-design`
- Bash `UserPromptSubmit` hook (skill-trigger reminders)
- Project template + docs-hub + ADR registry
- MIT license

---

## Versioning

- **Major** (X.0.0): scope changes (e.g. v0.2.0 mobile-only), license changes
- **Minor** (0.X.0): new skills, new hooks, new commands, breaking schema changes
- **Patch** (0.0.X): bug fixes, doc clarifications, ADR additions

## Change Date (for v0.2.0+ BSL releases)

The Business Source License 1.1 transition date for v0.2.0 is **2030-05-25**. On that date, v0.2.0 (and any patch releases backported to v0.2.x) automatically transition to MIT.
