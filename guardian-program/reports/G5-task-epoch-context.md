# G5 配置来源追踪与冻结 TaskEpochContext

## 范围结论

G5 新增 `sulde_config` 与 `sulde_execution`，把分散配置、权限约束、能力/验证器注册表、
宿主 session、任务定义、owned paths、runtime generation 和预算冻结为一个内容寻址的
`TaskEpochContext`。事件、纯 reducer、单写者 admission 和 G4 cutover 都绑定同一个
context ID；当前 epoch 中的热更新不会静默改变已冻结规则。

本阶段没有切换 production writer、安装 runtime、恢复历史事务或修改旧 JSON/JSONL
账本。空 context ID 仍保留给 G0–G4 兼容路径；正式 cutover 一旦选择 context 模式，
缺失或漂移即 fail-closed。

## 已实现

- `ConfigLayerStack` 固定优先级：packaged < shared < host < workspace < task，managed
  constraints 最后收紧。
- 普通字段保留最终 `source_layer`；被安全边界收紧时记录 `constrained_by`。
- `permissions.*` 在所有层间只取集合交集，任务层或宿主层不能扩大低层权限；
  `limits.*` 的 managed 值只取当前值与约束值的最小值。
- managed layer 只能声明 `permissions.*` 或 `limits.*`，不能伪装成普通覆盖层。
- 配置层、字段、类型和大小全部有界，并形成确定性 `snapshot_sha256`。
- `EffectRouter` 暴露稳定、顺序无关的 capability manifest digest 与独立 verifier
  manifest digest；参数 schema、敏感字段、effect、authority、并行度、rollback 和 timeout
  都进入 capability digest。
- `TaskEpochContext` 冻结 workspace/intent/revision/task epoch、provider/native session、
  task definition digest、canonical workspace-relative owned paths、policy/config/capability/
  tool/verifier digest、runtime generation、legacy cut 和 budgets。
- context 为不可变 content-addressed value；配置、policy、registry、generation 或 owned
  path 任一变化都会形成新的 context ID，不可覆盖当前 context。
- `EventCorrelation` 和 `GuardianState` 携带 context ID；reducer 精确拒绝跨 context 事件。
- 单写者在 inbox admission 阶段返回 terminal `task_context_mismatch`，错误请求不会进入
  authoritative ledger。
- 已绑定 context 的同一 task epoch 不允许 generation activation；更新必须创建下一
  context/epoch，避免新旧 runtime 规则混用。
- G4 cutover 在 context 模式下同时核对 exact context ID、workspace、intent/revision、
  task epoch、target generation、legacy cut ID 与 contract material policy digest；binding
  仍然只是 data-only evidence，不转移 authority。

## 兼容与安全边界

- G3 typed supervisor 尚未接入 production，因此本轮没有迁移现网持久化 typed event；
  既有调用不传 context 时保持空值兼容。
- Config digest 只证明“采用了哪一组配置”，不自行授予权限；实际 effect authority 仍由
  reducer/approval/effect policy 判断。
- task override 对普通行为配置可覆盖，但对 permission 只能继续缩小；managed constraint
  永远不能被 task override 放宽。
- owned paths 必须是规范、无 `..`、非绝对的 POSIX workspace-relative 路径；context 不
  接受隐式 cwd 或宿主 home 展开。
- runtime 热更新可以生成新 context，但不能改变旧 context；旧 epoch 继续使用冻结规则，
  或在 quiescent boundary 明确结束后进入新 epoch。

## 验证结果

- G5 config/context/router/protocol/state/supervisor/cutover 小套件：48/48 通过。
- G0–G5 联合定向（config/context/effect/protocol/state/supervisor/projection/native journal/
  intervention/approval/recovery/readiness）：320/320 通过。
- 全部 `test_intent_guardian*.py`：194/194 通过。
- failure injection 覆盖：permission widening、managed 普通字段覆盖、limit 放宽、配置和
  generation drift、owned path escape、context digest tamper、未绑定 submission、cutover
  缺 context。
