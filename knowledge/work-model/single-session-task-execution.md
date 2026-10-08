---
doc_id: "work-model/single-session-task-execution"
container: work-model
platform: none
summary: "复杂 task 由**单个 Dev session 端到端跑通**的正向工作法。"
---

# 单 session 一次跑通工作法

> 复杂 task 由**单个 Dev session 端到端跑通**的正向工作法。适用协调端派单 + Dev 实施两端。

---

## 一句话

一个复杂 task,最优执行路径是**同一个 Dev session 一次性从头到尾跑完**——read 全真值 → transpile/实施 → 真机 e2e 验证 → 写 handoff——中途**不 `/clear`、不切 task**;主链路优先,polish 留 Phase 2。前提是协调端派单前把 4 项前置条件备齐。

---

## 为什么需要它

多轮返工的典型消耗来自派单后的 Dev 实施模式,而非反抽本身:

- Dev 用中配模型跑复杂 task,上下文压力大 + 多轮 `/clear` 丢上下文
- Dev 仅 read task md、不 read 一手真值源码 → 误把二手 design-truth doc 当真值
- 多轮 fix 反复重读 task md / handoff,重复消耗 token

结果:同一 task 被拆成 N 轮 fix,总时长翻倍。

---

## Decision:Dev 单 session 一次性完成

用**高能力大 context 模型(如 opus 档)在同一 session 一次性**完成整个 task:

1. **Read 全真值**:task md + design-truth + 平台知识库 + 一手源码关联 file(5-10 个)+ 前序 handoff 参考
2. **实施 + 验证**:transpile → build → install → 真机 e2e → handoff §0 写 trace 表
3. 中途**不 `/clear`**、不切 task
4. **Phase 1 主链路优先**,Phase 2 polish 留(占位组件 + handoff §upgrade 报后续)
5. 同一 bug **≥ 2 次 fix 失败** → 转入系统化 debug 流程,不再盲试

---

## 协调端派单前 4 前置条件(audit)

派单前协调端逐项核对,4 项全齐才派:

| # | 条件 | 谁备 |
|:-:|---|---|
| 1 | 平台限制 spike 全部 verified | 协调端 + sweep 平台知识库 |
| 2 | Server / env ready(测试账号 / token / 真响应抓包) | 甲方 + 后端 |
| 3 | Dev 端大 context 一次性 session | Dev terminal 切顶配模型 |
| 4 | 协调端输入完整(task md + design-truth + 源码 file:line nav + endpoint 表 + 反抽修订) | 协调端 |

**4 项全齐 → 1 次跑通预期 ≥ 90%;少 1 项 → 退回多轮 fix。**

---

## Phase 1 / Phase 2 划界

- **Phase 1(本 session 必交)**:主链路端到端可用 + 真机 e2e 过。
- **Phase 2(留后续)**:视觉 polish、边角态、占位组件替换等——handoff §upgrade 里列清,协调端按需再派单。

不追求一次做满;追求主链路一次跑通、增量项显式留痕。

---

## 收益对比

| 指标 | 旧 path(多轮) | 新 path(单 session 一次跑通) |
|---|---|---|
| 反抽 / 协调端时长 | ~2-3h(不变) | 不变 |
| Dev 实施时长 | 6-8h × N 轮 | 6-8h × 1 轮 |
| 协调端 review + fix 派单 | N 次 × ~1.5h | 1 次 × ~1h(仅 polish 派 Phase 2) |
| **总** | **~10-12h** | **~7-9h(省 25-35%)** |

---

## 关联

- 反抽不完整 → 多轮返工:本工作法补的是「派单后 Dev 实施模式」这一环,不替代反抽,反抽仍要跑深。
- 同一 bug ≥ 2 次 fail → 转系统化 debug,不盲试。
- task md 4 维完整(全链路 + endpoint + 业务逻辑 + 视觉真值)是前置条件 4 的展开。
