# 整仓迁移支持 v1：冻结控制清单

日期：2026-09-13；更新：2026-09-15。状态：R6 真实整仓改名已 committed、屏障已释放；317 项回归/规模演练及 r18 官方安装证据保留。r20 仅补齐 README/manifest 名称引用与本报告，按既定流程合 dev、关闭临时资源；清理终态以独立 completion receipt 为准。交互观测提示仍保留，不冒充全局 ready。
capability_tier: deep

## 目标与边界

**当前顺序覆盖历史章节的“下一步安装”建议**：安装前完整诊断 → 冻结必要修复 →
隔离生产形态整链演练 → 零未解释阻断后冻结候选 → 正式安装 → 仅复核现场漂移 →
单独授权实际改名。不能以一次修复的测试通过替代整条迁移链的就绪判断。

为 `sulde-cc-pro` → `sulde-pro` 整仓改名补齐受控迁移能力。
基线：`fc821c150ffcff42003246fab6e79675e15bf011`（dev）。
任务分支：`task/repository-relocation-v1`。
本文件是唯一进度、发现、证据和合并控制清单；此前归档的未实施方案保持原状。

2026-09-14 用户纠偏后的当前执行边界，以后文「R6 一次性改名收尾」为准：
停止继续开发迁移能力，已验证源码保留；历史 R0–R5 记录不删除、不重新展开。

本开发任务不授权生产安装、真实目录迁移、GitHub 写入、remote 或宿主配置修改。
这些动作须在源码与证据通过后，按当时精确路径、工件和状态另行确认。
禁止修改已安装 cache runtime、手工改生产合同/事件/效果账本、借用旧授权、旧路径
符号链接绕行、删除同仓校验、主分支直接提交、无关重构和扩大清理范围。

## 冻结验收与进度

- [x] R0：从精确 dev 基线建隔离 worktree，取得当前会话原生开发确认和 workspace handoff。
- [x] R1（只读预检）：冻结源/目的路径、物理 Git 身份及所有 linked worktrees；拒绝已有目的地、
  符号链接冒充、跨设备、相同 HEAD 的克隆替身、未决效果、并发漂移。
- [x] R2：精确执行卡经当前会话 native Allow 才能执行；Deny 不产生迁移权限。
  写者屏障、物理搬迁、Git 指针修复、重绑定、独立原生 effect/contract/commit 及
  终态屏障释放已闭合。隔离安装件的真实 Codex Allow/Deny 已分别通过；仅为候选验证，
  不构成当前真实仓库的执行权限。
- [x] R3：迁移后受控重绑定；历史账本不改写，旧任务授权不转移，重新确认才恢复业务执行。
  原合同按原字节归档；继任合同及映射已实际发布验证；15 个实际进程退出点和
  native pending append 恢复通过。Hook 在旧路径失效前路由精确恢复命令；普通工具
  不获例外。真实 Codex 已验证迁移后未复核的业务写入仍由 PreToolUse 拒绝。
- [x] R4：真实临时 Git 主仓与 linked worktree 全根迁移、中断恢复、幂等性、用户未提交
  内容保留、Allow/Deny、身份冒充/路径漂移的回归测试通过。
- [x] R5：相关官方隔离测试通过、证据归档、仅合并 dev，完成临时 worktree 生命周期。
- [x] R6：官方安装与真实改名分别经精确原生卡完成；文件系统、Git 指针、24 份合同、
  5 条会话映射及 1 个已知消费者配置均已独立核验，终态 committed 且屏障释放。
  r20 补齐有效名称引用与现场报告；临时资源清理独立记录，不继承旧任务权限。

## 当前发现

1. `session_workspace.py` 目前把绝对 `git_common_dir` 字符串作为同仓条件。
   整根目录移动后字符串变化；普通 rebind 不能证明物理仓库身份。
2. session mapping 在目标目录不存在时先失败，若搬迁中断，普通 Hook 路由也无法进入
   恢复。不能只让直接调用的单元测试通过，必须覆盖恢复入口。
3. 基线原生决策注册表没有整仓迁移种类。2026-09-14 已加入仅记录计划决定的
   `repository-relocation` 入口；内部物理阶段已接通，但尚无完整公开搬迁执行器。
   开发确认不是生产迁移权限。
4. 文件内容、Git index/HEAD 和实际权限是不同证据层。工作区脏文件必须保留；相同
   HEAD 不能证明是同一个物理仓库。
5. 已实现的预检不等于写者屏障，不保证任意外部进程在返回后不再写入。R2 必须在
   执行边界重新核验并建立受控写入边界；R3/R4 必须证明各中断点不会重放移动操作。
6. 预检显式拒绝外部 linked worktree、detached/locked/prunable worktree、alternates、
   子模块、path-bound worktree config、特殊文件及超过证据限额的树。不得静默跳过，
   不得为让真实搬迁通过而自动放宽。这些不是本次新建子任务。

## R1 实现记录

- 新模块 `repository_relocation.py` 提供物理仓库证据冻结、搬迁前/后只读核验及
  Guardian 绑定预检；现有 session mapping 同仓限制保持不变。
- `repository-relocation-preflight` CLI 只输出证据，明确
  `execution_authorized=false`、`authority_transferred=false`。
- 物理目录 device/inode、worktree 登记、branch/HEAD、refs、独立 index/config 摘要、
  用户文件内容/权限分开核验。忽略文件同样纳入；符号链接只读链接文本，不遍历目标。
- 使用不跟随符号链接的描述符相对遍历；读取有界，不打印文件内容或 Git 错误原文。
- 仅重放本仓现有工作区的合同/账本；历史孤儿和无关工作区保持原状。当前 session
  必须精确匹配；未决效果、审批和原生事务拒绝迁移。自身 host observation 不进入
  语义 CAS 摘要，已用回归测试验证。
- 测试曾有一例夹具错误：在构造已消失 worktree 的合同前未建立独立工作区标识，
  导致 `workspace_root()` 正常回退父仓库、夹具覆盖当前合同。已改为先建立历史
  selector、保存合同再移除该临时目录，保留原反例断言；不是放宽守卫校验。

## 下一实施点（仍在原计划内）

R2/R3：只增加整仓迁移的精确原生决策/机械恢复通道，不能复用开发提案或旧任务回执。
预检输出可由调用者复制或重算，摘要本身不是权限；执行器必须独立绑定当前原生决定。
在源根仍存在时准备外置恢复记录；在目录已移动、mapping 未提交的崩溃窗口中，
也必须可以进入唯一受控恢复入口。先补 Allow/Deny 与中断测试，再开放执行注册。
当前公开入口仍只有计划确认；执行卡与原生事务准备仅为源码内部接入，尚未注册
宿主/CLI 执行入口，没有真实搬迁批准或已经运行的搬迁进程。

## R2 实施记录（2026-09-14，部分完成）

- `prepare-repository-relocation` 在不随仓库移动的 home 中保存不可变、owner-only
  计划。计划绑定精确 provider/session、合同和 R1 物理/工作区证据；默认重复准备幂等。
- `native-decision-preview repository-relocation` → 当前宿主配对观察 → typed Allow
  → 计划决定记录的源码路径已接通。沿用宿主原生 Allow/Deny，不引入文字授权。
- 唯一同意真源是现有 typed approval 账本。旁路 `.decision.json` 只作为可独立
  回读的证据；返回值始终 `execution_authorized=false`，不得充当 bearer token。
  没有追加伪造的 T13 committed 事件，也没有创建迁移 effect 或修改合同路由。
- 自身那一笔精确问题按合同、plan、card、revision、session、effect 和 workspace
  匹配后才允许从预检的“其他未决审批”检查中排除；其他问题和真实 world drift 仍阻断。
- typed Allow 已持久化但决定投影未写入时，重试只回读同一请求，恢复同一投影；
  不再裁决一次，不移动目录、不创建新的旧任务授权。
- Deny 保持不可变。再次准备时可创建带拒绝前驱的新计划，由新原生问题重新确认；
  不复活旧的一次性 request。前驱文件和其真实 Deny 均独立核验。
- 独立 verifier 使用显式指定的 home，不被环境中的另一 store 重定向；journal
  head 使用只读验证，不借验证过程写入或修复生产账本。

### 本轮发现、修复与未覆盖项

- **发现并处理**：若把所有 open approval 无条件算作迁移阻断，原生问题会阻断自身。
  通过精确绑定豁免当前问题，测试证明无关问题仍阻断。
- **发现并处理**：typed 请求为终态一次性对象，Deny 后不能重复使用原 snapshot。
  使用带拒绝前驱的全新计划，保留旧拒绝记录，测试证明可以再次明确确认。
- **未覆盖**：执行授权提交、跨进程写者屏障、实际移动/修复/rebind、根消失后的
  Hook 恢复、当前安装件 live 验收。这些仍是原 R2/R3/R4 项，不另扩任务图。
- **证据边界**：本轮原生桥验证是合成宿主事件 + 真实临时 Git/账本/CLI 的源码测试，
  不是用户在生产会话点击迁移卡的证据。未请求或消费真实搬迁权限。
- **下一步**：为执行事务建立独立授权和恢复闭环；计划“同意记录”不能直接升级为
  目录移动权限。R6 的真实执行卡必须明确动作，不能复用本开发卡或本轮仅记录决定的卡。

## 已执行与证据

- R0：当前任务 worktree 初始 `git status --short --branch` 仅输出任务分支，无修改。
- 已读已安装守卫、派单、知识检索技能及命中知识原文；仅用于任务范围和证据约束。
- 官方隔离运行器：`scripts/kb/run-isolated-tests.py`，解释器 Python 3.10.7。
- R1 独立测试 30/30 通过，无 skip（含真实 CLI、临时主仓/linked worktree 全根
  移动、工作树/暂存/未跟踪/忽略文件、0400、克隆冒充、未决真实效果账本）。
- 守卫完整模块 272 项：255 通过，17 项既有退役测试 skip；没有新增或放宽 skip。
- 最终同轮组合回归：302 项，285 通过、17 项上述既有 skip，耗时 38.413 秒，退出码 0。
  原始运行输出：`.sulde/public-export/repository-relocation-v1-20260913/r1-combined-isolated-tests.log`。
- `git diff --check` 通过。相关测试属于源码证据，不是生产安装或 live 迁移验收。
- 2026-09-14 最终组合回归：313 项，296 通过、17 项既有退役 skip，68.553 秒，
  退出码 0。迁移模块 41 项（R1 的 30 项 + R2 新增 11 项）均通过、无 skip。
  原始输出：`.sulde/public-export/repository-relocation-v1-20260913/r2-combined-isolated-tests.log`。
- 尚未合并、安装、真实移动或远端写入；R2–R6 均未完成，R4 仅物理层用例已覆盖。

## R2 写者屏障接入（2026-09-14，仍非迁移执行器）

### 范围控制

- 发现 `approval_invariant._mutate/restore_authoritative_store` 与
  `intervention._mutate/restore_authoritative_store` 使用各自的存储锁，合同锁不能
  阻止它们写入；进程退出后，仅持有 OS 锁也不能保留迁移期间的写入限制。
- 已通过当前 Codex 原生 Allow 将开发合同更新为 revision 3，仅增加
  `scripts/kb/approval_invariant.py`、`scripts/kb/intervention.py` 两个源码接入点。
  R0–R6、基线、分支、合并顺序和禁止项不变。没有增加新项目或通用守卫重构。
- 首次保存提案被外层文件沙箱拒绝，按同一命令请求权限后保存成功；随后独立的
  当前会话原生决定完成并应用提案。未把保存提案的权限当作语义批准，未绕过守卫。

### 实现及边界

- 既有合同、mapping、审批、effect、native journal 和事件账本的真实锁按固定顺序
  收拢。最后重验 registry membership，避免新会话/合同在冻结期间漏入。
- 持久 fence 是额外写入限制，既不是批准回执，也不允许目录移动。其 owner-only
  记录保存在仓库之外，记录精确源/目标、受影响 stores 及预检绑定。
- 独立账本写者取得原有锁后检查 fence；新合同/mapping 注册还检查源/目标根及
  子工作区。注册锁仅覆盖短暂发布窗口，不在文件内容哈希期间占用。
- 不以 PID 死亡、超时、环境变量或不存在的旧目录自动撤除限制。内部发布支持相同
  证据的幂等重入，但目前没有通用解除入口，必须等执行事务的终态核验实现。
- 不修改原生批准语义或旧账本内容。为避免低层账本反向初始化完整 Guardian，
  迁移模块的 state 依赖延迟到既有计划/执行辅助函数内加载。
- 完整恢复和 Hook 入口尚未实现；本轮只证明底层只读 replay 不受限制，**不把它
  当作整个宿主 Hook 的只读可用性验收**。R3 必须覆盖根移动后路由及恢复入口。
- 不宣称冻结任意 Git/编辑器等非协作进程，也不宣称旧安装版本会理解新 fence；
  R4/R6 仍须核验切换后的写者版本并在实际动作边界复检外部文件漂移。

### 测试与发现

- 新增独立解释器测试：逐一探测 6 类真实写者锁；发布进程退出后检查 9 种写入
  或恢复入口；验证无关 workspace 可写、只读回放可读、新注册受限、漂移拒绝、
  同计划幂等、故障后锁释放、损坏/权限过宽的 fence 不会产生权限。
- 首轮 46 项中有 1 项失败：native journal 检查误接到了 request-validation
  上下文，而不是 `_store_lock`，独立进程写入探针捕获遗漏。已将检查移动到真实
  存储锁入口，保持原测试断言；这不是生产守卫故障，也没有降低安全门。
- 扩大回归首次 529 项出现 3 failure / 137 error。其中主要原因是新 writer 检查
  不应把迁移源的
  严格非别名要求套到所有普通 store 上；macOS `/var`、`/tmp` 别名触发异常，进而
  影响 bootstrap、会话和效果测试。已让普通 store 定位先 resolve 到既有真实路径，
  实际迁移源/目标仍走严格 preflight；新增别名正反例，证明普通写入可用且别名
  不能绕过已发布 fence。未跳过旧测试或删除身份检查。
- 同轮两项临时安装件续接测试还暴露打包遗漏：官方 `stage_plugin.release_entries`
  不自动收集任意未跟踪文件，新增的 `repository_relocation.py` 未入索引时不在
  安装件内。已仅将该源码加入当前任务分支的暂存区；没有提交、合并或放宽打包
  白名单。相关安装/宿主验证只发生在官方测试运行器创建的临时隔离目录。
- 最终同轮组合回归 **530 项：513 通过、17 项既有退役 skip**，169.179 秒，退出码 0。
  迁移模块 **49/49** 通过，无 skip（原 41 项 + 本轮 8 项）。没有新增 skip。
- 两项官方临时安装件测试经真实 `codex-cli-app-server` / `unified_exec` 通过；
  覆盖拒绝后继续普通写入、历史归档与同会话 handoff，外部模型请求数为 0。
  这证明现有宿主行为未被本次接入破坏，不替代整仓迁移执行验收。
- 原始输出：`.sulde/public-export/repository-relocation-v1-20260913/r2-writer-fence-combined-isolated-tests.log`
  （owner-only，本地证据）；`git diff --check` 通过。
- 生产 fence 未创建；真实目录未移动，未生产安装、未提交、未合并、未推送。
  root main 仍只有原有 `.ua` 三文件修改及未跟踪 `.sulde/`；没有覆盖用户修改。

本轮组合回归复现：

```sh
/Users/eric/.pyenv/versions/3.10.7/bin/python3.10 -B scripts/kb/run-isolated-tests.py \
  tests.test_repository_relocation tests.test_intent_guardian \
  tests.test_approval_invariant tests.test_intervention tests.test_intervention_batch \
  tests.test_native_decision_journal tests.test_native_session_continuity
```

运行临时安装件测试前，新运行时源码必须已在当前任务分支 Git 索引中；仅暂存不等于
提交或合并，不得通过放宽打包清单来吸入任意未跟踪文件。

### 下一唯一实施点

将精确的迁移执行原生决定、持久 fence、机械搬迁/受控重绑定和终态释放接成
同一个可恢复事务；不能把现有“仅记录同意”的决定或内部 inhibition helper
直接升级为执行权限。依旧属于原 R2/R3，不新增任务编号。

### R2 测试复现

```sh
/Users/eric/.pyenv/versions/3.10.7/bin/python3.10 -B scripts/kb/run-isolated-tests.py \
  tests.test_repository_relocation tests.test_intent_guardian
```

只在任务 worktree 内使用官方隔离入口；不要直接调用当前生产 guard 生成真实迁移卡。
本轮没有出现已安装守卫误拦、生产自锁或需要人重复授权的情况；失败注入均为隔离测试。

## R3 中断窗口诊断与继任草稿（2026-09-14，部分完成）

### 本轮交付

- 仍使用 revision 3 的已批准文件范围；没有新增任务、改基线或修改打包/安装规则。
- 新 `inspect-repository-relocation` 是纯只读控制命令，绑定显式 plan 与 provider/session。
  直接读取外置计划，不先调用可能已失效的 session mapping；因此目录已移动且 fence
  仍在、普通 mapping 报 target unavailable 时，也能完成诊断。不清账、不解除屏障。
- 物理证据升级到 v2：冻结 linked worktree 的 `.git`、admin `gitdir`、`commondir`
  内容与实际模式。仅接受已冻结前值或后值；未知指针、权限漂移、管理目录替换、
  index/HEAD/refs/config 漂移、额外 worktree 登记均拒绝。绝对 commondir 显式不支持。
