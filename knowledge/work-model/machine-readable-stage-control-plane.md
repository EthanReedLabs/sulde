---
doc_id: work-model/machine-readable-stage-control-plane
container: work-model
platform: none
summary: 多阶段人工与自动流程必须由单入口原子刷新机器可读状态、blocker 和 handoff，不能让旧派生工件或上下文记忆决定下一步。
related: [ap-0220, work-model/evidence-gate-contract, work-model/content-addressed-device-fixture-lifecycle]
sedimentation_schema: 2
problem_type: workflow
evidence_status: verified
---

# 多阶段任务的机器可读控制边与原子刷新

## 问题原型

任务跨越采集、审核、汇总、导入、最终门禁和交接。各阶段都有脚本和 Markdown，但一键刷新复用旧
计划或默认目录，handoff 只给笼统 pending 数，恢复后仍要人工替换路径、猜设备和判断下一步。
局部步骤完成后，协调端容易凭最近上下文宣告整体完成。

## 根因与证据

根因是没有单一机器可读状态图，也没有让派生工件在同一轮按依赖顺序重建。已验证流程把 source
manifest、review root、设备扫描、aggregate、import status、final gate 和 handoff 绑定同一 refresh
run；每个阶段写状态、输入摘要、输出路径、blocker target 和 next action。约束测试能阻止顶层证据
字段和可执行命令回退。已排除“只写更详细的 handoff”——若源状态变化后不原子刷新，详细文本仍旧。

## 适用边界

- 适用于三阶段以上、包含人工/外部事实、可中断恢复的任务。
- 简单单命令、无派生状态的任务不需要完整控制边。
- 低层命令保留为诊断入口，但不得成为要求人工拼接路径的主流程。
- 外部事实不可得时保持 typed blocker，并把准确下一步暴露给人，不伪造完成。

## 判定样本

### 路由正例

- **输入**：refresh 后最终门禁仍引用旧 scan，handoff 只有“pending=12”，复跑命令含占位路径。
- **预期**：apply
- **原因**：派生工件、可行动状态和恢复入口未统一。
- **来源**：observed

### 路由反例

- **输入**：一个原子命令读取固定输入并立即产生唯一终态，无人工阶段或持久化派生工件。
- **预期**：skip
- **原因**：没有跨阶段恢复和状态协调需求。
- **来源**：constructed

### 执行合格例

- **做法或输出**：单入口显式接收所有输入根与设备身份；先重建源依赖，再依序刷新每个工件；阶段
  状态包含 runId、输入摘要、blocker targets 和 next action；handoff 顶层列拍摄/扫描时间/关键证据；
  最终 gate 与审计重新解析同轮状态，逐项清单零遗漏。
- **预期**：pass
- **原因**：恢复和完成判定来自同一状态图，而非上下文记忆。
- **来源**：observed

### 执行失败例

- **做法或输出**：refresh 只改 summary，不重建依赖计划；用默认 review 目录混入生产工件；报告称
  完成但没有逐项读取状态清单。
- **预期**：fail
- **原因**：旧状态和近因语境可覆盖真实流程。
- **来源**：observed

## 正确做法

1. 定义阶段 DAG 和统一状态 schema：`pending/running/blocked/passed/failed/skipped`，skip 必带原因。
2. 单入口显式接收 source/review/output/device 等完整上下文，禁止主路径占位符和隐式默认根。
3. 每轮生成新 runId，从源状态重建依赖计划；按 DAG 顺序原子替换全部派生工件。
4. blocker 从总数展开为目标清单、缺失证据、责任边界和可直接执行的 next action。
5. handoff 顶层投影当前清单、扫描时点、证据路径和稳定复跑命令；约束测试锁定字段。
6. 最终审计重新读取阶段原文逐项对表；局部 PASS 或最近一轮完成不能代替总体结论。

## 执行流程

`load explicit context → refresh sources → rebuild plan → scan/review → aggregate → import status →
final gate → handoff → independent checklist audit`。失败保留同轮诊断，下一次 refresh 不复用旧 PASS。

## 验收与失败处理

更换 source manifest、review root 或设备后，所有派生摘要必须随同变化。故意让中间阶段失败时，
handoff、final gate 和 next action 必须一致指向该 blocker，且旧产物不能继续提供 PASS。

## 消费与防复发

协调器、refresh 脚本、状态生成器、handoff、SessionStart 恢复和最终 gate 共同消费。回归覆盖旧计划、
默认目录污染、部分候选、skip reason、占位符、字段回退和阶段输出替换失败。
