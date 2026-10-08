# R3-CLOSEOUT-REPORT — 编排迭代最终定向收尾（A1–A4）

- 任务：`sulde-orchestration-iteration-r3-closeout` rev 1（R3-CLOSEOUT-TASK.md）
- 复核基线：`37f4a9424285741e4331326230bf40fb5aac4df6`（代码 `766650a`）；基线 dev：`9936c7b`
- 候选提交：`774ab4c`（A1/A2/A3 修复）→ `d119756`（回归测试）→ 本文档提交
- 状态：**candidate-awaiting-independent-review**（不自行 accepted、不合并、不推送、不安装、不启动 B）

## 0. 修改前判断记录（R3-CLOSEOUT-TASK §4）

| 项 | 根因假设 | 实际偏差 |
| --- | --- | --- |
| A1 | recover_only 无身份匹配清除；无活动事务时盲目 unlink | 与实际 diff 一致；额外发现 install() 失败路径存在两处身份盲清除，一并删除（清理收敛到 _install_locked 的身份校验路径） |
| A2 | fence 写入无 block 条件 | 一致；另发现提交路径的无条件清除会误删 observe 安装期间的历史 fence（身份门控后由专用测试锁定） |
| A3 | 配额等待在共享 fence 锁内（30s vs 10s） | 一致；修复为锁内即时发布 + 锁外排队循环（每轮重检 fence），未引入新锁 |
| 验证 | 原“恢复测试”走普通安装、foreign fence 用另一文件名、无双进程屏障 | 全部按真实入口重写：failpoint 事务 + `--recover-only` CLI + 正式 fence 路径异身份 + 双进程/屏障用例 |

## 1. A1 恢复入口的 fence 生命周期 ✅

- **反例（HEAD 实测）**：failpoint `journal.after.prepared`（block）→ fence 发布 → 事务中止 →
  `--recover-only` 返回 0 且 active 清除，但 fence 仍在（准入仍被拒）。
- **变更**：recover_only 三分支——(a) 活动事务：独立成功恢复后，仅当 fence.transaction_id
  匹配被恢复事务才清除（记入 result["fence"]）；失败不清除、不扩大准入保证；(b) 无活动
  事务：fence 事务在 journal 中无记录 → 可证 orphaned PRE-mutation → 有界清除 + 诊断；
  有 journal 记录 → recovery_required 保留；(c) fence 损坏/不可解析 → recovery_required
  保留。install() 自动恢复分支使用同一匹配清除语义（R3-followup 已交付，回归锁定）。
- **回归**：`RecoverOnlyFenceLifecycleTests`（真实 failpoint 链 + `--recover-only` CLI）——
  匹配清除且准入恢复（fence_refusal 归 None）、异事务身份保留、二次 recover-only 的孤儿
  有界清除、重复 recover-only 幂等。

## 2. A2 observe 与 block 分离 ✅

- **反例（HEAD 实测）**：observe 安装仍产生 fence（写入无 block 条件），且提交路径的
  无条件清除会删掉 observe 安装期间的历史保护 fence。
- **变更**：`_install_locked` 内 fence 写入以 `generation_switch_gate.policy == "block"`
  为条件；observe 只记录复检证据。提交与失败路径的清除全部身份门控——observe 安装不
  创建、不删除任何 fence；历史保护原样保留。
- **回归**：`test_observe_install_keeps_preexisting_historical_fence`（真实链：observe 安装
  成功后历史 fence 仍在）、`test_fence_is_in_switch_during_chain_and_cleared_after_commit`
  （block：事务期间 in-switch、提交后清除）——不以“最终文件消失”反推安装中无阻断：
  阻断验证在 admission_fence 协议层（A3 用例）。

## 3. A3 共享锁中不得进行配额排队 ✅

- **反例（双进程隔离复现）**：A 等配额期间持共享 fence 锁（10s 上限），B 独立 scope 取锁
  超时。
- **变更**：准入循环——锁内只做 [fence 复检 + 即时租约发布（timeout=0）]；配额耗尽即释
  锁、锁外等待 0.2s、循环重进（每轮重新复检 fence，检查→发布仍原子）。锁顺序：deployment
  lock（安装全程，安装独有）→ fence lock（毫秒临界区，两侧）→ scope guard（租约内部）。
