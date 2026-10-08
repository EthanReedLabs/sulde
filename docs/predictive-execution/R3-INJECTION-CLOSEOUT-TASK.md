# R3-INJECTION-CLOSEOUT 任务:反馈消费故障注入收尾(2026-09-28 签发)

Reviewed HEAD `b81a941`(分支当前含其后 R3-closeout 提交,基线以工作树
`git log` 为准);真实模型调用预算 0。

## 冻结验收矩阵(先于任何生产代码修改)

不变量 I1:stdin 发送失败 → 消费登记不发生,反馈工件保留,发送失败事实入账。
不变量 I2:消费确认只删除与被确认 request 完全一致的工件;新请求不受旧确认影响。
不变量 I3:生成反馈的 attempt 不得消费自己的反馈(来源=消费 → 拒收)。
不变量 I4:无预测线程的任务,确认入口零写入(不建 predictions.jsonl、
不写运行账本预测事件)。
不变量 I5:语义不混淆——未发送/发送失败/不确定/已发送/已处理 分别的
持久化记录;stdin 写入成功 ≠ Agent 已处理。
配对正常路径:每次故障反例配一个同夹具正常例(发送成功 → 正常登记)。

| 场景 | 生产路径 | 故障点 | 预期 | 配对正常例 | 测试 |
|---|---|---|---|---|---|
| A1 stdin.write/close 失败 | run_task → monitor → on_input_delivered 闭包(真实工厂构建) | 管道(即时退出 provider) | I1,I5:无消费登记;工件保留 | provider 正常读取 stdin → 消费登记发生 | 注入 D1 + 配对 |
| A2 close 后 send_failed 转发 | 同上 | 回调参数注入 send_failed | 仅记录失败事实,不登记消费 | 无失败 → 登记 | 注入 D1b |
| B1 旧确认 + 新请求工件 | confirm_feedback_consumed | 工件 request 与被确认 request 不同 | I2:新工件保留 | 同 request → 工件清理 | 注入 D2 |
| C1 来源=消费 attempt | load_pending_feedback | artifact.run_id == consuming_run | I3:拒收 | 来源≠消费 → 正常 | 注入 D3 |
| C2 错任务/错合同 | load_pending_feedback | task/contract 摘要不匹配 | 拒收,工件原样 | 同上(既有) | 既有+回归 |
| D1 无预测任务 confirm | confirm_attempt_run 包装 | state 无 predictions 线程 | I4:零写入,状态 skipped | 有线程 → 正常 | 注入 D4 |
| D2 消费后残留清理 | load registry 判定 | registry 已含 request | 不重复投递+按身份清理 | — | 既有回归 |
| E 无预测任务完整 run | 实际 run 命令 | — | 运行成功,零预测文件 | — | e2e |
| F 正常发送+正常完成 | 实际 run 命令(wellbehaved) | — | as_predicted + 探针 ok | — | 既有路径 A |

预计修改范围:scripts/kb/prediction_feedback.py(consumption confirm/load)、
scripts/kb/agent-runtime.py(回调工厂与转发)。受影响消费者:受管链
run 命令的预测反馈路径;不影响无预测普通任务与既有纠偏通道。

## 四个已知缺陷(reviewed HEAD 上必须先复现目标断言失败)

1. stdin 失败仍执行成功消费确认(lambda 丢参 + 失败分支照常登记);
2. 旧确认未核对工件身份便删除新请求;
3. 来源 attempt 自我消费未拒绝;
4. 无预测任务的 confirm_attempt_run 仍写账本/建文件。

规则:真实生产函数 + 实际回调接线;仅外部边界注入(管道/进程/文件系统);
导入或环境失败不算有效反例;断言可观察结果;每反例配正常例。

## 执行顺序

最小语法检查 → 基线故障注入(红,存档)→ 最小修复 → 注入复验(绿)→
真实入口测试(路径 A/B/C+反例)→ 受影响模块回归。

## 交付

R3-INJECTION-CLOSEOUT-REPORT.md、STATUS.md、冻结矩阵证据索引、
最终代码身份与哈希清单;证据:`.../R3-injection-closeout/<唯一运行目录>/`。
完成后停止交还独立复核;状态 candidate-awaiting-independent-review;
真实模型调用 0。