- `git diff --check` 通过。

## 发现与决策

- **FG5-001**：配置“后者覆盖前者”不适用于权限。权限若使用普通 override，task/host
  layer 可无意扩大 managed 或 packaged 边界，必须使用单调交集。
- **FG5-002**：只冻结 runtime digest 不足以防新旧版本混用；approval、effect verifier、
  tool registry 和 config 必须共享一个 task epoch context identity。
- **FG5-003**：hot reload 不能修改当前 epoch 的 context。否则工具开始、确认和完成可能
  分别使用不同 policy，重现 approval binding/CAS mismatch。
- **FG5-004**：cutover ID 与 context ID 不能各自独立“看起来正确”；context 必须显式
  引用 exact legacy cut 与 contract material digest，目标初态也必须引用 exact context。
- **FG5-005**：provenance 是 operational evidence，不只是调试信息。最终值必须能解释
  来自哪一层、被哪一层收紧，才能判断频繁人工授权究竟源于 policy 还是配置漂移。

## 后续入口

- G6：有界 `ContextFragment`、hot/cold ledger 与 truncation marker、任意事件前缀 replay
  harness，并执行 G0–G6 总纲验收。
- production switch 仍受 G4 gate 阻断；待 G0–G6 集成进入 `dev` 并通过 release-level
  验证后，才通过官方安装链部署，再幂等恢复既有开放事务。不得直接编辑旧账本。

## 沉淀候选

### 候选：配置覆盖与权限约束必须使用不同代数

#### 任务与意图

- **问题类型**：anti-pattern series
- **任务目标**：统一多宿主、多 workspace、多任务配置，同时避免授权边界漂移。
- **用户真实预期**：普通行为配置可按范围覆盖；权限不能因为更靠近任务就被扩大；系统
  能解释为什么某一步需要或不需要人工确认。
- **触发场景**：packaged/shared/host/workspace/task/managed 多层配置使用同一 merge
  规则。

#### 观测与证据

- **可观察症状**：新旧 runtime 或不同宿主读取到不同 effective policy；相同动作有时
  自动放行、有时重复请求人工确认。
- **期望与实际差异**：期望 task override 只改变任务偏好；实际普通 override 也可能扩大
  capability roots 或 permission allow-list。
- **已确认根因**：权限集合、数值安全上限和普通字段被当作同一种“后者覆盖前者”。
- **证据状态**：verified
- **一手证据**：G5 单元与集成测试证明 permission widening 被交集消除、managed limit
  只能收紧，来源和约束层可稳定复现；历史多宿主漂移由 G0–G4 报告交叉证明。
- **正确做法及验证**：普通值按来源优先级覆盖；权限取交集；managed 上限取最小值；
  effective field 同时记录 source 与 constrained_by，并把快照 digest 绑定 task epoch。

#### 正负样本素材

| 样本 | 内容 | 固定预期 | 判定原因 | 来源 |
|---|---|---|---|---|
| 路由正例 | 多层配置包含 permission/capability roots | apply | 需要单调安全合并 | observed |
| 路由反例 | 纯 UI 文案偏好按 task 覆盖 | skip | 普通 precedence 已足够 | constructed |
| 执行合格例 | permission 逐层交集，managed limit 取最小并记录来源 | pass | 无权限扩大且可解释 | constructed |
| 执行失败例 | task 层整表覆盖 managed allow-list | fail | 靠近调用方反而扩大权限 | constructed |

#### 上浮边界

- **建议处置**：作为多宿主 policy/config drift 系列条目，与 approval 重复提示案例关联，
  不另建宿主专属条目。
- **必须删除或泛化**：具体 workspace、session、revision 和本机路径。
- **可跨项目复用的内核**：配置 precedence、权限 intersection、limit minimum、来源追踪、
  epoch snapshot digest。
- **建议容器**：anti-patterns
- **候选消费者**：agent control plane、CI policy、plugin runtime、scheduler、MCP adapter。
