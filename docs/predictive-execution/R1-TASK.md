# R1 任务:预测式执行修复轮(协调端 2026-09-27 签发)

工作区 `.worktrees/predictive-execution`,分支 `task/predictive-execution`。
已对齐 dev `f932ca8`(原候选 dcd4fb5 已在 dev/main)。不改原方案与历史证据;
本文件为唯一任务清单,完成边界见文末。

## R1-01 统一预测状态回放
已复现:投影 closed 后 `revise_prediction` 仍接受并变回 open。
- 所有修改入口(open 之外的 revise/stale/check/close)消费同一权威投影回放,
  正确处理 stale/closed。
- 关闭后的修订拒绝;重新开始走显式新生命周期(open 新线程)。
- 覆盖:关闭后修订、重复关闭、失效后修订、正常修订。

## R1-02 补齐纠偏回放验证
已复现:`_apply_event` 接受 actor=agent、无证据的 verified(回放不执行与
入口相同的校验)。
- 转换入口与回放执行同一不变量:verified/closed 限 human/system;
- 验证证据绑定问题与结果:`evidence_sha256` 必须等于
  `sha256(intervention_id + "\0" + verification_summary)`,summary 非空;
- v1 历史兼容,旧 applied 不自动升级 verified。
- 覆盖:非法验证者、缺失/错配证据、合法监督验证、历史回放。

## R1-03 补齐"实际少于预估"事实
已复现:预计 a.py+b.py 只改 a.py 时仍返回 as_predicted。
- 机械层显式列出未触及的预计范围(`untouched_expected`),交 Agent 判断
  合理简化还是遗漏消费者;
- 不把"少改文件"直接判为缺陷或触发人工拦截。
- 覆盖:精确路径、目录范围、合理简化、真实遗漏。

## R1-04 接通一个真实执行入口
- 复用 agent-runtime 受管任务链:预测 → 增量事实 → 当前 Agent 收到反馈 →
  调整动作 → 独立验证 → 关闭;有实际生产消费者,非仅手工 CLI。
- 绑定 task/run/session、预测版本与源码身份;过期/跨任务反馈不作用于当前任务。
- 复用既有纠偏/恢复通道;交互宿主未接通部分显式保留为未支持。

## R1-05 行为证据替换"写入答案"验收
- 保留协议测试,撤回其"自动发现缺陷"证明范围。
- 至少验证:①未揭示答案的缺陷任务(完成前触发判断、Agent 实际收到反馈并
  改变动作、独立验证原失败行为修正);②无缺陷/合理简化任务不误报不阻断;
  ③经验召回经正式入口改变后续动作(非仅保存 ID)。
- 保存初始输入、触发时点、反馈、后续动作、最终结果;判定标准与执行输入分离。
- 假 provider 只证协议;额外模型调用遵守 B0 冻结预算。

## 证据与完成边界
- 证据:`/Volumes/Optimus/Sulde/tasks/predictive-execution/R1/`;
- 先存修复前反例再修;不默认重跑全量;不重复安装、不刷 cachebuster;
- 五项逐项提交;更新 STATUS.md 与 R1-REPORT.md(协议/生产接线/真实行为/性能分开报告);
- 不自行 accepted、不合并、不推送、不生产安装;不顺手修历史债务或其他控制面问题。
