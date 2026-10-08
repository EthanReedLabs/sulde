# R1-REPORT — Sulde 执行与编排迭代 R1 集中返修

- 任务：`sulde-orchestration-iteration-r1` rev 1（R1-TASK.md，协调者签发）
- 被审查 HEAD：`6ee549a842803ed7aa1f8fbcf8b1fbe48442c27e`；基线 dev：`9936c7b`
- R1 候选提交：`f6e495d`（R1-01/02）→ `72ed54a`（R1-03/04/05）→ `20d9fc7`（R1-06）+ 本文档提交
- 状态：**R1 候选待独立复核**（执行者不自行标记 accepted）

## 0. 审查更正声明

原 REPORT.md（`6ee549a`）中"C1–C5 全部完成"的表述**不成立**：独立审查的六项反例
（真实输入、重复提交、并发交错）证明多项能力仅有合成通过而无真实契约覆盖。原报告与
原失败事实保留不改写；本文件为审查更正与返修记录。原证据索引曾包含清单自身条目——
本轮起清单摘要只放本外层报告（§6），索引文件不含自身。

## 1. 逐项返修

### R1-01 旧代际回收安全性 ✅

- **问题**：规划器读 `retired_tree_sha256` 并回退目录名 20 位摘要，而生产记录字段是
  `tree_sha256`；活跃完整代际因此永不匹配，计划仍返回 reclaimable=true；apply 不复核。
- **根因**：字段名凭推测；未确认 retired-tree 摘要与 delivered runtime-tree 摘要**本就不同**
  （retirement 规范化去 bytecode），任何"精确匹配同代际才保留"的完整匹配都不可靠。
- **变更**：身份只取真实生产者字段（`version`+`tree_sha256`），删去短摘要回退；"无引用"
  必须被**证明**——每个活跃租约代际可解析且 version、tree 两分量都不同；未知/损坏身份
  一律保留。apply 在租约目录 guard 锁内全量复核（记录字节绑定=计划新鲜度、保留窗口、
  引用、路径包含），消除检查-删除竞争。
- **回归**：`test_orchestration_r1.ReclaimIdentitySafetyTests` 6 例（真实形态、未知租约代际、
  同版本阻塞、计划过期记录漂移、计划后新增引用、路径替换、部分失败）+ phase3 既有 14 例。

### R1-02 租约并发竞争 ✅

- **问题**：租约文件先创建后加锁，窗口内被扫描者当陈旧租约删除；第二个执行突破
  max_concurrent=1。
- **根因**：创建/加锁/计数/修剪未在同一互斥域内；投影接口暗中执行清理。
- **变更**：`.guard.lock` 互斥域覆盖全部租约变更（含 release）；`active_run_leases` 只读化
  （陈旧租约保留，对代际安全是保守方向）；额度与投影范围显式标注为单租约目录。
- **回归**：`LeaseAtomicityTests` 3 例——真多进程：持锁者存活期间并发获取被限且租约不被
  误删；SIGKILL 崩溃持有者被下次获取正确回收、新持有者代际被正确投影；只读投影零突变。

### R1-03 报告契约启动前验证 ✅

- **问题**：预检只查 `.codex-agent/<slug>.last.md`，而正式收尾要求 owned_paths 恰有一个
  受支持 durable report——`task must own exactly one supported program durable report`
  仍可在模型执行后出现（g12 形态的残留）。
- **根因**：两处独立解析；预检与收尾不共享契约。
- **变更**：生产 codex 运行在 provider 交互前执行与收尾**同一**解析
  （`_durable_worker_report_relative_path`），结果写入启动描述
  （`durable_report_relative_path`）并在收尾交叉核对（漂移即错）。探针改 O_EXCL|O_NOFOLLOW。
- **回归（真实生产 CLI 入口，非合成）**：`DurableReportPreflightTests` 4 例——root
  `REPORT.md`、缺失、双报告均在 0 次模型调用前拒绝（无 run ledger 产生）；合法单报告
  通过预检并推进到后续生产门（installed-generation 检查）。

### R1-04 请求幂等语义 ✅

- **问题**：相同 request_id+内容在 closed 后重交返回 created=true 并重执行；原测试错误地
  要求重新执行。
- **根因**：注册表把"closed"当"可重来"，没有"完成使幂等固化"的概念，也没有显式的重试
  尝试身份。
- **变更**：attempt 链模型（v2 schema）：同一请求的完成尝试是最终答案——重复提交（无论
  先后）返回原尝试/结果；重试必须走 `open_retry`（新 attempt 号+retries_of 关联，仅限
  可重试 stop reason；awaiting_human 是人工门，**绝不自动重试**）；同 ID 异内容/异 slug
  永远冲突。三个崩溃窗口（opened 未 launched、launched 未写、closed 未写）经运行账本
  对账；活跃重复给出准确已有执行状态；N 次提交有效启动 ≤1（含完成后重复）。
- **回归**：`RequestIdempotencyWindowsTests`（真实 CLI 注入注册表行丢失）2 例 +
  phase1 重写后的 8 例注册表/CLI 测试 + phase1 embed 测试改为断言"完成后重复返回原结果、
  零新增轮次"。

### R1-05 真实用量协议、增量读取与累计 ✅

- **问题**：真实样本 `turn.completed.usage`（input=516328/cached=462720/output=8651）
  解析为 unknown/null；同 run 增量 100+20 聚合为 20；实现全量 read_bytes 且调用方无游标。
