# R3-INJECTION-BASELINE-R1 任务:决定性故障反例(2026-09-28 签发)

Reviewed HEAD `fcd28a4`;分支 `task/predictive-execution`,worktree 不变。
本轮真实模型调用 0;不修改生产代码;测试从一开始断言**正确行为**
(在 reviewed HEAD 预期失败,清楚标注),不先断言错误行为再反转。

## B1 实际接线上的 stdin 失败

路径:实际 `agent-runtime run` → run_task → monitor_process → 实际回调
包装(build_input_delivered_callback 工厂)→ 工厂回调。
故障注入:provider 瞬时退出(`exit 0`,不读 stdin)+ brief 填充至 >64KB,
使管道 write 在子进程退出后必然 EPIPE。

固定断言(正确行为):
1. 反馈工件保留(不被删除);
2. registry consumed 不含该 request(无成功消费登记);
3. 失败事实准确保留:feedback_consumed 账本事件 payload.send_failed 非空,
   或 registry send_unconfirmed 含该 request。

配套正常例:正常读取 stdin 的 provider → 消费登记正常发生(同夹具)。

## B2 发送结果不确定后的恢复

经生产失败处理形成 send_unconfirmed 后,再走实际恢复/反馈选择路径
(下一次 run 的执行输入)。

固定断言(正确行为):
1. registry send_unconfirmed 含该 request(经生产失败处理形成);
2. 无新增接收证据或明确恢复决定时,反馈**不再次纳入发送输入**
   (下一次 attempt 的执行输入不含反馈段);
3. 不伪记成功:消费登记不因重试而补记;
4. 不影响无关任务(无关 attempt 执行输入不含该反馈)。

## 三、来源检查边界(只读核实)

说明消费 run 身份何时产生、来源/续接关系在哪验证、run id 生成规则
(uuid4 一次性)是否使来源=消费 不可达;结论如实提交。

## 边界

故障只注入进程/管道边界;不改 scripts/ 生产代码、配置、账本;
测试产物临时目录,正式归档
`/Volumes/Optimus/Sulde/tasks/predictive-execution/R3-injection-baseline-r1/<唯一>/`。
测试文件未来修复后原样复跑,不改成功条件。
完成后更新 STATUS(标记 injection-baseline-awaiting-review)并停止;
不合并失败候选、不 accepted。
