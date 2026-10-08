# Guardian 同会话恢复：候选交付与验收边界

日期：2026-09-07。任务源：`/private/tmp/sulde-guardian-recovery-task.md`。
本报告与修复代码位于同一任务分支；首轮提交为 `21e8dae595b49e75244af77ad63c9ea41265c986`，
目录迁移补充以包含本报告更新的后续提交为候选身份；不是生产发布证明。

## 范围与基线

- worktree：`.worktrees/guardian-recovery-closure`；分支：`task/guardian-recovery-closure`。
- 开始时 `HEAD = dev = bd25bd049b9a54c648d7b3370c3ce19620cfa8b4`，工作区干净。
- 本地 `origin/dev = 619f094aed44f5f90f1f02ed7fe9ffc42c42a8dc`；没有 fetch、重置或覆盖其他分支。
- 当前任务身份：`interactive:97ec7d092af89aa806e42c06`；Codex session：`01a079eb-ab32-70a3-8869-06a8c0b7afaa`。
- 保留已有 PostTool、workspace 绑定、helper 漂移与安装 verifier 修复。
- 未安装、卸载、回滚生产插件，未维护生产共享恢复账本；未合并到 dev/main。
  本会话的技能审计、诊断、原生 task-lane resume 和记忆关系标注均单独说明如下。

## 修复内容

1. `production_recovery_readiness` 现在实际重放只读恢复账本，验证链完整性；不再用构造对象成功证明账本健康。
   `SupervisorState.snapshot_read_only` 不创建锁或日志，读取期间发生变化返回不确定状态。
2. 分开输出 `diagnosis_available`、`human_confirmation`、`repair_execution`、`recovery_verified`。
   状态投影不再从只读路由和 key 存在推导全套写入动作可用，也不再无条件声称 Hook 可热绑定。
   状态栏将结构就绪显示为“诊断可用·恢复未验”。
3. 封堵向任意 shell 命令附加 `sulde_recovery_request` 即获得放行的缝隙。
   生产写入只接受精确的 `production-recovery.py` 命令、当前 session/intent/workspace、完整原生卡片描述和密封能力。
4. 新增独立恢复控制入口与 PreTool/PermissionRequest/PostTool 接线，位于普通 Guardian 合同/策略加载之前。
   PermissionRequest 只记录问题并 defer；执行器需当前 `CODEX_THREAD_ID` 和匹配的原生问题记录。
   普通工具返回和文字授权不能替代配对记录。PostTool 独立回读，避免普通任务账本给同一恢复重复记债。
5. 两个真实文件适配器：按有效安装清单重建单个已注册 launcher；移除明确冻结的生成字节码及空缓存目录。
   使用实际文件操作、安装代际摘要、执行前再次比对、私有备份、失败回滚和独立 verifier 实例。
   回滚保留文件与目录权限；若目标已被第三方替换则保留 unknown，不覆盖第三方内容。
6. 密封计划绑定源代际、manifest、执行器、verifier、intent、session、workspace、目标与前态，十分钟过期。
   同一能力重入最多执行一次 material apply，之后仅允许有界 reprobe；终态重读也重新验证当前目标，不能把后续损坏说成仍已恢复。
7. 二进制恢复 key 使用与安装器相同的固定 32-byte 读取，去除会随机破坏首尾空白字节的 `strip()`。
   key 不可用时仍允许精确只读 doctor，写入恢复保持拒绝。
8. 发布清单包含三个新恢复入口/模块，并在实际 staged artifact 中检查可导入性。

## 四层证据

| 项目 | 当前真实会话 | 隔离候选 |
|---|---|---|
| 诊断可用 | 生产 doctor 成功，识别当前会话及安装 runtime | key 缺失、损坏恢复账本仍提供诊断，写权限不扩大 |
| 原生确认可达 | 已发生真实 resume Allow，见下节 | 实际 Hook 子进程检查精确描述、session 和 permission mode；输入是构造的 Hook payload |
| 修复可执行 | 旧生产版本的 task-lane resume 成功 | 真实 launcher/字节码文件适配器执行成功；不是成功 Adapter mock |
| 恢复已验证 | 独立读合同见 lane=bound，原任务补丁随后成功 | verifier 回读通过，修复 launcher 再运行输出原任务继续标记 |

**本候选尚未通过真实生产文件修复验收，不得据此宣告全部任务验收完成或发布就绪。**
隔离测试中的 native payload 仅为协议测试输入，测试不声称有人看到或点击了 UI。
独立开发终端、当前会话普通原生权限提示及旧版本 resume 成功都不能替代新候选桥的真实验收。

## 本会话实际恢复事件

