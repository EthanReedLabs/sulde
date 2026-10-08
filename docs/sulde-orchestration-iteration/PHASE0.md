# 阶段 0 — 冻结边界与测量基线

基线：`dev@9936c7b9e987100ba53f0e3e6af459fd59767ece`（与方案分析基线一致）。
方法：五路并行只读勘察（C1 启动、C2 执行身份、C4 观测、C5 恢复、C3 代际），
全部结论锚定 file:line；勘察报告摘录见本文，完整证据索引见 §6。

## 0.1 能力判定总表

判定口径：**复用**（已有且可复用，只接通）/ **未接通**（已有但未接通）/ **缺失**（确实缺失，需新建）。

| 子项 | 判定 | 关键事实 |
| --- | --- | --- |
| C1 统一版本化启动描述 | 未接通 | 版本化 binding（agent-runtime.py:3669-3695，持久化）、broker_frozen（:4804-3838，内存）、runtime authority（:3991-4070）、task_command（runtime_provider.py:490-558）分立；preflight 后重建命令（4354 vs 4775）；provider 选择实现两次（4709-4726 内联 vs select_provider:395） |
| C1 完整预检 | 未接通＋局部缺失 | 来源绑定/输入/报告位置/codex CLI 能力预检强且 fail-closed（agent-runtime.py:4220-4492）；host_capabilities 就绪度未接入 run_task；依赖就绪只在安装时查（python_environment.py:45-88），启动路径缺失；验收器契约预置（:4875）但可满足性不预检，verdict 落在运行后（:5378）——即 g12 报告契约不匹配浪费的根因 |
| C2 派发请求身份绑定 | 未接通 | run_id 每次无条件新铸（execution_backend.py:683）；binding 摘要从不与历史 run 比对；EventSubmission.submission_id（sulde_protocol/events.py:400-432）与 WorkspaceSupervisor（SQLite inbox 幂等回执，store.py:311-322）已建成且已测试但**无生产调用方** |
| C2 崩溃窗口（已提交未确认） | 部分复用 | 持久 execution.requested 先于 Popen＋fsync（execution_backend.py:660-694）；recover_incomplete_run 仅在进程树可证死亡时闭合，否则 recovery_blocked（:287-349）；下次启动 awaiting_human 拒绝而非重发（agent-runtime.py:4930-4942）。是 fail-closed 不是幂等续接 |
| C2 陈旧回执/心跳隔离 | 复用 | 账本回放拒绝混 run_id（execution_backend.py:169-170）；回执绑定 provider_run_id 并重验证（native_agent_broker.py:1372-1403）；round 归档旧心跳（agent-runtime.py:148-159）；缺口：heartbeat.json 读取侧无 run_id 校验（现无读者，潜在） |
| C4 增量事件读取 | 复用 | 投影缓存 tail replay（event_observer.py:2108-2133）；字节游标 scan_increment＋CAS 持久化接入活运行循环（audit_cursor.py:231-258；agent-runtime.py:2386-2401）；截断 fail-closed＋无 ghost 重建 |
| C4 LLM 用量采集 | 缺失 | 全仓无 token/成本/用量读取（grep 证实）；fleet.py 读 CC 转录仅取 cwd。C4 需新增用量层并自带跨续接去重 |
| C4 unknown≠零 语义 | 复用 | unknown/inconclusive 全仓惯例（event_observer.py:109-111, 324-344；disabled 快照报 null 不报 0） |
| C4 中断前统计留存 | 复用（事件）| 逐行 fsync＋游标 CAS（agent-runtime.py:2386-2401）；turn-finalize 持久 interrupted_events（policy.py:2903-2917）。用量值无——随新增用量层补 |
| C5 归属化恢复 | 复用 | 续接胶囊强制 zero-transfer authority 块（session_continuity.py:374-391）；RecoveryCapability 绑 provider/session/workspace/generation（recovery_lane.py:157-164, 454-482）；grant CAS 一次性消费（human_grant.py:622-739） |
| C5 问题持久化 | 复用 | grant-broker / approvals JSONL 幂等且可崩溃恢复（grant_broker.py:830-877；test_grant_broker.py:715）；超时问题确定性替换不重问（native_decision_journal.py:2591-2658） |
| C5 迟到消息隔离 | 复用（分散）| 不可变 commit 回执（task_continuation_routing.py:52-57）；epoch 丢弃（task_ownership.py:651-666）；stale_identity 探测（recovery_supervisor.py:325-341）；未匹配外部完成落 awaiting_human 债务（agent-runtime.py:2106-2184）。无单一命名机制——保持现状，不新建第二套 |
| C5 统一状态来源 | 部分复用 | sulde-status collect() 与 doctor 共享 operational_readiness＋recovery truth 投影（sulde-status.py:438-476；readiness.py:535-544）；物理存储仍多点，统一靠投影纪律——**不新建单一物理状态库**（方案 §2.1 禁止项） |
| C3 隔离候选安装 | 复用 | candidate_codex_plugin.py：环境隔离（:216-268）、真实宿主链验证（:583-682）、失败注入（:41-47）、CAS promote（install_codex_plugin.py:5145-5157） |
| C3 运行中任务代际保护 | 缺失 | peer 会话仅 observe-only（install_codex_plugin.py:1247-1319）；无按任务/执行尝试的 required-generation 绑定。阶段 3 核心 |
| C3 共享 schema 新旧兼容 | 部分 | 信封 schema_version 齐全；无新旧代际并发写共享状态的兼容策略 |
| C3 回滚与恢复通道 | 复用 | 事务回滚＋独立 journal readback（install_codex_plugin.py:4984-5083）；recover_only 独立于 Hook（:5386-5419）；recovery_lane 独立控制面 |
| C3 旧代际回收 | 缺失 | retired 树/墓碑无限保留；候选仅手动 discard。阶段 3 补按引用回收 |