- 在不跟随失效 `.git` 指针的前提下，分别报告 `source_intact`、`links_pending`、
  `git_repaired`。每一项都返回无执行权限、未发生修改；最终 Git 修复态仍须通过原有
  完整身份/status 验证，不能只看目录 inode。
- 老 v1 证据没有冻结 Git 指针，明确拒绝用于这一恢复诊断，须在源目录尚在时重新
  准备 v2 计划；不升级旧授权、不覆盖旧计划。尚无生产迁移计划被本轮改写。
- 新 `relocation_review_contract` 仅在内存生成确定性草稿：保留目标/验收/约束与
  intent lineage，revision 增加，新 epoch 仍采用现有全局协议；默认禁止物质写入，
  状态 paused，必须新的人类可读提案。runtime、旧回执、grants、task lanes 和未知
  扩展权限均不复制，源合同和全部历史账本不动。实际发布必须由后续执行事务完成。

### 发现、修正与证据边界

- 原证据只在完整 Git links 修复后可校验，不能判断两个指针写入之间的中断状态。
  本轮通过冻结指针前/后值、直接检查物理 admin 路径补齐该观察窗口，不调用泛化修复。
- 定向测试发现 `validate_contract` 会按 intent/revision/objective 重算 epoch；
  不能给单一迁移流程另塞一种 epoch 算法。已移除这段无效赋值，保留原协议，另以
  plan/源 epoch/目标 workspace 的绑定摘要区分迁移；新草稿仍不能消费旧 epoch 授权。
- 初轮迁移模块 55/55 通过；新增继任草稿定向测试修正上述绑定问题后 2/2 通过。
  不将这些局部测试当作 R2/R3 总体验收。
- 隔离用例覆盖每个 Git pointer 部分写入窗口、0400 保留、路径重建/clone 冒充、
  pointer symlink、index/注册集合漂移；真实 CLI 在 stale mapping + fence 条件下
  只读成功，错误 session 被拒绝。草稿测试证明无磁盘写入、源对象不变、无旧权限。
- 临时夹具由测试模拟目录移动和指针逐项写入，**不是已实现原生批准后的搬迁执行器**。
  宿主 Hook 在真实迁移 fence 下的恢复入口、实际 rebind 与终态释放仍未实现；
  也没有请求、消费真实迁移批准或执行生产改名/安装。

### 本轮最终验证

- 与前轮相同的 7 模块官方组合回归 **539 项：522 通过、17 项既有退役 skip**，
  157.934 秒，退出码 0。迁移模块 **57/57** 通过；本轮新增 8 项迁移用例、1 项
  只读控制路由用例，无新增 skip。`git diff --check` 通过。
- 两项临时安装件经真实 Codex CLI app-server / unified_exec 会话续接测试通过，
  外部模型请求 0。仅验证既有宿主行为回归，未验证生产整仓搬迁。
- 原始输出：`.sulde/public-export/repository-relocation-v1-20260913/r3-recovery-inspection-combined-isolated-tests.log`
  （owner-only 本地文件）。复现使用上节相同的 7 模块命令。
- 仅任务 worktree 内源码、测试和报告变化；无新分支、生产安装、实际改名、提交、
  合并或 push。范围继续受原 revision 3 与 R0–R6 清单约束。

### 续接点

仍按 R2/R3 将明确的执行型原生决定与同一持久迁移事务连接；复用本轮诊断、继任
草稿和前轮写者屏障，实施精确写入及终态核验。当前“仅记录同意”的决定不得用于
移动目录。R2、R3、R4、R5、R6 均不勾选，未完成项不隐藏或改名。

## R2 执行卡与原生事务准备（2026-09-14，部分完成）

### 本轮交付与范围

- 未新增任务编号、分支或诊断 CLI；继续 revision 3 的原有文件范围。
- 独立执行卡明确列出冻结写者、移动精确源/目标、修复登记的 Git 指针、发布暂停
  继任合同/会话映射、终态核验后释放屏障；明确排除安装、远端写入、恢复业务权限。
  旧 `review-repository-relocation` 卡仍保持“仅记录”，不能匹配新执行动作。
- 内部 `_prepare_relocation_execution` 只接受已经落账的、精确当前会话执行卡
  typed Allow；独立核验原生 actor、request binding、prompt snapshot 与完整预检。
  它不创建问题、不替人裁决，也不读取旧 `.decision.json` 作为权限。
- 复用现有 native journal 的 durable seal、prepare、canonical T12 authority reader，
  到达 `approval_decided`；没有另外发明一套通用事务账本，也没有伪造 committed。
- 中断恢复从精确 seal 还原弹卡时的 journal 前缀，避免自身 seal/prepare 导致错误
  CAS。预检仅允许本计划、卡片、revision/epoch、session 和真实 Allow 对应的这一笔
  prepared/approval_decided；旧 review 不享受该豁免，其他未决事务和物理漂移仍拒绝。
- 同一计划加外置准备锁，保持 contract → ledger 的既有锁顺序。重复运行只回读
  同一事务；不给出业务权限，不移动目录，不发布 fence，不修改源合同或 mapping。

### 为什么暂不注册执行入口

物理搬迁、受控 rebind 和终态释放尚未完成。如果现在让宿主调用到
`approval_decided` 就返回，会主动制造一笔生产未完成事务，重演用户报告的自锁。
因此执行卡/准备适配器只接入源码内部，公开 native preview/execute 仍拒绝该种类；
等原 R2/R3 的整个终态链闭合后一起注册。不是新增人工授权门或改变冻结验收标准。

### 发现与测试

- 首轮 65 项迁移测试有 3 项错误：把 `AuthorityAdvancementResult`（TypedDict）
  当成属性对象读取 `stage`。已改为按键访问；保留断言，定向 3/3 复测通过。
- 新增 10 项用例：旧 review Allow 不能授权执行、Deny、无 prompt、错误 session/
  actor、Allow 后文件漂移、其他事务不豁免、公开入口未注册、重复准备不追加回执，
  以及三个持久化节点的恢复。
- 除普通失败注入外，使用独立解释器在 sealed/prepared/approval_decided 三个节点
  `os._exit(73)`，随后再开解释器恢复，证明退出后锁可释放、批准账本字节不变、
  seal 和事务各只有一笔。相关定向 2/2 通过。
- 这是合成 native producer + 真实临时 Git/账本/独立进程的源码证据；不是生产会话
  点击迁移执行卡、实际迁移或安装件迁移恢复验收。
- 最终同轮 7 模块官方隔离组合回归 **549 项：532 通过、17 项既有退役 skip**，
  169.737 秒，退出码 0。迁移模块 **67/67** 通过，无新增 skip。
  `git diff --check` 与 `git diff --cached --check` 均通过。
- 两项临时安装件真实 Codex CLI app-server / unified_exec 续接回归通过，外部模型
  请求 0；仍不替代新迁移执行器的 live 验收。
- 原始输出：`.sulde/public-export/repository-relocation-v1-20260913/r2-execution-native-preparation-combined-isolated-tests.log`，
  owner-only、本地保留。复现使用原清单中的同一 7 模块命令。

### 下一唯一实施点

在这条精确执行卡/事务准备链上接通持久 fence、机械搬迁、暂停继任合同与 mapping
发布、终态独立核验和释放；再开放宿主恢复/执行入口，按 R4 做完整跨进程集成。
R2–R6 不勾选，不把“批准已入账”当作“迁移已执行”。未提交、合并、安装或实际改名。

## R2 受控物理阶段（2026-09-14，部分完成）

### 本轮交付

- 内部 `_execute_relocation_filesystem` 接通既有执行型 native 准备链、完整写者锁集、
  外置恢复 manifest、持久 fence、整根原子移动、精确 Git 指针修复和物理终态核验。
  仍不注册生产 native/CLI 执行入口，不复用仅记录 review 卡。
- 初次执行与进程中断后的恢复都持有同一组合同、mapping、approval/effect/native/
  audit 锁；registry 锁只用于短暂 manifest/fence 发布。普通写者没有新增 bypass。
- manifest 先于 fence 持久化；只保存计划/真实事务绑定与 stores 的哈希、模式，
  不复制凭据、业务权限或账本内容。恢复必须再次独立重放真实原生 seal/Allow；
  manifest、文件状态和调用者传来的编号都不能单独产生权限。
- 旧根消失后，恢复按已冻结 mapping 的原始结构核对语义，而不是调用普通失效路由；
  普通 workspace-handoff 的 same-common-dir/目标可用校验保持不变。
- 使用 macOS SDK 声明的 `renameatx_np(RENAME_EXCL)`，不回退到可能覆盖后来出现的
  空目标目录的普通 rename。调用原生 API 前仍触发标准 Python `os.rename` 审计，
  官方隔离运行器或其他审计拒绝可阻止 syscall；不是绕过沙箱的备用入口。
- 只修复计划里冻结的 Git links，逐项要求前值/后值与实际模式相符。暂存文件在
  仓库外同设备的专用恢复路径中，避免中断残片污染用户内容哈希；写入、目录项均
  fsync。原 0400 指针仍为 0400，不通过 Git checkout/rebuild 物化成 0644。
- 中断后根据源/目标物理身份与逐项前后值继续，不重复根移动或已完成的指针替换；
  缺失 fence、未知指针、store 漂移或不支持的平台均不得自动放行/补造权限。

### 本轮发现与处理

1. 第一次物理集成的两个测试失败：`verify_request_binding_receipt` 返回的是不可变
   asked 前缀，那里没有后续 prompt/Allow。保留前缀完整性校验，另从 canonical
   approval projection 读取终态，再与 native stage 的真实回执逐字段比对。没有
   删除原生校验、补造 Allow 或修改生产账本。
2. 普通 `os.rename` 在 POSIX 上可能覆盖迟到的空目录，单次 exists 检查不是保护。
   改用明确 no-replace 的宿主原子原语；迟到目标的独立反例证明源和空目标均保留。
3. 原生 FFI 不自动产生 Python 的 rename 审计事件。已显式保留该标准审计边界，
   独立进程装入拒绝型 audit hook，验证根移动前被阻止。
4. 目的路径若包含换行，会生成不可解析 Git 指针；现于预检拒绝，不等搬迁后失败。

### 证据与剩余边界

- 定向主流程/中断/真实锁测试 3/3 通过；八个拒绝/漂移/平台门测试 8/8 通过；
  Python 审计拒绝测试 1/1 通过。共新增 12 项，无新增本机 skip。
- 最终同轮 7 模块官方隔离组合回归 **561 项：544 通过、17 项既有退役 skip**，
  209.919 秒，退出码 0。迁移模块 **79/79** 通过；两项临时安装件真实 Codex
  app-server/unified_exec 续接测试通过、外部模型请求 0。`git diff --check` 和
  `git diff --cached --check` 均通过。
- 原始输出：`.sulde/public-export/repository-relocation-v1-20260913/r2-physical-execution-combined-isolated-tests.log`，
  owner-only、本地保留；复现仍使用原 7 模块命令。这不是生产迁移 live 验收。
- 实际临时 Git 夹具包含 staged/unstaged/untracked/ignored 文件及 0400 文件/指针。
  native journal、合同、session mapping 与其他冻结 stores 的字节保持不变。
- 独立解释器在 manifest、fenced、moved、每个 link 的 staged/repaired、
  physical_verified 八个节点 `os._exit(73)`，逐次由新解释器恢复；最终只移动一次，
  已完成指针和原生账本在重复执行时不再改写。三个阶段的独立非阻塞 flock 探针
  证明实际持有完整锁集合，不只是 mock 锁函数。
- 物理阶段成功仍返回 `physical_verified_rebind_pending`，保留 fence，native
  transaction 仍为 `approval_decided`；不伪造 effect_applied/committed，不解除
  旧路径保护，不转移旧授权。这不是完整 R2/R3/R4 验收。
- 本轮验证宿主是 macOS；v1 的实际移动原语仅启用在已核验 macOS API 上。既有 CI
  还含 Ubuntu/Windows discovery，平台测试安排与发布级检查仍在 R4/R5 内待核验，
  当前候选不能据本机组合测试合并发布。本轮未修改 CI 或扩大已批准文件范围。
- 仍不能宣称冻结任意外部 Git/编辑器进程或旧版本写者；真实安装代际、写者静止与
  live 恢复门仍在 R4/R6 验收。没有在真实仓库创建 fence、迁移目录或安装运行时。

### 该阶段续接点（已由下节推进）

原 R3：发布暂停的继任合同/映射，补齐 native effect/contract/commit 的独立证据与
终态 fence 释放；接通宿主 Hook 恢复后，再按 R4/R5 验收并决定是否开放执行入口。
本轮不新增任务编号，不勾选 R2–R6，不提交、合并、push 或真实改名。

## R2/R3 闭环与 R4 安装件验收（2026-09-14）

### 范围与状态

- 当前会话原生 Allow 已将开发合同更新到 revision 4，仅增加 `audit.py` 的精确
  恢复早期路由与 `.github/workflows/kb-quality.yml` 的 macOS 测试登记。目标、
  R0–R6、基线、分支及禁止项未变；没有增加独立任务或通用守卫重构。
- 新执行种类 `repository-relocation-execution` 与旧“仅确认计划”卡完全分离。
  `recover-repository-relocation` 只核验当前 session 的既有真实执行决定，不能创建
  问题或裁决；拒绝复合命令、重复参数、不同 session/home、伪造启动器及 MCP 冒充。
- 新合同只含目标/约束等人类事实，使用新 revision/epoch，默认暂停且禁止业务写入。
  源合同 link/unlink 归档保持原字节；归档路径不能作为 active contract 加载。
  旧审批/effect 账本不改写，协调方 native journal 仅追加同一事务的精确完成尾部。
- 完成次序：重绑定并独立验证 → 原生 effect/contract/committed → 终态记录 →
  退休 fence。中断不会放宽普通写者；最终回读不会重放迁移或撤销后续已确认的任务。

### 发现、修复、证据

1. **闭环自锁**：正常 native head 校验会获取写锁，而 fence 尚未退休。给最终回读
   增加纯只读验证选项；未取消正常写锁检查。专用完成适配器只允许源 native
   journal 和三类完成回执追加，异常时恢复原上下文，其他写者始终受 fence 限制。
2. **半写账本恢复**：只读投影遇到 pending append 会拒绝，不能据此宣布永久卡死。
   先用原有锚定协议作无写入预演，核验冻结前缀、唯一事务、真实批准及完整重绑定，
   再在完整锁集合下恢复同一 append；没有重试旧外部效果或新增审批。
3. **真实预检缺口**：SessionStart 产生的旧 revision、非 typed 的意图展示卡，在
   新合同已经生效后仍被错误地当作开放权限请求。仅将同一 intent 的旧展示卡按
   惰性历史读取，不改原行；当前卡、typed 请求、其他来源和未决 native tx 仍阻断。
   该修复既有正反例，也由安装件验证捕获，不是删除历史审批来使测试通过。
4. **夹具前置缺失**：原安装件夹具只有合同，没有迁移要求的显式 session mapping。
   改用官方目标任务建立及同仓 handoff 建立映射，未放宽 preflight 的精确 lane 要求；
   安装件 Allow 同时覆盖主仓和 linked worktree 的两个合同。
5. **证据过早**：工具 1 秒 yield 返回的是运行中进程，模型结束 turn 时不能断言迁移
   已完成。将夹具改为等待有界执行终态，再核验独立终态文件；不是把运行中当成功。

- 内部迁移模块 85/85（当时版本）通过；正式 CLI/Hook 新增定向测试 3/3 通过。
- 七模块组合 571 项：554 通过、17 项既有退役 skip，288.384 秒、退出码 0。
  该批早于最后的旧展示卡修复和安装件新用例；不把它算作最终树完整验收。
- 官方临时安装件真实 `codex-cli-app-server` / `unified_exec` 的 Allow/Deny **2/2**
  通过，46.671 秒、退出码 0；每例精确一次模拟人类响应，外部模型请求为 0。
  Allow 后 0400 保留、源根消失、两个继任合同受控发布、fence 清除，并实测未复核
  的业务写入被 PreToolUse 拒绝；Deny 无迁移、无 native 执行事务。不是生产批准。
- 安装件原始证据：`.sulde/public-export/repository-relocation-v1-20260913/r4-installed-native-allow-deny.log`。
  失败输出保留在同目录的 `r4-installed-first-failure.log`、
  `r4-installed-binding-failure.log`、`r4-installed-premature-terminal-failure.log`。
- v1 明确只在 macOS 执行物理迁移；macOS CI 已登记整模块。Linux/Windows 运行
  平台拒绝用例，物理集成用例明确跳过；这些平台 skip 不是迁移成功证据。
- 最新九模块组合（增加 production recovery 两模块）**603 项：586 通过、17 项
  既有退役 skip**，356.262 秒、退出码 0。本机迁移模块无 skip，包含两项真实
  Codex 安装件审批/执行用例。原始完整输出：
  `.sulde/public-export/repository-relocation-v1-20260913/r3-r4-final-combined-isolated-tests.log`。
- R5 的现有 macOS 发布相关七模块检查 **134 项：132 通过、2 项环境/platform skip**，
  327.102 秒、退出码 0。一项需要原生 Windows PowerShell，另一项嵌套 Seatbelt
  因宿主外层限制跳过，单独申请沙箱外补验仍显示同一限制。两项均不计通过；未改
  原测试门禁，不宣称跨平台发布验收。原始输出为同目录
  `r5-release-related-isolated-tests.log`。本次不执行 dev → main 发布合并。
- R1–R5 共 12 份原始日志已按原字节复制并逐文件核验到仓库主目录的
  `.sulde/public-export/repository-relocation-v1-20260913/`，目录 0700、日志 0600。
  该持久目录在任务 worktree 外，后续临时工作区清理不会删除证据；既有 root
  `.ua` 和其他 `.sulde` 内容未覆盖。报告内证据路径均以仓库主目录为准。