在更新发布清单时，生产 Guardian 拒绝了一个 Python 批量文件编辑命令，理由为“破坏性动作不在 Agent 自主权内”。
命令未执行，随后精确 apply_patch 也因 task lane 已暂停被拒绝。
这是真实执行期间的意外限制事件，不是预先设计的受控生产故障注入。

使用既有生产入口生成当前卡片后，通过本会话原生 Allow 执行 `native-decision resume`：

- transaction：`ndt-7c97d76494ac4d4286eb1bca43a6d1f6`；request：`apr-fa47ae86647e7e871521f20b`。
- receipt：`33030c54d4b0c2d715a6479934369c56c4d14623a8a083e149236ffc799cb907`。
- 独立合同回读：revision=1，status=active，当前 session lane=bound，source=explicit_resume，pause_class 为空。
- 随后原先被拒绝的精确发布清单补丁成功，测试继续运行。

此恢复没有复制其他会话 grant、改变任务目标或安装候选代码。当前真实宿主仍加载
`0.2.5+codex.20260906133700-210c01af6d`，不是本 worktree 候选。

## 测试证据

环境：macOS arm64，Python 3.14.6；真实文件候选放在系统 TemporaryDirectory 内。
所有安装器调用均使用测试临时 home/runtime；无生产安装动作。

| 命令中的 unittest 模块 | 结果 |
|---|---|
| `test_production_recovery_control test_production_recovery_readiness test_recovery_lane test_decision_kernel test_operational_readiness test_sulde_statusline` | 97 tests OK（中间检查点） |
| `test_stage_plugin test_stage_release_inventory` | 26 tests OK，1 skipped（需原生 Windows PowerShell） |
| `test_codex_hook_bridge test_launcher_contract test_recovery_supervisor test_dual_runtime_contract test_r2_guardian_integration` | 107 tests OK |
| `test_production_recovery_control test_production_recovery_readiness` 最终定向复验 | 21 tests OK，1.948s |
| `git diff --check` | 通过 |

以上是各组执行次数，存在跨组引用/重复，不相加声称独立用例总数。
早期试跑发现并修正发布清单测试的预期项；一次命令误包含不存在的 `test_supervisor_state` 模块，
随后改用覆盖真实状态存储实现的 `test_recovery_supervisor`，107 项组通过。

新增旅程覆盖：普通动作被限制；不同 session cwd 与 task worktree；未配对问题；错误描述、权限模式、身份；
旧 Hook；外部 helper 后续改变；源代际改变；损坏账本；symlink/组合命令；执行后故障与只读 reprobe；
launcher 回滚；字节码与目录权限回滚；已成功目标再次损坏；PostTool 重复债务隔离；原任务继续。

## 保留的边界与发布端验收

- `settle/abort/uninstall/rollback` 没有注册到本候选文件修复适配器；不能把协议枚举当作已实现的生产动作。
  verifying/unknown 债务或损坏权威账本不被清空、伪造成功或重写历史。其具体结算仍须已有独立效果证据和对应恢复入口。
- 本候选可在普通任务合同/账本不可用时修复受支持的派生产物；不修复损坏的运行时源代码、安装 manifest 或恢复 key。
- 旧 Hook 缺少新入口时，测试证明其拒绝候选执行，不会冒称原生确认已接通。
  “所有旧 Hook 都能同会话热加载新桥”没有证据，本交付明确不作此承诺。
- 恢复日志损坏时拒绝写入、保留原字节；允许诊断。没有借新账本绕过旧权威历史的逃逸通道。
- 进程硬中断后的重入只做回读；若部分动作没有完成且无法证明已回滚，保持 unknown 并保留备份。
  不通过第二次 apply 猜测补齐，也不把单个已修复文件等同于整个普通任务已解锁。
- 单一发布端安装候选后，仍需在同一真实 Codex 会话完成：受控故障注入、普通动作受限、原生 Allow/Deny、
  精确文件修复、独立回读、原任务继续；并记录当时 session、安装代际与候选提交。
  Deny、旧 Hook 载入行为、真实 crash/rollback 和残留债务均须分别报告。该步骤未在本终端越权执行。

## 沉淀候选：Layer1 问题卡

**问题类型**：host-inconsistency / bug-fix。
**任务目标与用户真实预期**：当前宿主在技术故障时完成原生确认、精确恢复及独立验证，不要求另开会话复制授权。
**触发场景**：恢复模块具有密封协议和读路由，但尚未连接生产 Host/Adapter/Verifier。

