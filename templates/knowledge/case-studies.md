---
doc_id: tech-docs/案例研究/<domain>/<slug>
container: case-studies
platform: none
summary: <一句话案例问题>
sedimentation_schema: 2
problem_type: bug-fix
evidence_status: verified
---

# <案例标题>

## 场景与系统架构

用脱敏后的结构图或文字说明系统上下文。

## 问题原型

描述可观测现象、实测数据，以及期望与实际的差异。

## 根因与证据

深入到平台或系统机制；区分已观测事实、推断和已排除方案。

## 适用边界

说明案例可迁移到哪些系统、不适用于哪些系统，以及证据不足时如何处理。

## 判定样本

### 路由正例

- **输入**：<应该参考本案例的问题描述>
- **预期**：apply
- **原因**：<共享的机制与条件>
- **来源**：observed / constructed

### 路由反例

- **输入**：<表象相似但机制不同的问题>
- **预期**：skip
- **原因**：<不同根因或边界>
- **来源**：observed / constructed

### 执行合格例

- **做法或输出**：<修复与验证闭环>
- **预期**：pass
- **原因**：<证据满足验收>
- **来源**：observed / constructed

### 执行失败例

- **做法或输出**：<只缓解表象或缺少复测的方案>
- **预期**：fail
- **原因**：<闭环缺口>
- **来源**：observed / constructed

## 正确做法

给出方案、why-this-not-that、实施步骤与复测结果。

## 可迁移原则

提炼至少三条项目无关的工程规律。

## 消费与防复发

写明哪些知识只供人阅读，哪些进入 Skill、门禁、测试或 review checklist。
