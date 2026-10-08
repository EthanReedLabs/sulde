# R3-CLOSEOUT 任务:合同/续接身份校验、消费时序恢复、超时诊断精化(2026-09-28 签发)

Reviewed HEAD `b81a941`;分支 `task/predictive-execution`,worktree 不变。
保留 R1/R2/R3 已通过成果;真实模型调用预算 0。

## 一、合同与续接身份校验
- 生产路径先 rebind 覆盖合同版本再校验 → 旧反馈可跨合同修订被放行。
- 修复:先验证原预测绑定、反馈来源合同与当前合同,再更新执行身份;
  rebind 只记录 attempt_contract_version(不覆盖预测绑定的 contract_version)。
- attempt 合同 ≠ 绑定合同 → 反馈失效保留(明确拒收),不被消费;
  同合同合法续接正常消费,不继承授权。
- 校验来源 attempt 与消费 attempt 的关系(非仅不相等)。
- 回归经实际 agent-runtime run 生产顺序。

## 二、反馈消费时序与恢复
- 现状:stdin 写入前登记 consumed 并删工件;registry 写后、删前崩溃会重复投递;
  spawn 成功被当作已发送。
- 修复:准备输入 / 发送结果 / 接收处理证据 分开;发送成功(stdin 写入+关闭
  无错)后才登记消费;登记参与 load 判定;损坏状态显式降级;未启用预测任务
  零新建文件;残留清理绑定精确 request 身份;不确定发送如实记录。
- 覆盖 7 场景:启动失败可恢复;stdin 失败不伪记;registry 已落盘未清工件→
  不重复消费;已消费 request 再现被识别;不同请求不被误删;错合同/非法来源
  不进执行输入;无预测任务零新建。

## 三、超时诊断精化(只读归档)
- 配对 permission_denied(r3fix 3 次、r3fix2 4 次)的 tool_use_id、后续动作与
  可见结果;区分"240s 未完成"与"240s 设置不足";权限阻碍纳入分析,
  贡献不可定标 inconclusive;不扩大权限、不关守卫、不改生产配置;
  给出下次真实验收的最小权限/输入准备;不默认建议延长超时。

## 交付
- R3-CLOSEOUT-REPORT.md、STATUS.md、超时诊断更新;
- 证据:`/Volumes/Optimus/Sulde/tasks/predictive-execution/R3-closeout/<唯一>/`;
- 逐项提交;不自行 accepted、不合并、不推送、不安装;真实模型调用 0。
