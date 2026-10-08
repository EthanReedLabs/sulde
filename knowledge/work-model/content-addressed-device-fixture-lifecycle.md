---
doc_id: work-model/content-addressed-device-fixture-lifecycle
container: work-model
platform: cross
summary: 真实设备评测素材必须从扫描、去重、人工审核、接受、归档到导入全程绑定内容哈希，并把短缺、拒绝、跳过与失败保留为机器可读状态。
related: [tech-docs/端侧大模型文件必须做内容哈希校验, work-model/evidence-gate-contract, work-model/machine-readable-stage-control-plane]
sedimentation_schema: 2
problem_type: workflow
evidence_status: verified
---

# 内容寻址的设备素材 fixture 生命周期

## 问题原型

严格设备评测需要若干真实素材。流程只记录路径和候选数量，导致同一路径被替换、已拒绝素材重复拉取、
语义不匹配视频被拿来填数，或旧扫描摘要在采集失败后继续显示“已有候选”。候选尚未接受，交接却提前
展示带占位路径的导入命令。

## 根因与证据

根因是把设备路径、人工决定、内容身份和完成数量拆成松散文本。已验证链路中，设备端先按 SHA-256
排除已知内容，再只拉取未知素材；审核、接受、归档、导入和 readiness 使用同一 digest。0/目标数、
部分候选、拒绝、扫描失败和跳过原因都有结构化终态，旧摘要在新扫描前失效。已排除“复制一个素材
凑齐覆盖”——它只增加数量，不增加语义覆盖和独立证据。

## 适用边界

- 适用于来自真机、相机、外部媒体库的评测 fixture，尤其有最小数量和人工审核要求时。
- 仓内人工构造的纯文本 fixture 可直接内容寻址，不需要设备扫描阶段。
- 自动建议只能排序/标注，接受与拒绝仍由声明的审核权威决定。
- 无真实素材时状态是 `blocked_external_fixture`，不能误报实现回归或复制样本。

## 判定样本

### 路由正例

- **输入**：需要三个新视频，当前只有一个可审核候选；旧扫描仍显示三个路径，导入命令含占位符。
- **预期**：apply
- **原因**：存在内容身份、数量门禁、人工审核和陈旧状态四类风险。
- **来源**：observed

### 路由反例

- **输入**：固定仓内 JSON fixture 已由 commit tree 和 SHA-256 绑定，不来自外部设备。
- **预期**：skip
- **原因**：无需设备扫描、媒体归档或人工素材审核。
- **来源**：constructed

### 执行合格例

- **做法或输出**：扫描命令显式设备序列号；设备端先按 digest 去重；扫描失败清空本轮摘要但保存
  诊断；已有候选先审核并显示短缺量；接受/拒绝均落盘；归档工具重命名并刷新媒体库；达到最小
  eligible 数后才生成真实 dry-run/commit 导入命令，所有阶段 digest 一致。
- **预期**：pass
- **原因**：内容、决定、数量和下一步动作可重放且无占位符。
- **来源**：observed

### 执行失败例

- **做法或输出**：只按文件名去重，多个候选静默取第一个；扫描错误复用旧 summary；1/3 时不给补采
  动作；用重复或语义不匹配视频填满三项。
- **预期**：fail
- **原因**：数量看似达标，但内容身份、覆盖和审核均不可证明。
- **来源**：observed

## 正确做法

1. 为目标 manifest 定义语义类别、最小 eligible 数量、排除 digest 和人工审核字段。
2. 每轮扫描前使旧 summary 失效；命令显式绑定设备 serial，跳过也写 typed reason。
3. 在设备端计算内容哈希并排除已知/拒绝项，只传输未知内容；保留扫描时间和诊断摘要。
4. 部分候选立即进入审核，同时披露 `total_pending / actionable_pending / unassigned_noise / shortfall`。
5. 接受、拒绝和例外均结构化保存；自动建议不得替代决定，多个候选不得静默选首项。
6. 归档工具统一目录、重命名、媒体库刷新和 digest 回读；导入前再验证详情完整、唯一与哈希稳定。
7. 未达到最小数量时非零退出但保留摘要与下一步；只有 accepted 候选才生成无占位符的导入主路径。

## 执行流程

`invalidate old scan → scan(serial) → device-side dedupe → pull unknown → archive → review →
accept/reject → minimum-count gate → dry-run → import → readiness`。

## 验收与失败处理

0/N、1/N、N-1/N 都必须失败且给出补采动作；扫描失败与“没有新素材”分开。路径替换、重复 digest、
拒绝项重现、多个 accepted 冲突和归档后 digest 漂移均 fail closed。

## 消费与防复发

设备扫描器、归档工具、review UI/CLI、导入器、refresh、handoff 和最终门禁共同消费。fixture 覆盖
全部短缺边界、失败后旧摘要、显式 serial、拒绝持久化、唯一性与内容替换。
