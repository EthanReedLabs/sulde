# G1 强类型事件协议与纯 reducer

## 范围结论

G1 新增 host-neutral 的 `sulde_protocol` 和无 I/O 的 `sulde_state_machine`。
它们目前是兼容层和后续迁移目标，不写第二份权威账本，也没有替换现有 production
projection；G3 单写者接入前，旧账本仍是唯一真相来源。

## 已实现

- `EventEnvelope`：schema、sequence、previous head、workspace、runtime generation、
  domain/type、provider、actor、TaskEpoch correlation 和 bounded payload 全部进入
  64 位 content digest；对象冻结并支持严格 round-trip。
- `EventType` 与分领域状态 enum：intent、task、approval、effect、intervention、
  supervisor 独立建模，避免 `success/completed/succeeded` 和跨域 `paused` 漂移。
- 纯 `transition(state, event)`：唯一迁移入口，连续 sequence/head、task epoch、
  runtime generation、request/attempt/intervention identity 均 fail-closed。
- `replay(initial, events)`：同一事件序列得到相同 projection；精确最后事件重复为
  no-op，非连续、旧 epoch 和错误 generation 拒绝。
- 不变量：最多一个 task terminal；未验证 effect 不能 task succeeded；abort 只终止
  effect workflow，不证明外部真相；五分钟 reassessment 不是 expiration 或 authority。

## 依赖边界

`sulde_state_machine` 只依赖标准库与 `sulde_protocol`，不依赖 filesystem、SQLite、
subprocess、Codex/Claude adapter、Hook 或现有 Guardian 模块。测试用 AST 固定这一边界。

现有 `event_contract.py` 是脱敏 observation projection，明确不是状态迁移协议；本轮
没有修改或复用它来产生 authority。

## 验证结果

- G1 新增协议/reducer：11/11 通过。
- G0 + G1 联合定向：246/246 通过。
- `git diff --check` 通过。

## 发现与决策

- **FG1-001**：强类型不等于只用 dataclass 校验字段。真正边界是所有状态变化必须
  收敛到一个 reducer；G1 先建立纯函数，G3 才接 writer。
- **FG1-002**：不能把 task、approval、effect、intervention 的状态压成一个 enum；
  它们有不同终态和不同恢复权限。
- **FG1-003**：`abort` 是控制流终态，不是外部效果成功/失败证据，因此 reducer
  仍禁止 task succeeded，允许显式 inconclusive。

## 后续入口

- G2：EffectRouter 产生 typed effect events，并把 legacy 文本分类降为 fallback。
- G3：bounded inbox + generation-fenced 单写者消费这些事件。
- G4：从旧 JSON/JSONL 只读适配成 event replay，比较 projection；切换前不 dual-write。

## 沉淀候选

### 候选：字符串状态拆枚举仍不等于状态机收敛

#### 任务与意图

- **问题类型**：design-decision
- **任务目标**：降低多模块对相同状态理解不一致造成的恢复和授权错误。
- **用户真实预期**：任务不再莫名挂起、自锁或因新旧模块状态词不同而无法恢复。
- **触发场景**：多个 Hook/CLI/recovery 模块直接修改 dict/JSON。

#### 观测与证据

- **可观察症状**：相似状态字符串散落，不同模块有自己的迁移分支。
- **期望与实际差异**：字段即使被 enum 校验，多个 writer 仍可产生非法组合。
- **已确认根因**：缺少唯一 transition reducer，而不只是缺少数据模型。
- **已排除假设**：单独引入 Pydantic/dataclass 不能消除写入口竞争。
- **证据状态**：verified
- **一手证据**：现有写入口审计，以及 G1 reducer 的 replay/terminal/epoch 测试。
- **正确做法及验证**：分领域 enum + 唯一纯 reducer + 单写者；任意事件前缀验证不变量。

#### 正负样本素材

| 样本 | 内容 | 固定预期 | 判定原因 | 来源 |
|---|---|---|---|---|
| 路由正例 | 多模块都有 `if status == ...` 并直接写 JSON | apply | 写入口和迁移语义同时分散 | observed |
| 路由反例 | 单模块内部局部 enum 且无共享状态 | skip | 不存在跨 writer 状态竞争 | constructed |
| 执行合格例 | 所有 typed event 经同一纯 reducer，replay 与 persisted projection 相等 | pass | 迁移入口唯一且可重放 | constructed |
| 执行失败例 | 新增 enum/Pydantic，但 Hook 和 CLI 继续各自改 dict | fail | 只改善字段校验，没有收敛状态变更 | observed |

#### 上浮边界

- **必须删除或泛化**：模块名、路径、任务编号和具体宿主会话。
- **可跨项目复用的内核**：强类型治理的核心是唯一 reducer 和单写者，不是模型类数量。
- **建议容器**：tech-docs
- **候选消费者**：状态机设计、Hook adapter、recovery、架构 review。