**可观察症状**：结构探针报告恢复 ready、全部动作可用、Hook 可热绑定；代码没有生产写适配器；
恢复账本构造成功时甚至尚未读取损坏内容。
**期望与实际差异**：读路由/存储形状可用被错误升级为“当前人能确认且修复能成功”。
**已确认根因**：readiness 投影把两个结构布尔值作为整个恢复闭环真值，测试 Host/Adapter 的成功被混入能力解释。
**已排除假设**：不是仅缺 UI 文案；原始生产适配器确实没有 trusted_adapter/trusted_verifier；只改文案不能执行恢复。
**证据状态**：结构误报与隔离修复 verified；新候选真实生产故障旅程 inconclusive。
**一手证据**：本提交 diff、上述测试、当前真实 doctor 输出与 resume 事件。
**正确做法及验证**：分别记录四层真值，精确原生命令连接真实适配器，独立回读并保留未验收项。

| 样本 | 内容 | 固定预期 | 判定原因 | 来源 |
|---|---|---|---|---|
| 路由正例 | key/route 存在，状态却声称人可确认并可修复 | apply | 结构证据被升级为执行证明 | observed |
| 路由反例 | 同 session 已有配对 Allow、真实目标改变和独立回读 | skip | 已具备该层所需证据 | constructed |
| 执行合格例 | 四层状态独立；真实 adapter 测试通过，但 live 验收仍标未完成 | pass | 无扩大授权或伪造效果 | observed |
| 执行失败例 | 只增加 mock 成功用例，继续宣称所有旧 Hook 热绑定/全部动作 ready | fail | 缺少生产 Host 与效果证据 | constructed |

**上浮边界**：删除项目名、路径、session、提交及 receipt；复用“结构就绪不得替代当前宿主授权与效果真值”。
**建议容器**：anti-patterns。**候选消费者**：Hook、恢复 readiness、宿主集成 review。
未直接写知识库文件。按全局要求标注 1 条记忆关系并独立 graph 回读：结构恢复 readiness `does_not_prove`
当前会话原生确认和已验证修复；图谱将其保持 unverified（无原始 memory entry 绑定），不能作为新的授权或事实凭据。

## 目录迁移补充交付

本节执行任务文件 2026-09-07 补充要求；继续使用上述 task worktree，复核 dev 仍为 `bd25bd0`。
恢复端关于生产 verifying、缺失 seal、代际未切换的报告仅作为调查线索，本终端没有将其当作实测结果。

### 已确认根因与权威路径

旧 bootstrap 把 launcher 根传给 `install_launchers`，后者又在该根下读取 scheduler 数据；
独立刷新 verifier 则反向在数据根下读取公共 launcher 清单。目录分离后两处均读错。
另外，旧 seal 重建遗漏 POSIX runner 实际要求的 `scheduler_activation_id`。

| 产物 | 权威位置 | 写入与回读 |
|---|---|---|
| 六个公共 launcher、launcher manifest、command-effects snapshot | `launcher_home(kb_root)/bin`；默认 `.sulde/bin` | launcher contract、bootstrap、安装适配器及独立 verifier 使用同一解析规则 |
| deployment-generation、runtime-owner | 数据根；默认 `.sulde/data/kb` | scheduler 安装器写入，seal preflight 和 verifier 原位回读 |
| scheduler runner | 数据根 `bin/sulde-scheduled-run`（POSIX）或 `bin/sulde-windows-task.py`（Windows） | 保留真实 scheduler 安装器位置，按平台核对唯一文件路径、owner、权限与摘要 |
| runtime 与解释器 | 明确传入 runtime 根及数据根 venv | 核对密封代际及 launcher 字节；不从公共根猜测数据根 |

`SULDE_LAUNCHER_HOME` 显式覆盖现在与 scheduler 安装器一致，只作用于对应配置的数据根；
自定义产品根、分离的显式根和支持的旧同根布局均保留。没有复制状态文件或搜索备用清单。

Codex launcher-only 刷新在写入前核对 deployment/owner 的身份、代际、状态、runner 摘要，
以及 POSIX activation 一致性；缺失或不匹配返回具体 incomplete 原因，保留旧清单字节。
只有通过检查的字段进入新 seal。首次完整安装仍允许先生成 launcher、再安装 scheduler；
无 staged generation 的源码布局显示 `not_applicable`，不能通过恢复效果 verifier。

独立 verifier 重新读取公共根的新清单和数据根的 scheduler 输入，验证实际 runner 文件。
接线检查与 scheduler seal 分开输出。两个既有宿主 helper 的摘要漂移例外提取为共享谓词，
安装 verifier 保持原有边界，刷新效果证明复用该边界；不会授权执行漂移的 helper，
也不会豁免 command-effects snapshot 校验和、launcher 或 runtime 损坏。

### 隔离执行与验收结果

新增 `tests/test_launcher_split_recovery.py` 使用真实 bootstrap 子进程、实际文件安装与独立 verifier，
不 mock 安装成功或验证成功。runtime 中六个命令目标和 scheduler runner 是隔离 fixture，
没有声称真实 scheduler 作业已运行。人工决定及已完成调用是构造的合同/账本前态，不是原生 UI 证据。

