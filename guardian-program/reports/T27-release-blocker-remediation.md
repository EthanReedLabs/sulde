# T27 release blocker remediation

## 结果
✅ 完成检查：`python3 -m unittest tests.test_intervention tests.test_intervention_batch tests.test_operational_readiness tests.test_sulde_statusline tests.test_scheduler_entrypoints tests.test_mem_sync tests.test_auto_distill_windows && env -i HOME=/tmp PATH=/usr/bin:/bin TMPDIR=/tmp LC_CTYPE=UTF-8 PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 scripts/kb/auto-distill.py --help >/dev/null && git diff --check`，exit 0；协调端补齐真故障优先级后 146 个测试通过、2 个仅限 Windows 的测试跳过，macOS `/usr/bin/python3` 在最小环境解析 `auto-distill.py --help`，且 diff 无空白错误。

✅ 完成检查：`python3 -m unittest tests.test_intervention.InterventionTests.test_aborted_unknown_is_quarantined_but_still_blocks_same_resource tests.test_intervention.InterventionTests.test_unknown_blocks_same_effect_target_across_sessions tests.test_intervention.InterventionTests.test_inventory_replays_archived_truth_without_double_counting_live_store tests.test_operational_readiness.OperationalReadinessTests.test_aborted_debt_is_quarantined_from_global_readiness_not_settled tests.test_operational_readiness.OperationalReadinessTests.test_pending_verification_is_current_effect_debt tests.test_operational_readiness.OperationalReadinessTests.test_only_authoritative_settlement_clears_derived_pending_debt tests.test_sulde_statusline tests.test_scheduler_entrypoints tests.test_mem_sync -v`，exit 0；21 个聚焦测试证明 abort debt 全局 quarantine、同资源跨 session 继续阻断、pending 不冒充 settlement、两种黄色等待态、真实红故障、scheduler UTF-8 入口和 upstream 故障注入。

实现结果：T27 冻结范围内的源码、测试、Codex cachebuster 和本报告均已更新；未安装插件、未加载 LaunchAgent、未访问远端、未写生产账本或缓存。受管执行协议禁止 commit，因此本 worktree 保留未提交改动。

## 过程
- 保留 `blocking_attempts()` 作为同资源权威安全集合；resolved `abort` 的 unknown attempt 仍在该集合中。
- 新增 terminal quarantine 与 readiness blocker 投影。全局 current-lane gate 排除终态 abort debt，但 open、acknowledged、retry-authorized、reprobe-authorized 和无 intervention 的 unknown 继续阻断。
- effect truth 同时披露 `authoritative_blocking`、`terminal_quarantined`、`authoritative_settled_pending` 与 `terminal_quarantined_pending`；abort pending 不再被标为外部权威结算。
- statusline 只在 SessionStart lineage 已 live verified、prompt 未观察且其他必需交互 capability 无故障时显示黄色等待；`stale_observations == 0` 为 `等待首个提示`，大于零为 `空闲，等待下一条提示`。没有修改 host capability gate，也没有合成 `interactive_ready`。
- 协调端代码审查发现纯等待文案可遮蔽同时存在的 runtime/scheduler 故障；在原 owned paths 内修正优先级并加两个反向断言。运行时、接线、调度、generation、authority 和 effect 真故障仍为红色。
- `auto-distill.py` 增加显式 UTF-8 source declaration；macOS 回归在临时 runtime 树、最小环境和 `PYTHONDONTWRITEBYTECODE=1` 下调用 `/usr/bin/python3 --help`。
- mem-sync 在 pull 前解析 symbolic branch，分别读取且只接受一个 `branch.<name>.remote` 与 `branch.<name>.merge`，验证 remote/ref 后把精确值传给 `git pull --rebase --autostash <remote> <ref>`。单测全 mock git，未接触真实远端。
- 源测试通过后才把 Codex 插件版本从 `0.2.5+codex.20260823151846` 更新为 `0.2.5+codex.20260824102056`。

## 遇到的问题
- 受管 worker 中 `tests.test_correction_intervention`、`tests.test_host_capabilities` 和 `tests.test_dual_runtime_contract` 受 `.native-command-scratch`/here-doc 隔离约束影响，被报为 `inconclusive`，使官方 worker 外层严格返回 FAIL。
- 协调端在同一候选树、不经过受管 command scratch 的环境独立复跑上述三个模块，42/42 全部通过。因此这三项已被证明为 worker 隔离环境假阴性，不是产品回归。

