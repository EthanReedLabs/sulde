# Sulde 生命体 P0/P1 修复总纲

状态：FROZEN

基线：`dev@1d37c177a227ab28102173c5fe89a3e3a466f2c9`

## 目标

让生命体从“能够发现并起草问题”推进到可观测、可恢复、可结算的运行闭环。修复按依赖串行推进；每条任务使用独立 worktree 和 Codex `agent-runtime.py`，只在任务范围测试及证据通过后合入 `dev`。

## 共同边界

- `main` 仅用于发布回滚，不直接修改。
- 保留 `feat/sediment-harmony-navigation-state` 的所有未提交内容；其中 `ap-0249` 编号冲突不进入本批。
- 不删除或改写权威 intent/effect/approval/execution 日志，不把 `unknown` 改写为成功。
- 不通过修改阈值、灯色、清空队列或隐藏错误制造 ready。
- 不依赖 Claude Code CLI、Claude MCP、Claude Skill 或 Claude 用户目录作为运行前置条件。
- 所有机械操作由 Agent 执行；控制面、安全规则、外部写入、破坏性操作、秘密外发和不可逆知识语义决策保留人类确认。
- 失败后才运行重诊断；正常成功路径不得新增全量扫描。小改跑定向测试，中等改按影响面测试，跨主链重构才跑全量测试；测试证据绑定 source/runtime 版本并按 TTL 清理可重建明细。

## LIFE-P0 — 运行主链与恢复

范围：`mem-sync`、调度 readiness、安装迁移、`agent-runtime provision`。

必须完成：

1. `mem-sync` 仓库迁移到 Sulde 自有数据根；先复制、哈希和 Git 真值校验，旧目录本批不删除。
2. 导入、导出和远端集成共享跨进程互斥与事务边界。不得依赖 `git pull --rebase --autostash` 吞并发；明确区分 fetch、集成、生成、commit/push 和恢复状态。
3. 覆盖远端前进、本地待提交生成物、并发 import/export、中断恢复、冲突 fail-closed 和幂等重试。
4. 修复 `agent-runtime provision` 对 primary/main 工作树清洁度的错误依赖：只验证精确 `dev` 基线、目标 branch/worktree 不存在及共享 common-dir；不得读取、暂存或改变 main 用户修改。
5. Scheduler 对失败 actor 提供有界机械重试和真实成功回读；不能手改 last-exit 或状态文件。真实 canary 后必须 16/16 ready。
6. 当前 production generation 保持可回滚；候选失败不替换 production。

停止线：若需要删除旧同步仓库、丢弃本地数据、改写远端历史或无法证明两份同步数据等价，停止并请求精确人工决策。

## LIFE-P1A — 事件、队列与闭环状态

依赖：LIFE-P0 合入并通过。

必须完成：

1. 新产生的 self-repair/evolution 发现立即进入统一事件观察流；事件必须携带 source/version/run/fingerprint/status/evidence 摘要。
2. 历史 invalid/unsupported 行保留原文摘要，通过兼容投影或 supersede 记录结算；不删除审计事实。
3. self-repair 队列以稳定指纹去重，区分 `pending/inconclusive/verified/unresolved/superseded/expired/draft_error`；为重试、TTL、默认动作和次数上限建模。
4. `draft_error` 只在运行环境或 generator version 改变后有界重试；相同确定性失败不得无限重跑。
5. `closed_loop` 分开表达能力可用、当期已运行、证据已验证和被合同阻断；顶层 ready 不得掩盖 `sense/persist/decide/act/verify=false`。
6. 普通低风险、可逆、精确限定且有独立 verifier 的机械动作由 Agent 完成；高风险边界继续使用原生 Allow/Deny。

停止线：不得为了让状态变绿而伪造事件、补写不存在的执行证据、自动裁决外部效果或删除 pending 事实。

## LIFE-P1B — 图谱与治理质量

依赖：LIFE-P1A 合入并通过。

必须完成：

1. graph-audit 不得把目标态、规划态、`PLANNED/NOT_READY` 或反事实描述提升为已实现事实；覆盖 edge 1306 正反例。
2. 对 edge 407 先核验来源全文；只有证明通用抽取根因后才改代码，否则输出单条 supersede 提案。
3. 治理报告输出机器可读的桶定义、纳入/排除规则、重叠、未归桶和全集对账，不改变既有阈值及灯色。
4. Golden candidate 按生成、待审、返修、可入库、终态分阶段计数；不得用文件总行数冒充 pending。
5. L2 coverage 输出绝对分子、分母、窗口、数据源、基线和 discontinuity；证据不足保持 inconclusive。
6. 五组知识去重先全文对照和引用核验。实际合并或删除知识正文属于不可逆语义决策，逐组使用人类确认，不批量推定。

停止线：任何知识正文删除/合并、阈值实改、批量图谱重写或外部发布必须停在可审阅 diff/提案前。

## 集成与交付顺序

`LIFE-P0 → candidate/live canary → merge dev → LIFE-P1A → merge dev → LIFE-P1B → merge dev → release-level verification → push origin/dev`

任务内只运行影响范围测试；最终跨主链集成才运行一次全量测试。每轮记录 exact HEAD、命令、退出码、耗时、通过/跳过/失败数和证据 TTL。失败任务不合并，新的相邻问题进入后继任务，不扩张当前验收。

## 完成定义

- `mem-sync-import` 真实执行成功且 Scheduler 16/16 ready。
- Sulde 自有目录是唯一活动同步数据根，旧 Claude 路径仅作为已校验、待过期清理的保留副本。
- 最近生成的 self-repair 问题在统一事件流可回读，队列无无期限 pending/draft_error。
- 生命体状态能够解释每个 false/blocked，而不是同时宣称完整闭环 ready。
- 目标态误抽取回归通过；治理指标可复算；知识语义动作均有独立确认和回读。
- `dev == origin/dev`、任务 worktree/branch 已清理、`main` 和用户工作不变。
