# LIFE R1 与任务正文派单：集成阶段验收

## 结论

本阶段的源码集成、定向回归和隔离候选验证通过。尚未合入 dev、推送或正式安装；
不能宣称生产 Hook 故障、全部生命体能力或跨平台验收已经闭环。

任务分支为 `task/life-r1-dispatch-integration`。合并提交 `492cf12` 保留 LIFE R1
`c0fa7a0` 与任务正文派单 `3a3b29d` 的祖先关系。新增修复与验证工件提交
`76d234cba4bc465d43bd189f55a93eaa380c2dfa`。之后只补本报告和验收摘要。

## 完成项与结果

| 项目 | 结果 |
|---|---|
| 独立集成 | 从 dev `f687193` 创建任务工作树；两批提交无冲突合并，dev/main 及原任务分支未修改 |
| 派单默认行为 | 文本只含任务文件；JSON 的 actions/notices 为空、model_advice=false；未输出模型切换前缀 |
| 插件结构 | plugin-creator 官方校验器通过；未更新生产 cachebuster 或 marketplace |
| 环境身份修复 | 跨 venv 比较允许 PyYAML 相同字节位于不同目录；精确回执路径绑定保持不变 |
| 最小回归 | 修复前 8 项中正例失败；修复后 8 项全部通过，含实际复制包、六类内容漂移反例和精确回执路径反例 |
| 组合回归 | 148 项通过、0 跳过，284.209 秒；完整原始日志与首次失败记录均已提交 |
| 真实 CLI PostToolUse | 4 次工具执行、12 条故障事实；新会话、续接、worktree 和不同会话隔离场景通过，无人工 ingest |
| 单次隔离候选 | prepare 1.791 秒、verify 23.277 秒；状态/回执均 verified、摘要配对，promotion_consumed=false |
| 隔离边界 | 使用仓库 OS 写入禁令及独立宿主/数据根；生产写入尝试记录为空；不运行正式安装和生产调度加载 |

首次组合测试运行 145 项，产生 49 个失败条目及 1 个错误（含 subtest 条目，不能用简单相减推算通过用例数）。
它们指向同一个环境等价比较阻断，而非 50 个独立产品缺陷。两端 Python 二进制相同，PyYAML
同为 6.0.3 且内容摘要相同；差异仅在包目录。修复未切换解释器、安装全局依赖或放松内容漂移门禁。
根因和正反样本见 [沉淀候选](CANDIDATES.md)，未直接写入共享知识库。

## 测试与源码绑定

- 当前通过记录：`20260907T160601.793744-5cefc7086d64`。
- 原始日志 SHA-256：`4154580c533ee5ec7adae2860834f3f03809cb9083d2ebf1c98f2a48e39a8092`。
- 测试时 HEAD 为 `492cf12`，环境修复尚未提交；执行输入摘要为
  `5dcf907860e4546b487ed0e372337ea53357ae6e0a1a6e13259294324067e8a1`。
- 修复提交 `76d234c` 后重新计算源码摘要，逐字一致。候选绑定这个已提交且干净的源码。
- R1 原 1,905 项全量通过只作为未受影响部分的基线；没有将其改标成新 HEAD 的全量通过。
- 这次 8 行产品修复仅影响两个发布消费者的环境等价判断，已覆盖两者完整定向测试。
  没有修改 Guardian 权限、决策核或 Hook 执行语义，因此未重复全库测试。
- 测试记录保留 30 天有效期元数据；本轮不执行历史数据清理。报告更改不使源码证据失效。

## 候选边界

候选 ID：`integration-76d234cba4bc-20260908T015158Z`。
runtime tree：`d14ddc7c78616365f2442173d8cc8541df75fa150f63637daecc99eed49cb986`。
摘要及回执摘录见 [evidence.json](evidence.json)，实际候选保存在本任务 `.sulde/data/life-r1-candidates/`。

候选验证覆盖 artifact、独立 Codex registry/cache、Hook 入口、MCP initialize、doctor 和
16 个 scheduler label 的 dry-run。新进程 PreToolUse 协议拒绝及其 loaded_module_generation /
artifact_generation 匹配，测试 marker 不存在。

必须区分：现有候选 PreToolUse 验证是直接调用候选 CLI/Hook 协议，并非 Codex 宿主真实
发起工具后的否决。真实宿主自动链证据本轮覆盖的是 PostToolUse，不能合并成 PreToolUse 生产证明。
正式生产切换前仍须补齐真实宿主拒绝验收；若需要证明候选安装就能阻止宿主动作，应先补该隔离宿主 canary。

本候选使用隔离宿主的 prestate，版本字段沿用源码版本且没有生产 cachebuster；它是测试候选，
不是当前 production 的可直接 promote 回执。单样本耗时不能替代 R1 性能分布或推断正式安装时间。

## 保留项与下一道门

- Desktop、原生 Windows、未包装第三方 Hook、历史业务 exit-1 归因继续独立跟踪。
- 报告写入误判 destructive 及暂停 lane 的旧问题未在本轮修改或宣称解决。
- 当前全局 AGENTS 的任务正文规则未改；main 三项既有 `.ua` 修改保留。
- dev 仍为 `f687193`，main 仍为 `bd216b3`；两条原任务分支和工作树保留。
- 没有生产安装、远端发布、设备操作或共享业务账本迁移；正常宿主审计不在字节不变承诺内。

下一阶段必须明确授权 dev 集成和发布边界，固定精确发布源码后，使用正式的 cachebuster / 候选与
原生确认安装流程。新发布件只对变更影响和真实宿主边界追加证据，不因本报告或旧失败日志再跑全量。
生产 scheduler、原生安装决策、真实 Hook 和实际业务验收分别回读，不能以候选 verified 代替。