- **根因**：解析器未覆盖真实宿主事件形状；增量扫描无状态合并；累计/增量语义未区分。
- **变更**：支持 `turn.completed`（线程累计）等真实形状；累计事实单调推进（迟到的旧报告
  记 out_of_order_ignored，绝不覆盖新值），分片独立累计，累计后追加的分片降级为
  lower_bound（basis=cumulative-plus-fragments，不混冒完整）；缓存计数独立成度量、绝不
  重复加进 input。游标（offset+prefix 摘要+inode+报告）原子持久化；每扫描流式重哈希前缀
  （完整性为 O(n) 哈希，不虚称只读尾部）；轮转（inode 变化）开新流代并保留旧流总量；
  截断/重写 fail closed；无新数据原值返回。接线运行入口（settle/超时/失败/崩溃恢复四路径）。
- **回归**：真实样本只读解析测试（挂载时）+ phase2 新增 5 例（真实形状、100+20=120、
  乱序忽略、轮转保留、原子游标）+ 既有 15 例。

### R1-06 候选升级保护接线与端到端证据 ✅（部分项未验收，见 §3）

- **问题**：generation guard 无安装调用方；记录租约≠安装过程在用。
- **变更**：①安装事务描述新增 `generation_switch` 投影：显式 opt-in 范围
  （SULDE_ACTIVE_LEASES_DIRS），默认 observe 记录进事务证据，block 策略可 FAIL 安装；
  不把"存在不同代际"当全局禁令、不终止任何会话。②候选 verify 新增真实入口演练：真候选
  运行时 `agent-runtime.py` 真实持有租约期间，候选自身 guard 必须识别候选代际、拒绝异代际
  切换、保持同身份退役树不可回收；运行退出后两段式 apply 回收隔离夹具（真实代码路径，
  零外部模型调用，删除只发生在隔离 scratch）。
- **回归**：`InstallerGenerationSwitchTests`（observe/block/缺范围）+ 候选 verify 全链
  （含新演练步骤）。

## 2. 测试与性能

- 新增/修正：R1 套件 19 例；phase1 修正+新增；phase2 新增 5 例。四套件合计 83 例全绿。
- 受影响链回归：execution_backend / runtime_provider / candidate / install journal 全绿。
- **最终完整官方回归：2536 例（2453 基线 + 83 新增），失败恰为 §3 所列 3 项基线既有
  失败，无任何新增失败**（`R1/r1-final-full-suite.txt`）。
- 过程披露：第一次全量回归曾出现 47 失败——根因是执行者用 `py_compile` 在运行时树
  留下 `__pycache__`（字节码洁净扫描正确地拒绝）加上本轮测试文件 6 处 encoding 守卫
  违规；两者均已清除/修复。该中间失败清单保留于
  `R1/r1-intermediate-regression-bytecode-pollution.txt`，不删除历史失败事实。
- 过程披露：`_generation_switch_projection` 曾嵌入密封事务描述符，导致 journal 的
  frozen 字段集校验失败；更正为放入安装结果负载（未密封证据），密封 journal 契约
  零改动。
- **正常执行性能（配对 A/B，交叠采样抵消机器状态漂移）**：base `2365dcf` 中位 0.767s vs
  R1 候选中位 0.770s，**Δ=+4ms**（7+7 原始样本存 `R1/paired-ab-perf.txt`）。更正：早前
  "0.66→0.77 (+110ms)"为跨时段机器漂移的未配对比较，作废并记录为
  inconclusive-then-resolved；结论以配对为准。
- 恢复路径（超时/崩溃）不另设预算，遵守方案"深度扫描不逐动作重复"。

## 3. 未验收与披露

| 项 | 状态 |
| --- | --- |
| 真实生产宿主上运行中切换（live codex session 跨升级） | 未验收：需生产安装授权；候选隔离演练用真实 CLI/真实租约但 provider 为 test-mode 假执行器 |
| SULDE_ACTIVE_LEASES_DIRS 的真实运维填充（跨工作区发现） | 未接线：范围声明显式 opt-in，无全局发现机制（方案禁止项使然） |
| Windows 平台 | 未验收 |
| 基线 3 项失败 | 逐项：①sandbox-exec `Operation not permitted`——本机沙箱限制，影响 OS 隔离证明测试 1 项；②distill-conflict exit 2≠0——既有行为断言失败，与本任务无关；③subprocess encoding guard——4 处既有测试文件编码违规。三项均非本任务引入、未修复、不扩大范围 |

## 4. 证据与索引

- Optimus：`/Volumes/Optimus/Sulde/tasks/sulde-orchestration-iteration/R1/`
  （基线/中间/最终全量回归输出、配对 A/B 原始样本）
- 候选 HEAD、树摘要与命令记录于本文件与 STATUS.md；全量回归输出独立可回读。
- **清单哈希（外层记录，索引文件不含自身）**：见 §6。

## 5. 最终工作树状态

- 分支 `task/sulde-orchestration-iteration`，提交序列：`f6e495d` → `72ed54a` → `20d9fc7` → 本文档提交（`fd3a1a6f392ed15f70c10f44a5eac4179d5163f8`，树摘要 `0badc7609b1ad299783cfb15d1ba3c62d7a6dffd`）。
- 测试命令：`python3 scripts/kb/run-isolated-tests.py`（官方入口，一次性隔离环境）；定向套件 `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_orchestration_{phase1,phase2,phase3,r1} ...`。
- 完整回归后 `git status` 干净（本文件提交后）；未合并 dev/main、未推送、未生产安装、
  未删除真实代际、无新增付费实验。

## 6. 证据哈希清单（R1）

见 Optimus `R1/R1-evidence-sha256.txt`；清单文件不列入其自身条目。
