# G3 generation-fenced 单写者 Supervisor

## 范围结论

G3 新增 `sulde_supervisor`：producer 提交不带 sequence/head 的强类型
`EventSubmission`，SQLite 单写者在一个事务中分配权威序号、执行 G1 reducer、追加
ledger、更新 projection 并形成唯一终态 receipt。当前它是下一阶段迁移的 shadow
control-plane substrate，尚未让 production Hook 双写，也未替换旧 JSON/JSONL 真相源。

## 已实现

- `EventSubmission`：content-addressed、不可变、host-neutral；producer 只能声明事件语义，
  无权分配 sequence、previous head 或 event ID。
- bounded inbox：冻结最大 pending 数量和总字节数；容量耗尽在接收前返回明确
  `InboxFull/not accepted`，不会形成半接收任务。
- 单写者 drain：`BEGIN IMMEDIATE` 取得一次短事务 writer epoch；SQLite 自身保证同一
  workspace 只有一个 reducer writer，不保留跨进程 lease/file-lock 状态。
- 原子状态变化：ledger append、projection update、receipt terminal 和 generation meta
  同事务提交；任一点崩溃全部回滚，恢复后只应用一次。
- 终态 receipt：合法事件为 `applied`；确定性非法迁移为 `rejected`；精确重复 submission
  返回既有 receipt，不重复执行 reducer。
- generation fence：普通 submission 必须匹配 active generation；切换必须在 supervisor
  `stopped`、inbox 为空时作为唯一 activation 进入；切换期间拒绝其他请求，切换后旧
  writer 返回 `StaleGeneration`。
- bounded busy：另一个 writer 持有事务时，在冻结的 0–5000ms timeout 内返回
  `SupervisorBusy/not accepted`，不会无限等待或遗留“paused”任务。
- replay audit：从 initial state + authoritative ledger 重放，必须与 projection、active
  generation、applied receipt 数量和 inbox bounds 完全一致。
- 持久化边界：数据库创建为 POSIX 0600，拒绝最终 symlink、非普通文件、非 owner 或
  group/other 可读写模式；Windows 保留 ACL 适配边界，不伪造 POSIX mode 结论。

## 为什么没有立即接入 production Hook

旧 Guardian 仍有多个 JSON/JSONL 真相源。此时同时写 SQLite 会形成两个 authority，
而直接切换又无法证明旧历史投影无损。G3 只建立唯一 writer 的完整机制；G4 将旧账本
只读适配为 typed events、逐前缀比较 projection，验证通过后才允许一次性切换 producer。

## 验证结果

- protocol + reducer + supervisor：23/23 通过。
- G0–G3 联合定向（protocol/state/supervisor/effect/resource/intervention）：103/103 通过。
- 全部 `test_intent_guardian*.py`：194/194 通过。
- failure injection 覆盖：projection 写入前崩溃、显式 SQLite writer lock、并发 drain、
  queue full、stale generation、错误 task epoch、非法 transition、projection tampering、
  mode/symlink 违规。
- `git diff --check` 通过。

## 知识库对照

- AP-0192 证明共享写者不应依赖“大家恰好不并发”，而要串行共享写入口；G3 将同一
  workspace 的 state mutation 收敛到 SQLite writer transaction。
- AP-0200 提醒并发测试不能共享固定结果/缓存目录；G3 每个用例使用独立临时数据库，
  并单独验证真实同库竞争，不以并发污染制造假证据。

## 发现与决策

- **FG3-001**：让 Hook 构造完整 EventEnvelope 会把 sequence/head 的 writer 权限泄漏
  给 producer；因此引入独立 EventSubmission。
- **FG3-002**：持久 lease 文件会在宿主异常退出后变成新自锁源；短 SQLite transaction
  崩溃自动回滚，更适合 Hook/CLI 多进程模型。
- **FG3-003**：invalid transition 若只回滚队列项，会被每轮重复消费；单写者必须把
  确定性拒绝也写成一个 terminal receipt。
- **FG3-004**：generation 切换不能与普通 queued events 混批；必须 stopped + empty +
  singular，否则新旧 policy 会在一个 writer epoch 内混用。
- **FG3-005**：backpressure 不是 pause。未被 inbox 接收的请求必须明确返回 busy/full，
  由上层决定有限重试或通知，不能把沉默等待建模成任务状态。

## 后续入口

- G4：建立 legacy ledger → typed event 的只读 adapter、projection comparison 和切换门；
  一致性通过前 production 仍只写旧真相源。
- G5：把 TaskEpochContext、EffectRouter/config/tool registry digest 绑定到 submission 和
  generation activation。
- G6：terminal receipt/ledger 分层归档、bounded context fragment 和任意事件前缀回放
  harness，并完成总纲验收。

## 沉淀候选

### 候选：跨进程文件锁不能承担长期 actor ownership

#### 任务与意图

- **问题类型**：anti-pattern series
- **任务目标**：消除多 Hook/CLI 直接写状态与异常退出后残留锁造成的自锁。
- **用户真实预期**：任务不再莫名挂起；一个终端故障不能让其他正常任务永久失去控制面。
- **触发场景**：多个短命进程用文件锁读取、修改并覆盖同一 JSON projection。

#### 观测与证据

- **可观察症状**：并发写可能交错；旧 lock/lease 或错误 lock ordering 让只读和恢复入口
  也被阻断。
- **期望与实际差异**：期望请求有界完成或明确拒绝；实际表现为无限等待、paused 或必须
  人工卸载 Hook。
- **已确认根因**：把 actor ownership 建模为跨进程持久文件状态，而不是一个可回滚的
  单写事务。
- **已排除假设**：单纯增加更多文件锁或延长 timeout 不能保证一个请求只有一个终态。
- **证据状态**：verified
- **一手证据**：SQLite lock failure injection 在 timeout 内返回 not accepted；事务崩溃
  后 ledger/projection/receipt 全回滚，随后只应用一次。
- **正确做法及验证**：bounded inbox + short transaction single writer + terminal receipt
  + replay equality。

#### 正负样本素材

| 样本 | 内容 | 固定预期 | 判定原因 | 来源 |
|---|---|---|---|---|
| 路由正例 | 多个进程共享状态并需要严格迁移顺序 | apply | 需要 workspace actor / single writer | observed |
| 路由反例 | 彼此独立、无共享状态的只读任务 | skip | 不需要集中 writer | constructed |
| 执行合格例 | producer 只提交 request，事务 writer 分配 head 并原子写终态 | pass | 权限与顺序入口唯一 | constructed |
| 执行失败例 | Hook 各自拿锁后直接覆盖 JSON，锁失败转 paused | fail | 竞争与任务语义耦合并可自锁 | observed |

#### 上浮边界

- **建议处置**：作为 AP-0192“共享写串行化”的控制面系列条目；不与 Git index.lock
  主题直接合并。
- **必须删除或泛化**：仓库名、会话 ID、具体插件路径和任务编号。
- **可跨项目复用的内核**：短事务单写者、bounded admission、terminal rejection、
  generation fence 和 replay audit。
- **建议容器**：anti-patterns
- **候选消费者**：Hook runtime、workflow engine、approval ledger、scheduler supervisor。
