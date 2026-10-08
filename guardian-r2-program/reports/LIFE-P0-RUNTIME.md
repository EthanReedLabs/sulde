## 结果
✅ LIFE-P0 runtime 密封范围回归通过：`PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -q tests.test_mem_sync tests.test_scheduler_entrypoints tests.test_agent_runtime.AgentRuntimeTests.test_repository_full_clone_git_read_probe_remains_available tests.test_agent_runtime.AgentRuntimeTests.test_linked_or_external_git_common_dir_fails_once_before_codex tests.test_agent_runtime.AgentRuntimeTests.test_control_root_freezes_task_authority_and_projects_guardian_paths tests.test_agent_runtime.AgentRuntimeTests.test_task_authority_mismatch_is_stateless_before_provider tests.test_agent_runtime.AgentRuntimeTests.test_task_authority_rejects_bad_digest_schema_base_and_path_bindings tests.test_agent_runtime.AgentRuntimeTests.test_durable_report_authority_fails_closed_for_path_and_file_drift tests.test_agent_runtime.AgentRuntimeTests.test_structured_git_lifecycle_provisions_commits_and_fast_forwards tests.test_agent_runtime.AgentRuntimeTests.test_provision_fails_closed_for_conflict_drift_and_git_metadata_alias tests.test_life_cycle tests.test_operational_readiness.OperationalReadinessTests.test_scheduler_failure_does_not_reclassify_live_interactive_supervision tests.test_operational_readiness.OperationalReadinessTests.test_background_scheduler_can_be_ready_without_claiming_interactive_ready tests.test_operational_readiness.OperationalReadinessTests.test_life_cycle_fails_closed_for_each_scheduler_process_failure tests.test_operational_readiness.OperationalReadinessTests.test_background_scheduler_process_failure_is_not_hidden_by_artifact_pass`，exit 0；Ran 38 tests in 9.380s，OK；candidate_sha256=10a464c9ed1c5836e0b0418bdcf463c04549ed77bb55747591c7a75c1c654671；execution_binding_sha256=8e2f6e388adf56510407b8cd14144412e5fd2231e32cd230875fd56452a3fe10；environment_sha256=de9e5e69a747b1e9a4744143048508260afca4fc1060b8ba60d37fd29a9b45d6；command_sha256=54f55db0099d988436e379a21f7b433704074a106a5dc0aff0188d3f8c363526；count=38

## 过程
- `mem-sync.py` 的默认与显式运行根限定在 `SULDE_KB_HOME`（默认 `~/.sulde/data/kb`），同步仓必须是该根内的真实 `mem-sync-repo/`。旧 Claude 数据只通过显式 `migrate-legacy` 进入：复制配置、状态和完整同步仓，重写仓路径，写入内容摘要回执；重复执行核验同一回执，`rollback-legacy` 只在迁移产物摘要未漂移时删除新副本，旧源始终保留。普通 config/import/export/status 路径不查询旧目录，也不调用 Claude CLI 或 MCP。
- import/export 在同步仓真实 Git common-dir 上共用 `sulde-mem-sync.lock`。每轮只解析一次 attached branch、唯一 remote、唯一 merge ref，并要求 fetch/push URL 同一且唯一；pull 与 push 都复用该已验证 tuple，push 使用显式 `HEAD:<merge-ref>`。
- export 在 pull 后冻结 HEAD、精确生成物集合和恢复 journal。提交前异常会恢复原字节并清理未跟踪生成物；进程中断后的下一次 import/export 会在同一锁内按 journal 恢复；push 后异常保留本地已提交真相且不提前推进 state watermarks，重试依靠业务键去重后完成显式 push。
- 两个 mem-sync LaunchAgent 模板显式传入 `--scheduled`。人工调用对临时 Git/锁错误维持同步错误语义；调度调用最多三次，采用 0.1s/0.2s 有界指数退避，耗尽后返回临时服务退出语义 75。
- `agent-runtime.py provision` 不再读取主 worktree 或 dev worktree 的无关脏状态，而是在 lifecycle lock 内双重核对 exact `refs/heads/dev^{commit}`，用 `clone --no-local` 生成内部真实 `.git/` 的完整隔离执行根，再验证 HEAD、branch、toplevel、remote source、Git common-dir 和 Codex Git layout。目标占用、base 漂移、branch 冲突和 Git 元数据别名继续 fail closed。
- 完整 clone 与 coordinator control root 通过 `sulde-source` 的唯一 canonical source 及共享 coordinator Git common-dir 建立认证关系；remote 替换会被拒绝。当前 `guardian-program/reports/` 与旧 `guardian-r2-program/reports/` 报告目录均保留严格的唯一报告、常规文件、摘要与路径约束。
- 静态核验另行通过：Python compile 覆盖改动的 Python 文件；`plutil -lint` 对两个 plist 均返回 OK；`git diff --check` 无输出。未修改 `life-cycle.py`、`operational_readiness.py`、`install-agents.sh`、阈值、灯色或生产状态。