- R5 源码提交 `7f5de8d` 已快进合入 dev；两 worktree 均干净，任务 HEAD 已验证为
  dev 祖先，未作冲突改写。main、远端与生产 runtime 未修改。
- 本报告的代码侧快照止于合并核验。其后的 R5 临时资源终态，由当前会话的官方
  `release-completed-workspace` / `finalize-workspace-cleanup` 回执闭合：要求仅删除
  此已合并任务的 worktree/分支、12 份外置日志仍在、清理回执为 `complete`。
  不能把“提交已合并”替代该独立清理终态，也不能在清理前宣称 R5 全项完成。
  R6 的安装与真实改名仍未执行。

### 当前唯一续接点

R2–R5 已完成；R5 官方清理回执于 2026-09-14T02:33:30.872302Z 为 complete，
原任务分支和 worktree 均不存在，源码及报告已合 dev `8adf3b0`，12 份外置日志保留。
继续 R6 官方安装与真实迁移卡；在真实执行前还必须
确认执行 runtime、恢复 home、宿主进程及运行 turn 的 cwd 不依赖即将失效的旧路径。
本开发卡和隔离测试响应不能授权实际安装/移动，不能绕过下一次精确原生确认。

## R6 发布执行控制（2026-09-14）

- 从已验收的干净 dev `8adf3b00306c86f90996cf4f4785efdb9cdf5a46` 建立
  `.worktrees/repository-relocation-r6` / `task/repository-relocation-r6`。
  仍是原 R6 的发布工作区，不新增功能任务或改变 R0–R6 验收。
- 当前会话准备 revision 2 receipt：
  `ea41c09d99154e40aca96501d40cc067863791d12023b34ad7c897184756795e`；
  正式 workspace handoff receipt：
  `b12f3fcc495da2a425366bf6468fe75b1ea00ccfae08822828831c44202691b6`。
  交接不继承旧安装 grant，后续安装必须重新绑定目标 worktree。
- 只更改 manifest 的 cachebuster 和本报告；不改已验收运行源码。
  使用既有 Python `/Users/eric/.pyenv/versions/3.10.7/bin/python3.10`，不安装依赖。
- 单个官方候选 prepare → verify → promote；verify 事先请求宿主权限，以免
  已知嵌套沙箱拒绝把一次性候选落为失败。任一步失败保留证据，不重复消费。
- 安装器只按既有定义处理原 16 labels 和 RunAtLoad；不额外 kickstart 或主动发起
  模型调用。允许范围以本轮原生安装卡及密封 grant 为准。
- 安装后独立核验 artifact/cache、当前会话 Hook、迁移 CLI、安装效果、scheduler；
  不用临时安装测试代替现场证据，不把全局历史告警说成已经清零。
- 通过后只合 dev，证据归档并完成本发布工作区生命周期；不合 main、不推送。
  实际 `sulde-cc-pro` → `sulde-pro` 必须再冻结精确物理证据、单独 native execution
  Allow、独立迁移终态及新路径验收。本安装卡不覆盖真实移动。
- 上述冻结时未安装、未改名；安装结果见下节。失败回滚由官方事务安装器执行；不手改生产 cache、账本、
  合同，不建立旧路径符号链接，不放宽迁移预检。

### 本轮准备阶段问题

- 组合执行 marketplace 只读 helper 与另一条 help 时，Guardian 在执行前拒绝整个
  组合；分别执行原命令成功。没有生产效果，不作为新增修复任务。
- `prepare-proposal --workspace <新 worktree>` 仍解析当前 session mapping 到 dev，
  所以第一次待审卡的安装 grant 指向 dev；在批准前核验发现，未执行 helper/install。
  已用仅交接准备的不可变提案替换，再经原生 handoff 绑定目标；旧待审卡未获权限，
  不修改原始历史行。这是需保留的实际入口语义问题，不在 R6 扩大源码修复。

### R6 正式安装结果与剩余门禁

- 正式安装卡 revision 3 经当前会话原生批准，receipt：
  `4bf8a1ca8a75292a049b455b633d57f909d6bf1aaaf596c81e1de425c0a5202f`。
- helper 一次，manifest validator 通过，版本提交 `ef4a6171137470e8f8fb2b99079438c1f0a7227f`
  仅改变一行版本；已验收运行源码未变。冻结报告提交为 `d8d47bd`。
- 已正式安装 `0.2.5+codex.20260914025156-282ed36131`，不是仅 staged。
  runtime tree `c2c8f257943c2d7590363e0e0aaa218bbaac6e0e134105e1b3e4219f38ffff3d`；
  plugin tree `e923f579b69a9c3a6f98e72d970bc81e56d888bef931086fdea2ccd2dc1748c4`。
- 官方候选 `r6-20260914`：prepare 1.956 秒、verify 18.801 秒、安装内部 total
  39.769 秒；status=promoted，单次消费。候选回执
  `288845c59543fda073c680549a7480cbf63e63a086090d408989027f9070e897`。
- production artifact/cache 递归逐文件比较一致（exit 0），generation_verified。
  当前 lane 的 helper/install 两笔 attempt 均 system_verified，pending verification=0，
  effect debt clear；native pairing settled=true、unsettled=0、cas_mismatch=0。
- 原 16 labels：真实 launchctl loaded=managed=16，failed/missing/retired 均为空，
  scheduler ready；没有额外 kickstart，不宣称全部后台业务重跑完成。
- 当前真实 Hook 在执行前拒绝官方 canary 删除，官方 finalize verified，marker
  已机械清理且独立检查不存在；proof_current_generation=true。proof：
  `facf060c8bfe1673445b6ca9fe042f20e30e6cbe5c7131062568e42433f37ea9`。
- fresh installed MCP 进程 initialize/tools/list/kb_status 三请求通过，8 tools，
  snapshot fresh；background degraded 保留，不替换已有长连接，不作全局健康声明。
- **当前 interactive/operational 仍 degraded**，唯一 readiness reason 为
  `host_interactive_fresh`：新版 prompt_control 尚未被真实用户输入观察；tool guard/result
  已 live_verified。不得用 CLI 或模拟事件补造 UserPromptSubmit，也不将其标为 ready。
- 只读进程核验：当前 Codex PID 4127 的 cwd 仍为原仓库根。实际迁移前必须将宿主
  进程和运行 turn 的 cwd 移到源根之外；改变某条工具子进程 cwd 不足以证明宿主已迁出。

### 真实仓库容量门失败：需新决定，禁止自动扩大

- 新安装 CLI 的只读 `repository-relocation-preflight` 返回 exit 2：
  `relocation content entry bound exceeded`，未产生计划执行授权、fence 或目录移动。
- 实际源码上限是 250,000 条目录/文件/链接、8 GiB 内容。全根 `rg --files --hidden
  --no-ignore` 只读统计 322,225 个文件；该口径包含 Git、但不含目录，**不等同于**
  Guardian entry count。容量失败事实来自官方预检，不是由 rg 数量推断。
- `.worktrees` 实占 7,252,404 KiB，root `.sulde` 269,204 KiB、`.ua` 595,032 KiB。
  `du` 是磁盘占用，不等于预检逻辑字节；8 GiB 门尚未通过，不能保证只改条目上限就够。
- `git worktree list` 只有 root、dev 与本轮发布 worktree；但物理 `.worktrees` 下
  还有历史 fullclone/候选归档，许多含各自 `.git`，不属于 registered linked worktree。
  例如 dev 的 `.sulde` 文件计数为 100,253，若干旧 fullclone 各数千文件。
  已完成的注册资源清理不能被表述为整个物理目录已经清空。
- 本轮不擅自删除/移走历史文件，不跳过未跟踪或忽略内容，不调高安装缓存常量，
  不绕过预检；也不把 R6 勾选完成。是否无损归档特定历史目录，或在源码增加经过
  边界验证的容量适配，必须取得明确的新范围决定，不能偷渡到“仅版本发布”。
- 当前发布 worktree 保留，未合 dev/main、未推送、未清理。本轮已验证安装证据和
  该真实迁移阻断一并提交；原 R0–R5 不重新展开。
- 续接时先回读本报告、候选 state/receipt 与当前 installed generation；禁止重复
  helper、verify、promote。先解决容量方案及宿主 cwd，再重新采样精确物理状态并
  发起独立的 repository-relocation-execution 原生卡。所有旧卡均不授权目录搬迁。

原始候选、安装结果、doctor、真实负向 proof、fresh MCP 及容量诊断位于本发布
worktree 的 `.sulde/public-export/repository-relocation-r6-20260914/`。发布分支保留期间
证据不删除；后续若清理必须先无损归档并核验。本轮没有触发任何共享知识库写入。

## R6 有限容量适配（2026-09-14，用户“允许”后的同计划续接）

### 范围与权限

- 用户批准保留全部历史文件的有限容量适配，当前任务原生确认至 revision 4；
  receipt `81ff1d4c0d6a80bc2dd9a5898ba5f1a8dcc9077a454ebf7f48771b9f52b3e592`。
- 仍使用本分支与 R0–R6 控制面，不重开 R0–R5。仅改迁移模块、对应测试及本报告，
  诊断证据写入既有 R6 目录。此次批准不是安装或物理改名执行权限。
- `MAX_ENTRIES` 固定为 500,000；8 GiB 内容上限不变，没有环境变量绕过或目录豁免。
  用 descriptor-relative `scandir` 在枚举时预留全局额度，祖先尚未遍历的兄弟项也计入；
  不再先由 `listdir` 无界分配整个目录。排序与原有内容摘要格式保持一致。
- SHA、inode、权限、同设备、no-follow、TOCTOU、原生确认及恢复门均保留；
  未删除、移动、归档历史 clone，未编辑已安装 cache 或历史账本。

### 真实仓库证据与边界

- 只读元数据诊断：359,907 entries（316,514 files、42,209 directories、1,184 symlinks），
  logical bytes=7,540,002,167，最大深度 25；6.355 秒。此诊断不是原子快照或执行证据。
- 当前源码生产 `freeze_repository_identity` 未替换常量、未模拟文件系统，完整遍历后：
  359,910 entries、7,540,010,472 bytes、3 registered worktrees；43.357 秒。
  数量差异来自诊断工件及本轮修改，不能把先后采样当成同一快照。
  content SHA `989487db125ddb2ddbdc23df5372a3d9ebe702f8cc48ce0febf6353c90895280`；
  snapshot SHA `a5abc042fc284b9a0bd8301edc4144ffc87795e53af45d880edf36499ae7647a`。
- 以上仅证明该采样时刻的物理预检通过，不覆盖 Guardian bindings、不产出执行授权。
  后续报告、测试、提交改变源内容后必须重新采样，不复用该摘要进行搬迁。
- 完整只读源码 CLI 预检已越过容量门，但 exit 2：
  `relocation requires settled contract state: pending_proposal_digest`。
  因此不能表述为“完整预检通过”或“可以立即移动”。
- 只读合同清点发现 dev 的 workspace/session 历史卡仍有 pending proposal，部分
  session 保留 active skill frames，root 卡有 open event。当前卡在结束 skill 后无这些
  pending 状态；没有为迁移而直接清空任何旧字段或代替其他会话作授权决定。
- 用户本轮真实输入后，已安装 doctor 的 prompt_control=live_verified，
  interactive/operational readiness=ready、effect debt clear、pairing settled、scheduler ready。
  上一节的 `host_interactive_fresh` 是当时状态，现已解除；不是本轮剩余容量阻断。

### 验证、失败记录与处理

- 增补 8 项容量回归：条目/字节恰好上限与超一项、无界枚举提前停止、全局待遍历
  额度、只排除 registered Git 管理入口、旧摘要顺序，以及真实 250,001 个文件。
  最后一项使用实际 inode 和生产遍历，验证末尾内容改变仍被识别、0400 保持不变。
- 修复前两项针对性测试失败；修复后的 8 项容量回归通过。
- 首轮 9 模块 611 项：593 passed、17 既有 retired skips、1 error（418.634 秒）。
  Deny 的全部行为断言已通过，随后 TemporaryDirectory 清理报 `Directory not empty: plugins`；
  单独复测同一路径再次报 `Directory not empty: objects`（16.646 秒）。两份失败保留，
  不用行为断言通过掩盖整个用例失败。
- 对应测试的宿主原仅等待主进程，未保证其后台子进程退出；现为该测试启动独占
  process group，并在宿主结束后做有界 TERM/KILL 与退出核验，再清理测试目录。
  不改共享执行器，不扫描/终止其他宿主，不忽略 rmtree 错误。尚未捕获最初写入进程，
  不把具体 Git 后台命令认定为已证实根因。
- 两项收尾回归使用真实父/子进程验证主进程退出后仍能收尾，并证明无关进程不受影响；
  同时拒绝向当前测试运行器的进程组发信号。诊断中 `ps` 被隔离器拒绝已如实保留，
  去掉非必要进程枚举后，两项通过（0.089 秒），不放宽隔离配置。
- 修改后实际原生 Allow/Deny 均完整通过（非 skip）；最终 9 模块组合回归 exit 0：
  613 项、596 passed、17 既有 retired skips、0 failed/error，402.912 秒。
  迁移模块 102 项全部通过；其余覆盖 intent_guardian、approval_invariant、intervention、
  intervention_batch、native_decision_journal、native_session_continuity、
  production_recovery_control、production_recovery_readiness。
- `capacity-final-combined.log` 保存工具返回的最终回归输出和完整终态摘要；其中一段
  中间输出受工具长度限制截断，明确保留截断标记，不冒充逐行完整 trace。
  `capacity-final-result.json` 单独记录退出码、计数、命令范围和证据边界。

### 容量批次完成时的后续顺序（已由下节收窄，R6 保持未完成）

1. 完成当前 scoped 回归与证据记录，只将通过的候选按 task → dev 纪律整合。
2. 通过官方链创建新的不可变安装候选与精确原生卡；已安装版本及旧候选不原地覆盖/复用。
3. 通过正常合同收尾入口闭合已识别的历史 pending 状态；需要其他会话决定时明确请求，
   不改 JSON/JSONL 或删除历史。宿主进程及 turn cwd 仍需移出源根。
4. 全部前置门通过后重新冻结实际物理快照，另发精确搬迁原生卡；实际迁移、重绑定、
   0400/内容/Git 身份终验完成后才可勾选 R6。

## R6 一次性改名收尾（2026-09-14，当前执行边界）

### 纠偏与冻结

- 用户指出一次改名引发过多实现，并同意收窄为本仓一次性维护。实施复杂度已经
  膨胀，不能因为仍称 R6 就否认这一点。停止迁移器、协议、守卫及测试框架的继续开发；
  保留已验证且合 dev 的 `b11cf0b`，不回滚这些成果，也不再以泛化完善作为改名前置。
- 当前原生卡 revision 5 仅批准 GitHub 名称、本地 origin 与本报告/证据更新；receipt
  `95494c1778489a95af79ee20bf7e32bbb1f17a8bacef7403ac3ecaab8280dd97`。
  不是安装、物理搬迁、守卫停用、旧合同代决、历史删除或 main/远端代码发布授权。
- 本地普通 rebind/retire 只接受孤儿工作区，映射重绑还要求原 Git common-dir。
  因而不能承诺“先直接 mv、再普通 rebind”可行；不会绕过现有检查或改账本凑通过。

### 已实际交付

- 事前 GitHub GET 核验旧名称、admin 权限与目标 404；不是假定名称早已改完。
- 一次 PATCH，仅提交 `name=sulde-pro`：`EthanReedLabs/sulde-cc-pro` →
  `EthanReedLabs/sulde-pro`。随后独立 GET 新路径确认仓库 id 仍为 `1248015247`，
  private、main 默认分支、archived=false、disabled=false、返回的账号权限均不变。
- 再次 GET 旧 API 路径返回同一 id 的新名称，说明此次旧 API 路径重定向可用；
  不把该检查扩大表述为所有历史链接、Git/marketplace 客户端和 Pages 均已验证。
- 独立读回通过后才执行一次 `git remote set-url origin git@github.com:EthanReedLabs/sulde-pro.git`。
  root、dev、本任务 worktree 的 origin 均读回新地址。
- 改名动作前后（文档提交之前），排除 origin URL 的本地配置摘要均为
  `cf4f6fae9f72437f39745ad4fe7eb96bc092f62a5034edb02b5b1c0b3707e027`；
  Git refs 摘要均为 `f24bbdb99c0a7a7c31f5710a9f0856d9f1281ab06e94d6b06ff0e8bec1440593`。
  没有 fetch/push，没有通过改名动作改 HEAD/index/refs 或用户文件。
- 当前 doctor ready、native proposal 已 applied、pending_verifications 为空、
  当前 intervention=0。本轮没有修改运行源码或安装件，故不重跑 613 项源码回归；
  本次验证是 API 身份/字段读回、Git 配置差异和报告差异检查，不冒充新的代码验收。
- 原始读回和对照记录保存在既有证据目录的 `name-change-result.json`、
  `name-change-doctor.json`；本任务 worktree 仍承载未完成 R6 证据，不进行清理。

### 剩余交付与硬停止条件

1. 当前任务树尚有两个有效引用文件：`README.md` 的 marketplace 安装地址，以及
   Codex plugin manifest 的 homepage/repository。后续只做这些名称替换与对应检查，
   不重写历史报告、历史日志、旧发行件或已安装 cache。
