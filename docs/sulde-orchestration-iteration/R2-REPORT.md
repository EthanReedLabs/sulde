# R2-REPORT — 编排迭代 R2 定向返修

- 任务：`sulde-orchestration-iteration-r2` rev 1（R2-TASK.md）
- 被审查 HEAD：`574a2004f834b7ad9ab2c5c0c0dc9875b02ff8a0`（树 `472a8ee1…`）；基线 dev：`9936c7b`
- R2 候选提交：`52cd59e`（R2-01/02）→ `a1e320a`（R2-03/04）→ `d02d2e1`（R2-05）→
  policy-pause 可续接更正 → 本文档提交
- 状态：**R2 候选待协调者独立复核**
- 测试命令与环境：`python3 scripts/kb/run-isolated-tests.py`（官方入口，一次性隔离环境，
  Python 3.10.7 / macOS Darwin 25.3.0）。全量回归所测代码树 = `5847984`
  （`fix(orchestration): R2-02 — policy pauses stay resumable…`）；本报告提交（`376ecbd`）
  相对该树为 docs-only：`git diff 5847984 376ecbd --stat -- scripts/ tests/ tools/` 为空。（执行者不自行标记 accepted）

## 0. 审查更正声明

R1-REPORT 中 R1-04"✅ 完成"的口径**收窄更正**：R1 的幂等层保证"完成请求不重复执行"，但
(a) 重复回放把 provider 进程退出码当任务结论（失败任务可被改写为成功）、(b) timeout 等可
重试终态会被普通重复投递自动重跑。R1-06"✅ 接线"同样收窄：gate 曾在 launcher/deployment/
scheduler 变更之后才执行（事后回滚而非事前阻断），且 scope 覆盖语义把"缺失目录"当安全。
STATUS.md 已同步更正；历史报告保留不改写。

## 1. 逐项返修

### R2-01 重复请求返回原任务结论 ✅

- **问题（已复现→回归）**：provider 退出 0 但报告仅 `## drill`，首次运行 rc=1/status=failed；
  原样重交返回 rc=0/status=success——重复请求改写结论。
- **根因**：重复回放用 provider 进程退出码重算成败，把进程退出、报告验收、效果验证、
  任务结论混为一谈。
- **变更**：close 行携带权威任务结论（task_status+task_returncode）；重复路径回放原结论；
  结论缺失/损坏/未结算时从原 run 的 status 文件对账（run=<id> 绑定），仍不可解则
  awaiting_human，不伪造成功、不盲目重跑；迟到回执不可降级已关闭尝试（单行 no-op）。
- **回归（CLI 真实入口）**：进程 0+报告失败→重复仍 failed；真成功→重复 success；进程非零
  →重复 failed；closed 行丢失（崩溃窗口）→按 status 文件对账回放 failed；结论完全不可解
  →awaiting_human 且不重启；迟到回执 no-op。验收记录含 CLI 码/状态/原因/run 身份/启动数
  （各断言均在测试内，原始输出存 Optimus）。

### R2-02 重复投递与明确重试分离 ✅

- **问题（已复现→回归）**：timeout 请求的普通重复投递自动 `open_retry()` 启动 attempt 2。
- **根因**：可重试 stop reason 单凭名称即成为新启动许可。
- **变更**：普通重复对 closed 尝试只回放/对账，绝不新启动；新尝试必须 `--retry` 显式操作
  （关联原 run，retries_of 落册）；重试操作自身幂等（重复 --retry 回放上次重试结果，不出
  attempt 3）；重试拒绝 awaiting_human 人工门（不自动清除人工门/未知效果）；policy_paused
  在显式操作下允许（运行自身会处理已排队的 correction——可证明安全的局部恢复）；崩溃未
  关闭的尝试仍属"恢复已有尝试"，普通重提交可续（恢复≠重试）。
- **回归**：普通重复 timeout 不新启动（launched=1、attempt=1）；--retry 仅启动一次且
  repeats 不再启动（opened=2/launched=2）；--retry 遇人工门拒绝（注册表层）；同 ID 异内容
  冲突（phase1 保留）；崩溃窗口先对账（R1 窗口测试保留通过）。

### R2-03 切换保护先于生产变更 ✅

- **问题（代码证据）**：投影在 launcher 发布/deployment/scheduler 变更之后才执行——block
  是事后发现＋回滚。
- **变更**：门在 install() 中、任何生产变更前执行（此前仅 stage/检查，均非活动状态变更）；
  并在 `_install_locked` 内 begin_transaction 之前复检——两次门之间的新租约在复检被拦截，
  拒绝发生在任何 journal/生产变更之前（无需回滚）。门+复检证据记入安装结果。锁顺序：部署
  锁（全程）→ 各 scope guard（仅回收 apply 时按排序获取）；不用全程全局长锁。
- **回归**：`InstallerGateOrderTests`——block 时 `_install_locked` 未被调用（mutation 为零，
  mock 断言）；兼容正例可推进（observe 记录 unverified 而非 safe）；门后新租约交错在复检
  被拦截；中途失败按既有事务恢复（install journal 测试全绿）。调用顺序证据：patch 计数 +
  异常消息（"blocked before any production change"）。

### R2-04 完整引用证明与 unknown 语义 ✅

- **问题（已复现→回归）**：B 工作区持有活跃租约，GC 只读 A 返回 reclaimable=1；安装
  block 下缺失目录仍 compatible=true。
