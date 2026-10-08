# G4 旧账本只读适配与 cutover gate

## 范围结论

G4 新增 `sulde_projection`，对旧 contract、observation、approval、effect 和 native
decision 真相做只读冻结、当前语义投影与 cutover 比较。迁移采用 quiescent boundary：
旧历史不重写、不删除、不伪造成新 authority；只有旧侧所有开放控制事务归零且新
Supervisor 仍为空初态，才生成 `authority_transferred=false` 的 data-only binding。

当前 production shadow audit 明确为 **blocked**，因此没有切换 production writer，
也没有让 Hook 双写 SQLite。

## 已实现

- `SourceFingerprint`：冻结 7 类源的 path/device/inode/size/mtime/digest：contract、
  observations、approvals、effects、native journal、native head anchor、pending sidecar。
- optimistic stable cut：冻结前后任一源发生变化即 `LegacyCutChanged`，单源与总 cut 都有
  512 MiB 上限，contract 另有 16 MiB parse 上限。
- `LegacySemanticProjection`：映射 contract/task/approval/effect/intervention 当前状态，
  并显式计数 open event、pending verification/proposal、active skill、paused lane、open
  approval、active native transaction、blocking effect、open intervention 和 integrity
  breach。
- 历史 `effect=read` 的 unknown row 保留在完整源摘要中，但不会成为 material cutover
  debt；真实未验证写仍 fail-closed。
- `load_projection_read_only`：native journal 现在可在不创建 lock、不执行 pending repair、
  不删除 sidecar 的情况下纯 replay；发现 pending head 时返回“需要恢复”而不是自行写入。
- `assess_cutover`：同时绑定 exact cut、旧 generation、目标 generation、workspace、task
  epoch 和空 supervisor projection；任一 drift 返回 blocker，不生成 binding。

## 避免自引用 CAS

cut 保留完整 audit source fingerprints，但 material cut ID 不直接绑定 observation log 尾部
或 active JSON 的原始 audit counters。否则“执行 cut audit”自己的 Hook completion 会追加
observation 并立刻让 cut 过期，复现 proposal → audit → CAS mismatch。

material cut ID 只绑定：

- approval/effect/native journal 与 native anchor/pending sidecar；
- contract 的规范 material view（revision、task epoch、目标/约束/权限、material sequence、
  proposal/pause material state 等）；
- 当前开放控制状态的 semantic projection。

测试证明 observation 尾部只追加时 material cut ID 不变；contract preserve constraint
变化时 cut ID 必然变化。

## 当前 production shadow 结果

2026-08-25 的只读 shadow collection 成功 replay 现有旧账本，但 gate 未就绪：

- `open_events:2`：两笔已落文件但缺 completion closure 的本地 ApplyPatch 记录；
- `pending_native_transactions:6`：包含本轮真实复现的旧运行时 completion receipt 故障；
- 已读回验证的历史远端 Git attempt 已是 `system_verified`，不再计入 blocking effect。

这些是现有旧控制面的真实开放状态，不是 G4 新增任务。正确处置是在 G0 runtime 安装后
用幂等 recovery 和现有文件/ledger 证据闭合；禁止删除 active JSON/JSONL、直接改 projection、
重放 Git push 或把 tool success 当成 evidence。

## 验证结果

- projection + native journal + protocol/state/supervisor/effect/intervention：168/168 通过。
- 全部 `test_intent_guardian*.py`：194/194 通过。
- failure injection：source 中途变化、audit-only append、material contract drift、nonempty
  target、stale cut、read-only native pending sidecar、read effect historical debt。
- native read-only replay 前后 journal/anchor bytes、mtime 和 lock existence 完全不变。
- `git diff --check` 通过。

## 发现与决策

- **FG4-001**：把 observation log 原始哈希放进 material CAS 会形成 observer self-CAS；
  audit evidence 和 authority material 必须分层绑定。
- **FG4-002**：`pending()`/`load_projection()` 名称看似只读，但 native journal 旧实现会以
  `a+` 创建 lock 并执行 recovery；受限宿主因此连审计都失败。
- **FG4-003**：4 万余条 observation 不应改写为新 authority event。完整历史内容寻址
  保留，迁移只在 quiescent boundary 建立新 writer 初态。
- **FG4-004**：cutover binding 不是 approval。它只证明 source cut 与空 target 一致，
  不启动 writer、不安装 runtime、不继承旧 PermissionRequest。
- **FG4-005**：当前 gate blocked 是正确结果；为追求“看起来完成”而删除 2+6 个开放项
  会破坏用户要求的真实落地性。

