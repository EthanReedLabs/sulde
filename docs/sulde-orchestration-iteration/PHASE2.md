# 阶段 2 — 过程可观测、续接不串线（C4 + C5）

基线：`dev@9936c7b`；实现于 `task/sulde-orchestration-iteration`（阶段 1 之后）。

## 1. 变更清单

### 新增模块

| 模块 | 职责 |
| --- | --- |
| `scripts/kb/usage_ledger.py` | C4 用量核算层：从受管运行已逐行 fsync 的 provider 原始事件流（`{slug}.events.jsonl`）增量扫描用量；三态语义 `complete`（识别到的累计事实：Claude `result.usage` / Codex `token_count` totals）/ `lower_bound`（仅有逐轮片段，流中断后仍是下限非零）/ `unknown`（null 永不记零）；按 run_id 去重聚合（跨续接不重复计数，独立运行不错误合并）；流前缀被截断/重写时 fail-closed 报损，不伪造数字；只采集 token 计数字段（无 prompt/工具输出/推理内容） |

### 修改模块

| 模块 | 变更 |
| --- | --- |
| `scripts/kb/agent-runtime.py` | run_task 接线：settle 后（含 timeout/中断）扫描用量并落 `{slug}.usage.json`（随 round 归档）；崩溃恢复路径在归档前抢救已观测用量；except 路径同样保留；guardian summary `execution.usage_report` 嵌入；用量投影失败只降级为报告缺口（stderr 警告），**不改变任务终态** |

### C5 判定：复用为主，零新建

阶段 0 勘察确认 C5 六个子项中五项为强既有实现（续接胶囊 zero-transfer 结构强制、RecoveryCapability 五元组绑定、grant-broker/approvals 持久问题幂等、commit 回执不可变+epoch 丢弃+stale_identity 探测、sulde-status/doctor 共享投影）。本轮**未新建任何恢复/状态机制**，仅以测试锁定归属不变量（双 session 不串线、聚合不合并身份），并满足方案"不另建竞争性状态系统"约束。已知保留项（阶段 0 已记录）：迟到消息隔离由多账本组合保证，无单一命名机制——维持现状。

## 2. 验收对照（方案 §5）

- [x] **双 session 同项目不串任务，不继承旧授权**：两独立 CLI 运行的用量报告 run_id/slug 互异；聚合按 run 身份去重（集成测试）；授权不转移由既有结构保证（阶段 0 锚定，本轮未触碰）。
- [x] **重复采集不重复计数**：同 run 报告三次聚合计一次；独立运行求和；complete+unknown 贡献降级 lower_bound，不伪造完整。
- [x] **日志轮转、损坏和中断明确报告**：前缀摘要不匹配 → UsageLedgerError fail-closed；撕裂尾部忽略在最后完整行边界；调用方（agent-runtime）将失败降级为"报告不可用"警告，不产生伪造成功统计。
- [x] **超时仍可回读已观测证据**：timeout 集成测试确认 status=timeout 时 usage.json 已落盘且为 lower_bound；崩溃恢复路径归档前抢救扫描。
- [x] **执行结束、报告成功、验收通过、发布完成分别可查询**：既有 run ledger stop_reason / report_verdict / 状态行 / 部署代际各自独立（阶段 0 锚定），本轮 summary 增加用量维度不压缩任何标志。
- [x] **结束任务不因旧缓存恢复为活动任务**：投影缓存"解析捷径非权威"纪律未触碰；陈旧心跳读取侧拒绝（阶段 1）补强。
- [x] **增量读取**：scan_usage 支持游标式增量（offset+prefix digest）；监控管道已有逐行 fsync+audit cursor，报告可多次增量推进得到与单次全扫一致结果（测试验证）。
- [x] **字段最小化**：报告仅含 token 计数/轮数/流位置摘要/身份归属；工具调用与敏感内容不进入报告（测试断言）。

## 3. 测试范围

- 新增 `tests/test_orchestration_phase2.py`：16 例（扫描 8 + 聚合 4 + 真实 CLI 集成 3 + 归属 1），全部通过。
- 回归：test_agent_runtime / execution_backend / event_observer 121 例通过；完整官方回归见 STATUS/REPORT。

## 4. 性能与用量数据完整性

- 本阶段新增工作全部位于运行收尾路径（settle 后一次有界文件扫描）；正常路径监控循环零改动。
- 用量数据完整性：每运行必有 `{slug}.usage.json`（成功/超时/失败/崩溃恢复四路径），状态 ∈ {complete, lower_bound, unknown}，缺失明确披露。
- 早期对照样本 g12 的 `usage: null` 失败形态，在新管道下将表现为 `unknown` 状态报告而非空缺——可区分"未采集"与"采集为零"。

## 5. 已知限制

- Codex `token_count` 事件形状按当前已知版本识别；未识别形状归 unknown 并保守标注，不猜测。
- 用量聚合的跨任务视图由 `aggregate_usage()` 提供（按需调用）；未新建常驻聚合服务（方案禁止项）。
