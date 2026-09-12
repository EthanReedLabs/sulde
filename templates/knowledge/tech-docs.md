---
doc_id: tech-docs/<slug>
container: tech-docs
platform: none
summary: <一句话通用主张或症状>
sedimentation_schema: 2
problem_type: design-decision
evidence_status: verified
---

# <技术原则标题>

## 问题原型

说明这条原则解决哪类工程问题，期望与常见实际结果有何差异。

## 原则与机制

解释通用机制、关键不变量和证据。

## 根因与证据

写明错误决策为何形成、证据来自哪里、哪些假设已被排除。

## 适用边界

说明应当应用、不应当应用和证据不足时的决策方式。

## 判定样本

### 路由正例

- **输入**：<应该使用本原则的问题描述>
- **预期**：apply
- **原因**：<命中条件>
- **来源**：observed / constructed

### 路由反例

- **输入**：<相似但不适用的问题描述>
- **预期**：skip
- **原因**：<边界依据>
- **来源**：observed / constructed

### 执行合格例

- **做法或输出**：<正确应用原则后的结果>
- **预期**：pass
- **原因**：<满足的不变量>
- **来源**：observed / constructed

### 执行失败例

- **做法或输出**：<形式正确但实质错误的结果>
- **预期**：fail
- **原因**：<破坏的不变量>
- **来源**：observed / constructed

## 正确做法

给出决策步骤、替代方案和验证方式。

## 取舍

说明成本、收益、被拒方案与何时重新评估。

## 消费与防复发

写明 Skill、设计评审、门禁或测试如何消费，以及语义判断边界。