2. 本地物理目录尚未改名，目的目录不存在；本轮 lsof 证实当前 Codex PID 4127
   的 cwd 仍在源根。先安排涉及本仓的维护窗口，正常收尾必要合同/会话并将宿主及
   turn cwd 移出源根；退出进程不自动等于历史待审状态已结算。
3. 复用已验证的官方安装/迁移入口；若需要安装容量修复，绑定一个新候选、单次验证
   和精确安装卡，不重复旧候选。通过现有门禁后使用新物理快照与精确迁移卡执行一次。
4. 只验收本次交付：新名称/remote/有效引用、Git/worktree 身份、用户文件与 0400、
   必要会话重绑定。新路径可用且这些证据齐全才关闭 R6。

任何前置门若需要新的运行源码修复、扩大扫描/清理范围、其他会话代决或新权限，
保留当时证据并报告唯一阻断，不自动新增任务、不重复相同失败审批、不换入口绕行。
本节是对原改名任务的收窄，不是另建通用迁移项目。

### 本地改名续接实测（2026-09-14，尚未移动）

- 当前 Codex PID 63991 的 `lsof -d cwd` 与本轮 `pwd` 均为
  `/Users/eric/ClaudePlugin`，宿主及 turn 已在源根之外；不再要求重复重启。
- 原失效提案通过官方 propose-revision 刷新当前状态绑定，保留原目标和禁止开发边界。
  当前原生 Allow 已 applied 至 revision 6，receipt
  `ff9e2608c829797800925d4921b2a8912a1c9e7e29855e04e2ecc27cdf0a810c`；
  doctor ready、operational ready、pending proposal=false、pending_verifications=[]。
- 本轮只读重查已识别目标，不扩大扫描：已安装迁移模块仍为 250,000 entries；
  `b11cf0b` 已验收源码为 500,000 entries。这不是新代码缺陷或新的开发任务。
- 五份既有合同状态仍未闭合：dev workspace `1170bc6c6dcbc53ca6216128`（r9，
  pending proposal、3 skills）；dev session `completion-267ee3915da180f817ed2dddf4597e42`
  （r9，pending proposal）；dev session `completion-4901980147fa40cd8e933e77490bae28`
  （r1，3 skills）；dev session `completion-6cbefb0ee2086d965bbeb0994b7df5e1`
  （r1，2 skills）；root workspace `db613882e8d8ba05a196234d`（r195，1 open event）。
  不将这些状态自行认定为完成，也不假冒原会话关闭记录。
- revision 6 明确不授权插件安装、停止其他会话或改历史账本；正常安装需新的密封卡，
  历史语义决定需逐项收尾确认。用户确认这些维护动作之前，不安装、不关闭历史状态。
- 本轮没有运行源码变更、没有重跑 613 项代码回归、没有再次修改 GitHub/origin，
  源目录仍存在、目标仍不存在。本次独立状态读回保存为
  `.sulde/public-export/repository-relocation-r6-20260914/local-rename-resumed-status.json`。

## R6 安装与改名评估续接（2026-09-15）

- 仅延续 R6，没有新增源码修复或任务图。复用 dev `9d550ec` 的 650 项回归
  （633 通过、17 既有 skip）；本轮唯一非报告源码树差异为 manifest cachebuster。
  manifest 提交 `4ef47ebc3bd7be50a88322e9ab49f5791a1cbf16`；后续仅合并 dev，
  不合并 main、不 push、不清理尚承载 R6 证据的 worktree。
- 当前会话原生 Allow 将合同应用至 r8；receipt
  `0dd3a3ed04b9f7a6d974da5c3a080958197b3654a96048ab02664e69f27ae085`，
  transaction `ndt-ccb1ade4f004b03d593aa81523acbedc`。仅授权一次 cachebuster、
  官方候选安装、安装后只读评估和报告，不授权实际目录迁移或历史合同代决。
- 新候选 `r6-decoupling-20260915` 完成 prepare → verify → promote，
  状态 `promoted`、`promotion_consumed=true`；不复用旧 `r6-20260914`。
  正式安装版本 `0.2.5+codex.20260915033753-c7a2a13096`，runtime 摘要
  `906afdcc83614c954843c50fbe5b67ffde2520708d2bfe52a11f740457220d95`，
  与上述源码回归使用的工件一致；候选验证 receipt
  `3adfe1b08754fa4e9594886e035af85030a40cedbf392221111dab32abe0fbd2`。
- prepare 2.602 秒、verify 19.001 秒、promote 42.271 秒；这些是程序执行时间，
  不含人工确认等待与前后检查。验证包含隔离真实 Codex PreToolUse 拒绝、MCP
  initialize、scheduler dry-run；隔离 native PermissionRequest UI 明确 unobserved，
  不冒充当前会话人工确认。实际安装使用前述当前会话 r8 原生决定。
- 本轮一次调用格式错误：Agent 给 candidate promote 加了普通 v2 安装入口使用的
  `PYTHONDONTWRITEBYTECODE=1` 前缀，被 PreToolUse 执行前拒绝，候选未消费。
  只读核对 `resource_preflight.codex_candidate_promotion_candidate` 及既有回归后，
  使用该候选适配器支持的 `python -B … --candidate-home … --json promote … --kb-home …`
  格式，Guardian 核验同一 grant 后安装成功。没有改缓存、绕过守卫或重复安装。
- 安装器完成时保守返回 `generation_verified / live_host_unverified`。随后当前
  原会话通过官方 stable bridge 实际观察到新版 tool_guard/tool_result，prompt/context
  通过 verified_hot_rebind 续接。另执行当前会话、新 artifact generation 的独立负向
  canary：临时标记删除在 PreToolUse 被拒，finalize 验证标记未被执行删除后清理；
  proof `5d1e620530b1312241119726dfac5b1039527bacef3b8eb76e43669e34a5ca98`。
  `proof_current_generation=true`、`gaps_cleared=0`，没有清除任何历史会话缺口。
- 最后 doctor：ready、interactive/operational ready、pairing settled、effect debt clear、
  pending_verifications/open_events 均为空；helper/install 各自已有 system_verification。
  scheduler 16/16 loaded、missing/failed labels 为空、generation 一致。安装前四项历史
  非零退出已记录，重载后状态正常只证明当前装载健康，不宣称所有周期业务已运行成功。
  不额外 kickstart、不新增调度。MCP 验证为官方安装链 initialize，非当前长期 MCP
  连接重启证明。当前 Hook 已 live 验证，不把安装器一般性 restart 提示当作必须新开线程。
- 安装后的官方 `repository-relocation-preflight --assessment-only` 在廉价状态门返回
  `relocation requires settled contract state: open_events, pre_execution_gaps`，exit 2。
  未作全仓内容快照、没有实际搬迁。已知根合同 `db613882e8d8ba05a196234d` r195
  仍有 1 个 open event 和 71 条 pre_execution_gap 记录（不是 71 个独立外部操作），
  涉及 `01a03c4f-f99d-7bb3-96ef-3ac88c23fbab`、
  `01a04634-318f-7203-ba2d-26fa6ac442b0`、`01a056c7-99b3-7e41-a13f-61a89fa02b61`。
  这是首个失败门，不能宣称剩余全仓阻断已穷尽。未手改记录、未代决或替其他会话运行
  canary；下一步需通过既有正式恢复流程闭合真实遗留状态，再单独冻结物理迁移执行卡。
- 本轮使用 intent-guardian/dispatch-task 约束原任务续接，plugin-creator 的官方 helper
  和安装链生成候选；kb-search 命中并全文核对 canonical-byte authority 原文，以独立
  新工件进程及实际宿主事件验收，避免磁盘新版本冒充旧进程已更新。
- owner-only 原始证据目录：`.sulde/public-export/repository-relocation-r6-20260915/`。
  `installation-result.json` SHA256 `89d1b5393f84cc2c1a11d8e8acfb23b99b919180c0f92ecc40325a12c9a9fe05`；
  `post-install-doctor.json` SHA256 `b51ca0976bf1c51e8eada55e2f8d0e15340c41a85d6b7b8a1c92f85015e61459`；
  `current-session-preexecution-proof.json` SHA256 `bb34eb05090072b56d164b59813b6b472916d67a8a15e32cbd1cd365c01ed7f7`；
  `relocation-assessment.json` SHA256 `1a9df070b3d8a929c208c0a3bfa5202cc075bd545186f7912cb995e830bc8608`。

## R6 历史终止补丁部署与 live 验收（r10，2026-09-15）

- 只延续原 R6 安装阶段，没有新增源码任务。当前会话原生 Allow 已应用 r10，
  receipt `8a47bdc3fdfba554f024ca0e00aa9d0491c30ccdee015be1dc68490fee0fdd28`，
  transaction `ndt-28fae946e9e8f3c2fa9f48317410a3ef`。两项密封动作各一次：官方
  cachebuster helper、官方候选生产安装。另允许只读检查、当前会话负向 canary 和报告。
  不授权真实历史 terminate/reprobe/abort、目录迁移、其他会话代决或新修复。
- 沿用 dev 已验收的 `ae74c3c`；唯一非报告源码改动为 manifest 版本标识，提交
  `a8971ab81e0179173ae273de8316951c9e7e9701`。官方 plugin validator 通过；
  不重跑上一轮 517 项回归。候选 runtime SHA256
  `223735a7d3e29a6759d4479c817d50b3f3159fc5afee93d45ea746d9e7c8b563`
  与上一轮实际原生 Allow/Deny 及相关回归的运行源码工件完全一致。
- 新候选 `r6-historical-retirement-20260915` 完成 prepare → verify → promote；
  `status=promoted`、`promotion_consumed=true`。正式版本
  `0.2.5+codex.20260915063408-f8a11f699a`，验证 receipt
  `4c91e80aa38aba7c38645785194b50e4d92e52823e9fa8f7d4b787966d6d7eb1`。
  未复用旧候选或旧安装权限。程序耗时：prepare 16.662 秒、verify 19.452 秒、
  promote 48.922 秒；不包含交互等待与前后核对。
- 隔离验证包含真实 Codex PreToolUse 拒绝、MCP initialize、生产调度入口 dry-run，
  外部模型调用为零。隔离 native PermissionRequest UI 的 unobserved 不当作当前
  人工批准证据；生产安装使用上面的当前会话真实 r10 决定。
- 安装器最初返回 `generation_verified / scheduler_ready_live_host_unverified`，
  首次 doctor 已观察到新版本 tool_guard/tool_result，但尚无同 generation 的
  完整工具往返，因此 prompt/context 暂为 unobserved。后续真实工具回调形成
  独立往返证明后，两项均转为 `verified_hot_rebind`，没有伪造 SessionStart、
  修改观察账本、重复安装或要求用户重启。此中间状态没有新建修复任务。
- 当前会话独立负向 canary 已验证：临时测试标记的删除在 PreToolUse 被拒绝；
  finalize 核验标记未被工具删除后机械收尾。proof
  `306d8fd3cfd968ffb89fe589abb2a59fdd70d22f4d5b4a815e44d8dcfec32b4a`，
  `proof_current_generation=true`、`gaps_cleared=0`，未清除其他会话历史缺口。
- 最终 doctor/operational/interactive 均 ready；原生 pairing settled、CAS mismatch 0，
  当前效果债务 clear。scheduler 16/16 loaded、无 missing/failed labels、generation
  匹配。该结果只证明当前装载健康，不宣称所有周期业务都已运行成功。
  host_approval 和长期 MCP 连接在新 generation 下仍 unobserved；当前不需要新审批，
  安装链 MCP initialize 也不冒充当前长期 MCP 连接重启。静态 Skill catalog 若需刷新，
  仍按宿主生命周期处理；本次新 Hook 及新 CLI 已验证，无需为此重启当前会话。
- 新 `prepare-historical-retirement --help` 正常；没有对真实源合同调用 prepare 或
  terminate。廉价迁移 assessment 仍 exit 2：
  `relocation requires settled contract state: open_events, pre_execution_gaps`。
  不做全仓内容快照、不改账本、不移动目录，不把当前控制合同 ready 当作根 r195 ready。
- 首次组合只读检查被 Guardian 的逐步骤效果证明门整体拒绝；按反馈分别执行
  独立只读命令后成功，未重复已完成安装动作、未改守卫策略。仅记录，不扩张本轮范围。
- 本轮 intent-guardian/dispatch-task 冻结安装边界；plugin-creator 使用官方 helper、
  validator 和候选安装链；kb-search 全文核对 ap-0181，落实“磁盘安装”和“真实会话
  新 Hook”分开验收。沉淀沿用下方原候选及 ap-0181，不直接写共享 KB。
- owner-only 原始证据仍在 `.sulde/public-export/repository-relocation-r6-20260915/`：
  `r10-installation-result.json` SHA256 `78c31138713d57d989bb9154a552e2eea0a2c3af8850af845df2c952089fd91f`；
  `r10-post-install-doctor.json` SHA256 `924222d84ba715c764b22f82224f3ee880d11c481339f8e1af98186c5b81c1b8`；
  `r10-current-session-preexecution-proof.json` SHA256 `6530123c41dfe53834e35224ad16e17921091b08febff26358842865d94e5223`；
  `r10-relocation-assessment.json` SHA256 `6d7a0c78fb8d0e170f141ce126059f3c083682256025eedf01a1354c9b1271fe`。
  候选完整验证结果与终态摘要分别保存为 `r10-candidate-verification.json`、
  `r10-candidate-state-summary.json`。
- 本阶段安装与当前会话 live 验收已完成；报告与 manifest 只合 dev，不合 main、
  不 push，原 R6 worktree 继续保存证据。下一决定是基于真实历史快照的精确终止卡，
  批准和核验后才重新评估实际改名；不是再次安装，也不预先豁免剩余真实效果债务。

## R6 真实历史阶段终止与迁移复检（r11，2026-09-15）

- 当前会话原生批准已应用 r11，receipt
  `2c1d6a9f6666b951fda4982b757f762bef2fdb1ec435b8eaab8038f999349101`。
  只允许准备并单独原生确认根合同 r195、epoch `c046c4a19b7f7a2129ecb502`
  的历史终止，随后只读 assessment、报告和合 dev；不授权源码修复、再安装、
  实际移动、其他历史裁决、main/push 或 worktree 清理。
- 正式 prepare 冻结原文、目标和当前控制会话；独立的精确 terminate 原生 Allow
  已成功执行一次，request `apr-f00c149050e5cb2ad19e3558`，plan
  `08d92cda85c71b3abd8a3a5e40454a02193164ada40e2ea3382b2fd2b9af6f07`。
  返回 `retired_inconclusive`；`effect_asserted`、`authority_transferred`、
  `execution_authorized` 均 false。没有重试历史操作，也没有将未知认定为成功。
- 独立回读：目标 revision 仍为 195、状态 paused、终止标记绑定精确 plan/epoch；
  1 条 open_event 和 71 条 gap 与计划内容逐项相等，`pause_requires_revision=true`。
  计划保留的 `source_raw` SHA256 与处理前原合同完全一致：
  `5c61cc725d5112371bc3747472244c51ddaac81ee968193b979a0ebfaae2109d`。
  官方暂停后的 active JSON 摘要变化符合预期；原 events 与 interventions 文件
  前后摘要完全相同，未改写历史审计或效果账本。
- 随后的 `repository-relocation-preflight --assessment-only` exit 2：
  `relocation has an open approval question`。已通过该目标的历史终止证明校验，
  但预检是首错返回，不能据此宣称其他工作区或所有后续门禁均已通过。
- 只读审批投影确认：根合同保留 9 条 `status=asked` 的旧请求，全部已过期，
  revision 分布为 18、25、66（两条）、83、84、87、159、172；包括
  2 条 effect-intervention、5 条 proposal、2 条 session_resume_card。
  不是 9 个当前等待用户的新问题，也不是全部可按展示卡豁免的记录。
- 已确认口径差异：`approval_invariant.open_requests/summary` 排除 expired；
  `repository_relocation._binding_inventory` 直接遍历原始 asked，未应用过期判定。
  这些请求不满足已有 `intent_confirmation_card` 特例；因此单改 paused/active
  条件不能解决。本轮未取消、重放或批准这 9 条请求，未修改账本。
- 当前 R6 控制合同 doctor：operational/interactive ready、pairing settled、
  CAS mismatch 0、effect debt clear。当前会话没有被此次历史终止自锁。
  本次沙箱内 scheduler 探针 `launchctl_list_unavailable`，是未观测，不能据此
  报告服务失败或重申 r10 的 16/16 为当前实测；本轮不涉及 scheduler 改动。
- r9 的隔离回归及原生终止通过仍有效，但未覆盖“历史终止 + 已过期旧审批 +
  实际迁移预检”的组合。这是集成验收缺口，不是用户没有批准，也不能靠重复 Allow
  解决。仅保存诊断，不把它自动扩展成新的任务图。
- 下一最小修复候选（尚未批准、未实施）：迁移审批检查复用权威的有效请求语义，
  expired 不生成授权、不修改历史；仍独立检查真实 effect debt 和未终结 native
  transaction。补三类旧请求、TTL 边界、当前未过期/typed 请求、未终结事务及
  真实效果反例，并覆盖历史终止后的实际预检。仅凭过期不能宣称原操作已结算。
  通过后才按官方链部署并重跑 assessment，不预先承诺实际改名就绪。
- 本轮只有报告和本地证据变动，无源码变动；不重跑无关全套测试。证据核对与
  `git diff --check` 是本轮报告合 dev 的门禁，不替代 R6 实际迁移验收。
  原 worktree 与本地证据继续保留；物理源目录仍为 `sulde-cc-pro`，目标尚未创建。
