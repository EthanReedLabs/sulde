---
task_id: orchestration-closeout-then-predictive-execution
revision: 1
issued_by: codex-coordinator
target_provider: claude
capability_tier: deep
status: issued-awaiting-executor-acceptance
issued_on: 2026-09-26
reviewed_head: 37f4a9424285741e4331326230bf40fb5aac4df6
observed_dev: 9936c7b9e987100ba53f0e3e6af459fd59767ece
source_intent_id: completion:658277a0f9d2c235958cad16
coordinator_document_revision: 18
---

# 顺序总纲：A 编排任务收尾 → B 预测式执行与持续纠偏

## 用户确认的目标

先完整结束上次编排迭代，再让 Sulde 具备修改前预测风险、执行中识别范围偏差、
及时调整方案和独立验证结果的能力。不得把 B 混入 A，以免旧任务再次无限延长。
本总纲及两个任务文件是可读任务工件，不是执行端权限回执。

## 本次签发事实

- 原 worktree：`/Users/eric/ClaudePlugin/sulde-pro/.worktrees/sulde-orchestration-iteration`。
- 原分支：`task/sulde-orchestration-iteration`；签发前工作树干净。
- 当前候选 HEAD：`37f4a94`；相对代码提交 `766650a` 只有三份文档差异。
- 当前 dev：`9936c7b`；`git rev-list --left-right --count dev...task/sulde-orchestration-iteration`
  为 `0 25`。这是签发时观察，不是将来执行时可跳过的检查。
- R3-followup 未通过协调者独立复核；重试身份修复已通过定向复核，fence 仍有三个阻塞项。
- 旧 Claude 循环已由执行者报告取消；本次没有启动新循环或证明原 Dev 已接收任务。
- 协调者本轮仅落盘三份任务文档，不实施代码修复、不提交、不合并、不推送、不安装。

## 严格顺序与负责人

| 阶段 | 执行者 | 输入 | 完成依据 | 下一步 |
| --- | --- | --- | --- | --- |
| A 开发返修 | 原 Claude Dev | `R3-CLOSEOUT-TASK.md` | 三个阻塞项的反例、修复、定向验证、候选报告 | 等待独立复核 |
| A 独立复核 | 协调者 | exact 候选和原始证据 | 逐项可复算结论；不得由执行者自批 accepted | 合入与发布前置检查 |
| A 集成发布 | 获授权发布执行者 | 已接受候选及届时最新 dev | 集成验证、隔离候选、正式安装、真实宿主及恢复验收 | 推送、资源清理、最终回读 |
| B 新任务 | 后续 Dev | `PREDICTIVE-EXECUTION-PLAN.md` | A 完整收尾凭据；从届时 dev 新建任务 worktree | B0–B5 |

A 代码 accepted 但生产验收未完成时，分别报告状态，不称 A 全部闭环，也不开始 B 功能实现。
因新权限或外部条件而等待时，说明具体条件，不用 B 的工作填充等待、不扩大 A 范围。

## 立即执行的任务

原 Dev 在原分支、原 worktree 完整阅读 `R3-CLOSEOUT-TASK.md`，核对当前 HEAD、脏文件和
并发占用，承接自己的会话任务，然后依次执行 A1–A4。三份本轮新增文档是协调者交付，
可在核对后纳入 A 的文档提交，不当作不明用户脏改动删除。

本轮新增返修范围以该文件为准；历史 PLAN、R1–R3 报告继续作为事实来源，不能覆盖、
改写或借最新任务暗中宣称原来未完成的能力已经交付。

## 发布与清理边界

- 未通过的候选不合入 dev；main 为发布专用，本任务不修改。
- 合并前复核目标 dev 是否前进、是否干净及是否存在其他执行者，不覆盖并发工作。
- 用户顺序确认不替代宿主要求的原生高风险确认或精确安装授权。
- 使用已有候选/正式安装与恢复流程；不手改已安装缓存、调度配置或权威账本。
- 推送前检查远端状态和明确目标；不强推。生产失败按已冻结恢复方案处置并保留证据。
- 清理只针对已合并、干净、无活跃任务且证据已结算的 A worktree/分支。
- A worktree 删除后，B 从 dev 中的同一相对文档路径读取方案，不能依赖已删除的绝对路径。

## 循环与续接规则

若执行者使用 Claude 的循环能力：每轮先回读当前任务状态和本任务测试进程；存在运行中
测试时继续收集同一运行，不启动重复套件。只有明确的未完成步骤才能推进。
候选待独立复核、需要新授权、外接盘不可用或实际终态时，保存 handoff 并取消本任务循环；
不得创建嵌套循环、无限重试、自动扫描新问题或把安静状态当作新工作。
纠偏/任务继承必须使用执行端自身身份；本文件不携带 grant、token、审批或效果债务。

## 总体交付标准

- A：旧故障真实解决，未扩大影响；代码、集成、安装和恢复分别有证据。
- B：Agent 在执行中提前发现风险、更新预测并调整动作；不是仅生成风险报告。
- 两批均报告事实、未验收边界、运行成本及下一位消费者，不用测试数量替代用户结果。
