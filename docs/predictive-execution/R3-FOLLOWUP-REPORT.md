# R3-followup 报告(2026-09-28)

Reviewed HEAD `d826f94`;本轮分支提交:R3-TASK 至本报告。真实模型调用预算:0(全程未调用)。

## 一、正式反馈消费链(已接线,经真实 run 验证)

- 消费入口:`prediction_feedback.load_pending_feedback` — 校验任务摘要、
  预测 id/版本(旧反馈不带入新修订)、合同版本一致性、require-adjustment;
- 纳入执行输入:`execution_prompt` 新增「监督端预测对照反馈」段;
  fake provider 从 **stdin 实测到该段** 才执行修复分支(投递证明=执行输入内容,
  非写文件/登记状态);
- 消费登记:attempt 启动后 `confirm_feedback_consumed` 以真实 run/session
  摘要写入 consumed registry,工件移除,不可重复投递;
- 账本:prediction.rebound(attempt 启动)/ attempt_started / feedback /
  feedback_consumed 全部注册为生命周期中立事件(带 provider),不再破坏回放。
- 分开记录:已生成(feedback 事件)/已纳入执行输入( consumption 事件 +
  prompt 捕获)/后续行为(provider 写入内容)/独立验证(probe exit 0)。

## 二、真实入口测试(三路径 + 反例,全过)

| 测试 | 证明 |
|---|---|
| 路径 A 正常修改 | 无反馈 → in-scope 修改 → checked as_predicted,无反馈工件,探针 ok |
| 路径 B 反馈送达 | attempt1 越权 → 工件生成 → 正式续接(prompt 含反馈段)→ 修复 → as_predicted → 探针 ok |
| 路径 C 不投递 | attempt1 only → overreach **保持破坏状态**(探针 rc≠0),prompt 无反馈段 |
| 反例:错任务 | 错任务工件不被消费入口读取,原样保留 |
| 反例:过期反馈 | 预测修订后旧反馈(版本不匹配)不进入执行输入 |

test_mode 替代边界(显式声明):替代生产 provider 权限链(codex 原生
runtime authority)、生产安装与调度器;真实受管运行器、参数绑定、git 冻结
基线、纠偏投递边界、续接与验证逻辑均为真实执行。不称生产权限链验收。

## 三、超时诊断(R3-04 真实运行)

见 `docs/predictive-execution/R3-TIMEOUT-DIAGNOSIS.md`:provider 未完成
(240s SIGTERM,事件流无 result,报告零字节)。此前"格式不合规/需命令层
结构化保证"的确定性归因撤回(inconclusive)。

## 四、成本

- 真实模型调用:0(本轮);
- 历史:R3-04 三次真实调用全部计入成本;两次归档运行各 240s(累计 480s
  运行耗时),第 3 次墙钟 unknown;
- "监督模型调用为零"仅指监督审查维度;整体预算合规性:基线未测,inconclusive。

## 状态

candidate-awaiting-independent-review。未合并、未推送、未安装。