- 使用 intent-guardian/dispatch-task 限定精确续接与裁决；kb-search 全文核对
  ap-0234，分开记录“终止资格”“历史结果未知”“当前迁移就绪”，不写共享 KB。
- owner-only 本地证据（均位于前述 R6 证据目录）：
  `r11-historical-retirement-result.json` SHA256 `3b0150e31cb3138e9d6b7413788702d1e216a3f01bf8e61aa4ff46f155abd348`；
  `r11-historical-retirement-readback.json` SHA256 `11bf4f1e4af457abf89676a1427183bdb5963293eff03439d7624c823057e81c`；
  `r11-relocation-assessment.json` SHA256 `8e4a055e70a645f7c0228a73c8c5b6c58681ed363ffb839e434aceb74a25d556`；
  `r11-approval-blocker-diagnosis.json` SHA256 `5cbc0e30e7b419426d52790b2efe11e3faf93df57dd0009d33227717a8497651`；
  `r11-controller-doctor-summary.json` SHA256 `3ed944c14f786e1dee539acc167a7a7d80b6c048d17a40118888dfd9bf94a7b9`。

### Layer1 候选：过期审批历史与有效阻断口径不一致

- 问题类型：workflow / regression；目标：按原冻结计划完成整仓改名，避免重复授权。
- 场景与症状：历史终止成功后，迁移提示 open approval，而审批摘要 open=0、expired=9。
- 根因与证据状态：上述两个读取入口的过期语义不一致，源码及当前历史投影 verified；
  修复效果尚未验证。已排除“本轮 Allow 未生效”和“单纯 paused 展示卡特例遗漏”。
- 正确做法及验证：统一有效请求语义，独立保留效果与原生事务门禁；补组合回归，
  当前仅为候选，不能通过直接删除账本或自动裁决历史请求达成。
- 路由正例（observed）：迁移被过期 asked 阻断 → apply，当前门禁与权威摘要矛盾。
- 路由反例（constructed）：当前有效原生请求待人决策 → skip，等待授权并非此缺陷。
- 执行合格例（constructed）：旧请求不可授权，历史原文不变，真实债务/事务继续阻断
  → pass；完整临时仓迁移预检应有独立证据。
- 执行失败例（constructed）：无条件忽略所有 asked 或因 TTL 到期认定效果成功
  → fail，破坏审批与效果边界。
- 一手证据：本节 5 份记录和两个源码入口。上浮前泛化私有路径、会话及摘要；
  可复用内核是持久历史状态与当前有效状态必须共享语义；建议 anti-patterns，
  消费者为迁移 review/回归测试。仅留任务报告，未直接写共享 KB。

## R6 过期审批口径修复（r12，2026-09-15）

### 冻结范围

- 当前 Codex 原生 Allow 已应用 r12，receipt
  `1afefd6e3d393de9e51b735a6d8ac2ae6d5a7e14eec556a80082f8833974810c`，
  transaction `ndt-668c75305268d64986138334419b2628`。
  基线 `e223142`，沿用原 R6 worktree、任务分支和本控制报告，不增加任务图。
- 仅两个源码文件 `approval_invariant.py`、`repository_relocation.py`，对应三份
  测试文件、本报告及本地证据。验证后只提交/合入 dev；不生产安装、改名、push、
  合 main、清理 worktree、重放裁决或手工改生产账本。额外问题只记录。

### 实现与发现

- 从审批模块的既有判定抽出纯读取 `request_is_open`；有效审批列表、摘要和迁移
  预检共享它。保留原 TTL：`asked` 且未过期才是有效问题；到期等于截止时间即失效。
  不改期限、schema、审批执行器、显示卡特例或任何原历史字节。
- 该谓词只处理已验证账本投影，不产生权限。缺失或不可解析期限不会被它视为
  过期；完整预检仍先校验账本。未过期 typed 请求及需要重新提醒的问题仍阻断，
  过期 typed 请求不可被迟到 Allow 消费。真实 effect debt 和未终结 native 事务
  仍独立阻断，不能用问题过期推断效果已结算。
- 先写回归，再修源码：修正后的三个复现用例在旧源码下均于预期的迁移审批门失败，
  包括真实独立 CLI 的“历史终止 + 三类旧请求”。不是靠测试名称或模拟返回成功。
- 第一轮测试夹具自身曾失败：同时创建 proposal 和 intent-confirmation 会被真实
  API 正确 supersede；typed 提示的 lane 必须由 provider/session 实际计算。
  已改为时间推进后逐个生成历史请求及真实 lane 摘要；不改生产校验来迁就夹具。
- 针对性 22/22 非 skip 通过，15.281 秒：包含历史保留、终止恢复、真实外部债务
  拒绝、截止时间前一微秒/正好到期/之后、typed 提醒与迟到拒绝、临时 Git 全根
  迁移及独立 CLI assessment 前后整个测试 home 文件内容不变。
  未终结 native 事务叠加过期问题的反例为明确的投影故障注入，不冒充真实宿主日志。
- 最终官方组合回归 **248/248 通过、无 skip，428.157 秒，exit 0**：审批、迁移、
  历史终止和原生事务四个模块。本次新增 6 项回归，并扩展既有两个历史终止用例，
  包含真实损坏测试账本的拒绝反例；未增加 skip 或削弱原断言。
- 真实隔离安装件上的 Codex 迁移 Allow/Deny、历史终止 Allow/Deny 共四项均通过，
  各仅一个原生问题；实际执行使用 `codex-cli-app-server` / `unified_exec`，
  迁移后未复核的业务写入仍拒绝。四项使用相同 runtime SHA256
  `7f311a14c784b4ea7a12449079428afa831d8f6cd1ca0f6bdd3b9157d66864d7`。
  这里的安装全部是临时隔离工件，不是生产升级；没有重放 r11 的真实终止。
- 原 Git `0400` 物化为 `0644`、历史权限不转移、真实效果阻断、多阶段进程退出
  恢复均通过。`git diff --check` 通过；六个改动文件全部落在冻结范围内。
  通过后按 task → dev fast-forward 合并，不合 main、不 push；R6 worktree 和
  owner-only 证据继续保留，因为实际迁移尚未完成。
- 下一个边界仍是单独确认官方部署并重新执行真实 assessment，不再新增源码任务。
  已安装版本仍不含本补丁；当前不能宣称真实预检已通过，更不能把候选测试回执
  当作物理改名权限。其余预检条件以部署后实测为准。
- owner-only 原始证据位于前述 R6 证据目录：
  `r12-scope-approval.json` SHA256 `c85da62baaccd3065c7115db604a833bfdeb3edf5335e155853f31b549a93ca0`；
  `r12-expired-approval-red.log` SHA256 `cd91130c36cc47c187cbe71d5a98ba5899602e2ea675733c5db2f4cf5d4f7708`；
  `r12-expired-approval-targeted.log` SHA256 `1d8ae0c31b60b240a03eef00d59d7e7b6a0a04fe5cb3c4e3f5cc46beb41a62dd`；
  `r12-expired-approval-combined.log` SHA256 `7ffc735ba2ccb7e31e8e4731279104afd2657d151867b5cce79a171a6c4a776a`。

组合回归复现（仅临时隔离环境，不指向生产账本）：

```sh
/Users/eric/.pyenv/versions/3.10.7/bin/python3.10 -B scripts/kb/run-isolated-tests.py \
  tests.test_approval_invariant tests.test_repository_relocation \
  tests.test_historical_retirement tests.test_native_decision_journal
```

### 收尾记录

- 本轮技能影响：intent-guardian/dispatch-task 限定继续原任务；kb-search 全文核对
  ap-0234 和 schema-fixture-migration-and-real-execution，保留历史时点，并通过真实
  API 构造夹具、真实 CLI/临时 Git 执行验收。本节是既有 Layer1 候选的修复证据，
  不直接写共享 KB。
- 准备时一次组合 help/派单命令被守卫按上下文变更规则拒绝，拆成独立只读命令
  后成功；没有重复语义裁决或修改守卫来绕行。此问题仅记录，不扩大本轮源码。

## 安装前整链检查与风险清单（2026-09-15，用户纠偏）

### 范围、证据和结论

- 本轮为检查和方案，不执行新源码修复、安装、历史事务裁决或真实移动；原 r12
  代码提交 `ae7343249588a8169354be81fec4c064f4940ab0` 保持不变。
- 问题不在于 r12 测试造假，而在于之前把“局部修复验收”当成“可以开始下一次
  部署”，以及只取 fail-fast 预检的第一处错误，没有分层检查真实状态的其他门禁。
  248 项测试没有替代真实多版本账本、真实数据量和仓库外消费者检查。
- 使用修复后的源码直接调用只读 assessment，不安装也已复现后续阻断：
  `relocation has an unfinished native transaction`。另逐项调用只读投影/验证器收集
  其他域；未修改预检控制流、未构造执行授权、未调用 recovery/advance 来探测。
- 覆盖本仓 3 个真实 worktree、24 份相关合同、5 条会话 mapping：所有相关审批、
  效果和原生账本均可只读重放；没有有效待确认审批、没有 blocking effect attempt；
  mapping 文件名、目标合同和 Git common-dir 均匹配，无 registry selector 异常。
  根 r195 的 1 个 open event/71 条 gap 仍完整保留，正式历史终止证明可验证。
- 物理独立检查通过：同设备、目的地不存在、Git 主仓及两个内部 linked worktree、
  refs/index/配置/Git links 和内容遍历符合现有限制；macOS exclusive rename API
  可用但未执行。真实内容 **359,958 项、7,541,081,655 bytes**，快照检查 40.480 秒。
  此为观察证据，不是迁移权限或未来不会漂移的保证。
- 实际宿主 cwd 在待迁移目录之外；已安装 runtime 和恢复 home 也位于目录外。
  当前 controller ready、effect clear；沙箱内 launchctl 不可见，另经用户批准只读
  宿主探针确认 scheduler **16/16 loaded、无 failed/missing**。没有据此保证未来每次
  任务业务成功，亦未重启/重载服务。
- 原 r195 active、events、interventions SHA256 与 r11 终止后的摘要完全相同。
  本轮只读探测没有改变其历史结果或产生新的原生裁决。

### 安装前必须处理的三类问题（不是新增三组无限任务）

1. **历史事务语义与尾段恢复，已实测阻断。**
   根账本 9 笔非终态：5 笔 r66/r83/r84/r87 的 prepared，已被原生账本现有
   `is_legacy_unsealed_prepared_diagnostic` 精确认定为只读旧版相关记录；关联问题
   已过期、没有 typed Allow。迁移 gate 却只看 stage，仍全部阻断。
   另外 4 笔 r164/r177/r191/r192 为 v5 sealed、已有 typed Allow，停在
   contract_applied，不能套用上述豁免。只读重验其已记录合同回执时，前三笔失败于
   `native proposal approve postcondition is not proven`，后一笔失败于
   `native resume postcondition has no formal lane projection`：验证仍依赖现时合同，
   而历史阶段已演进。没有 committed 历史可直接认领。
   修复边界：复用精确旧版分类；四笔独立核对封存证据，能机械闭合才闭合，证据不足
   则使用经批准的非效果终止机制，不伪造 committed、不改写现时合同去迎合旧回执、
   不重放旧 proposal/resume。必须用有效合成账本覆盖这两种真实形态及反例。
2. **账本与 Git index 共用错误容量上限，已实测阻断。**
   检查 158 个既有迁移 store，总量 121,527,979 bytes；根 events 文件
   98,783,398 bytes。`_frozen_store_bytes` 调用 `_index_digest`，后者上限 64 MiB，
   实际只读调用即报 `relocation index is not a bounded regular file`。这是审批门后
   才会出现的执行阶段错误，不应该等生产执行才发现。
   修复边界：保留 Git index 的原有限制，为账本设计独立有界流式快照与类型化错误；
   提前核验单文件/总量/所有者/link count/并发漂移。补 >64 MiB 合成账本、边界值、
   流式内存与恢复测试，不删除历史日志、不无条件提高所有类型上限。
3. **仓库外源码消费者未纳入迁移，改名后可预期失效。**
   `auto-sediment-source.json` 的 source_root 与 git_common_dir 仍分别指向旧 dev
   worktree 和旧 `.git`。`auto-sediment.py:490` 读取该显式绑定并 strict resolve；
   原路径消失且配置未重绑定时会失败。当前迁移 recipe 只覆盖合同、mapping 和账本，
   没有覆盖这份 sidecar；稳定 launcher/已检查 LaunchAgents 未发现旧根硬编码。
   另有 Codex config 的旧根 project trust 条目，属于宿主配置待核实项，不等同于
   已观测执行失败，也不能静默把旧权限复制到新路径。
   修复边界：只冻结已发现的有效消费者，提供官方受控重绑定和中断恢复，搬迁前
   不提前改坏现有服务；验证改名后自动沉淀只读 source resolve 可用。历史会话文本、
   归档旧路径和已废弃 trust 条目不做全局字符串替换，不扩大成主机清理任务。

### 风险预估与上线门禁

- 当前内容约占 8 GiB 上限的 87.8%，剩余约 1.05 GB；项数低于 500,000 上限。
  这是容量余量风险，不是当前失败。新安装工件/导出/缓存增长需在候选冻结前再核对，
  不为了赶进度删除未验证文件或把所有内容上限取消。
- 一次完整物理快照实测约 40 秒；准备、核验和执行会多次读取，真实耗时可能为分钟级，
  不能沿用小型临时仓测试的耗时。需提前做真实规模合成演练并核对宿主超时与写者
  静默窗口，避免在持锁期间遇到活跃文件或后台消费者持续修改；不把一次 lsof
  无写者当成未来无并发的证明。
- 最终执行只能在现场验证的事项保留为切换门：精确当前原生 Allow、冻结后无新增
  状态、实际改名后 inode/权限/内容/Git links、受控配置重绑定、真实宿主连续性及
  终态屏障释放。这些是对预期结果的确认，不用于首次发现已可提前检查的静态问题。
- 安装前验收固定为：三类问题各自闭合 → 用合成秘密/有效账本重建真实 revision、
  stage、24 合同/5 mapping 和大账本规模，不复制生产授权 → 候选隔离安装及整链
  迁移/恢复/消费者演练通过 → 逐项诊断无未解释 blocker/unknown → 才冻结生产安装卡。
  不用脱敏后失效的签名数据冒充真实可验证回执，不强行开启真实生产写入来验证。
- 本轮不声称所有未知风险已消失：未来文件/会话变化及其他未放入检查范围的外部
  消费者仍需最终冻结清单。也不承诺“再装一次就能改名”。下一轮开发必须绑定上述
  明确缺口和验收，不借此重开整体 Guardian 重构。
- 技能影响：intent-guardian 限制为只读诊断和报告，dispatch-task 保持原计划续接，
  kb-search 原文要求提前核验真实运行条件、用有效 fixture 走实际路径。本节为原
  Layer1 候选追加证据，不直接写共享知识库。尚未执行这些新增修复。

### 本地证据索引

均在既有 R6 owner-only 证据目录，未上传：

- `preinstall-all-gates.json`：`c58009cd6ad804580fe9a720ab05cd78a53ab8aece3329b67065e53962d622d6`
- `preinstall-native-details.json`：`332b5e7dab45e266417727054642c3f2682b56c31d2e029c819c28f4f5159c60`
- `preinstall-native-reverification.json`：`b3c53bd6d6e1f82f3e4d0769bfe4513dff3f88b15993514b01fc91c242f41c97`
- `preinstall-physical-snapshot.json`：`3e1fba1e849537bb40fcb121b9f48cfefd360088ee7c69f5eacad8224f3a5fcc`
- `preinstall-store-capacity.json`：`623955de7ae327cbd0a4471d18638031f7a8802b66ab3d527acadd07b9b4e4d3`
- `preinstall-doctor-live.json`：`e0e904c83b64966b21cfe3705650b8b20b3ace638c44c170c3ccee0949aef513`

### Git 收尾复查跨层诊断（2026-09-15，只诊断，尚未修复）

以下保留修复前诊断；后续源码修复证据见本节后的 r13/r14 记录，不代表生产已更新。

- 用户补充：多个项目报告“仅剩提交后的最终状态复查，被 Intent Guardian 核验授权
  机制阻断”。没有对应原始命令、Hook 拒绝内容和运行时代际，不能把这些个案直接
  归为同一根因，也不能把终端摘要当成精确 reason code。
- 当前源码与已安装 `0.2.5+codex.20260915063408-f8a11f699a` 的
  `command_template.py`、`decision_kernel.py`、`intent_guardian_parts/policy.py`
  和 Codex `_recovery_defer.py` 分别字节一致。因此不能笼统解释为未安装 Git 放行修复；
  其他项目是否仍运行旧快照尚未核实。
- 诊断不执行被测 shell 命令。向真实 `normalize_hook_event` / `process_hook` 注入
  合成 Bash payload；两条独立恢复路由返回无匹配，KB 路径为临时目录，session resolver
  模拟不可用。此探针检验普通决策链，不验证生产恢复路由、实际宿主完整生命周期或
  真实项目事故。未运行生产 Hook 回调、重放批准或创建生产效果记录。

| 命令 | 归一化后的普通决策链（模拟映射失效） | 独立 Codex 降级分类器 |
| --- | --- | --- |
| `git status --short` / `git rev-parse HEAD` / `git diff --stat` | Git passthrough；不查询 session mapping | 不要求拒绝 |
| `git status && git diff --stat` | Git passthrough；不查询 session mapping | 不要求拒绝 |
| `git status \| head -n 20` | effect=read；read_diagnostic_fallback 放行 | 要求拒绝 |
| `cd /tmp && git status` | effect=unknown；查询 mapping 并抛出模拟映射异常 | 要求拒绝 |
| `git status \| tee status.txt` | effect=local_write；不能套用只读兜底 | 要求拒绝，保留负例 |

