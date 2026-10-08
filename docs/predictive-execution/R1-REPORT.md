# R1 报告:预测式执行修复轮(2026-09-27)

分支 `task/predictive-execution`(自 `dcd4fb5` 对齐 dev `f932ca8` 后推进)。
五项逐项提交;B 套件 **97/97 通过**(2.2s);未合并、未推送、未安装。

## 协议层结果

| 项 | 反例(修复前) | 修复 | 覆盖 |
|---|---|---|---|
| R1-01 | closed 后 revise 仍接受并变回 open | 所有变更入口统一消费 `load_projection` 权威回放;closed 拒绝 revise/check/close(重复关闭拒绝);stale 可修订;重新开始=显式新线程 | 关闭后修订、重复关闭、失效后修订、正常修订(4 测试) |
| R1-02 | 回放接受 actor=agent、无证据的 verified(伪造账本行) | `_apply_event` 执行与入口相同不变量;verified 证据绑定 = `sha256(intervention_id+NUL+verification_summary)`,摘要必须描述实际结果;v1 账本兼容回放,旧 applied 不升级 | 非法验证者、缺失/错配证据、合法监督验证、历史回放 |
| R1-03 | 预计 a+b 只改 a 仍 as_predicted | 返回 smaller_than_predicted + 显式 `untouched_expected` 清单;目录范围前缀计入触及;"合理简化 vs 真实遗漏"由 Agent 判断(两条合法判断路径演示),机械层不下结论不拦截 | 精确路径、目录范围、合理简化、真实遗漏 |
| encoding 回归 | 3 处(本任务 2 + 编排 A 1) | 机械补齐 `errors="replace"` | guard 2/2 OK |

## 生产接线结果

- `prediction_feedback.record_completion_feedback` 接入 agent-runtime 受管链
  (run 命令 post-monitor 位):有预测的任务在完成后得到机械对照 + 账本 check +
  非平凡判定走既有纠偏通道(managed_run_monitor 边界排队);无预测任务零开销
  (一次 stat)。
- 身份纪律:run_id 绑定拒绝跨运行反馈;stale 跳过不复活;closed 不结算;
  proposal 去重走纠偏存储 request-digest 幂等映射;消费者失败降级为账本披露,
  运行继续。8 项消费者测试。
- 发现并修复两个接线期真实缺陷:fact bundle 顶层缺 changed_paths(误判
  smaller);代际演练 runner 契约错配(0.8.6 发布门禁期间,已在 main 修复 f932ca8)。
- **未接通(显式保留)**:交互宿主无实时注入;纠偏文本按方案只存摘要,
  投递文本由提议方在下一 attempt 组装。

## 真实行为结果

> **R2-01 更正(2026-09-27)**:本节的"真实行为"实为**脚本模拟的行为验证**
> ——attempt 1 的越权和 attempt 2 的修复均由测试脚本 write_text() 构造,
> 不是真实 Agent 在收到反馈后自行改变动作。原始记录保留如下,不改写;
> 真实 Agent 行为证据由 R2-04 单独交付。

- `tests/test_r1_behavior_evidence.py`:执行输入不含答案(任务只说"导出 VALUE")。
  attempt 1 过度触及并破坏 consumer.py → 反馈在交付前触发
  (larger_than_predicted + 排队纠偏,含具体事实);attempt 2 收到边界反馈后
  改变动作(修复破坏的 import);**独立验证=实际执行 consumer(exit 0,"ok 2")**,
  不依赖预测;纠偏由监督者 verified(绑定摘要)结算。
- 经验召回链:后继不同任务经 `experience.recall` 正式入口召回 verified 经验,
  其 recommended_tests 被真实执行(行为改变),并以 `based_on_experience`
  进入新预测。
- 排查过程中发现并修复一个真实环境缺陷:同秒同大小改写导致陈旧 pyc 被判定
  有效(探针现用 `-B` + PYTHONDONTWRITEBYTECODE)。

## 性能结果

- B 套件 97 项 2.2s;反馈消费路径为纯本地 git diff + 文件 sha + 有界 grep,
  无模型调用;新增模型审查 0 次(B0 预算内)。

## 实施卡点(如实)

- shadow 场景夹具把答案写入输入(方案 §7 禁止的形式),已按 R1-05 撤回其
  "自动发现"证明范围,改为协议测试;真实行为证据由本报告行为运行承担。
- 纠偏文本摘要化与"投递含具体事实"存在张力:文本不入库是既定隐私边界,
  投递内容由提议方(父级/协调端)在下一 attempt 组装,消费方返回披露供组装。
