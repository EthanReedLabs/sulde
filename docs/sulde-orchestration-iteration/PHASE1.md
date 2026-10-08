# 阶段 1 — 启动正确、派发不重复（C1 + C2）

基线：`dev@9936c7b`；实现于 `task/sulde-orchestration-iteration`。
复用原则落实：全部缺口用"已建成但未接通"的原件接通或最小新增，未建第二套状态系统。

## 1. 变更清单

### 新增模块（3 个，均为最小职责）

| 模块 | 职责 |
| --- | --- |
| `scripts/kb/launch_description.py` | 单一版本化启动描述（`sulde-launch-description-v1`，仅摘要无 argv/prompt）；构建/解析/摘要漂移检测；语义身份 `launch_description_identity`（排除可执行文件依赖的 command 摘要）；0 模型调用预检（报告契约/报告位置可写/可执行解析）与失败证据 `sulde-launch-preflight-failure-v1` |
| `scripts/kb/dispatch_registry.py` | 派发请求身份持久层：`{slug}.dispatch.jsonl` append-only+fsync；`opened→launched→closed` 段语义；request_id 永久绑定内容摘要；三值派发语义（确定已开/确定已启动/未知走运行账本核证） |
| `scripts/kb/run_concurrency.py` | 有限并发额度：租约文件+排他锁（复用 `file_lock.py` 跨平台原语）；死进程租约修剪；默认上限 4（`SULDE_MAX_CONCURRENT_RUNS`），无可用槽 fail-closed 不启动 |

### 修改模块（3 个）

| 模块 | 变更 |
| --- | --- |
| `scripts/kb/runtime_provider.py` | 新增 `resolve_managed_run_provider()`：把 run_task 内联的 provider 环境链（含 `SULDE_AGENT_PROVIDER` 与 codex-host 捷径）收编为唯一实现；无静默切换语义原样保留（既有测试钉死） |
| `scripts/kb/execution_backend.py` | `start()` 接受可选 `launch_description_sha256` 嵌入 `execution.requested` 首事件；回放校验其格式；旧账本（无该字段）照常回放 |
| `scripts/kb/agent-runtime.py` | run_task 接线：统一 provider 选择；构建+预检+持久化 `{slug}.launch.json`；同 slug 语义漂移显式拒绝（可执行文件更换单独豁免——恢复 finisher 流程）；派发注册表（lock 后开启、start 后 launched、终态 closed、崩溃恢复后补 close）；启动前有限并发租约；陈旧非终态心跳拒绝（`_refuse_stale_phase_heartbeat`）；CLI 新增 `--request-id` |

## 2. 验收对照（方案 §4）

- [x] **可预检错误 0 次模型调用发现**：报告契约损坏、报告位置逃逸/符号链接/不可写、可执行不可解析 → 启动前 fail+证据落盘；真实 CLI 入口测试（非纯解析器）验证。
- [x] **同请求重复或并发提交仅 1 次有效启动**：并发第二次被 per-slug lock 拒绝（集成测试）；注册表同 ID 同内容续接原尝试。
- [x] **同 ID 不同内容明确冲突**：request_id 永久绑定内容摘要（含终态后）；同 slug 语义漂移（effort/provider/brief/task/binding）显式拒绝。
- [x] **崩溃/确认丢失后先核对已有执行**：opened-not-launched 续接；launched 后以运行账本（含归档轮次）核证 terminal 才补 close；进程树可观测 → 沿用 awaiting_human 不盲发。
- [x] **老尝试回执/心跳不污染新尝试**：既有 run_id 绑定+round 归档之上，新增读取侧心跳 run_id 校验（原先无读者校验的潜在缺口）。
- [x] **明确未执行的合法新请求仍能启动**：terminal 尝试后同请求 = 新 round（集成测试验证 archive+重跑成功）；首次执行永不被防重复拒绝（opened 即允许继续 launch）。
- [x] **状态未知仅限制对应请求**：未知状态只阻塞同 slug（lock+awaiting_human），无全局锁。
- [x] **不绕过既有权限/宿主隔离/密封调用**：描述仅记录摘要；权限组合、broker、installed authority 路径零改动。

## 3. 测试范围

- 新增 `tests/test_orchestration_phase1.py`：28 例（单元 22 + CLI 集成 4 + 账本嵌入 3 类），全部通过。
- 回归：test_agent_runtime / execution_backend / runtime_provider / launcher_contract / supervision_lifecycle_e2e / orchestration_phase1 共 167 例通过（含 hard-kill 恢复、双宿主 e2e、bootstrap 契约）。
- 完整官方回归（run-isolated-tests.py）：见 STATUS/REPORT 汇总。

## 4. 性能（冻结预算对照）

| 路径 | 基线中位 | 实施后中位 | 判定 |
| --- | --- | --- | --- |
| `agent-runtime.py run` time-to-fail（缺失 brief，N=7） | 0.35s | 0.35s | 不变慢 ✅ |
| 全 fake-run 总耗时（信息性，无冻结基线，N=7） | — | 0.66s 中位 / 0.78s 最大 | 含预检+描述+注册表+guardian+监视全链；健康 |

## 5. 已知限制

- 并发额度按工作区 state 目录计（单工作区内上限）；跨工作区全局额度需跨工作区协调，本轮不做（避免新常驻服务）。
- `dispatch.jsonl` 随重试轮次线性增长（每轮 ~3 行小 JSON）；清理策略归阶段 3 资源回收统一处理。
- 预检不能保证模型行为满足报告契约（那是运行后验收器的职责）；预检覆盖的是基础设施类不匹配（g12 失败形态中的可预检部分）。