## 遇到的问题
- 扩展诊断运行整个 `tests.test_agent_runtime` 时，76 项中 73 项呈绿、1 项跳过，两个与本次 provision/control-source 路径无交集的既有终态断言呈红：用例期待 `failed`，当前基线运行结果为 `paused`。依任务禁令未改终态或灯色语义。
- macOS installer 组合用例在当前单层原生沙箱内创建 shell here-document 临时文件时被宿主拒绝；同一轮其余 26 项完成。随后把验收收敛到 38 项密封回归，并单独确认 provider 统一契约用例通过。

## 解决方式
- 把“Git ref/commit 权威”与“其他物理 worktree 清洁度”解耦；以临时 staging clone 完成全部校验后原子改名到目标，避免任务准备工件反过来锁死 provision。
- 把同步仓并发、上游身份、生成物恢复和 watermarks 提交顺序收束为一个锁内事务；用 committed HEAD 是否前移区分“应回滚的临时生成物”和“应保留并重试 push 的真实提交”。
- 用显式迁移/回滚命令隔离历史 Claude 边界；正常运行只读取 Sulde 数据根。用 `--scheduled` 明确调用来源，而不是从宿主进程或 CLI 存在性猜测。

## 遗留风险与建议
- 按任务边界未安装候选、未加载或 kickstart 正式 scheduler、未执行真实远端同步。协调端应在候选安装后验证两个 mem-sync actor 的 `--scheduled` 参数、三次退避和 16/16 scheduler 活性。
- 完整 clone 的任务 branch 位于隔离仓；协调端合并前需按 exact commit 从该执行根 fetch/import 到协调仓，再走既有 sealed commit/merge 验收。不要退回 linked worktree 以换取共享 branch。
- 协调端应在允许 shell 临时 here-document 的安装验收环境重跑 macOS scheduler reconciliation 组合用例，并独立判定上述两个既有终态断言是否另案修订；本任务不建议借机改变状态机。
- 未提交、未合并、未推送；协调端提供的 `guardian-program/briefs/LIFE-P0-RUNTIME.md` 与 task definition 保持未改且未纳入本任务源码候选摘要。

## 沉淀候选
- 问题语境：隔离执行器把共享仓中任意物理 worktree 的脏状态当成 exact base ref 的否定证据，且 linked worktree 的 `.git` 文件无法满足正式 Codex full-clone profile。证据状态：verified。正向路由：定位到 Git lifecycle/provision 与 Codex layout 合同；反向路由：归因于业务测试或清理协调端未提交工件。正向执行：双重校验 ref/commit、内部 `.git/` staging clone、source/common-dir 认证；反向执行：清理/stash 无关 worktree 或放宽 Git 元数据检查。
- 问题语境：共享同步仓仅依赖 Git 自身瞬时 index lock，无法覆盖 pull、生成、commit、push 与 watermarks 的跨进程事务，push 不确定时容易把临时文件带入下一轮。证据状态：verified。正向路由：定位到 mem-sync transaction/恢复 journal；反向路由：只增加 scheduler 频率或无限重试。正向执行：统一 common-dir 锁、单一 remote/ref、按 HEAD 前移选择回滚或保留、业务键幂等重试；反向执行：隐式 push、多项目重复解析 upstream、失败时提前写 state。
