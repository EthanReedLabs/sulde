# Layer1 原始问题卡

> 本卡保留在来源项目、任务 handoff 或本地候选记录中，可以含项目内部细节；上浮到
> Layer2 前必须脱敏。无法从一手证据确认的字段写 `inconclusive`，不得补写成事实。

## 任务与意图

- **问题类型**：bug-fix / regression / performance / intent-drift /
  skill-mcp-misuse / host-inconsistency / workflow / platform-fact /
  design-decision / other
- **任务目标**：<用户或系统原本要达成什么>
- **用户真实预期**：<如有主观要求，记录已确认的表达；未知则写 inconclusive>
- **触发场景**：<在哪类任务、状态、平台或约束下发生>

## 观测与证据

- **可观察症状**：<用户或系统实际看到了什么>
- **期望与实际差异**：<具体差异>
- **已确认根因**：<根因；未确认写 inconclusive>
- **已排除假设**：<至少记录已证伪方向；没有则写“无”>
- **证据状态**：verified / inconclusive
- **一手证据**：<日志、测试、diff、用户确认或 memory entry id>
- **正确做法及验证**：<采取什么动作，怎样证明有效>

## 正负样本素材

| 样本 | 内容 | 固定预期 | 判定原因 | 来源 |
|---|---|---|---|---|
| 路由正例 | <什么输入应该召回这条知识> | apply | <命中哪些必要条件> | observed / constructed |
| 路由反例 | <最相似但不应召回的输入> | skip | <缺少哪个必要条件> | observed / constructed |
| 执行合格例 | <什么结果算真正完成> | pass | <满足哪些验收不变量> | observed / constructed |
| 执行失败例 | <什么结果看似完成但仍错误> | fail | <违反哪个验收不变量> | observed / constructed |

每项必须独立写来源和判定原因；构造样本不得伪装成实测事故。

## 上浮边界

- **必须删除或泛化**：<项目名、路径、人物、提交、业务名等>
- **可跨项目复用的内核**：<准备沉淀的规则>
- **建议容器**：anti-patterns / platform-kb / tech-docs / case-studies / work-model
- **候选消费者**：<Skill、Hook、MCP 监督器、lint、review checklist 或仅供检索>