- 纠正初步推断：基础 `git_execution_passthrough` 和 `is_read_only_command` 均返回
  false，不足以断言最终 Hook 拒绝；`git status | head` 在资源归一化层实际被证明为
  read。其已复现缺口仅在 runtime unavailable 的降级路径，而非普通决策路径。
- 已确认的工程缺口：字面量 `cd && git` 未保持 Git 执行域；正常归一化与独立降级
  分类器对 Git 只读管道判断不同。后者只认纯 Git 分段或精确恢复入口，不承接正常层
  的 read 证明。二者均可能使已完成提交后的取证重新依赖控制面，但不能据此声称
  已复现用户的生产事故。
- 官方隔离器运行以下既有回归 **4/4 通过、0 skip**：
  `tests.test_decision_kernel.DecisionKernelTests.test_git_passthrough_never_resolves_session_mapping`、
  `tests.test_decision_kernel.DecisionKernelTests.test_read_diagnosis_survives_unavailable_session_mapping`、
  `tests.test_intent_guardian.IntentGuardianTests.test_git_execution_passthrough_is_audit_only_even_when_paused`、
  `tests.test_command_policy.CommandPolicyTests.test_git_is_an_execution_domain_not_a_read_write_policy`。
  初次沙箱内运行在 OS 隔离自检失败，未执行测试；经当前宿主批准后仍用官方隔离器
  重跑成功，没有禁用隔离。四项覆盖直接 Git、纯 Git 组合、暂停和映射异常，不能
  替代上表新增边界或完整提交后收尾旅程。

#### 最小修复范围候选（须更新开发范围后实施）

1. 仅补可证明的字面量工作目录切换与 Git 组合识别；保留引用、短路语义和真实 cwd，
   不把命令替换、未知 shell、输出写入、额外外部操作整体当成 Git 放行。
2. 正常层、独立降级层使用同一组结构化输入/预期结果进行一致性验收；降级层不得
   重新依赖已损坏的 Guardian 账本或运行时导入。不要为去重引入新的启动依赖。
3. 在隔离仓验证提交 → 完成回调 → status/HEAD/diff 复查 → 收尾的完整链，覆盖正常、
   映射失效、runtime unavailable、遗留债务；实际执行与仅合成回调的证据分开记录。
   真实未知外部写入不得因一次只读检查自动变为成功。
4. 不扩展到整体 Guardian 重构、不取消原生宿主权限、不自动修其他项目历史账本。
   当前 r12 仅覆盖过期审批迁移口径，此小节是诊断和方案记录，不是新源码开发、
   安装、生产裁决或任务完成授权。

沉淀候选（不写共享 KB）：路由正例为正常/降级层对相同安全复查判断不一致；路由
反例为管道确有文件或外部写入。执行合格例为保留纯读取可达、额外写入原边界，且
两层及收尾旅程同时通过；执行失败例为只测基础分类器、或整体放行所有含 git 的 shell。
分类与异常路径证据已验证；用户多个生产个案的归因仍为 inconclusive。技能影响：
intent-guardian 保持诊断边界，kb-search 提醒区分复合命令的实际效果；未将历史 Git
主目录污染条目误当成本次分类缺口的一手证据。

### Git 收尾识别修复 r13/r14（2026-09-15，源码验收通过，未安装）

- r13 当前会话原生批准已 applied：receipt
  `247f59517205f6260972231256b4e219783c02a5eff95efc563ed1b95eca14ee`，
  transaction `ndt-1ea2f6b0c41de87b59aeabc70d136911`。冻结两个识别缺口、相关回归及报告，
  不安装、不实际改名、不改其他项目或生产效果历史、不推远端或合 main。
- 执行中补齐依赖清单漏项：稳定桥还有 `scripts/kb/codex_recovery_defer.py`，原先
  只检查普通分类器及静态适配器不够。新增三方一致性回归在 4 个安全管道上真实失败。
  未通过改变 Git passthrough 含义来绕开文件范围；r14 只增该文件，目标与验收不变，
  经原生批准后才修改：receipt
  `68911341c02cb25083d8a0ae9fbf12e933c3de18d9802d7bb703dd2ffcb80e8a`，
  transaction `ndt-456b1ecc9841bded3ff65bf3b08ad03b`。
- 第一次准备补充提案因 OS 文件锁权限失败，没有提案；按原入口请求权限后成功，
  没有编辑 active JSON、重放批准或绕过隔离。依赖清单漏项是本轮流程教训，不新建任务。

实现仅涉及 4 个源码文件、1 个新测试文件和本报告：

1. `command_template.py` 识别一个字面量 `cd [--] path &&` 前缀，后续仍须由原有
   纯 Git 结构证明通过；只用于分类，不修改 shell 命令、工作目录或 Git 参数。
   `cd` 失败时原 shell 短路行为不变。动态路径、额外操作、非 `&&` 前缀不获得此证明。
2. 增加有界 Git + stdin 过滤器证明：仅接受 `head`/`tail` 的默认或精确 `-n/-c N`，
   以及 `wc` 的计数参数；不接受文件操作数、自定义路径程序、重定向、替换或额外命令。
   最大 64 KiB 命令、8 段、7 位非负数字参数。Git 本身仍由宿主授权，这不是 Git
   子命令白名单，也不是把 Git 写入伪称为成功；只证明其余过滤阶段无新增写入。
3. `resources.py` 在普通分类中采纳该证明；稳定桥导入相同纯函数；静态适配器保留
   独立纯解析实现，不依赖 Guardian 模块、账本或 runtime 可用性。三方用同一矩阵
   检查，避免只测一份实现导致再次分叉。

验证结果：

- 先在未修源码上跑新回归：6 个测试中出现 7 个失败/10 个错误子例，覆盖 cd 未进入
  Git 通道、缺失 mapping、静态降级拒绝；附加写入负例通过。此为预期红灯，不计通过。
- 补稳定桥前，三方一致性 4 个安全管道子例失败；修复后全部转绿。
- 最终官方隔离回归 **81/81 通过、0 skip，测试主体 2.386 秒**（不含授权等待）：

  ```sh
  python3.10 -B scripts/kb/run-isolated-tests.py \
    tests.test_git_final_verification tests.test_command_policy \
    tests.test_decision_kernel tests.test_intent_guardian_resources \
    tests.test_codex_hook_bridge \
    tests.test_intent_guardian.IntentGuardianTests.test_git_execution_passthrough_is_audit_only_even_when_paused
  ```

- 新增 11 个测试方法，含纯 Git、只读过滤、额外写入/未知 shell 负例、映射失败、
  暂停/不可读账本、真实有效 unknown 外部效果历史保持不变、静态适配器实际错误输出、
  稳定桥一致性、数量/长度边界及 `cd` 失败短路。未将旧债务清零作为放行代价。
- 在临时含空格路径仓库真实执行一次本地 commit，之后独立执行 status、HEAD、diff
  及 head 管道，确认提交数恰为 1、结果正确；分别向真实策略入口提交合成 Pre/Post
  payload，再调用真实 `finalize_host_turn`，open_events/pending_verifications/attempts
  均为空。另一用例保留原有效 unknown 外部债务账本字节和阻断状态。
- **证据分级**：临时 Git 命令真实执行；Hook/映射故障为隔离合成输入；适配器 runtime
  unavailable 为故障注入；不是已安装运行时的真实新会话验收。其他项目原始拦截记录
  尚缺，因此其个案归因仍 inconclusive；不宣称已修复所有 shell 写法或所有收尾故障。
- `git diff --check` 通过；原 r12 源码未改动，保留先前安装前检查的全部报告内容。
  合并只允许本任务提交 fast-forward 到已核对干净的本地 dev，并在提交后独立检查
  status/HEAD/diff/祖先关系；不使用本报告预先替代这些实际 Git 结果。

当前交付边界：这两个源码缺口通过验收，生产插件未更新；原 R6 的历史事务、账本
容量和仓库外消费者三类安装前事项仍未完成，目录未移动。本 worktree 保留用于原 R6，
不以本次局部修复冒充整个任务完成或触发清理。技能影响：intent-guardian 冻结两项
范围及明确依赖补充，dispatch-task 仅续接原报告，kb-search 保留复合命令实际效果边界；
此为原沉淀候选更新，不直接写共享 KB。

### R6 账本容量修复 r15（2026-09-15，源码验收通过，未安装）

- 延续原安装前三类清单，本轮只做容量项，不新建任务图。r15 当前会话原生批准
  applied：receipt `24ccd95a89dafa0bf79960b18dcd86ca528a75b0e805b25715c3c08e60a885f9`，
  transaction `ndt-366f7a36b297146d43350ce7e7947674`。开发基线 `024931e`；范围只有
  `repository_relocation.py`、两个容量/迁移测试文件和本报告；验证后只合本地 dev。
- 根因不是账本坏了：迁移快照、原合同归档和迁移后读回混用 `_index_digest`，把
  Git index 的 64 MiB 限制施加给审计账本。只修第一次快照仍会在恢复读回再次失败。

修复与固定边界：

1. `_index_digest` 及其 64 MiB 限制不变，现在仅供 Git index 使用；仓库整体的
   8 GiB/500,000 项限制亦不变。账本独立单文件 256 MiB、总量 1 GiB、1 MiB 分块读取。
   超限继续拒绝，不删除或截断日志，不无上限读取。
2. `freeze_relocation_preflight` 在生成执行计划/发布屏障/移动前检查冻结范围内的
   store 容量与类型；执行仍在原有锁与屏障下重新读回。预检不把当时可变审计字节
   塞进批准卡作为永久事实，也不授予执行权。
3. `_store_snapshot` 从同一打开的 FD 取得摘要、大小和 mode，验证当前所有者、普通
   文件、链接数，以及读取前后 dev/inode/mode/uid/nlink/size/mtime/ctime 一致。
   缺失后继槽和空文件区分不变；manifest 仍只有既有 path/sha256/mode，不升级格式。
4. 原合同及归档、后继、mapping、日志的读回不再套用 index 容量限制；核验阶段也
   检查账本总量。只对原流程已证明为同一源文件/归档的精确双硬链接中间态保留恢复
   兼容；普通快照及其他 store 不接受多链接。没有新增通用放宽链接的执行入口。

已取得的证据：

- 修复前新大文件用例报 `relocation index is not a bounded regular file`；新增独立
  限额尚不存在。漂移负例原来已拒绝，本轮保持拒绝并改为正确的 store 错误分类，
  不把错误文案变化冒充新发现的防护缺陷。
- 专项 **7/7 通过**（5 个摘要测试与 2 个真实临时迁移测试），测试主体 7.599 秒。
  包括约 96 MiB 合成 JSONL 的流式摘要、摘要阶段 tracemalloc 峰值 <8 MiB、原 index
  限制仍拒绝同样大小文件、单文件/总量精确边界及越界、缺失/空文件、符号链接/
  硬链接/非普通文件/错误 owner、读取中追加/截断/替换/改 mode。
- 临时仓真实迁移带约 96 MiB 合成审计；在 archive_linked 边界中断，确认源 nlink=2，
  随后原入口恢复成功。账本独立流式摘要未变、事务只有一个且再次执行不追加 journal，
  fence 正常释放、后继仍 paused 且没有 local_write 权限。
- 对之前已定位的真实根审计文件仅调用新的只读摘要器，不运行生产迁移或恢复：
  **98,783,398 bytes，0.042 秒**，SHA256
  `b29db088d61abaf001be1c7fd301a2e0cfffce86c61fccd4fb62df73468fbfa0`，与先前记录一致。
  原 mode `0644` 保留；此次摘要可用不等于目录迁移或完整权限验收已经通过。
- 最终官方隔离回归 **181/181 通过、0 skip，373.629 秒**，覆盖完整迁移模块、
  本轮容量、r14 Git 收尾及 r12 审批口径。耗时主要包含真实临时大目录遍历、独立进程
  与中断恢复，不是反复人工批准。隔离 Codex Allow/Deny 均非 skip：每次一个原生问题，
  Allow 只移动临时仓并保持后继暂停，Deny 不移动、不创建执行事务，模型请求为零。
  候选 runtime digest `7ee47f8f6c3087fd4c5cee24e3be0a1c74b554588ac48f86ecb9e2720cd317fc`。
  这不是生产插件已更新的证据；保留其与真实账本只读探针的不同证据等级。
- 最终差异检查限定 4 个批准路径；交付只允许 fast-forward 到干净本地 dev，随后
  独立核对 HEAD、status、diff 和祖先关系，不把测试完成替代 Git 提交后复查。

完整回归命令：

```sh
python3.10 -B scripts/kb/run-isolated-tests.py \
  tests.test_repository_relocation tests.test_relocation_store_capacity \
  tests.test_git_final_verification tests.test_approval_invariant
```

中途发现/解决：完整调用链核查提前发现恢复读回也使用 index 摘要，因此纳入同一
文件内修复；特别保留精确归档双链接中间态，避免新增恢复自锁。没有扩大到历史
事务裁决、消费者重绑定、安装、真实改名、生产日志清理或其他项目。

沉淀候选（原 Layer1 更新，不直接写共享 KB）：路由正例是不同对象共用错误容量
策略导致迁移和恢复不一致；路由反例是超过已批准账本预算的真实超限，仍须拒绝。
执行合格例是独立有界读取、前置检查、同一恢复读回及真实大文件/中断回归一起通过；
执行失败例是只提高一个数字、删除历史、或只跑小文件样本。知识库“迁移切流前最终
备份验证”用于保留最终独立核验，不把历史预演当现场状态；intent-guardian 冻结本轮
容量项，dispatch-task 沿用原报告续接。当前原清单另两项（历史事务、仓库外消费者）
仍未修复，生产安装与 R6 总验收仍未完成，任务 worktree 继续保留。

## R6 历史原生事务修复（r16，2026-09-15）

### 冻结范围与当前状态

- 开发基线 `13d4a9ab086c4d22a06426424d7dbf039c01ec92`，沿用原 R6
  worktree 和任务报告；本轮只处理原安装前清单的历史原生事务项，不增加任务图。
- 当前会话原生开发确认已 applied，revision 16：
  receipt `8416c0c42bedd60b0e1f17c82da96f217bf042e5bb4cad7c30d6a2b0820feef0`，
  transaction `ndt-78e6e6ef0c927f0e2a4ac19a75377947`，
  request `apr-0ca2edaa586713793153a223`。这只批准源码开发、隔离验证和本地 dev
  集成，**不批准生产历史事务终止、安装、实际目录移动、main 合并或推送**。
- 修改限于既有 CLI/历史终止路由/审批说明/原生账本/迁移 gate、新的历史合同事务
  模块及相关测试、此报告。没有改 effect 执行器、已安装 cache 或其他项目。
- 源码通过与生产处置分开：真实根账本仍为 **5 笔旧版诊断 + 4 笔 contract_applied**，
  本轮没有终止它们。原清单仓库外消费者重绑定仍待修复；R6 总验收仍未完成。

### 实现与安全边界

1. 迁移 gate 复用 `is_legacy_unsealed_prepared_diagnostic` 的精确分类，
   与现有 legacy adapter 一致；原记录按字节保留，没有给旧诊断添加批准或终态。
   当前审批问题、形态不匹配的事务、真实 effect debt 仍由独立门禁拒绝。
2. 复用 `prepare-historical-retirement --native-transactions` 与现有
   `historical-retirement` 原生确认路由，不新增通用恢复/绕行入口。
   只冻结同仓库、不同于控制合同、已具正式历史终止证明且仍暂停的源合同。
   候选限定较旧 revision 的 sealed proposal/resume、stage=contract_applied，
   非当前会话，且原始 typed Allow 的请求/决定/authority 证据均独立可验证。
3. 不使用现在时合同去补造旧 contract receipt；不调用旧操作适配器，不声称旧操作
   成功。新的当前会话 Allow 只授权精确冻结清单的后续推进资格终止；之前的 epoch
   retirement Allow 只证明旧阶段已停止，不能代替本次批准。
4. 复用既有 `superseded` 事件语义、账本单写者和 anchored pending 恢复协议；
   同批事件一次追加，整个原生投影 cut 在写者锁内 CAS，其他事务变化也拒绝。
   双合同锁按确定顺序获取，重复同一决定只读回同一批终态。源 active 合同不改，
   没有删除历史，也没有将旧事务补为 committed。批次管理回执的 committed 文件
   不是旧操作成功回执，明确返回 inconclusive / effect_asserted=false。
5. 新批次最多 100 笔；不可变计划在写入前校验 16 MiB 上限。旧批准核验失败、
   Deny、跨会话、源内容漂移或原生 cut 变化不能产生该批 supersession。
   原生/审批协议错误经既有 CLI 错误类型返回，不以裸 traceback 代替领域拒绝。

### 一手证据与验证

- 真实根合同只读复核：历史终止证明仍为 retired_inconclusive；r164/r177/r191
  proposal 和 r192 resume 的 **原始 Allow 4/4 验证通过**；5 笔 legacy 分类不变。
  这证明它们可成为待审终止候选，不是新的执行权限。
- 读取前后 active / events / native journal / head anchor 摘要完全一致：
  active `0a798d4c85d2aa0cc591fe35c940acd1f4c3bd3935144f3421c9d8a374ed1181`；
  events `b29db088d61abaf001be1c7fd301a2e0cfffce86c61fccd4fb62df73468fbfa0`；
  native `ae4ce2285d088df79c040aaadf8fec50a8f2653918df57d4219253c11a64f535`；
  head `738c87546f3d24d759cfc3daf062278d9289933370f5f8b6b588870ea3c3d452`。
