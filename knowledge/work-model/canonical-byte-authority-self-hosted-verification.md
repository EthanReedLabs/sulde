---
doc_id: work-model/canonical-byte-authority-self-hosted-verification
container: work-model
platform: none
summary: 报告与回执共享版本化字节权威；热更新验证需使用候选绑定的新进程，并把实际事件的模块代际与发布件代际沿真实宿主链核对。
related: [ap-0181, ap-0250, work-model/evidence-gate-contract, work-model/idempotent-registration-verifier-contract]
sedimentation_schema: 2
problem_type: workflow
evidence_status: verified
---

# 规范化字节权威与自托管验证

## 问题原型

同一报告在文件、终端和原生 receipt 中语义一致，却因尾换行、编码或序列化顺序不同产生不同摘要；
修复规范化函数后，已启动父进程继续加载旧模块，测试却用新源码生成期望，形成“代码已修但真实回执
仍旧”的代际分裂。

## 根因与证据

根因一是多个消费者各自规范化文本，根因二是让加载旧代码的进程验证自己的热更新。已验证方案让
报告、最终回复和 receipt 都消费同一 canonical bytes；即使只差尾换行也拒绝身份等价。修改负责
规范化的运行时后，由新启动且绑定候选摘要的自托管子进程产生和验证回执，父进程只读结果。已排除
“语义相同就接受”——权限和发布身份需要确定性字节，而非自然语言近似。

发布验收还观察到另一层证据需求：prepare/finalize 的环境一致，并不能证明中间的
真实动作由同一代码处理。已取得的真实宿主正反证据同时核对事件的
`loaded_module_generation` 和 `artifact_generation`，证明实际加载模块与候选发布件
身份都在链内；不能由外层进程手工补字段来代替事件来源。

## 适用边界

- 适用于摘要绑定的报告、授权卡、receipt、manifest 和任务权威。
- 普通用户自由文本比较可使用语义或展示层归一化，但不能承担权限身份。
- 已启动进程是否支持热重载必须由宿主事实证明；未知时按旧代码处理并新启 verifier。
- canonical 规则升级必须版本化，旧记录按原版本重放，不能静默重算。
- 双代际绑定用于发布身份验证，不意味着每次普通只读查询都需要运行完整深度扫描。

## 判定样本

### 路由正例

- **输入**：文件报告与原生回执只差末尾换行却摘要不一致；父进程刚修改规范化模块后立即自验。
- **预期**：apply
- **原因**：存在字节权威分叉或运行时代际自证。
- **来源**：observed

补充样本：

- **输入**：候选热更新的 prepare/finalize 都匹配，但真实 PreToolUse 拒绝缺少模块代际或发布件代际，无法证明中间执行来自本候选。
- **预期**：apply
- **原因**：两端身份一致不足以覆盖实际动作的处理进程。
- **来源**：constructed

### 路由反例

- **输入**：搜索系统比较两段普通说明文字是否主题相近，不产生权限或发布身份。
- **预期**：skip
- **原因**：语义检索不需要逐字节权威。
- **来源**：constructed

### 执行合格例

- **做法或输出**：唯一 canonicalizer 输出版本化 bytes；文件、receipt 和最终回复从同一 bytes 派生；
  尾换行篡改被拒绝；新启动、自托管且绑定候选代码摘要的进程完成 round-trip 验证。
- **预期**：pass
- **原因**：身份与验证运行时都可确定性证明。
- **来源**：observed

补充样本：

- **做法或输出**：全新进程实际加载候选 artifact，经真实 CLI、unified exec 和 Hook 完成业务正例，同时正确阻止越界动作。真实事件的 loaded_module_generation 与 artifact_generation 均匹配冻结代际，越界 marker 未产生；合法执行和安全阻止两项验收都通过。
- **预期**：pass
- **原因**：业务执行成功与越界动作被阻止共同构成合格结果；这里的拒绝是预期的安全结果，不是发布验证失败。中间事件、两种身份与真实目标状态均已核验。
- **来源**：observed

### 执行失败例

- **做法或输出**：各消费者自行 `strip()`/JSON dump；或父进程 import 缓存未刷新却宣称新代码已验收。
- **预期**：fail
- **原因**：规范化不唯一，验证者也未加载候选实现。
- **来源**：observed

补充样本：

- **做法或输出**：手工调用事件归一化函数并构造 proof，或只核对 prepare/finalize 的环境就宣称真实 Pre 拒绝属于新发布件。
- **预期**：fail
- **原因**：没有经过实际宿主调用与加载候选的新进程，事件身份和执行前拦截均不可证明。
- **来源**：constructed

## 正确做法

1. 定义并版本化 canonical byte schema：编码、字段顺序、换行、终止字节和大小界限。
2. 生成一次 canonical bytes，报告文件、UI 文本和 receipt 仅从它派生并记录同一 digest。
3. 所有读回先按记录的 schema 精确解析；语义等价、额外字段或尾字节漂移均拒绝。
4. 修改 canonicalizer/runtime 后启动绑定候选 tree digest 的新进程做 round-trip；旧父进程不得自证热加载。
5. 验证结果记录 verifier runtime digest、输入 digest、输出 digest 和进程代际。
6. 发布链的实际物质事件携带并匹配 loaded-module 与 artifact 两种代际，同时核对
   provider/session、请求及目标。实际拒绝必须在动作执行前发生；Post 诊断不能替代。

## 执行流程

`freeze schema/version → render canonical bytes → persist/project → exact readback → spawn candidate-bound
verifier → compare digests → terminal receipt`。

## 验收与失败处理

覆盖尾换行、编码、字段顺序、额外字段、旧 schema、父进程缓存和 verifier 替换。任何字节或运行时
摘要漂移保持 blocked，并保留可读差异。

## 消费与防复发

报告器、原生 broker、HumanGrant、manifest、发布门禁和自托管 runner 共同消费。回归必须同时在
PTY/non-PTY、新旧进程和 fresh clone 运行，不能只做同进程函数单测。
双代际回归覆盖模块旧/发布件新、模块新/发布件错配、缺字段和真实目标是否产生；
报告区分直接函数测试、隔离真实宿主以及当前生产会话观察，不把夹具的人工决定写成真人点击。