- **回归（两个真实进程 + 同步文件屏障）**：`QuotaOutsideFenceLockTests`（A 配额排队期间
  B 独立 scope 准时取得租约、延迟 < 1s）；`TwoProcessBarrierTests` 覆盖“租约先发布”与
  “fence 先建立”两种顺序；兼容/目标代际正例与失败恢复由真实链测试覆盖。

## 4. A4 验证与报告

- 反例先固化：7 例新回归在 reviewed HEAD（`37f4a94`，detached 临时检出实测）失败
  **3 项**（orphan 诊断缺失、unresolvable 保留缺失、lease-first 后准入拒绝缺失——均为
  目标行为；其余 4 项在 HEAD 上因夹具自身问题未能进入测试体，不计为行为证明，修复后
  全部通过），输出存 `R3-closeout/counterexamples-failing-at-head.txt`（exit=1，3 failures）。
- **最终全量（官方入口，候选树）**：**2694 例**；失败逐项：
  1. sandbox-exec（基线既有，本机限制）
  2. distill-conflict 退出码（基线既有）
  3. encoding-guard 4 处基线既有违规
  4. 本轮发现并修复的两处过程失败（bytecode 污染导致的 bootstrap/statusline/launcher
     簇失败——由执行者 py_compile 残留 `__pycache__` 引发；retained-fence 测试断言与
     A2.3 要求相反）——修复后全量复跑确认归零，见 §5。
- **性能（交叠配对 vs R3-followup reviewed HEAD `d50ee94`；样本存
  `R3-closeout/paired-ab-perf.txt`）**：跨作用域配额压力下，B 独立 scope 准入延迟
  base 中位 0.30ms vs 候选 0.34ms（Δ=+0.04ms，预算内；关键断言是 B 不因 A 排队而
  串行化——两种实现下 B 均及时，但候选修复了 A 排队期间持共享锁的安全缺陷）。
  正常成功与恢复路径的配对沿用 R3-followup 数据（本轮未改该路径的共享锁边界）。
- 基线既有失败逐项绑定：三项身份/原因与本任务无关，不构成发布豁免。

## 5. 过程失败披露

- 第一次收尾全量出现 7 失败：执行者 py_compile 残留 `scripts/kb/__pycache__` 触发
  bytecode 洁净门（bootstrap/statusline/launcher 簇 5 项）+ 执行者新测试
  `test_recovery_failure_retains_the_fence` 断言写反（要求无关安装清除孤儿 fence，与
  A2.3 相反）。两者均已修复；失败日志保留于 Optimus
  `R3-closeout/r3co-first-full-suite-failures.txt`，更正后的最终全量见 §6。

## 6. 证据与工作树

- Optimus：`/Volumes/Optimus/Sulde/tasks/sulde-orchestration-iteration/R3-closeout/`
  - `counterexamples-failing-at-head.txt`（reviewed HEAD detached 检出实测：3 目标失败，
    exit=1）
  - `r3co2-final-full-suite.txt`（更正后最终全量）
  - `r3co-first-full-suite-failures.txt`（过程失败，保留）
  - `paired-ab-perf.txt`（跨作用域配额压力配对）
  - 哈希清单 `R3-closeout-evidence-sha256.txt`（不含自身）
- 候选 HEAD/树：见 STATUS.md；工作树干净（文档提交后）。

## 7. 未验收与剩余限制

| 项 | 状态 |
| --- | --- |
| C 层真实宿主运行中切换/双 session/回滚 | 未验收（依赖生产安装授权，按 ORDERED-PLAN 由获授权发布执行者执行） |
| Windows | 未验收 |
| 自动回收能力 | 安全关闭（R3-01），未交付 |
| recover_only 孤儿诊断的竞争窗口 | fence 写入后、begin_transaction 前崩溃会留下带 id 的孤儿 fence——诊断可证安全清除；残余窗口为毫秒级且下次安装覆写 |

## 8. 沉淀候选（未写正式知识库）

- “字节码洁净门会被开发者本机 py_compile 静默触发”——建议任务收尾前统一
  `find … __pycache__` 自检；证据：本轮两次全量簇失败。
- “清理身份必须绑定事务身份”——recover/commit 对 fence 的清除一律按 transaction_id
  匹配；无条件存在性清除曾误删历史保护（本轮 A2 修正）。
