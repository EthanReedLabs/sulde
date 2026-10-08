# 阶段 3 — 升级不中断与发布闭环（C3）

基线：`dev@9936c7b`；实现于 `task/sulde-orchestration-iteration`（阶段 1/2 之后）。
授权边界：本地候选验收与代码实施；**不执行生产安装**，运行中真实宿主升级演练不在本授权内（见 §5 未验收项）。

## 1. 变更清单

### 既有机制复用（阶段 0 判定"复用"，本轮零改动，仅验证）

| 能力 | 证据 |
| --- | --- |
| 隔离候选安装 | `candidate_codex_plugin.py`：环境隔离/真实宿主链/失败注入/CAS promote —— 既有测试套件全绿（test_candidate_codex_plugin 等） |
| 事务回滚＋独立读回 | `install_transaction_journal.py` hash-chain、`_install_locked` 回滚路径、`recover_only` —— test_install_transaction_journal 全绿 |
| 恢复通道独立于 Hook | recovery_lane / production_recovery_control —— 测试全绿 |
| 回滚不重放未知效果 | 无任何自动重放代码（vacuously satisfied），本轮亦未新增 |

### 新增（补缺口）

| 模块 | 职责 |
| --- | --- |
| `scripts/kb/generation_guard.py` | ①切换兼容投影：从运行租约目录投影活跃代际（未知代际保守判不兼容，绝不假设安全），`assert_switch_allowed` 支持 observe（默认）/block 两策略；②旧代际回收规划：仅当（a）无活跃租约引用该代际且（b）保留窗口已过且（c）退役记录 schema/身份可解析，才判可回收；身份不明的记录永远保留；apply 有目标越界防护 |
| `scripts/kb/generation-gc.py` | 显式 CLI：默认 dry-run 出计划（JSON），仅 `--apply` 执行回收；不挂接安装事务，停用/回收是明确人工动作 |
| `run_concurrency.py` 扩展 | 租约证据记录 `runtime_generation`（C3：升级/回收决策可见在飞执行的代际）；新增 `active_run_leases()` 只读投影（先修剪死进程租约） |
| `agent-runtime.py` | 启动租约传入运行代际（生产取 installed authority，测试环境取 `SULDE_RUNTIME_GENERATION`） |

### 共享 schema 新旧兼容纪律（补测试锁定）

新增共享工件（dispatch registry / usage report / launch description）对未知 schema 一律类型化 fail-closed，不猜测不崩溃——测试锁定该纪律，旧代际读到新工件时得到明确错误而非静默误读。

## 2. 验收对照（方案 §6）

- [x] **集成候选完成风险相称的完整回归**：candidate/install/journal/recovery/canary 套件 168 例全绿（含新增 3 套）。
- [x] **候选失败不破坏正常旧任务**：既有 CAS promote + 回滚路径测试通过；本轮未触碰安装事务。
- [x] **回滚可执行且有独立回读**：既有事务日志独立读回测试通过。
- [x] **安装成功不替代业务链通过**：候选验证含真实宿主 PreToolUse 拒绝 canary（既有）。
- [x] **无活动引用且满足保留条件后回收旧代际**：generation_guard 计划/应用两段式；引用=活跃运行租约，保留窗口默认 168h，显式 apply。
- [x] **运行中任务保留执行归属和所需代际**：租约代际记录＋切换兼容投影；安装器既有 observe-only peer 会话/live-session bridge/scheduler 代际匹配保持不变。
- [ ] **真实宿主验证：运行中升级、双 session 跨升级、未知启动恢复和回滚** → **未验收**（需生产安装授权，本轮明确不执行；见 §5）。

## 3. 测试范围

- 新增 `tests/test_orchestration_phase3.py`：14 例（租约代际 2 + 切换兼容 3 + 回收规划/应用 5 + CLI 1 + schema fail-closed 3）。
- 验证证据：test_orchestration_phase1/2/3 + test_candidate_codex_plugin + test_install_transaction_journal + test_recovery_lane + test_production_recovery_control + test_native_canary_boundary + test_codex_plugin_install 共 168 例全绿。
- 完整官方回归：见 STATUS / REPORT。

## 4. 性能

- 正常执行路径新增成本：租约证据多写一个字符串字段；切换兼容/回收规划均为显式调用（安装/回收时），不在运行热路径。入口与全 fake-run 耗时与阶段 1 后持平（见 PHASE1 §4）。

## 5. 未验收项（明确披露）

| 项 | 原因 |
| --- | --- |
| 真实宿主运行中升级演练 | 需在装有生产 Sulde 的宿主执行安装事务；本轮授权不含生产安装 |
| 跨代际双 session 串线实测 | 依赖上述升级演练 |
| 回滚的生产宿主演练 | 同上；本地事务日志回滚测试已通过，但不等价于生产演练 |
| 跨平台（Windows）验证 | 未执行 |
| assert_switch_allowed 的 block 策略接入安装事务 | 接线会改变生产安装器行为；按授权边界仅提供库函数与投影，接入需另行确认 |

## 6. 回滚方法

- 本分支全部变更位于 `task/sulde-orchestration-iteration`；未合并 dev/main，未安装。放弃 = 删除分支与 worktree。
- 新运行时工件（launch.json / dispatch.jsonl / usage.json / run-leases/）只出现在任务 worktree 的 `.codex-agent/` 内；旧代码忽略即可，无需迁移。
- generation-gc 未接自动路径；未来如需回退其效果，退役树一旦删除不可恢复——这是设计上的显式选择（apply 前有计划与保留窗口两道门槛）。
