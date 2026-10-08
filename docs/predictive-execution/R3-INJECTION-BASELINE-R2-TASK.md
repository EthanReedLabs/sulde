# R3-INJECTION-BASELINE-R2 任务:测试夹具修正与双版本对照(2026-09-28 签发)

Reviewed HEAD `fcd28a4`(冻结旧版);候选 = 工作树当前 HEAD。
仅修改 tests/ 与 docs/predictive-execution/;不改 scripts/。

## 一、建立合法正常夹具
复用已通过 5/5 的 test_r3_real_entry_chain.py _Chain 夹具。
验证链:预测存在 → 正常发送 → 输入含反馈 → 消费登记 → 正常完成。
正常对照不过则停止。

## 二、B1:实际链路上的 stdin 失败
经真实 run_task → monitor_process → 实际回调;管道边界注入。
断言:无成功消费登记;反馈工件保留;失败事实在册。
配对正常例:同夹具 + 正常 provider → 消费登记正常。

## 三、B2:发送不确定后的恢复
send_unconfirmed 在册 + 工件保留 → 下一次实际 run 的执行输入不含该反馈;
显式恢复标记后可再投递(仅验证 load 门控)。
不影响无关任务。

## 四、双版本对照
同一测试文件、同一输入、同一断言,分别在旧版(fcd28a4)与候选(当前)的
隔离目录/独立进程/独立数据根上运行。旧版应因目标行为失败,候选应通过。
启动/导入/契约失败不算有效反例。

## 边界
真实模型调用 0;不合并、不推送、不安装;只提交测试与文档。
完成后交还协调端;状态 injection-baseline-awaiting-review。
