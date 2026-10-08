# R2 报告:预测式执行第二轮修复(2026-09-27)

分支 `task/predictive-execution`(Reviewed HEAD c8fe716 → 本轮 5 提交);
B 套件 + 消费者/基线/生命周期测试 **120 项全绿**。未合并、未推送、未安装。

## 协议层

- **R2-01**:测试产物与正式归档隔离——archive_evidence 显式调用、按 run_id
  唯一、存在即 FileExistsError;反例证明外接盘挂载下普通测试不改写历史证据。
  R1-REPORT"真实 Agent 行为"已显式更正为"脚本模拟的行为验证"(原记录保留)。
  prediction_feedback.py 当前 HEAD diff --check 干净(无空行问题)。
- **R1-01 回归**:统一权威回放后 15 项预测测试全绿(含关闭后修订/重复关闭/失效修订)。

## 生产接线层

- **R2-02**:受管链改为传递 `checked_task_definition["base_commit"]`(已验证的
  git OID)替代 task_epoch;消费者先 `rev-parse --verify` 校验基线可解析,
  不可解析显式降级(无 verdict);task_epoch 仅保留为任务身份(cursor_generation)。
- **R2-03**:消费者核对 session/contract_version 绑定,不匹配拒绝;预测绑定的
  source_identities 进入事实收集(绑定源漂移 → stale,无 verdict);
  新 attempt 经 `prediction.rebound` 显式重绑(仅身份,无权限继承);
  旧 run/session 重绑后即被拒收。
- **运行账本**:prediction.rebound/feedback/feedback_degraded 注册为
  生命周期中立事件(带 provider),不再导致账本不可回放而误标 run 失败。

## 真实 Agent 行为层(R2-04)

真实 Claude 会话(非脚本、非 write_text)完成两轮任务,输入不含答案与
监督端验收标准:

- **attempt 1**:任务"settings 段"——Agent 实现数据驱动读取,监督端数据驱动
  探针一次通过 → **验收②成立**:真实正常任务零误报、零人工阻断。
- **稳定性标准加入**(监督端持有):重排 settings.json 键序+缩进 → 首版输出
  随键序漂移 → **反例捕获**(真实缺陷,非写入)。
- **反馈投递**:事实+新标准经真实会话续接(SendMessage)送达同一 Agent
  ——已生成/已送达有据(纠偏账本 queued+applied,投递边界=manual 会话续接)。
- **attempt 2**:Agent 真实调整(规范化 sort_keys+紧凑分隔输出,仍只改
  app.py)→ **已处理**;**独立验证**:稳定性探针(重排→输出字节不变)与
  数据驱动探针(值变更→输出变化)双双通过 → **已验证**;监督者
  verified→closed(绑定摘要)→ **已关闭**。四阶段状态链完整:
  proposed→queued→applied→acknowledged→verified→closed。

## 成本

- 真实 Agent 子会话 2 次(25,806 + 28,009 tokens,~132s);新增监督模型审查
  0 次(探针均为确定性脚本)。B0 预算内。

## 未完成边界(如实)

- 假 provider 协议测试仅证协议;真实 Agent 样本 = 本次 1 个缺陷任务 +
  1 个正常任务,样本量单一,不宣称普遍收益(方案 §7 要求的多样本对照待
  协调端安排)。
- 交互宿主实时注入仍不存在(设计边界);反馈经会话续接投递。
- 受管链的端到端基线回归使用 fake provider(SULDE_TEST_MODE=1),
  真实生产 managed run 的回归待生产安装后。
