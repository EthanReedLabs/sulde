---
doc_id: work-model/<slug>
container: work-model
platform: none
summary: <一句话工作流症状或目标>
sedimentation_schema: 2
problem_type: workflow
evidence_status: verified
---

# <工作模型标题>

## 问题原型

说明什么任务、角色、阶段或失败信号需要启用这套工作法。

## 根因与证据

解释旧流程为何失效，列出已验证证据与未决判断。

## 适用边界

说明应启用、不应启用和无法判定时的安全动作。

## 判定样本

### 路由正例

- **输入**：<应该启用本工作法的任务或信号>
- **预期**：apply
- **原因**：<命中条件>
- **来源**：observed / constructed

### 路由反例

- **输入**：<相似但不应启用的任务>
- **预期**：skip
- **原因**：<边界条件>
- **来源**：observed / constructed

### 执行合格例

- **做法或输出**：<流程正确闭合后的证据>
- **预期**：pass
- **原因**：<验收条件>
- **来源**：observed / constructed

### 执行失败例

- **做法或输出**：<只走形式、没有形成闭环的结果>
- **预期**：fail
- **原因**：<遗漏步骤或证据>
- **来源**：observed / constructed

## 正确做法

给出角色、步骤、状态转换、失败处理与中断恢复。

## 执行流程

用清单、状态机或时序描述消费者如何执行。

## 验收与失败处理

定义通过、失败和 `inconclusive` 的判定及后续动作。

## 消费与防复发

列出实际 Skill、Hook、MCP、任务模板、门禁和正反回归测试。
