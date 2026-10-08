# R3-FOLLOWUP-REPORT — R3 独立复核后三项阻塞项返修

- 复核基线：`d50ee94`；候选 HEAD：`766650a`（代码）；文档提交随后（docs-only 可证明）
- 状态：**候选待协调者独立复核**（未合并、未推送、未生产安装、未自行 accepted）

## 0. 报告更正（按实际代码）

R3-REPORT.md 的 R3-02 表述更正：**当前源码没有 `lease_guard(create=)` 接口**——该编辑
从未进入 R3 提交（`14649d5` 不含 run_concurrency 变更）。R3-02 的实际安全改善来自
**关闭实际回收入口**（apply 函数与 CLI apply 路径整体删除），而非目录创建语义分离。
本报告按实际代码记录；未为匹配旧报告补写无用功能。

## 1. 阻塞项一：重试身份错配 ✅

- **反例（HEAD 实测，`R3-followup/counterexample-r3f-01-head.txt`）**：重复 op-1 抛
  DispatchConflictError traceback（"different predecessor"，因 CLI 用 latest run 推导
  predecessor）；op-2 成功后再提交旧 op-1 返回 op-2 的 success（错误结论）。
- **根因**：CLI 用 latest attempt 推导已有操作的 predecessor；open_retry 的已注册分支
  与 latest 链比较而不是定位自己的 attempt。
- **变更**：注册表新增按 attempt 投影（`_project_attempts`）与 `lookup_retry_op`（按
  retry_op_id 解析**其绑定的 attempt**）；open_retry 注册后解析自己的 attempt 段落；
  run_task 先按 retry-op 定位——已注册且已关闭 → 回放其自身结论；已注册且活跃 → 续接；
  未注册才按当前 latest 注册（predecessor 绑定正确）。
- **回归（真实 CLI，`tests/test_orchestration_r3f.py`）**：首次超时 → op-1 超时 → 重复
  op-1（回放 op-1、无 traceback）→ op-2 成功 → **再提交旧 op-1 仍返回 op-1 的
  status=timeout 结论**；断言含终态、run/attempt 身份（op-1→attempt2/timeout、
  op-2→attempt3/completed）、启动数=3（对应三次真实尝试，旧 op 不新增）、无 traceback。

## 2. 阻塞项二：fence 竞争窗口 ✅

- **反例**：运行端读"无 fence"→ 安装器写 fence 并复检 → 运行端才发布旧代际租约——
  窗口内旧代际租约可静默穿过。
- **根因**：租约准入与 fence 写入/复检无共享互斥。
- **变更（短临界区协议，非长全局锁）**：新增 `generation_fence.py`——`fence_lock`
  （kb_home 级、有界、短临界区）；运行端 `admission_fence` 在**同一把锁内**完成
  [fence 检查 + 租约发布]；安装端在**同一把锁内**完成 [fence 原子写入 + 最终 scope
  复检]。两侧互斥：先发布的租约必被复检看见；复检后准入的运行必读到 in-switch fence
  并被拒绝（被替代代际）。锁顺序：deployment lock（安装全程，不共享）→ fence lock
  （毫秒级临界区）→ scope guard；普通任务/旧在飞运行（保留既有租约）/恢复通道不被锁到
  安装全程。fence 损坏时准入 fail-open（可用性优先），安装端总是在锁内重写 fence。
- **回归（真实安装链，非整体 mock）**：`test_codex_plugin_install.
  GenerationSwitchFenceChainTests`——真实 install 子进程链上断言：fence 在事务期间为
  in-switch（`fence_state_at_recheck`）、含事务身份、提交后清除；block + 不兼容活跃租约
  → 拒绝且零生产变更（无 deployment-generation、无事务 journal、无 fence、租约文件原
  样）；进程屏障交错的准入拒绝在 `FenceAtomicityTests`/`admission_fence` 单元+集成覆盖。

## 3. 阻塞项三：活动事务恢复遗留 fence ✅

- **问题**：recover_only 对无活动事务场景盲目清除 fence；fence 未绑定事务身份。
- **变更**：fence 写入移入 `_install_locked`（descriptor 存在后、begin_transaction 前，
  token=transaction_id）；提交/回滚清除；`recover_only` 与安装内恢复分支：**仅当恢复
  成功且 fence.transaction_id == 被恢复事务身份**才清除；恢复失败或身份不匹配一律保留；
  无活动事务时不盲目清除（孤儿 fence 由下一次安装覆写，期间保持可见供诊断）。
- **回归（真实事务）**：`test_recovery_clears_only_the_matching_fence`——failpoint 制造
  真实活动事务 → 匹配 fence 被恢复清除、异身份 fence 保留；`test_recovery_failure_
  retains_the_fence` 覆盖保留路径；`test_install_level_writes_no_untracked_fence` 断言
  install 层无未绑定 fence。

## 4. 测试与性能

- 新增/修正：r3f 套件 4 例 + r3 修正 + 安装链 2 例真实链测试 + harness extra_environment。
- 定向全绿：r3f/r3/r2/r1/phase1-3 + codex_plugin_install（含全部 process-death 恢复用例）
  + install_transaction_journal + candidate + agent_runtime。
- **最终全量（官方入口，候选代码树 `766650a` 所测）**：**2629 例，失败恰为 3 项基线既有
  失败（sandbox-exec / distill-conflict / encoding-guard 4 处既有违规），零新增失败**。
  上一轮的真实宿主 45s 超时本轮未复现（该用例通过），归因仍记 inconclusive。
- **性能（交叠配对 vs R2 head `c815202`；样本存 `R3-followup/paired-ab-perf.txt`... 实际
  存 R3-followup 与 R3 目录）**：正常成功 base 0.759s vs R3 0.764s（+5ms）；恢复续接
  0.309s vs 0.309s（0ms）——预算内。

## 5. 未验收与剩余限制

- C 层真实宿主运行中切换/双 session/回滚演练：仍未验收（依赖生产安装授权）。
- Windows：未验收。
- fence 崩溃窗口残留：crash 发生在 fence 写入后、begin_transaction 前的毫秒窗口会留下
  带 transaction_id 但无活动事务的 fence——不盲目清除（按复核要求），由下一次安装覆写；
  期间旧代际准入被拒绝属已知限制。
- 自动回收能力：维持安全关闭（R3-01），未交付。

## 6. 证据

- Optimus：`/Volumes/Optimus/Sulde/tasks/sulde-orchestration-iteration/R3-followup/`
  （HEAD 反例实测输出、最终全量输出；`R3F-evidence-sha256.txt` 不含自身）。
- 候选 HEAD `766650a`；所测代码树即该提交（后续仅文档）。
