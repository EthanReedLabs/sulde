# R3-INJECTION-CLOSEOUT 报告(2026-09-28)

分支 `task/predictive-execution`;reviewed 基线 b81a941(本轮起点,含其后
closeout 提交)。B 套件 + 注入测试全绿;真实模型调用 0;未合并、未推送、未安装。

## 冻结矩阵覆盖(全部通过)

| 场景 | 不变量 | 故障点 | 结果 |
|---|---|---|---|
| A1 stdin 写入/关闭失败 | I1,I5 | 管道(send_failed 注入) | 不登记消费;工件保留;失败事实入 registry send_unconfirmed + 账本 |
| A2 send_failed 转发 | I5 | 回调参数 | 参数完整转发(修复 lambda 丢参) |
| B1 旧确认 vs 新请求 | I2 | 工件 request ≠ 被确认 request | 新工件保留,不被旧确认删除 |
| C1 来源=消费 attempt | I3 | artifact.run == consuming_run | 拒收(cannot consume its own feedback) |
| C2 错任务/错合同 | — | task/contract 摘要不匹配 | 拒收,工件原样 |
| D1 无预测任务 confirm | I4 | 无线程 | skipped 零写入(不建 predictions.jsonl) |
| D2 消费后残留 | — | registry 已落盘、工件未清理 | 不重复投递+按身份清理 |
| E 无预测完整 run | — | 实际 run 命令 | 成功,零预测文件 |
| F 正常发送+正常完成 | — | wellbehaved provider | as_predicted + 探针 ok |

## 四个已知缺陷:旧版红 → 新版绿

1. **stdin 失败仍登记消费**:基线红(反例断言"登记发生"通过)→ 修复后
   反例翻转为"不登记、工件保留、失败事实入 send_unconfirmed"。
2. **旧确认删新请求**:基线红(新工件被删)→ 修复后 confirm 校验工件
   request 身份,仅删除一致工件。
3. **来源自我消费**:基线红(自我消费被接受)→ 修复后 load 以持久化摘要
   判定 来源==消费 → 拒收。
4. **无预测任务写账本**:基线红(predictions.jsonl 被创建)→ 修复后
   skipped 零写入。

基线红存档:`.../R3-injection-closeout/20260928T030627-baseline-0558A4EC/baseline-red.log`;
复验绿:`.../20260928T<ts>-postfix-*/postfix-green.log`。

## 三路径与反例(实际 run 命令,全过)

- A 正常修改:无反馈也成功(checked as_predicted,探针 ok,无反馈工件)。
- B 反馈送达:attempt1 越权失败(exit 1 可重试)→ --retry 正式续接 →
  执行输入实测含反馈段 → 修复 → as_predicted → 探针 ok。
- C 反例:错任务反馈工件原样保留,不进入执行输入。

## 语义澄清(冻结矩阵 I5)

stdin 写入成功 = "已发送"(消费登记仅在此后发生);Agent 是否处理由后续
行为与监督端验证单独证明——本轮不声称已处理。发送结果不确定时记入
registry send_unconfirmed 并保留工件,不伪记成功、不无条件重发;
该状态只影响该反馈,不锁死无关任务。

## 成本

真实模型调用 0;监督模型调用 0;机械开销毫秒级;墙钟:注入套件 0.3s,
受影响套件 8.9s。整体预算合规基线:未测(标注)。

## 未完成边界(登记)

- 真实 Agent 验收待 R3-closeout 三节的最小权限准备后重跑(独立待办);
- 多样本对照、历史债务恢复、任务清理映射:既有独立待办不变。
