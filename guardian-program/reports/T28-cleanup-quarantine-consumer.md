# T28 cleanup quarantine consumer correction

## 结果
✅ 完成检查：`env -u SULDE_GUARDIAN_STREAM_OWNER python3 -m unittest tests.test_self_repair tests.test_intervention tests.test_intervention_batch tests.test_operational_readiness tests.test_sulde_statusline tests.test_scheduler_entrypoints -v`，exit 0；159 个 self-repair 与 T27 intervention/readiness/statusline/scheduler 测试全部通过，terminal abort cleanup 完成归档并删除临时 worktree，五类非终态 unknown 均拒绝 cleanup。

✅ 完成检查：`env -u SULDE_GUARDIAN_STREAM_OWNER python3 -m unittest tests.test_self_repair.SelfRepairTests.test_cleanup_archives_resolved_intervention_truth_before_removal tests.test_self_repair.SelfRepairTests.test_cleanup_refuses_unresolved_intervention_even_with_force tests.test_self_repair.SelfRepairTests.test_cleanup_refuses_every_nonterminal_unknown_projection -v`，exit 0；3 个聚焦故障注入测试通过，证明 abort debt 在 authoritative projection 中继续阻断同资源、在 readiness projection 中被 quarantine，且 unhandled/open/acknowledged/retry-authorized/reprobe-authorized 全部在归档和删除前 fail closed。

实现结果：仅修改 `scripts/kb/self-repair.py`、`tests/test_self_repair.py` 与本报告；未修改生产 contract/ledger、安装缓存、LaunchAgent 或远端，也未执行安装、实时 scheduler/session 操作或 commit。

## 过程
- 将 self-repair cleanup 的全局 worktree 删除门从 authoritative `blocking_attempts()` 切换为 T27 `readiness_blocking_attempts()`。
- 保留原有顺序：先加载并检查 readiness blocker，再归档 append-only intervention truth，归档成功后才执行 `git worktree remove` 和分支删除。
- terminal abort 正例在 live projection 与 archive replay 两处分别断言：attempt 仍为 `unknown`，仍出现在 `blocking_attempts()`，但不出现在 `readiness_blocking_attempts()`；因此没有把 quarantine 描述成外部结算。
- 保留原 unresolved intervention 真实日志拒绝测试，并新增投影级 failure injection，覆盖 unhandled、open、acknowledged、未消费 retry authorization 与 reprobe authorization。每例同时断言两个投影均阻断、archive 未调用、worktree 与 branch 均保留。
- 测试只在临时目录生成 git worktree 和 intervention fixture；`env -u SULDE_GUARDIAN_STREAM_OWNER` 仅作用于测试进程，使临时 fixture 可写，不改变当前受管任务的 contract 或审计谱系。

## 遇到的问题
- 当前受管进程设置 `SULDE_GUARDIAN_STREAM_OWNER=1`，直接运行会按设计拒绝单测在临时目录构造 intervention truth；首次红灯因此停在 fixture mutation，而不是待修 cleanup gate。
- shell 的原地替换工具需要在源码目录创建未登记临时文件，被 owned-path 沙箱拒绝；该尝试未改变源码。

## 解决方式
- 对测试命令局部移除 stream-owner 环境标记，让单元测试仅写其 `TemporaryDirectory` fixture；生产 contract、ledger 与任务审计文件保持只读。
- 文件修改改为对三个精确 owned path 直接写回，不创建旁路临时路径。
- 先复现真实 T28 红灯，再完成最小消费者切换；随后分别执行 3-test failure injection 和 159-test T27 回归集合。

## 遗留风险与建议
- 按任务边界未运行协调端完整隔离套件、release-level gate、安装验证或 live scheduler/session 验证；这些仍由协调端负责。
- archived abort debt 会继续进入 inventory 和同资源 authoritative blocker，这是预期安全债务而非遗留缺陷；后续消费者不得把 readiness quarantine 误解为 external settlement。
- 受管协议禁止 commit，本 worktree 保留未提交改动供协调端验收。

## 沉淀候选
### Layer1 问题卡

- **问题类型**：consumer-projection mismatch / bug-fix
- **问题语境**：同一外部 effect attempt 的“同资源安全阻断”与“全局当前 lane readiness”具有不同语义；terminal abort 只终止 intervention workflow，不证明外部效果 settled。
- **已确认根因**：cleanup 错把 authoritative same-resource `blocking_attempts()` 复用为全局 worktree 删除门，导致已 terminal-quarantined 的历史债务无法先归档再删除本地 worktree。
- **证据状态**：verified。聚焦 3-test 与完整 159-test 命令均 exit 0；archive replay 仍显示 state=`unknown` 且 authoritative blocking 命中。
- **路由正例**：消费者决定 current-lane cleanup/readiness，输入包含 resolved abort unknown debt，应使用 readiness/quarantine projection。
- **路由反例**：消费者决定同一 external resource 是否允许新写入，必须使用 authoritative blocker，不能使用 quarantine 后的 readiness 集合。
- **执行合格例**：abort debt 先归档再移除 worktree；archive replay 继续阻断同资源，且不计作外部 settled。
- **执行失败例**：直接从 authoritative blocker 删除 abort debt，或把 abort 标成 verified/settled，或让 open/ack/retry/reprobe/unhandled unknown 绕过 cleanup。
- **建议容器**：anti-patterns；可泛化内核为“资源互斥、安全审计、全局 readiness 应使用独立命名投影，workflow terminal 不等于 external truth terminal”。
