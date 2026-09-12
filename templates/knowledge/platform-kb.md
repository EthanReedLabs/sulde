---
doc_id: platform-kb/<platform>/<slug>
container: platform-kb
platform: <受控平台>
summary: <一句话平台症状或事实>
sedimentation_schema: 2
problem_type: platform-fact
evidence_status: verified
---

# <平台知识标题>

## 问题原型

说明在什么平台能力、版本边界或 API 组合下需要这条知识。

## 平台事实与约束

记录可核验的平台机制、限制和证据来源。

## 根因与证据

解释常见误判为何发生；未验证结论必须标 `inconclusive`。

## 适用边界

分别说明适用版本/能力、不适用情况，以及能力未知时的探测或降级策略。

## 判定样本

### 路由正例

- **输入**：<应该召回本条目的平台症状>
- **预期**：apply
- **原因**：<命中条件>
- **来源**：observed / constructed

### 路由反例

- **输入**：<相似但平台机制不同的情况>
- **预期**：skip
- **原因**：<排除条件>
- **来源**：observed / constructed

### 执行合格例

- **做法或输出**：<正确 API、探测或兼容结果>
- **预期**：pass
- **原因**：<验收依据>
- **来源**：observed / constructed

### 执行失败例

- **做法或输出**：<常见错误用法或假兼容>
- **预期**：fail
- **原因**：<违反的平台约束>
- **来源**：observed / constructed

## 正确做法

给出推荐用法、探测步骤和验证方式。

## 兼容与降级

说明版本差异、回退路径和不可支持时的明确结果。

## 消费与防复发

写明检索入口、平台检查器、测试矩阵和仍需人工判断的部分。
