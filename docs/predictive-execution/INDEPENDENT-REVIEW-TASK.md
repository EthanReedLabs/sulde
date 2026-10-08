---
assignee: existing-dev-session
branch: task/predictive-verification-recovery-20260928
capability_tier: deep
---

# 验证恢复与 B2 修复：非作者集中复核

## 唯一目标与身份

原 Dev 接手审查，不再实施 B1/B2（已经完成）。一次给出本分支能否进入合入准备的结论。
worktree：/Users/eric/ClaudePlugin/sulde-pro/.worktrees/predictive-verification-recovery-20260928。
冻结审查 HEAD：7ceb93c3f5a843c67f177d8ff2b2157632ba1008。
合入比较基线 dev：5a2d951a50cea246d52cbc827e0ef63c0053fd7e。
B2 修复：d1a72963773c30ba8d2b52c90907350dfc4d18ec；之前反例：7fb4c5367c3ff63922a56bcadbb0658e02116d64。
任务文件的后续 docs-only 提交不改变以上代码审查身份。
审查者需未编写这些协调端修复提交；原 Dev 曾写前期 WIP 不等于编写本次替换实现。
如参与过被审改动，明确非独立，不能伪称通过。本任务不要求换模型或新启会话。

## 最小阅读顺序与检查项

先读 B2-PRODUCTION-REPAIR-REPORT.md，再读 VERIFICATION-RECOVERY-REPORT.md、
docs/dispatch-continuous-execution.md；历史报告只在发现矛盾时回溯，不逐篇重读全部历史。

1. 对照 dev...冻结 HEAD 的实际 diff：仅一个生产模块、测试、报告及既有规则集成。
2. B2：producer 保留 exact 未恢复请求；新观察仍入 check；消费者不因换 run/新 ID 绕过恢复。
   检查直接恢复和“阻断运行后恢复”、不同任务、预测修订、损坏数据；不只读测试名称。
3. 注入：实际等待 provider/wrapper 退出，真实管道异常，原 run_task/monitor/callback 未替换。
   相同驱动旧版因目标行为失败、候选通过；正常控制有效，前置失败/未到达不算修复证明。
4. 回读消费事实、源/目标 request、实际 run、工件字节和独立 probe，不采信模拟报告自证。
5. 正常双版本驱动、连续派单五文件与历史更正是否符合冻结任务；不得把指令集成称已安装。
6. 评估有界串行修复的安全性及退化行为；并发协议/生产恢复入口等已披露未验收项单列。
   只有发现其直接推翻本次正确性或安全性，才能列本次阻断；不把整个项目旧待办扩成验收。

## 证据与测试预算

优先回读 Optimus，不因“独立”而重跑所有测试：
- tasks/predictive-execution/R3-normal-pair/20260928T111000-recovery/normal（205 项清单）；
- tasks/predictive-execution/injection-verification/20260928T120000-b2-repair（654 项清单）。
以上相对根为 /Volumes/Optimus/Sulde/；摘要与完整路径见报告。旧失败档案保留。
核验清单不含自身、源码/驱动摘要、两侧结果和一条关键状态链。
输入等价可复用 73 项回归。需要实跑时优先：
`PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest tests.test_r3_injection_baseline_r2 tests.test_prediction_feedback -q`。
仅对具体疑点补最小反例，输出进入临时目录；不得放宽产品/测试契约取得绿测。
不跑全量、不调用真实模型、不重建候选或重复归档同等证据。挂载缺失只记录证据不可用。
同一失败两次无新证据就换诊断；上下文续接从检查点继续，不以复述本任务代替审查结果。

## 交付与禁止事项

仅写本目录 INDEPENDENT-REVIEW-REPORT.md；可追加 STATUS 的明确复核引用，不改旧历史。
报告包含：reviewer 独立性、冻结 HEAD、检查/复用证据、必要实跑结果、发现（严重度、
file:line、反例、影响）、范围外待办及结论 review_passed 或 changes_requested。
一次集中列出与本次有关的全部阻断项；无问题也给出可核验审查依据，不只复述作者报告。
可在本任务分支提交审查文档；源码和测试只读，发现问题先报告，不混入“审查者自行修复”。
不合并 dev/main、不推送、不安装、不改 cachebuster、生产状态或其他 worktree。
review_passed 仅代表有界交付可进入合入准备，不等于全项目 accepted 或已生产安装。