## 后续入口

- G5：将 contract material、EffectRouter、tool/config/verifier registry 和 runtime
  generation 收敛成冻结 TaskEpochContext；cutover binding 必须引用 context ID。
- G6：在受控 Stop/supervisor boundary 消费 cutover binding，完成 prefix replay harness、
  有界归档与总纲验收；production switch 前先安装含 G0 的集成 runtime，并幂等闭合当前
  2+6 项。

## 沉淀候选

### 候选一：只读 API 内部创建锁文件会让治理层自我阻断

#### 任务与意图

- **问题类型**：anti-pattern
- **任务目标**：在 restricted host 中只读冻结旧 authority ledger。
- **用户真实预期**：诊断和恢复前检查不需要额外人工授权，也不会改变待检查对象。
- **触发场景**：`pending()`/`load_projection()` 为保持一致性进入 `a+` file lock，并可能
  顺带恢复 pending sidecar。

#### 观测与证据

- **可观察症状**：shadow cut 读取 native transaction 时因无法创建 `.lock` 返回 EPERM。
- **期望与实际差异**：期望纯 replay；实际读取具有写副作用。
- **已确认根因**：查询 API 和 recovery owner 共用同一带修复能力的 load path。
- **已排除假设**：不是账本损坏，也不是用户未授权读取。
- **证据状态**：verified
- **一手证据**：真实 restricted run 的 PermissionError；新增纯 replay 后真实 shadow
  collection 成功，70 个 projection/native 测试通过。
- **正确做法及验证**：提供严格 read-only replay；pending repair 只报告 blocker，由单写
  recovery owner 处理。

#### 正负样本素材

| 样本 | 内容 | 固定预期 | 判定原因 | 来源 |
|---|---|---|---|---|
| 路由正例 | 查询函数会创建 lock/repair/delete sidecar | apply | “读”实际需要写 authority store | observed |
| 路由反例 | 写事务显式取得 lock 并记录 recovery | skip | 写语义明确 | constructed |
| 执行合格例 | 无锁读取 frozen bytes，pending 时 fail-closed 返回 recovery_required | pass | 零状态变化 | constructed |
| 执行失败例 | 为了查询 pending 数量先执行 recovery | fail | 诊断改变被诊断对象 | observed |

#### 上浮边界

- **建议容器**：anti-patterns
- **必须删除或泛化**：具体 home 路径、workspace hash 和 transaction 数量。
- **可跨项目复用的内核**：query/replay 与 repair/mutate API 必须物理分离。
- **候选消费者**：ledger、doctor、migration、readiness、sandbox adapter。

### 候选二：observer 事件不能无条件进入 proposal/cutover material CAS

#### 任务与意图

- **问题类型**：anti-pattern update
- **任务目标**：冻结迁移 cut 时避免审计动作自我改变基线。
- **用户真实预期**：只读诊断不会让原本合法的下一步永久 CAS mismatch。
- **触发场景**：proposal/cut 绑定完整 events log 或包含 observation sequence 的整份 JSON。

#### 观测与证据

- **可观察症状**：每次读取/审批/诊断都会追加审计事件，旧 material base 随之变化。
- **已确认根因**：audit evidence 与 authority material 使用同一无差别 digest。
- **证据状态**：verified
- **正确做法及验证**：完整 audit prefix 保留；material digest 只绑定会改变决策语义的
  typed fields。测试中 audit append 保持 cut ID，constraint 改动改变 cut ID。

#### 正负样本素材

| 样本 | 内容 | 固定预期 | 判定原因 | 来源 |
|---|---|---|---|---|
| 路由正例 | 读取行为会被同一 observer 追加进被绑定日志 | apply | 存在自引用 CAS | observed |
| 路由反例 | 外部业务对象版本发生变化 | skip | 这是真实 material drift | constructed |
| 执行合格例 | audit prefix 单独留证，typed material view 进入 CAS | pass | 审计完整且不自锁 | constructed |
| 执行失败例 | raw active JSON + events JSONL 整体哈希作为唯一 CAS | fail | observer 自己使结果过期 | observed |

#### 上浮边界

- **建议处置**：并入已有 proposal base material CAS/Guardian 自引用故障条目。
- **必须删除或泛化**：具体事件数、revision 和文件名。
- **可跨项目复用的内核**：audit identity 与 decision material identity 分离。
- **建议容器**：anti-patterns
- **候选消费者**：approval CAS、migration cut、doctor、event observer。
