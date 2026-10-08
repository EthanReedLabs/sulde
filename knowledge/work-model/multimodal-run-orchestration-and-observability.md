---
doc_id: work-model/multimodal-run-orchestration-and-observability
container: work-model
platform: cross
summary: 多模态任务必须以 run identity 串联输入、转写、媒体分析、缓存、后台生命周期和终态证据，并让慢支路不阻塞附件落库。
related: [tech-docs/异步分析不阻塞事实汇总, tech-docs/派生产物缓存双失效与负缓存, tech-docs/pose-first-open-set-motion-arbitration]
sedimentation_schema: 2
problem_type: workflow
evidence_status: verified
---

# 多模态 run 编排与端到端可观测性

## 问题原型

一次输入同时包含语音、图片或视频。附件需要立即出现在消息流中，媒体分析又需要语音转写作为关注
提示。若所有步骤串成一个阻塞调用，慢 ASR 会拖住落库；若媒体提前启动，用户意图会丢失。批量
评测还可能复用旧缓存、旧 Activity 或后台任务，最终日志无法归属到本次 fixture。

## 根因与证据

根因是没有稳定 run/job identity，也没有分开“附件已接受”“依赖已就绪”“分析完成”和“用户终态”。
已验证链路表明：附件可先持久化并展示，语音转写在独立状态机推进；真正需要 transcript 的媒体
分析等待该依赖，而不需要它的预处理可并行。ASR 输入输出、prompt、采样帧、native 推理、parser、
融合结果统一绑定 runId 后，缓存污染和完成信号误配可被定位。已排除“只增加一条成功日志”——
它只能证明某层没崩，不能证明输入、模型和最终结果属于同一运行。

## 适用边界

- 适用于语音与媒体联合输入、端侧多模态推理和批量设备 fixture。
- 纯文本或单一同步媒体操作可简化，但仍需唯一请求身份。
- 附件展示不应等待 ASR；依赖 transcript 的推理不得在 transcript 终态前启动。
- 产品缓存可用于普通用户路径；严格评测必须显式绕过或绑定实现版本与 fixture digest。

## 判定样本

### 路由正例

- **输入**：界面显示语音和视频，但分析 prompt 没有 transcript，完成日志又可能来自上一次样本。
- **预期**：apply
- **原因**：多支路依赖与运行身份没有统一编排。
- **来源**：observed

### 路由反例

- **输入**：一个纯本地同步函数接收单张图片并在调用栈内返回结果。
- **预期**：skip
- **原因**：没有跨阶段异步依赖或后台生命周期。
- **来源**：constructed

### 执行合格例

- **做法或输出**：附件立即落库；ASR、预处理和分析阶段共享不可变 runId；媒体推理只等待声明的
  transcript 依赖；批量 fixture 隔离 Activity/Worker/私有存储并绕过缓存；终态同时匹配 fixtureId
  与 runId，日志可从输入追到最终融合结果。
- **预期**：pass
- **原因**：用户响应、依赖正确性和证据归属同时闭合。
- **来源**：observed

### 执行失败例

- **做法或输出**：用样本名匹配“完成”，复用旧 narrative 缓存，或让旧 Activity 接收新 intent 后
  继续沿用旧 Worker。
- **预期**：fail
- **原因**：历史结果可冒充当前运行，且生命周期没有隔离。
- **来源**：observed

## 正确做法

1. 创建 runId，绑定输入摘要、fixtureId、实现版本、缓存策略和用户会话。
2. 附件先持久化/展示；ASR 与无依赖预处理并行，声明依赖 transcript 的阶段等待其明确终态。
3. 每阶段记录输入/输出摘要、开始结束时点、状态和父 runId；原始媒体只记录受控引用。
4. 批量评测显式绕过产品缓存，为每个 fixture 重建 Activity/Worker 生命周期并使用应用私有路径。
5. 完成信号同时匹配 fixtureId、runId 和阶段图；最终用户 outcome 与底层 telemetry 分开保存。

## 执行流程

`accept media → persist/display → ASR + preprocessing → dependency join → inference → parse → fuse →
user outcome → terminal receipt`。取消只传播到仍运行的后代，不回滚已经持久化的用户附件。

## 验收与失败处理

严格验收随机化 runId、复用 fixture 名、保留旧缓存和旧 Worker，当前运行仍必须只消费自己产生的
事件。ASR 失败时给出明确降级；媒体分析失败不删除已展示附件。

## 消费与防复发

消息状态机、WorkManager/后台任务、缓存层、设备批跑器、日志 schema 和最终门禁共同消费。回归覆盖
ASR 慢/失败、缓存旧值、Activity 复用、存储拒绝、完成信号重放与并行 fixture。
