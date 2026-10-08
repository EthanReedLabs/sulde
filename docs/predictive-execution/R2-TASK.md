# R2 任务:预测式执行第二轮修复(协调端 2026-09-27 签发)

Reviewed HEAD `c8fe716`;工作树干净、无并发占用;dev `f932ca8` 已是本分支祖先(已对齐)。
R1 协议修复与历史证据保留;不改写旧结论,更正以显式标注追加。

## R2-01 隔离测试与正式证据
- `tests/test_r1_behavior_evidence.py` 不得默认写入固定 Optimus 目录;
  普通测试产物一律临时目录;正式归档必须显式指定、每次唯一、禁止覆盖已有运行证据。
- 新增反例:即使外接盘已挂载,普通测试也不改写历史证据。
- R1 的"真实 Agent 行为"更正为"脚本模拟的行为验证"(显式标注,原始记录保留)。

## R2-02 修复真实入口的 Git 基线绑定
- agent-runtime 现把 `task_epoch` 当 Git baseline 传入反馈消费者——类型错误。
- 改用受管任务真实冻结的源码基线;校验其属于本仓库且可解析为 commit;
  缺失/错误基线显式降级(不得返回 checked/as_predicted),不得静默回退 HEAD。
- `task_epoch` 保留为任务身份。
- 回归经过实际 agent-runtime run 的参数传递与反馈消费者,非仅直调。

## R2-03 补齐反馈身份与源码时效
- 反馈消费者核对预测与当前任务的 task/run/session、合同版本及源码身份;
  不得丢弃 `current.source_identities` 为 {}。
- 区分预计范围内的变化与使预测依据失效的范围外变化。
- 覆盖:同 run 不同 session、合同版本变化、绑定源码漂移、合法同身份反馈、
  新 attempt 显式关联与重新绑定。
- 续接不得复用旧 run/session 身份,不继承旧执行权限。

## R2-04 真正贯通反馈消费与 Agent 调整
- 链条:实际受管入口 → 预测形成与身份绑定 → 事实反馈 → 当前 Agent 或正式
  续接 attempt 收到反馈 → 修改动作 → 独立行为验证。
- post-monitor 只记录/排队 ≠ 已送达;区分 已生成/已送达/已处理/已验证。
- 验收:①不提供缺陷答案的真实 Agent 任务,Agent 真实执行、按反馈调整、
  独立探针验证;②正常/合理简化任务不误报不阻断。
- 禁止 write_text() 冒充 Agent 的错误与修复;禁止直调 apply_queued_corrections
  冒充宿主投递;假 provider 结果单独标注为协议。
- 额外模型调用按 B0 预算;无授权则先提出成本与数据范围。

## 证据与边界
- 证据:`/Volumes/Optimus/Sulde/tasks/predictive-execution/R2/<唯一运行目录>/`。
- 先存修复前反例;复用 R1 有效证据;不默认全量、不重装、不刷 cachebuster。
- 修正 prediction_feedback.py 的 diff --check 空行问题。
- 完成四项后停止交还协调端;不自行 accepted、不合并、不推送、不生产安装;
  范围外发现只登记。
