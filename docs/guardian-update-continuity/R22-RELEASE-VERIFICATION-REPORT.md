# r22 — 开发候选与冻结源码发布门通过

2026-10-07，原分支 `task/guardian-update-continuity`。
验收提交：`b3203536365e1ddaa69c5fc020a747d81b65a315`。
源码树：`a5dde0fd069a41a9fc6e8d6b473087536301a9b9`。
限定结论：L1 development-candidate verified；L2 POSIX frozen-source gate passed。
**不是 production install-ready；不允许将同版本不同内容覆盖现役。**

## 1. 本轮变化与范围

只修改本任务文档及 `record-layered-candidate.py`：显式绑定 reviewed HEAD、
检查 tracked clean、严格验证 Claude 精确 manifest、保存发布件文件摘要。
相对已复核 2108178，除本任务文档/runner 外无 tracked 差异；未改产品源码、
测试断言、插件版本或 installed cache。全量期间未修改 tracked 输入。

dev `3012363a50be1d73e8f7f6f415e650d4ae9f3b9c` 仍为验收树祖先；main
`f932ca8ca6b3ecdff01d03065981a4f7447e1fe7` 未变。收尾报告追加提交不是新的
全量运行身份，不把 b320353 凭据重写为后续 docs-only HEAD 凭据。

## 2. L1 — 当前开发候选

本地证据：`.codex-agent/layered-r22/20261007T120123.828916Z/`。
Codex 候选：`/private/tmp/sulde-s3c-r22-20261007T120123.828916Z/r22-posix`。

- 官方 prepare 2.597s、verify 23.081s，exit 0；receipt 自摘要经独立复算。
- receipt SHA：`023ce7286379627fd3471f9b96fa64628c019931499a806a2561fdfa7a4a5bd5`。
- runtime SHA：`c1856020660c0e4a4b2a9dcd09b2ea84c2cf217939b0e3efb3067a3e8f6aaaa3`。
- plugin tree SHA：`a8f31cdb2f4c6156f80a7f3632755e8aacc06510cf6f07b0f8fa0c87e8f335c0`。
- Codex CLI 0.160.0；Python 3.10.7 / PyYAML 6.0.3；未消费 promotion。
- 真实 CLI app-server/unified exec：正向执行、普通计划外写入执行、破坏性
  调用 PreToolUse 拒绝且 marker 不存在；外部模型请求 0。
- 该拒绝的 event `10a17c16b1ed5c0db927c8ce`，call `candidate_native_2`，
  session `01a1163d-9788-7350-972f-8f66310412ec`，proof
  `96da62851785f511e2053eadf8087a2840031370d8cc71fdd36a05ddde852755`。
- loaded module generation `df25fe7b0b7558218e27e9d8ceb76d0d2d59f0bebb0aae44da8f79c6ab4ff75e`；
  artifact generation 为候选版本加上述 runtime SHA。两种身份分别匹配，不互等。
- Claude 官方 stage 后由 CLI 2.1.282 对精确 `.claude-plugin/plugin.json`
  执行 `--strict --json`，success/strict 均 true；851 文件，identity 文件 SHA
  `6778a7832ac1d2ecff0e3f2f6e4e7cce59e54f94b0aa5e59afb749b64416412c`。

Codex runtime/plugin 摘要与 r20 相同是正确的：r21 变化在仓库 release 安装及
held-source 执行器，不在 Codex packaged runtime。Claude staged artifact 则
包含 r21 五个 release 文件和 kb_cli helper，逐文件摘要与冻结源码一致。
L3 仍须从最终冻结源生成实际维护 plan/bundle，不能拿 Claude 文件图谱代替。

替代边界：native_permission_ui exit 78/unobserved；scheduler_host exit
79/unobserved；scheduler 只跑隔离 dry-run；初始 hooks untrusted 与 doctor
degraded 保留在原始日志；测试合同走 agent-policy，不是真人生产审批。
四个明确生产文件（deployment、Codex config、Claude registry/marketplaces）
前后摘要一致，仅证明这四项未漂移，不外推全部 HOME 无写入。

## 3. L2 — 本轮全量

run `20261007T120209.624061-a56e2738bc1c`，正式本地记录在
`.codex-agent/s3c-maintenance-evidence/formal/` 的同名 JSON/log。

- 2990 总计 = **2961 passed + 29 skipped**，失败 0，exit 0。
- 运行 2620.149s；unittest 自身 2618.156s；input_drift=false。
- 日志 SHA：`62a0dd947c109266eae1d4317714f71c2a2018d263564553d5a9f43aa402b57a`。
- 源码字节码清理前后均为 0 文件/0 目录，不是靠清理污染才获得通过。
- 中途只轮询同一个 session 68114，未重启、未追加产品修复。

29 项跳过逐条回读：17 项已退休的 Git/Guardian 职责；5 项 Windows 专属；
3 项需显式启动的真实 CLI/audit；2 项外层 launcher 禁止嵌套 Seatbelt；
2 项需显式 benchmark baseline。它们不是测试通过，也不是隐藏失败；限定
当前 POSIX 源码门的证明范围，不能用于声称 Windows 或全部真实宿主已验收。
日志 `ERROR llm ... offline fixture` 是注入场景输出；最终 unittest 无 ERROR/FAIL。

同一独立复核线程已回读源码差异、candidate receipt、Claude 文件摘要、正式
全量及所有 skip 理由，确认 L1/L2 上述限定结论，无本轮已知阻断项。

## 4. 归档

最终：Optimus `Sulde/tasks/guardian-unified-plan-20261004/S3-C-repair/r22-layered-20261007T124624.139748Z/`。
25 文件逐项哈希回读一致；自排除清单 SHA：
`037d035ce8b43cac7d2ba3e5c4c86ced95f6df3673b5a3942d48d19bfc43690b`。
早期仅 L1 的 23 文件归档 `r22-layered-20261007T120525.337545Z` 保留，未覆盖。
没有复制凭据或整个生产 HOME；历史失败仍在 r20/r21 归档。

## 5. 剩余安装条件

1. 本候选仍是 Codex `0.2.5+codex.20261005134315-d918c7a2ed` 和 Claude
   `0.8.10`，与现役版本冲突，不得 promote。下一阶段须用正式入口冻结唯一
   版本并重建两个发布件，显式证明最终代码与本轮所测输入的差异和复用范围。
2. 最终版本树的门禁必须按差异判断；若仅版本/报告变化，提出可审核的有界
   复用与身份验证；若代码/依赖变化影响行为，不能静默复用本次全量。
3. 获明确权限后再合 dev；绑定精确旧/新代际、回退资产、宿主 cohort、时限、
   维护 worker 来源和真人原生决定后进入 L3。
4. Codex 正式迁移后真实调度/信任/Hook 正反与旧线程恢复；失败使用限定逆向
   而不是 committed recover-only 伪降级。Claude 使用独立官方安装/恢复流程。

本轮无生产安装、版本变更、宿主终止、合入、推送、正式知识库/记忆写入。
双宿主安装目标仍未完成，不将 L1/L2 通过冒称整体目标完成。