- 新增 14 项历史合同事务用例，通过真实 typed 请求/裁决/方案应用/恢复链生成
  3 proposal + 1 resume，在 contract_applied 处中断后演进到 r195；仅旧版已经停产
  的 prepared 格式按明确历史 fixture 构造，未复制任何生产授权。
- 覆盖 Allow、Deny、无批准、跨会话、源漂移、整个 cut 漂移、原批准损坏、错误
  candidate、三批次边界及 journal pending-anchor 中断、重复恢复、两合同真实
  跨进程锁排斥；只追加 4 个 superseded，5 个诊断原样保留；真实外部效果债务
  处置前后字节不变，迁移继续拒绝。
- 迁移 gate 增加独立 legacy-only 正例及近似形态/活跃问题反例。
- 完整相关套件：**283/283 通过，0 skip，478.245 秒**；命令如下。包含候选隔离安装后的旧 epoch Allow/Deny、
  新历史事务 Allow/Deny、整仓迁移 Allow/Deny，均为实际 Codex 原生传输、非 skip。
  新历史事务用例先为 epoch 终止单独确认一次，再为精确事务批次确认一次；
  拒绝第二次后源保持原有暂停，4 笔事务不变。
- 本次隔离候选 runtime digest：
  `bcda217f7c88573f53d8fa8fec6c750f66eab77b8aefa4b7924b2352530bd622`。
  没有修改生产已安装版本；原生测试使用本地合成模型端点，不请求外部模型。

```sh
python3.10 -B scripts/kb/run-isolated-tests.py \
  tests.test_historical_native_retirement tests.test_historical_retirement \
  tests.test_native_decision_journal tests.test_repository_relocation \
  tests.test_relocation_store_capacity tests.test_git_final_verification \
  tests.test_approval_invariant
```

### 中途发现与解决

- 首轮 fixture 导入把 pause_contract 当作 state 导出，测试立即失败；改用现有 CLI
  领域入口，未改生产实现去适配错误测试。
- 强化原批准核验时发现请求创建前缀还没有 prompt_shown；不能要求旧前缀包含未来
  展示/决定。保留 typed 请求绑定，另由原有终态前缀重放器验证后续 Allow 与准确
  provider/session/actor/outcome，不放宽审批结构。
- 新模块尚未 git add 时，源码测试能导入，但 tracked-only 候选打包漏掉它，
  隔离安装测试真实报 ModuleNotFoundError。暂存新模块后重新跑安装原生链通过；
  暂存不等于提交/验收通过。没有扩大修改安装器、伪造文件清单或修改生产 cache。
- 官方隔离测试器与技能登记的沙箱权限失败，均通过当前宿主原生提权机制重新执行；
  没有绕过隔离器或修改 Guard 策略消除错误。失败轮次不计入通过数字。
- 相关套件全绿后按原规则精确提交并快进本地 dev；任务 worktree 保留给原 R6
  消费者修复与最终验收，不能因本轮提交已合并就删除整个未完成任务。

### 沉淀候选（Layer1，追加原报告，不直写共享 KB）

- **类型/平台**：regression / none。
- **任务与真实预期**：安装/迁移前发现并解决真实历史状态兼容问题，不让局部单测
  通过掩盖安装产物缺文件或旧合同回执自锁；不扩大原任务图。
- **根因与排除**：历史相关记录与可推进事务混为一类；旧合同回执复核误依赖
  现在时合同投影。原始批准不是缺失，已只读核验 4/4；不能据此伪造完成回执。
- **证据状态**：源码根因、合成历史整链与隔离 native 验收为 verified；
  生产终止/安装/真实迁移尚未执行，不把它们写成成功。
- **判重**：症状检索 ap-0234《把历史证据用现在时写成当前状态》0.820762，
  全文为文档时态混淆，与本次可执行账本恢复不同根因；建议系列关联而非强并。
  work-model/ownership-aware-receipt-locks 0.725442，全文支持双合同锁覆盖，
  仅可关联并发验收原则。根因检索《流式快照合并的单调性守则》0.750526、
  《端侧文本推理连续请求的状态边界》0.718153，全文属于其他数据/推理状态域，
  不把高分当同根因，不套用“有值覆盖”或重置状态。未取号、未改索引或 knowledge。
- **路由正例（observed / apply）**：旧合同已演进，仍以旧事务 stage 一律阻断迁移；
  原批准可核验但现在时 postcondition 不再等于历史。应分离历史事实、继续执行权
  与当前效果证明，不要求将现合同回滚成旧合同。
- **路由反例（constructed / skip）**：真实外部写入结果未知，即使合同事务过时也
  不得忽略 effect debt；缺少非效果终止的适用前提。
- **执行合格例（constructed / pass，已运行 fixture）**：当前原生 Allow 精确绑定
  批次；一次追加非效果终止、保留历史/未知、重复恢复不重复事件，真实债务仍阻断，
  并用安装产物的实际原生链验证。
- **执行失败例（constructed / fail）**：清空 JSONL、批量补 committed、重放旧
  proposal/resume，或仅源码测试通过就宣称安装后的恢复可用；违反历史/授权边界。
- **上浮**：建议 anti-patterns；消费者为迁移 gate、审批/回执恢复 review 与隔离
  发布测试。上浮须去掉项目路径、会话/事务 ID、日期和提交，只留历史前缀与当前
  状态的证据边界。intent-guardian/dispatch-task 冻结并沿用任务，kb-search 提供
  原文判重，sediment 只产出本段候选，不承担共享库写入。


## 沉淀候选（延续原候选，不直接写共享 KB）

### R6 历史阶段终止修复冻结（r9，2026-09-15）

当前原生开发确认已 applied（receipt
`f38c73a2d7d9bbb30fd36167faf75cae879696c331afb0d18af1a2a463af2dfa`）。
基线 `b0045cf`，沿用本 worktree；不增加任务图。只开发一个历史阶段终止入口：
冻结同仓不同目标合同、当前控制会话与记录；原生批准后追加非效果收尾证据并撤销
目标旧阶段执行资格。保留原文与未知结果，不清除真实效果账本，不声称历史测试通过。
生产安装、真实历史状态处理和目录移动均不在本开发卡内。

- [x] H1：冻结只读计划与当前原生决定；Deny/伪造/跨会话/CAS 漂移不改变目标。
- [x] H2：追加证据、旧阶段不可继续授权、未知结果保留，中断恢复最多一个终态。
- [x] H3：迁移只接受已验证的历史终止证明；新记录与真实效果债务仍阻断。
- [x] H4：官方隔离回归与真实临时 Git/native 宿主链验收，逐项记录后仅合并 dev。

超过上述入口所需范围的修复另报，不静默扩大。失败实现不合并；原 R6 实际改名
验收仍单独保留，不以 H1–H4 源码通过替代安装或真实历史处理。

### r9 实现与阶段证据

- 新入口 `prepare-historical-retirement` 只保存 owner-only 不可变计划，不创建执行权限。
  `native-decision historical-retirement --decision terminate` 精确绑定当前 Codex 控制
  会话、同一物理仓库、目标原文、revision/epoch、控制策略和 runtime generation。
  这是对另一份冻结历史合同的非效果终止，不是清空当前会话状态的开关。
- typed 原生批准账本是决定真源；独立 `.committed.json` 是可回读的终止证明，
  不伪造 T13 committed 事件，也不是原操作的成功回执。目标保持暂停，历史
  open event/gap 原记录保留，原合同字节另存于不可变计划；返回 `inconclusive`，
  不重试、不迁移旧权限。终止标记进入 policy digest，旧提案和旧 epoch 不可续用。
- 目标内容变化仍拒绝；自身观测序号不作为内容变化。审批后、目标暂停后和
  终态写入后的中断均可用同一精确决定恢复，已验证不二次裁决、最多一个终态文件。
  恢复仍要求原控制会话、策略和 generation 精确匹配；不是跨版本/跨会话授权转移。
- 原迁移预检只在完整终止证明验证通过后接受冻结历史记录；新增记录、伪造证明、
  pending verification、真实效果债务和其他未决审批/事务仍由原有门禁拒绝。
  完整临时 Git 迁移测试已证明：原合同按字节归档，后继合同保持待确认，不复制
  历史执行 runtime/权限。该后继流程不等同于直接恢复被终止的旧合同。
- 针对性官方隔离测试：17/17，12.392 秒，exit 0；包含上述中断边界和一次真正的
  临时 Git 整根移动。日志 `historical-retirement-unit.log` SHA256
  `09c6f3f81e23530b039e4d4a977b07bc72543dfa7176d61dfadafc5de2db6c0c`。
- 实际 Codex 原生 Allow/Deny 均已通过，各仅一张问题；隔离候选 runtime SHA256
  `223735a7d3e29a6759d4479c817d50b3f3159fc5afee93d45ea746d9e7c8b563`。
  不把隔离注册/安装当作生产升级。
- 最终统一官方隔离回归：`tests.test_historical_retirement`、
  `tests.test_repository_relocation`、`tests.test_intent_guardian`、
  `tests.test_approval_invariant`、`tests.test_native_decision_journal`。
  共 517 项，500 通过、17 个既有 retired Git 语义用例 skip，467.984 秒，exit 0。
  本次新增 19 项（17 个针对性用例 + 2 个实际安装件原生用例）全部非 skip 通过。
  原迁移的实际原生 Allow/Deny 也非 skip 通过，工件 SHA 与历史终止测试一致。
  既有 Git 0400 物化为 0644 的反例、中断恢复、未知效果和审批账本回归通过；
  未改 skip 标记或删除断言。证据为完整未截断日志
  `historical-retirement-final-regression.log`，SHA256
  `de4aae1a70ec789d1e5963631b66566e88ddac3e28d381c36cad1ecd1721bb6b`。
  日志均在本报告前述 owner-only 证据目录；源码与证据通过后才提交/合入 dev。
- 源码提交 `81640295e5457b5d513df66b4d80c882b52a2c64` 已从 `b0045cf` fast-forward
  合入 dev，无冲突、无另行改写源码，合并后 dev 工作树干净。H1–H4 开发闭合。
  本次未合 main、未 push、未生产安装、未处理真实 r195 或执行真实目录改名。
  原 R6 worktree 继续保留，其实际迁移任务与 owner-only 证据尚需后续使用，不清理。
  下一步只剩按新工件单独授权官方部署，再按精确历史快照处理阻断并重新预检；
  不预先承诺所有实际阻断已穷尽，不扩大当前源码任务。
- 测试过程中修正的夹具问题：使用实际 `model_host` 而非不存在的导出名称；
  迁移后读取正式 successor 路径，而非猜测普通 workspace 哈希路径。
  实现审查修正：历史终止资格拒绝应先于一般“缺少 decision 字段”的拒绝，确保
  拒绝原因与旧阶段不可继续的实际边界一致。未通过的中间尝试不计入正式验收。
- 第一轮广义回归的终态输出未完整保留，未计入最终通过数量；最终统一回归另行
  完整收集日志。此处只记录证据缺口，不把“进程已经退出”当作测试通过。
- 本轮使用 intent-guardian 和 dispatch-task 维持冻结续接边界；kb-search 全文
  核对 ap-0234/ap-0242，明确历史证据不能冒充当前成功，真实控制面本地写入
  不能套用只读 MCP 自动恢复规则。未写共享知识库；上述证据保留在任务报告内。

#### 沉淀候选：终止历史执行阶段与证明历史成功不是同一件事

- 问题语境：已有控制面写入缺少完成证据；不同会话历史监督缺口阻止物理迁移。
- 根因：执行资格、历史结果和迁移就绪原先共用“未闭合”投影，缺少非效果终止语义。
- 证据状态：临时仓库和隔离原生宿主 verified；生产处理未执行，真实 R6 仍未完成。
- 路由正例：冻结同仓另一历史 epoch，经当前原生人工批准 → 终止阶段并保留未知。
- 路由反例：当前会话记录、跨仓、外部效果或已关联 attempt → 拒绝进入此入口。
- 执行正例：同一 Allow 在暂停后中断 → 恢复同一终态，不重试旧操作。
- 执行反例：终止后新增记录或真实效果债务 → 迁移仍阻断，不扩大已批准快照。
- 一手证据：`tests/test_historical_retirement.py` 与本节日志；仅为 Layer1 候选，
  不直接入共享 KB，也不由当前通过推断历史操作成功。

### 2026-09-15 历史恢复入口核对（只诊断，未执行历史裁决）

- 用户要求继续后，核对原 R6 阻断和现有正式恢复路径；没有重新安装、物理改名、
  假冒历史 session、直接修改 active/events/effect ledger 或自动扩展源码任务。
- 官方 `report --contract` 指向根合同 r195，审计完整性 valid，自动可对账项为零。
  未闭合事件 `bf54cf4dfbd0808a4b5e39b8` 是 2026-09-02 的 `tool:apply_patch`，
  涉及 `integrations/codex/plugins/sulde/scripts/pre-tool-use.py` 与
  `scripts/kb/intent_guardian.py`；分类为 `quarantined_high_risk`，原因
  `control_plane_local_write`。没有 attempt_id，不能直接套 effect-intervention abort。
  不能据此断言旧补丁失败、成功或从未写入；结果仍未知。
- 71 条 pre_execution_gap 对应 64 个不同 event_id，分布为 3 个 session 的
  2/67/2 条（不同事件 2/60/2），时间范围 2026-08-30 至 2026-09-01。
  它们不是 71 笔外部效果债务。`clear_pre_execution_gaps` 的正式调用者只有
  `pre-execution-proof-finalize`，只清除完成真实负向测试的同 provider/session；
  当前会话的成功测试不能证明其他历史 session。
- 现有入口边界：`reconcile-verifications` 处理注册 verifier 的效果对账，不清除
  上述控制面 open_event 或跨会话 gap；stale local write 自动结算拒绝控制面目标；
  独立 production recovery 仅支持 `repair_launcher` 和 `repair_generated_bytecode`。
  原生 kind 注册没有历史控制面事件终止/历史 gap 退役入口。因此没有发起无执行器
  支持的确认卡，也没有用新 revision 清空状态来冒充恢复。
- 根效果报告另外保留 1 个 unknown 安装 attempt、0 个 open intervention；它与上述
  apply_patch 无 attempt 事件不同。只记录该投影，尚未判定其是否仍有真实阻断权，
  不把 `interventions_open=0` 或当前版本安装通过当作历史效果已核销。
- `doctor --workspace <root> --session-id <current>` 实际沿当前 session mapping
  返回 R6 合同；因此它的 ready 不代表根 r195 ready。这里采用明确 `--contract`
  的 report/interventions，避免检查目标错位。
- 知识检索命中 ap-0242 并全文核对；其只读误分类自动恢复规则不适用于本次真实
  local_write 控制面目标，未据此降级效果或自动 abort。
- 当前唯一实现候选（尚未批准/实施）：精确历史快照及原生人工决定驱动的非效果
  终止/退役入口，追加结算证据、不声称历史执行成功、不重试、不转移旧权限；历史
  lane 必须失去继续执行资格，恢复执行需新的合法绑定。真实未决效果仍阻断。
  验收必须包含 Allow/Deny、跨会话拒绝、历史不可改写、CAS 漂移、中断幂等和实际
  迁移预检；不能仅给预检增加“忽略旧记录”开关。该候选超出 r8 的禁止源码修改
  边界，需新的明确范围批准，不自动开工、不增加一组重构任务。
- 证据：`.sulde/public-export/repository-relocation-r6-20260915/historical-recovery-diagnosis.json`。
  R6 保持未完成；既有安装与当前会话 live 验收结论不变。

### Layer1：整仓改名中的路径身份与物理身份

- 问题类型：workflow / regression。
- 任务目标/用户真实预期：整仓改名后继续原计划，不丢文件、不复制旧授权、不新增自锁。
- 触发场景：主仓根包含 linked worktree，守卫路由保存绝对 Git common-dir。
- 可观察症状/差异：根移动后路径变化；相同 HEAD 的克隆也有相同代码，二者不能
  仅凭路径或内容摘要区分。
- 已确认根因：路径字符串不具有跨根移动的物理身份语义；HEAD 不包含工作树、
  index、忽略文件或非可执行权限位。
- 已排除假设：相同 HEAD 足以证明同仓；Git 自身能证明 0400 权限保留。
- 证据状态：物理层、临时 Git/native 迁移与崩溃恢复 verified；生产实际迁移未执行。
- 一手证据：`tests/test_repository_relocation.py` 的真实临时 Git 回归；本报告测试记录。
- 正确做法：物理身份与内容/权限分层核验；预检绝不产出执行权限。完整修复仍需 R2–R4。

| 样本 | 内容 | 固定预期 | 判定原因 | 来源 |
|---|---|---|---|---|
| 路由正例 | 主仓与其内部 linked worktree 整根改名 | apply | 绝对路径变化但预期保留同一物理仓库 | constructed，真实临时 Git 测试 |
| 路由反例 | 同一 common-dir 下普通 worktree handoff | skip | 不涉及整根迁移，应保留已有同仓规则 | observed，既有 handoff 回归通过 |
| 执行合格例 | 临时根移动并修复 Git links 后，inode/index/内容/0400 均一致 | pass（物理层） | 各证据层独立核验，无权限转移 | constructed，真实临时 Git 测试 |
| 执行失败例 | 相同 HEAD 克隆冒充，或把 0400 物化成 0644 | fail | 物理身份/权限不一致，即使 HEAD 一样 | constructed，反例回归 |