| 检查范围 | 结果 |
|---|---|
| `test_launcher_split_recovery test_launcher_contract test_sulde_paths test_codex_plugin_install test_candidate_codex_plugin` 加现有 scheduler/launcher verifier 用例 | 105 tests OK，265.799s；目录修复检查点 |
| 最终 `test_launcher_split_recovery test_launcher_contract test_sulde_paths` 加现有 scheduler/launcher verifier、安装独立证明用例 | 38 tests OK，3.119s；包含共享 helper 漂移谓词及债务保留断言 |
| `bash -n scripts/kb/bootstrap.sh`、`git diff --check` | 通过 |

两组存在重复，不相加为独立用例总数。补充测试构造曾触发现有同资源债务阻塞，随后改为不同资源；
合同规范化会补全 task epoch/runtime generation，保留断言以写入后正规回读为基线，未修改生产逻辑绕过检查。

覆盖默认 `.sulde/bin` 与 `.sulde/data/kb` 分离、自定义产品根、显式独立公共根、旧同根布局；
负例包含 owner 缺失、seal 缺失、代际/activation/runner 摘要不符、公共目录下同名 runner、
旧数据目录里的诱饵清单、刷新后 runner 损坏、helper 后续漂移、snapshot 及 launcher 本体损坏。

正规 `reconcile_pending_verifications` 在 seal 缺失时保留 verifying；实际刷新后，通过注册 verifier
追加 `system_verified`，清除这次已证明的 pending 项，重复回读不重复结算。
另一个 session 的其他资源未验证债务逐字段保留，journal 原始字节前缀完整保留。
没有手改终态、删除日志或新建生产账本。unknown 和损坏账本仍沿用首轮证据中的拒绝/保留边界。

| 交付层 | 隔离候选结论 | 当前生产结论 |
|---|---|---|
| 接线健康 | 四种布局真实安装与回读通过 | 本补充未重新验收 |
| scheduler seal | 输入验证、重建 activation、实际新清单回读通过 | 发布端待验收 |
| 恢复效果验证 | 正规 verifier 结算已有 verifying，其他债务保留 | 发布端待验收 |
| 同会话任务恢复 | 本补充没有原生 UI canary | 首轮旧 runtime resume 证据仍有效；新候选完整链未验收 |

串行发布端仍须对同一真实会话记录：原生确认 → 精确刷新 → 新清单含经验证 seal → 独立 verifier
→ 本次债务结算 → 原任务继续，并独立回读合同、审计日志、doctor，记录 session 与实际代际。
本终端没有安装、修改生产共享账本或切换代际，也不以 launcher READY 代替这条验收链。

### 沉淀候选：分离布局下的效果验证

**问题类型**：bug-fix / verification-path-mismatch。
**任务目标与用户预期**：目录迁移后刷新真实公共 launcher，并让已有恢复债务通过独立证据结算。
**触发与症状**：公共根和数据根分离；六个 launcher 健康，但 scheduler seal 缺失或 verifier 读取旧位置。
**根因**：安装 API 的单一 home 混合产物位置与状态位置；消费方未沿用路径解析；seal 重建遗漏 activation。
**排除项**：不是简单重跑刷新或将 READY 映射为成功；错误根下没有权威输入，且 runner 会校验 activation。
**证据状态**：源码调用链和隔离真实文件/正规账本验证 verified；生产同会话完整旅程 inconclusive。
**一手证据**：本提交 diff、新增分离布局测试、上述 105/38 项结果。
**正确做法**：显式传数据根，共用公共根解析；刷新前验证 scheduler 输入，刷新后原位回读新清单，正规结算。

| 样本 | 内容 | 固定预期 | 原因 | 来源 |
|---|---|---|---|---|
| 路由正例 | 接线健康而恢复 verifying，数据根与公共根分离 | apply | 应检查权威路径和效果 seal | observed |
| 路由反例 | 正确路径读到 runner 摘要真的不符 | skip | 应修复输入，不能归咎于目录迁移 | constructed |
| 执行合格例 | 实际刷新后独立 verifier 结算本次债务并保留其他 session 债务 | pass | 有文件证据且权限不转移 | observed |
| 执行失败例 | 复制旧清单、直接写 system_verified 或把 READY 当验收 | fail | 掩盖路径错误或伪造效果 | constructed |

**上浮边界**：去除本机目录、会话和提交；保留“产物根与状态根不能共用隐含 home”。
**建议容器**：anti-patterns；由协调端判重，未直接写知识库。
新增 1 条 `requires` 记忆边并独立 graph 回读（id=1972）：分离布局刷新证明依赖数据根 scheduler 输入/runner
及公共根新清单。因没有 memory entry 绑定，图谱仍为 unverified，不将其升级为授权或独立事实证据。