## 0.2 身份与事实来源表（单一事实来源约束）

| 实体 | 事实所有者 | 持久化 | 本轮约束 |
| --- | --- | --- | --- |
| 业务任务 | 冻结 task/brief 工件＋intent 契约 | intent contract; execution_binding（agent-runtime.py:2724-2732） | 新增请求身份必须引用而非替代此层 |
| 一次执行尝试（run） | execution_backend | `state/{slug}.run.jsonl`（append-only，回放校验） | 幂等层映射到 run_id，不改 run_id 语义 |
| 派发请求（新增） | 待阶段 1 落位 | 复用 WorkspaceSupervisor SQLite inbox 或等价持久层 | 禁止内存去重；submission_id 内容寻址已定义（events.py:400-432） |
| 宿主 session | task_ownership | task lanes `(provider, session_id, task_epoch)` | 不变 |
| 工作区 | sulde_execution/context | TaskEpochContext（context_id=sha256） | 不变 |
| 安装代际 | install_codex_plugin | deployment-generation.json（`{version}:{tree_sha256}`） | 阶段 3 在其上加任务级 required-generation 引用，不建竞争发布器 |
| 效果尝试 | intervention | `.interventions.jsonl`＋幂等投影 | 不变 |
| 用量（新增） | 待阶段 2 落位 | 挂 event_observer 投影纪律（safe_attributes/拒绝敏感键） | unknown/下限/完整三态，不记零 |

兼容约束：新增字段只增不改不删；所有新文档带 schema＋schema_version（信封惯例）；投影缓存永远是解析捷径非事实权威（event_projection_cache.py:1-8）；状态恢复不转移 grant/回执/未结算效果（既有结构强制，本轮不得弱化）。

## 0.3 基线数据

### 测试基线（官方入口 run-isolated-tests.py，dev@9936c7b）

- **Ran 2453 tests：2397 ok / 2 failures / 1 error / 28 skipped**，1312s。
- 基线已知失败（环境性、非本轮引入）：
  1. `test_isolated_test_runner.test_real_os_boundary_denies_alias_and_symlink_targets` — sandbox-exec `Operation not permitted`（本机沙箱限制）
  2. `test_distill_conflict_resilience.test_cli_reports_a_conflict_with_its_own_exit_code_and_machine_code` — exit 2 != 0
  3. `test_subprocess_text_encoding_guard.test_all_text_subprocess_calls_fix_encoding_and_errors` — 4 处既有 encoding 违规
- 本轮验收口径：不新增失败；上述 3 项维持基线状态即可，不要求修复。

