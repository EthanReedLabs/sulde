# REPORT — Sulde 执行与编排增量迭代

- 分支：`task/sulde-orchestration-iteration`（基线 `dev@9936c7b`，与方案分析基线一致）
- 宿主：Claude Code（本会话独立任务身份）；日期：2026-09-25
- 授权范围执行情况：本地实施与候选验收完成；**未合并 dev/main、未推送、未生产安装、未发起付费对照实验**——符合授权边界

## 1. 实际基线

- 测试基线（run-isolated-tests.py @ dev@9936c7b）：2453 例，2397 ok / **2 failures + 1 error（既有环境性，与本轮无关）** / 28 skipped。
  - sandbox-exec 不可用（本机沙箱限制）、distill-conflict exit code、subprocess encoding guard。
- 性能基线（N=7，冻结方法：同机顺序执行，中位/最大，判据 max(15%,100ms)）：
  - `sulde-status.py --json` 25.22s；`event-observer.py summary` 24.08s；`agent-runtime.py run` time-to-fail 0.35s。
- 既有失败形态样本：`/Volumes/Optimus/Sulde/fixtures/life-status-20260924/`（g12：反馈超时、usage=null、ptyStopVerdict=unverifiable）。
- 任务证据目录（冻结）：`/Volumes/Optimus/Sulde/tasks/sulde-orchestration-iteration/`（外接盘全程可用）。

## 2. 阶段结果与提交

| 阶段 | 提交 | 内容 | 结果 |
| --- | --- | --- | --- |
| 0 冻结边界 | `16e6c2f` | 能力判定总表（复用/未接通/缺失 ×C1-C5）、单一事实来源表、兼容约束、基线与验收矩阵、预算冻结（PHASE0.md） | ✅ |
| 1 C1+C2 | `2365dcf` | 统一版本化启动描述＋0 模型调用预检；provider 选择去重；派发注册表（幂等/冲突/崩溃窗口）；有限并发；陈旧心跳拒绝（PHASE1.md） | ✅ 28 例新测试 |
| 2 C4+C5 | `63643e5` | 增量用量核算（complete/lower_bound/unknown，永不记零）、run 身份去重聚合、四路径留存；C5 复用零新建（PHASE2.md） | ✅ 16 例新测试 |
| 3 C3 | `1884f9b` | 租约代际记录、切换兼容投影（observe/block）、旧代际两段式回收（dry-run 默认）；共享 schema fail-closed 纪律（PHASE3.md） | ✅ 14 例新测试 |

合计新增运行模块 6 个（launch_description / dispatch_registry / run_concurrency / usage_ledger / generation_guard / generation-gc CLI），修改 3 个（agent-runtime / runtime_provider / execution_backend）；未建第二套审批、权限或任务状态系统；权限组合、broker、安装事务、恢复通道零改动。

## 3. 测试范围

- 新增 58 例（phase1: 28 / phase2: 16 / phase3: 14），全部通过；含真实 CLI 集成（假执行器，零付费模型调用）。
- 最终全量官方回归（phase 3 后）：**2511 例，2450 ok / 3 failures + 1 error / 28 skipped**。
  - 3 项与基线完全相同（既有环境性）。
  - 1 项 `test_control_composition_performance.test_single_call_budget_against_base` 为**瞬态噪声**：全量运行时 single_control 中位差 9.6ms 超过该测试自身 1ms 预算；隔离复跑 3 次全过，实测 base 4.53ms vs candidate 4.51ms（噪声级）。该测试的 1ms 容差远严于本任务冻结的 max(15%,100ms) 判据。
- C3 既有机制验证：candidate / install journal / recovery lane / production recovery / canary boundary / codex plugin install 共 168 例全绿。

## 4. 证据路径

- Optimus：`/Volumes/Optimus/Sulde/tasks/sulde-orchestration-iteration/evidence/`
  - `baseline-full-suite-dev-9936c7b.txt`、`phase1-full-suite.txt`、`phase2-full-suite.txt`、`perf-control-plane-timings.txt`（sha256 见 evidence-sha256.txt）
  - phase 3 全量输出与本报告归档同目录（REPORT 附带 sha256 清单）
- 仓库：`docs/sulde-orchestration-iteration/{PLAN,SOURCE,PHASE0,PHASE1,PHASE2,PHASE3,STATUS,REPORT}.md`（脱敏；file:line 锚定）

## 5. 性能与 Token 数据完整性

- 控制面（冻结预算内）：入口 time-to-fail 0.35s→0.35s（持平）；sulde-status / event-observer 未触碰（复用基线记录）。全 fake-run 总耗时 0.66s 中位（信息性，无冻结基线）。
- 用量数据完整性：每受管运行四路径（成功/超时/失败/崩溃恢复）必产出三态用量报告；缺失报 unknown 不记零——直接消除 g12 形态的 `usage: null` 静默空缺。
- Token 收益：**待测**。本授权不含付费对照；方案 §8.1 的收益指标需在可比输入/模型/验收器下测量，本报告不承诺任何百分比节省。

## 6. 实测收益（可验证部分）

1. **可预检错误 0 次模型调用发现**（原为整个模型轮次浪费，g12 实证）：报告契约损坏、报告位置非法、可执行不可解析 → 启动前拒绝＋证据落盘。
2. **同请求有效启动 = 1**：并发重复提交被串行拒绝；崩溃窗口恢复原尝试而非重发；request_id 永久绑定内容，同 ID 异内容硬冲突。
3. **中断减少**：陈旧心跳读取侧拒绝、崩溃恢复后补关派发段、归档前抢救已观测用量——三类此前会滞留人工处理的状态现在自动收敛或明确分诊。
4. **用量可见性从无到有**：跨续接不重复计数的三态核算，为后续任何成本优化提供第一手数据（本项即消除重复劳动的第一原则的度量基础）。
5. **升级/回收不再盲切**：在飞执行的代际可见，旧代际回收需通过引用+保留窗口双门槛且默认 dry-run。

## 7. 风险与未完成项

| 项 | 状态 | 说明 |
| --- | --- | --- |
| 真实宿主运行中升级/回滚演练 | **未验收** | 需生产安装授权；本地候选/回滚/恢复测试全绿但不等价 |
| block 策略接入安装事务 | 未接线 | 会改变生产安装器行为；库函数与投影已就绪，接入需另行确认 |
| 跨平台（Windows） | 未验收 | 全部验证在 macOS |
| dispatch.jsonl 随重试轮次增长 | 已知 | 每轮 ~3 行小 JSON；清理归代际 GC 体系后续统一处理 |
| codex token_count 形状兼容 | 保守 | 未识别形状归 unknown，不猜测 |
| control-composition 性能测试容差 | 环境敏感 | 1ms 容差在满载机器上易噪声性失败（本次全量运行即一例），建议后续按方案口径放宽或固定测量窗口 |

## 8. 回滚方法

- 全部变更在 `task/sulde-orchestration-iteration` 分支 4 个提交上；未触碰 dev/main，未安装。
- 放弃整体：删除分支与 worktree 即完全回滚。
- 新运行时工件只存在于任务 worktree 的 `.codex-agent/`（launch.json / dispatch.jsonl / usage.json / run-leases/）；旧代码直接忽略，无需迁移。
- generation-gc 未接自动路径，且 apply 前有计划+保留窗口双门槛；已删除的退役树不可恢复（显式设计选择）。