## 解决方式
对上述 scope 外问题只做只读复核，没有修改任何 unowned path，也没有借机扩大 T27 设计。T27 自有验证使用不触发实时副作用的单元/临时目录边界：intervention 与 readiness 通过 append-only 临时 fixture 重放；mem-sync mock 所有 git 调用；scheduler 使用复制到临时目录的入口树；statusline 直接验证 capability projection 的渲染结果。

## 遗留风险与建议
- 由于任务明确禁止安装和 live side effects，本次没有验证“官方安装后 15 个 scheduler actor”或两个真实 Codex 会话恢复；应由协调端在允许安装的 release harness 中执行该 system gate。
- worker 环境假阴性已由协调端 42/42 复跑关闭，无需为此新增任务。
- 本次没有 commit：受管执行协议明确禁止 commit，优先级高于任务书中的提交要求。

## 沉淀候选
### Layer1 问题卡

#### 任务与意图
- **问题类型**：design-decision / bug-fix
- **任务目标**：在保留未知外部效果同资源安全边界的同时，解除已终态 abort 历史债务对无关 current lane 的全局自锁。
- **用户真实预期**：abort 表示 intervention 工作流终止，不表示外部效果已成功、失败或已结算；历史债务仍可审计且同资源 fail closed。
- **触发场景**：append-only effect attempt 为 unknown，最新 intervention 为 resolved abort，同时 runtime 仍有派生 pending verification。

#### 观测与证据
- **可观察症状**：旧实现把 abort unknown 从 `blocking_attempts()` 移除，并把关联 pending 计入 `authoritative_settled_pending`；资源保护与全局 readiness 被同一个集合耦合。
- **期望与实际差异**：期望只解除全局 lane gate，实际同时放松同资源阻断并伪装成权威结算。
- **已确认根因**：同一 blocker projection 同时承担资源冲突保护、全局 readiness 和派生 pending 结算三种不同语义，且 resolved abort 的 fall-through 被误当成 settlement。
- **已排除假设**：无需修改 host capability gate、生产 ledger 或历史事件；问题可由 append-only projection 分层解决。
- **证据状态**：verified
- **一手证据**：T27 聚焦 21-test 命令 exit 0；完整冻结范围 144-test 命令 exit 0；跨 session 同资源 blocker、全局 readiness clear、settled/quarantined pending 计数均有独立断言。
- **正确做法及验证**：保留权威资源 blocker，另投影 terminal quarantine 与 readiness blocker；对 pending 先判 quarantine、再判 authoritative settlement，并用 open/ack/retry/reprobe/unhandled unknown 反向矩阵证明没有放宽。

#### 正负样本素材

| 样本 | 内容 | 固定预期 | 判定原因 | 来源 |
|---|---|---|---|---|
| 路由正例 | unknown 外部写 attempt 的最新 intervention 已 abort，但无独立外部读回，且历史 pending 让无关任务全局 degraded | apply | 同时命中“终态 intervention”“外部结果仍未知”“资源保护与全局 gate 耦合” | observed |
| 路由反例 | 外部写 attempt 已由独立 read-back 进入 `system_verified`，pending 随权威状态清除 | skip | 已有 authoritative settlement，不属于 quarantine | constructed |
| 执行合格例 | abort attempt 仍被 `blocking_attempts()` 和跨 session 同资源 matcher 命中，但 readiness blocker 为空；pending 计入 quarantine 而非 settlement | pass | 同时满足审计可见、资源 fail closed、无关 lane 解锁和语义不冒充 | observed |
| 执行失败例 | 直接从 blocker 删除 abort unknown，或把它计入 `authoritative_settled_pending` 来让 readiness 变绿 | fail | 前者放松同资源安全，后者伪造外部结算证据 | observed |

#### 上浮边界
- **必须删除或泛化**：任务号、仓库路径、插件版本、具体 provider/session 标识。
- **可跨项目复用的内核**：工作流终态与外部事实终态是正交维度；资源安全集合、运行就绪集合和历史展示集合应分别投影，quarantine 不能冒充 settlement。
- **建议容器**：anti-patterns
- **候选消费者**：effect ledger projector、operational readiness、resource conflict matcher、status/doctor、回归测试清单。