- **根因**："单目录扫描完成"被当成"全部引用已覆盖"；缺失 scope 被当成安全。
- **变更**：覆盖显式声明（repeat --leases-dir）；缺失/不可读 scope = unknown，任何目标
  保持 not-closed；可执行回收需 coverage=complete **加**调用方 `--certify-scope-coverage`
  显式证明；dry 计划保持诊断（行级 eligible 可见，reclaimable 关闭）；apply 在**所有声明
  scope** 的 guard 锁（排序获取）下复核覆盖/身份/保留/引用并删除；installer 投影缺失/
  未声明 = unknown：observe 显示 unverified，block 拒绝。未新建全局权威注册表；单目录并发
  额度边界不变。
- **回归**：跨 worktree 引用（B 持引用→A-only 计划漏检、全量计划拦截）、缺失 scope、
  认证缺失禁用回收、计划后新 scope 租约 apply 拒绝、真正无引用+认证→回收成功、CLI 无
  认证 --apply 拒绝。

### R2-05 候选演练修复与分层证明 ✅（C 层未验收）

- **问题（已复现→回归）**：演练 fake provider 只写 `## drill`，run_exit=1 被 `:875` 正确
  拒绝——租约机制通过但任务本身失败。
- **变更**：夹具满足真实报告消费契约（五节+证据行+匹配 command digest）；演练门槛加
  `run_task_status == "success"`（进程成功≠任务成功）；scratch 每次演练新建（重复 verify
  不因既有状态失败）；断言走完整 `_verify_generation_protection()` 入口。
- **分层**：A=模块/投影单元（phase1/3/r1/r2 单元）；B=真实候选 runtime CLI+本地假 provider
  的完整演练（本轮，真实进程/真实租约/真实 guard，零外部模型调用）；**C=真实宿主运行中
  隔离切换/双 session/失败恢复回滚——未验收**，依赖：生产安装授权、真宿主上的调度器与
  launchd 环境；已检查的替代：隔离安装链内的完整 B 层演练（本轮交付）。不以"先生产安装"
  泛化。
- **C5 证据绑定**：持久问题续接/归属/迟到消息/状态一致性的既有合格证据 =
  `tests/test_supervision_lifecycle_e2e.py`（双宿主修正/恢复/隐私旅程，本候选树全绿）与
  `tests/test_grant_broker.py`、`tests/test_session_continuity.py`（树绑定见 §3 全量输出），
  未消失、未重写。

## 2. 测试、性能与影响矩阵

- 新增 `tests/test_orchestration_r2.py` 15 例；修正 phase3/r1（新 API 与覆盖语义）、
  phase1/2（无语义变化，仅 encoding 守卫合规）。定向全绿：五套件 98 例 + agent_runtime/
  candidate/install journal 全链 258 例（含 2 skip）。
- **影响矩阵 → 全量必要**：本轮修改共享状态机（dispatch schema、guard API、安装门），
  按冻结规则执行一次全量。结果见 §3。
- **性能（同机交叠配对，R1 head `574a200` vs R2 候选；原始样本存 Optimus R2/）**：
  - 正常成功：base 中位 0.795s vs R2 0.779s（Δ=−16ms）
  - 恢复路径（timeout）：base 1.445s vs R2 1.447s（Δ=+2ms）
  - 均在冻结预算 max(15%,100ms) 内。注：R1 的 2365dcf 配对只证明 R1 增量，本配对证明
    R2 增量；对 dev@9936c7b 的整体变化未在本轮重测。

## 3. 全量回归与基线失败

- 最终全量（官方入口，R2 候选树，含 policy-pause 更正）：**2554 例（2453 基线 + 101 新增）**；
  失败逐项：
  1. `test_real_os_boundary_denies_alias_and_symlink_targets`（error）——本机 sandbox-exec
     `Operation not permitted`；影响：OS 写拒绝证明在该宿主不可执行（基线既有，非本任务引入）。
  2. `test_cli_reports_a_conflict_with_its_own_exit_code_and_machine_code`——distill CLI
     冲突退出码断言失败（基线既有，未触碰）。
  3. `test_all_text_subprocess_calls_fix_encoding_and_errors`——4 处**基线既有**测试文件
     encoding 违规（本轮新增文件已全部合规）。
  4. `test_real_tool_fault_automatic_delivery_aggregation_resume_and_isolation`（error，
     仅本轮全量出现）——真实宿主 `codex exec` 调用 45s 超时；**隔离复跑 5.2s 通过**
     （配对证据：全量期间并行负载所致），判定 environmental timeout，原失败保留于
     `R2/r2-final-full-suite.txt`。
- 不称全绿；以上不阻塞本轮验收项，第 4 项建议协调者在低负载窗口复跑确认。

## 4. 未验收项

| 项 | 状态 |
| --- | --- |
| C 层：真实宿主运行中隔离切换/双 session/回滚 | 未验收（依赖生产安装授权与宿主调度环境） |
| scope 覆盖的全局证明 | 架构上不可自证：依赖调用方声明+认证；未声明=unknown |
| Windows 平台 | 未验收 |

## 5. 证据与工作树

- Optimus：`/Volumes/Optimus/Sulde/tasks/sulde-orchestration-iteration/R2/`
  （中间+最终全量输出、交叠配对原始样本；哈希清单 `R2-evidence-sha256.txt` 不含自身，
  摘要：final suite ba509df5…、intermediate 83feb1cf…、paired-ab 0a3e05bb…）。
- 候选 HEAD/树：见 STATUS.md R2 节与本文件提交序列；测试后仅文档差异时以
  `git diff <候选提交>..HEAD --stat` 证明代码树未变。
- 工作树：文档提交后干净；未合并、未推送、未生产安装、未删除真实代际。