### 性能基线（2026-09-25，本机，N=7 顺序执行，wall time）

| 控制面路径 | 中位数 | 最大(≈P95) | 备注 |
| --- | --- | --- | --- |
| `sulde-status.py --json` | 25.22s | 25.81s | 全量状态聚合 |
| `event-observer.py summary` | 24.08s | 24.91s | 观测投影扫描 |
| `agent-runtime.py run`（缺失 brief，0 模型调用，time-to-fail） | 0.35s | 0.38s | 启动路径入口开销 |

### 既有失败形态样本（Optimus fixtures，life-status-20260924）

- g12-f35a82：feedback 阶段 300s 超时，`usage: null`，`model_turn_completed: false`，
  `ptyStopVerdict: unverifiable` —— 方案 §8.1 所述"报告契约不匹配无法收尾＋用量缺失＋停止不可验证"的实证样本，供阶段 1/2 反例测试复用。
- 路径：`/Volumes/Optimus/Sulde/fixtures/life-status-20260924/`（385MB，脱敏）。

## 0.4 验收矩阵与预算（实施前冻结）

总验收：**中断减少、安全边界不扩大、正常执行不变慢。**

性能预算与比较方法（冻结，不得事后放宽）：
- 方法：同一命令、同一机器、顺序执行，N=7，报告中位数与最大值；实施前后同法比较。
- 判据"不变慢"：各控制面路径中位数增幅 ≤ max(15%, 100ms)；超出即回归，须修回。
- 深度扫描/账本重放等非正常路径不进入本预算（方案 §2.2 不变量 8）。

| 验收项 | 目标 | 验证方式 |
| --- | --- | --- |
| 可预检错误 0 次模型调用发现（C1） | 报告契约/依赖/配置类错误在启动前 fail | 假执行器＋真实启动入口测试 |
| 同请求有效启动 =1（C2） | 重复/并发提交仅 1 次启动；同 ID 异内容冲突 | 并发＋故障注入测试 |
| 崩溃窗口不盲重发（C2） | 恢复先核对已有执行 | 确定性故障注入 |
| 陈旧回执不污染（C2） | 旧尝试回执/心跳对新房无效 | 反例测试 |
| 状态未知不阻塞无关任务（C2） | 三值语义 | 单元＋集成 |
| 双 session 不串线（C5） | 既有结构保持，回归验证 | 既有测试＋新增反例 |
| 用量三态（C4） | 完整/下限/unknown 分别计数，不记零 | 假转录样本测试 |
| 日志异常不伪造成功（C4） | 轮转/损坏明确报告 | 注入测试 |
| 回滚可执行＋独立读回（C3） | 候选失败不破坏生产入口 | 隔离候选安装演练 |
| 运行中升级保护（C3） | 在飞任务保留执行归属与代际 | 真实宿主链验证（Codex） |
| 未实测收益 | 保持"待测"，不承诺 | — |

不在本轮授权内：付费模型调用、dev/main 合并、推送、生产安装、跨平台（Windows/远端）验收——相关项标"未验收"。

## 0.5 阶段 0 交付核对

- [x] 模块变更清单与单一事实来源表（§0.1/§0.2）
- [x] 身份／事件／状态兼容约束（§0.2 末段）
- [x] 基线数据与验收矩阵（§0.3/§0.4）
- [x] 性能预算及比较方法已冻结；无实测数据的收益保持"待测"
- [x] Optimus 任务目录冻结：`/Volumes/Optimus/Sulde/tasks/sulde-orchestration-iteration/`（外接盘当前已挂载；不可用时相关验收项记录缺口，不静默换位）

## 0.6 证据索引

- 五路勘察完整报告：本会话任务转录（key 事实已锚定 file:line 收录于 §0.1/§0.2）。
- 基线测试输出：`/tmp/sulde-iter-baseline-tests.txt`（临时；摘要已录入 §0.3，随 REPORT.md 归档至 Optimus evidence/）。
- 性能原始计时：`/tmp/t-status-*`、`/tmp/t-ev-*`、`/tmp/t-ar-*`（摘要已录入 §0.3）。
- 既有样本：`/Volumes/Optimus/Sulde/fixtures/life-status-20260924/`。