- 上浮前泛化：项目名、私有路径、提交、会话及计划编号。
- 可复用内核：路径不等于物理身份；证据不等于执行授权；临时 Git 集成用例不能
  替代真实宿主原生事务/中断验收。
- 建议容器：work-model；候选消费者：迁移 review checklist / 检索。
- 本轮仅保存在任务报告，不直接写共享知识库或图谱。

## R6 已知源码消费者重绑定（r17，2026-09-15）

- 范围沿用原安装前第三类缺口，没有新增任务图或通用配置迁移框架。当前原生 Allow
  receipt `604e3cea4a5059426c9a818e18e1e51cab922b115d5f05142d354dac615f468f`，
  transaction `ndt-ff51eac04c51e511a290e765f3b37c00`；开发卡只允许源码、测试和本报告，
  不含生产安装、真实配置变更、历史裁决、目录移动、main 合并或 push。
- 唯一外部配置为 `auto-sediment-source.json`：原始文本、摘要、0600 权限、精确旧/新
  source_root 与 git_common_dir 纳入原迁移快照、可读卡及同一恢复事务。不存在时不创建，
  指向无关仓库时保持原字节；旧冻结计划不会自动获得新配置写入权。
- 自动沉淀启动锁、执行锁先于合同/路由/注册锁获取，复用现有进程互斥；消费入口持锁后
  检查持久化迁移屏障。迁移中断不放行新工作树写入，持有旧路径的进程不能重建旧根。
  配置发布后独立核对 Git 顶层、common-dir、HEAD 和知识目录；恢复不重试业务操作。
- 中途修正：消费者检查最初误接到没有 home 参数的纯物理快照函数，审查时移回廉价
  预检入口；第一轮 11 项测试的两个错误分别是夹具错误字段名及旧格式 fixture 未重算
  摘要，已修正。其余 9 项通过不替代后续完整验收，也未修改生产来适配测试。
- 正式回归命令：`python3.10 -B scripts/kb/run-isolated-tests.py`
  加 `tests.test_relocation_consumers tests.test_auto_sediment tests.test_repository_relocation
  tests.test_relocation_store_capacity tests.test_git_final_verification
  tests.test_historical_native_retirement tests.test_historical_retirement
  tests.test_native_decision_journal tests.test_approval_invariant`。
  当前会话执行记录：316/316，0 skip，546.955 秒，exit 0。
- 追加真实规模组合用例
  `tests.test_relocation_consumers.RelocationConsumerTests.test_real_scale_registry_large_audit_and_consumer_move_together`：
  24 份有效合同、5 个会话映射、约 96 MiB 实际合成 JSONL 和已知消费者共同迁移；
  合同全部暂停、归档可读、映射正确、账本摘要不变、真实 consumer resolver 指向新根。
  1/1，12.039 秒，exit 0。不是生产日志副本；历史 revision/typed authority 另由有效
  原生账本用例覆盖，不把普通容量 JSONL 说成审批证明。
- 六个实际临时安装件原生 Allow/Deny 用例非 skip 通过，统一 runtime SHA256
  `0d41cb8faf06656774328b4b2681e7bf4d003a9d484d500a5efca0cb292b96d7`。
  迁移 Allow 同步更新配置且拒绝继任任务未经审阅的业务写入；Deny 保留旧配置与目录，
  无执行事务。历史终止用例不重放旧操作。所有模型响应为本地夹具，外部模型请求为零。
- 只读真实物理快照：359,974 entries、7,541,329,100 bytes，低于既定 500,000/8 GiB
  上限；内容摘要 `addd85bbb541935c72ce518fd132d71da12ff65bbebdd0bdc70af4cb1e2c513f`。
  这不是最终移动授权，提交/安装后执行前仍需新的最终冻结。根 r195 active/events/native
  三项摘要与 r16 相同，四个历史原生事务仍待新版精确裁决，没有提前修改真实历史。
- 问题分级：配置绑定及写者互斥是改名必修项，现已具备源码证据；旧项目 trust 条目、
  历史会话/归档文本不是当前迁移内容，不全局替换。父目录已有 trust 配置，但未声称
  已验证所有未来新会话的信任行为，现场仍核验新路径可用性。容量余量约 1.05 GB 是可接受
  风险，保留最终容量门，不删除用户文件。没有新建 scheduler 或整体 Guardian 重构。

### 沉淀候选：物理改名必须覆盖仍在消费旧路径的写者

- 类型/平台：regression / none。目标是只改物理名称并保留可用性；实际发现仓库外
  源码绑定仍会严格解析旧路径。排除“修好 Git 指针就覆盖所有消费者”的假设。
- 根因：物理迁移事务未包含同一仓库的外部源码配置及后台写者；只更新配置又会与
  在途旧绑定竞争。证据状态：隔离真实 Git、真实锁、进程退出恢复及 native verified；
  生产改名尚未执行，不提前声称线上闭合。一手证据见本节测试及 source resolver。
- 判重：症状检索 `work-model/final-backup-before-migration-cutover` 0.603835，全文
  确认为相关但不同根因；根因检索 `work-model/ownership-aware-receipt-locks` 0.5，
  全文确认“锁集合随同一事务所有权扩展”可并入深化。另一命中“流式连接三类终止路径
  与终态闸门”0.532408 全文为流式协议终态，不并入本问题。仅候选，由协调端最终判重。
- 路由正例（observed/apply）：精确仓库改名时有配置仍引用旧源码根；其仍参与运行。
- 路由反例（constructed/skip）：只有归档文本或无关仓库配置含旧名字；不参与当前迁移。
- 执行合格例（constructed/pass）：同一锁顺序、持久屏障、冻结配置、中断恢复一次、
  新路径独立解析成功；满足保留内容和运行绑定两个不变量。
- 执行失败例（constructed/fail）：配置变更后仍使用原批准快照，或中断时后台重建旧根；
  违反冻结范围/互斥，不因 Git 检查通过而放行。
- 上浮时删除项目名、路径、提交与会话标识；建议并入 work-model 的所有权锁条目，
  消费者为迁移评审与集成测试。遵循单写者规则，不修改共享 KB，不调用图谱写入。

## R6 统一发布及现场历史收尾（r18，2026-09-15）

- r17 提交 `175ac8d45f3229326dc02c9365a27bf547721462` 已 fast-forward 合 dev。
  安装卡原生 receipt `8a5468287ff594cbe061081154b0a0e43acb58a8aeb0265e4a70abaa82d27d0f`，
  transaction `ndt-fe4a8417e1f47d341d7eced56fd6e0df`；不复用旧安装授权。
- 官方 helper 仅更新 manifest 为 `0.2.5+codex.20260915114635-f9a88856ec`，validator 通过；
  提交 `a162d6f349a947061061a55f33761aa488ed1a16` 已合 dev。运行源码不变。
- 候选 `r6-relocation-cutover-20260915` prepare/verify/promote 均成功，promotion_consumed=true。
  runtime SHA256 与本轮六个原生用例完全一致（见 r17）；verification receipt
  `a1cee893cf5bfebd417c5b1ef8c79ebbac3a51bde9e77f300c7eb5114d4e6d2e`。
  机器耗时分别 2.222/19.487/49.267 秒，不含人工交互等待。原始候选状态与验证证据在
  `/Users/eric/.sulde/candidates/codex/r6-relocation-cutover-20260915/`，没有上传。
- 新版稳定入口可用；当前会话新 generation 的 PreToolUse/PostToolUse 实测，官方负向
  canary 在工具执行前拒绝，finalize 独立核验并回收测试标记；proof
  `4909a89b526c576f491c4d8905e1cb6c5234c40e7afdc32c5944ef8401360021`，gaps_cleared=0。
  没有清除其他会话历史缺口。第一次 finalize 缺少 probe-id，参数解析即拒绝，补齐精确
  probe 后成功；没有重复原 canary 操作。16/16 scheduler labels loaded、无 failed/missing。
- doctor 的 generation、supervision、effect clear、pairing settled/CAS 0 均通过；
  `host_interactive_fresh` 仍 degraded：新 runtime 的 prompt_control 未观察到近期用户输入，
  session_context 已经 verified_hot_rebind。未伪造 UserPromptSubmit、篡改时间或重复安装。
  这是当前交互投影限制，不升级成新的源码任务；不宣称普通业务全局就绪。
- 随后通过新 runtime 的真实 PermissionRequest 精确批准四笔历史事务终止，原生审批
  本身已 live_verified。plan `775d3e5eadcd53532fd6dd725ddcf84bafab15b84cb104f7d7afc50dba7c6a35`，
  request `apr-f671b5864656abfe1aa3248e`，返回 retired_inconclusive、effect_asserted=false。
  只追加四笔旧 proposal/resume 的 superseded；原 r195 active/events 摘要仍与 r16 相同。
  未重放、未认定历史成功、未复制权限。五笔旧版无授权诊断保留。
- 新版真实廉价 assessment 返回 ready_for_evidence：3 worktrees、24 contracts、5 mappings，
  未授予执行权限。宿主只读 pgrep 未找到 auto-sediment.py 在途进程；一次沙箱内 pgrep
  不可见后，经正常提权只读核验，没有杀进程。物理内容与配置还须由最终冻结重复核验。
- 仍未移动目录；后续仅原计划的精确迁移与独立终态验证，不新增源码、调度器、宿主配置
  清理或业务任务。当前提示与尚未执行的目录移动明确区分，不把 warning 当作迁移成功。

## R6 真实迁移终态及名称收尾（r19/r20，2026-09-15）

### 现场验收与原计划覆盖

- 原生迁移 plan `9738840d3e6d48504aa7b0101da9f3b33d5cc7cf9d06bdbde81ae6180e491ac2`，
  transaction `ndt-0005ce09147814a9afe7524ba7d1682a`。只执行一次，进程退出码 0，
  返回 `committed`、`fence_released=true`、`authority_transferred=false`。
- 持久终态在 `/Users/eric/.sulde/data/kb/intent/repository-relocations/` 下同 plan 的
  `.plan.terminal.json`；receipt SHA256
  `1fe15b5993b2134b898878af693844a705949fcfae76f33228dbda9a7ee2600a`。
  journal 独立读回仅有一次 `approval_decided → effect_applied → contract_applied → committed`。
  UTC 时间分别为 13:06:30、13:15:22、13:20:13、13:22:57；从批准落账到 committed
  约 16 分 27 秒，随后才完成终态屏障释放，不把目录 rename 的瞬间当作全部完成。
- 旧目录 `/Users/eric/ClaudePlugin/sulde-cc-pro` 不存在，新目录
  `/Users/eric/ClaudePlugin/sulde-pro` 存在。3 个注册 worktree 全部由 Git 读回新路径。
  迁移前后 main HEAD 为 `bd216b3d29e37b1aaf0e6be0c930b5221a925562`；dev 与任务 HEAD
  均为 `732f0677173267d720876e38e957fc3b1f2dcaa3`，且均干净（本轮文档改动之前）。
  main 原有 `.ua` 三份修改及未跟踪 `.sulde/` 保留，未在 main 提交。
- 全量迁移 verifier 覆盖物理身份、用户内容与 mode（包括 0400）、Git HEAD/index/指针、
  合同归档原字节与继任文档、会话映射和消费者。完成后额外只读元数据统计再次对上
  原快照的 359,976 entries、7,541,370,393 bytes，随后才修改本轮三个已授权文件。
- 重绑定工件共 24 份合同、5 条映射、1 个消费者；当前继任合同为
  `relocation-46bcb8901b31c2d342d1f3c6915aac4b.active.json`，r19 为 paused，零继承权限。
  `auto-sediment-source.json` 读回新 dev 路径与新 `.git` common-dir；未启动旧操作或重放审批。
- GitHub GET 再次确认 `EthanReedLabs/sulde-pro`，id `1248015247`、private=true、
  默认 main、archived=false、disabled=false。三个 worktree 的 origin 均为
  `git@github.com:EthanReedLabs/sulde-pro.git`；本轮没有 PATCH、fetch 或 push。
- 最终清单发现原有漏项：README 安装示例/目录示例及 Codex manifest 两个 URL 仍有旧名。
  不新增任务；r20 当前会话原生卡仅授权这两份文件与本报告。receipt
  `4f1981c62ea5581f98a1a869ea206b7c51730fb9c0106cf788e545181896eae8`，
  transaction `ndt-787fc80c789098fb69b965673e13c8d6`，已 applied。
- README 共 6 处名称引用、manifest 共 2 个 URL 替换为新名；插件 name/version 不变，
  未修改 marketplace、已安装缓存或运行源码。官方 `validate_plugin.py` 通过，
  `git diff --check` 与逐项差异检查通过；不为文档/URL 修改重复安装或重跑全部运行时套件。

### 7.54 GB 的实际组成（逻辑字节，不是新增副本）

统计只读文件元数据，不读秘密内容、不跟随符号链接；与迁移快照相同，排除注册的
Git 管理根/指针。共有 316,579 个普通文件。下表各项互斥，合计 7,541,370,393 bytes。

| 现有目录类别 | 逻辑字节 | 说明 |
| --- | ---: | --- |
| dev 的 `.sulde/public-export` | 5,264,963,984 | 历史验收候选、归档和隔离验证目录；目录名不代表已上传 |
| `.worktrees` 下其余历史目录 | 1,249,173,412 | 不含当前 dev 与 R6；目录存在不等于仍是注册 worktree |
| 根 `.ua` | 580,787,042 | 含历史分析回收/保留目录 |
| 根 `.sulde` | 235,220,432 | 本地数据及工件 |
| 当前 R6 worktree | 140,631,697 | 本次任务源码及现有工件；临时资源清理前统计 |
| 根 `.codex-agent` | 25,212,899 | 历史任务工件 |
| dev 除 public-export 外 | 22,838,028 | 源码、文档与其他本地文件 |
| 其余根目录文件 | 22,542,899 | 源码、测试、文档等 |

按路径组件独立分类：`fastembed_cache` 为 3,770,015,085 bytes（约 50%），
`node_modules` 为 526,356,785 bytes，`site-packages` 为 255,706,892 bytes。
例如 `legacy-branch-closure-20260913/sediment-floating-ui-invariants-local/kb-home`
的绝大多数磁盘占用位于 `fastembed_cache`。大头是历史工件及其模型/依赖缓存，
不能把 `.py` 的总量全部当作项目业务源码，也不能凭目录名称断言可删除。

`du` 包含 Git 管理目录且按已分配块统计，总计 8,222,984 KiB；与上述逻辑字节
不是同一口径。没有下载/复制出另一份 7.54 GB，也没有实际上传。清理这些历史目录
需要另行确认保留/依赖证据，不把它加入本次改名任务。

### 可接受限制、过程中问题与收尾边界

- **已处理、原清单内**：README/manifest 漏掉的有效名称引用，已在本次 3 文件范围内修正。
- **已结束的等待，不是授权重试**：同一个迁移进程一直存活，阶段账本持续前进。
  期间 `du` 与部分只读诊断被 busy/paused 分类拦截；没有绕过、杀进程或再次搬迁。
  r20 获批后同一 `du` 正常运行，统计完成。观察回执时曾漏写 `.plan` 路径段，
  纠正只读定位后取到正确工件，未据此认定迁移失败或重启事务。
- **保留的交互观测限制**：r20 doctor 为 degraded，仅交互原因 `host_interactive_fresh`；
  新 workspace 的 prompt_control/session_context 仍 unobserved，不伪造宿主事件补绿。
  实际 native Allow、PreToolUse/PostToolUse 成功；task lane 绑定，pairing settled、CAS 0、
  effect debt clear、pending verification 0，安装 generation ready，16/16 scheduler ready。
  这不影响已经独立提交的改名结果，但不能宣称所有会话/业务工作流全局 ready。
- **不纳入本次**：历史缓存治理、通用迁移性能优化、main 发布、生产再安装，以及恢复
  其他项目业务权限。旧历史链接/发行件不做全局替换；后续按独立任务决定。
- **临时资源生命周期**：本轮三个文件只合 dev；清理前复核精确任务 HEAD 已成为 dev
  祖先、任务 worktree 干净、无活动 Skill/待审批/效果债务。通过
  `release-completed-workspace → 普通 Git 清理 → finalize-workspace-cleanup` 记录独立
  completion receipt。未取得该回执不能声称清理完成；不删除其他历史目录或用户数据。

### r21 清理前证据保全（不新增功能任务）

- 名称与验收报告提交 `6d86235` 已 fast-forward 合 dev。清理前检查发现任务 `.sulde`
  含未入 Git 的原始验收证据，不能随 worktree 一并丢弃。确定性 Agent 门因跨任务路径
  和清理措辞未自动放行；原生 receipt
  `aefe7cc5a4ca242b5e622ca489610d52f2acffa04aa1414f00f0b2dffb504bf4`
  已批准 r21 的精确保全/清理范围，未改守卫放行规则。
- 原 `.sulde` 已原样保存在 dev 的
  `.sulde/public-export/repository-relocation-r6-evidence-20260915/.sulde/`。
  本报告历史章节中指向任务 `.sulde/` 的相对证据路径，清理后均在该归档根下读取。
  归档父目录为 0700，无上传；目标事前不存在，没有覆盖已有归档。
- 独立逐项核验 11,225 entries、118,032,560 逻辑字节，普通文件 SHA256、模式和
  符号链接目标全部一致；清单摘要
  `e38e00b4696e6c78ab8db6186ab14d96947822301af8ffa548ba20911d2c4f5e`。
  在源证据仍存在时完成比对，随后才允许临时 worktree 生命周期清理；本次不清理
  其他历史 `.worktrees` 目录、分析回收目录或模型缓存。
