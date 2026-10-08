# R3-CLOSEOUT 报告(2026-09-28)

分支 `task/predictive-execution`,reviewed HEAD `b81a941` → 本轮至
`<最终提交,见 git log>`。受影响套件 **133/133 通过**(8.8s)。真实模型调用:0。

## 一、合同与续接身份校验(R3-closeout 一)

**修复的核心缺陷**:生产路径先 rebind(把预测绑定的 contract_version 覆盖为
当前 attempt 的合同)再做一致性检查 → 旧反馈可跨合同修订被放行。

修复后语义(`impact_prediction.rebind_attempt` + `load_pending_feedback`):

- rebind 只记录 **`attempt_contract_version`**(当前 attempt 的合同)并更新
  session 绑定,**不再覆盖**预测绑定的 `contract_version`;
- 反馈可投递当且仅当:工件/预测/来源归属一致 + `artifact.contract_version ==
  bound contract_version`(同合同的合法续接正常消费,不继承授权——rebind
  事件只含身份摘要,无 grants);
- attempt 合同 ≠ 绑定合同 → 反馈**明确失效**:工件保留、不被消费,原因为
  "contract changed during continuation"。

生产顺序回归:链路测试经**实际 `agent-runtime run` 命令**覆盖完整顺序
(prompt 前重绑 → 执行输入组装 → spawn 后 run 绑定确认 → 反馈消费):
新合同的续接 → 反馈失效保留(工件仍在);同合同 → 反馈段进入执行输入。
单元级:错任务工件不被消费入口读取且原样保留;过期(版本不匹配)反馈
不带入新修订。

## 二、消费时序与恢复(R3-closeout 二)

时序拆分:`monitor_process` 新增 `on_input_delivered` 回调——仅在
**stdin 完整写入并关闭成功后**调用;run_task 传入闭包完成消费登记
(真实 run/session 摘要入 registry)+ 账本 `prediction.feedback_consumed` 事件。
stdin 写入/关闭失败 → 记录 `send_failed` 并跳过登记(工件保留可恢复),
异常上抛由既有失败路径处置。

- 消费登记**参与加载判定**:`load_pending_feedback` 读取 registry——
  已消费 request 不再投递;工件残留但登记在案 → 按精确 request/task 身份清理残留。
- 未启用预测任务:rebind/load 均在 store 缺失时提前返回,零新建文件(测试断言
  state 目录为空)。
- 降级:账本/工件损坏 → degraded 披露,不锁死普通任务,不伪造状态。

七场景覆盖(新增 6 项 ConsumptionTimingTests + 既有恢复测试):

| 场景 | 结果 |
|---|---|
| 1 启动失败 | 工件保留、registry 空、load 仍可投递(可恢复) |
| 2 stdin 发送失败 | 确认不发生(回调仅在写入+关闭成功后触发);发送失败事实入账 |
| 3 registry 已落盘、工件未清理 | 不重复消费;残留按身份清理 |
| 4 已消费 request 再现 | 识别,不二次投递 |
| 5 不同请求 | 不被旧确认误删 |
| 6 错合同/非法来源 | 不进入执行输入;自来源消费被拒 |
| 7 无预测任务 | 零新建文件 |

## 三、超时诊断精化(R3-closeout 三)

详见 `docs/predictive-execution/R3-TIMEOUT-DIAGNOSIS.md` 追加节。要点:

- permission_denied 配对:r3fix 3 次(Bash:`python app.py` 组合命令 multi-op
  审批 + 2 次验证类命令 requires approval);r3fix2 4 次(1 次 Bash 读
  Optimus 外部文件 + 3 次 Read workingDir 拒绝:冻结任务书/历史输出位于
  worktree 之外)。
- 修正归因:**结构性冲突**——报告契约要求 ✅ 证据行(实际命令+exit 0),
  而 provider 权限轮廓拒绝了验证命令本身;数值修复远早于超时完成。
  "240s 设置不足"与"240s 内未完成"两种表述均被替换为:
  权限轮廓使报告契约在该配置下不可满足。
- 贡献量化 → **inconclusive**(无反事实运行);不以此放宽沙箱/扩大权限。
- 下次真实验收最小准备:settings.permissions.allow 预置只读验证命令
  (如 `Bash(python app.py)`),或以监督端探针输出替代执行者自证;
  冻结任务与输入放入 worktree 内。

## 成本

- 真实模型调用:0;额外监督模型调用:0;
- 机械开销:确定性脚本(git/sha/有界 grep),毫秒级;
- 额外墙钟:本轮入口/套件运行合计 < 1 分钟;与真实 Agent 任务级的
  墙钟对照:未测(无真实运行)。

## 未完成边界(登记)

- 真实 Agent 验收仍待:按第三节最小准备重跑(需生产隔离下的授权与真实调用);
- 多样本对照、历史债务恢复、A C 层验收、任务清理映射:既有独立待办不变。
