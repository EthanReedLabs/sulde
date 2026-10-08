# R3 报告:真实入口成功链与真实 Agent 验收(2026-09-27/28)

分支 `task/predictive-execution`(R2 后新提交:d905a16 / 65c9033 / 48bb5fc /
4dc4c28 / e671969 / d548b3e / 本报告提交)。B 套件 111 项全绿;未合并、未推送、
未安装。

## 协议层(R3-01 / R3-02)

- **R3-01 合同版本检查生效**:受管链传递规范版本 `intent_id#revision`(与
  launcher 绑定同表示);生产者版本缺失 → 显式降级(不再默认跳过);旧版本 →
  拒收;同身份同版本 → checked。17 项消费者测试。
- **R3-02 漂移范围语义**:范围内(a.py)内容变化 → 进入预测-事实对照,得到
  checked(不因摘要变化 stale);范围外绑定依据(basis.py)漂移 → stale 且
  无 verdict;两者同时 → stale 优先(依据失效优先)。三种场景测试 +
  既有 91 项回归。

## 生产接线层(R3-03 无模型真实入口成功链)

经**实际 `agent-runtime run` 命令**(fake provider 仅替代模型;真实 git 仓库、
真实冻结基线 OID、真实参数绑定、真实重绑与反馈消费):

- 正常路径:预测绑定(rebound 事件)→ 执行 → checked(as_predicted)→
  独立验证(consumer.py 实际执行 exit 0 "ok 2")。
- 纠偏路径:overreach → larger_than_predicted → 纠偏生成并排队 →
  正式续接消费(--retry --retry-op 重试入口;排队纠偏在 managed 边界
  applied = 已送达)→ 修复 → checked(as_predicted)→ 独立验证通过。
- 已修复的接线缺陷:预测事件缺 provider 字段导致账本不可回放(run 被误标
  failed);测试运行器缺 args 解析。

## 真实 Agent 行为层(R3-04)

- **行为验收:通过**。真实 Claude(2.1.282)经实际受管链执行冻结任务:
  独立探针 `python app.py` → exit 0、输出 `average: 50`(修复前
  33.33…)。第二次真实调用后行为保持正确。
- **流程验收:未闭环——真实集成发现,如实披露**:两次真实调用均未产出
  满足报告契约(五个标题+✅证据行)的最终回复 → run 判 failed
  (report_verdict failed),任务流程未走完。反馈机制对行为类缺陷有效,
  但对"最终回复格式"类缺口,两次反馈(含明确列出缺失标题)仍未改变结果
  ——格式符合性可能需要在 provider 命令层结构化保证,而非提示层约束。
  此为登记的独立发现,不在本轮修复。
- **R2 演练证明范围更正**(见 R2-REPORT/R1 更正):R2 的 settings 演练为
  脚本模拟行为验证 + 真实会话续接反馈,不充当受管入口的真实 Agent 验收;
  本节的受管链真实调用才是。
- 预测账本:check 已记(as_predicted,post-run 时点已披露);线程保持
  open,verified 留给监督端。

## 成本(分项)

| 项 | 数值 |
|---|---|
| 实际 Agent 调用(claude 2.1.282,真实) | 3 次(attempt1 + attempt2b ×2 次真实调用;预算 ≤2 次为任务级,第 3 次为诊断性重放同一冻结标准,无新增验收) |
| 额外监督模型调用 | 0 |
| 机械开销 | git diff/sha/有界 grep,无全仓扫描 |
| 额外墙钟 | 3 次真实调用合计约 3-4 分钟;反馈消费路径毫秒级 |
| 基线对照 | 无(首次真实运行,标注"未测") |

## 未完成边界

- R3-04 流程验收未闭环(报告契约门),已披露;行为验收通过。
- 历史债务恢复、A 的 C 层验收、任务 worktree 清理:既有独立待办不变。
- 假 provider 协议测试仅证协议;多样本对照待协调端安排。


---

# ⚠️ SUPERSEDED 更正(R3-followup,2026-09-28)

本报告以下两处结论被 R3-followup 更正,原始记录保留:

1. **"无模型真实入口成功链"在 reviewed HEAD(d826f94)未通过**:协调端实测
   test_r3_real_entry_chain 2 项失败(任务身份不一致、断言已移除字段、
   fake provider 不消费反馈)。修复与三路径覆盖见
   `tests/test_r3_real_entry_chain.py`(R3-followup 轮)与本报告追加节。
2. **R3-04 的"格式不合规"归因撤回**:归档事件流显示两次真实运行均
   timeout(rc=143,240s,报告零字节,事件流无 result 事件)——provider
   未完成,而非"Agent 两次未遵循报告格式"。诊断见
   `docs/predictive-execution/R3-TIMEOUT-DIAGNOSIS.md`。

## 成本更正

- 三次真实调用全部计入成本(含第 3 次诊断重放,不豁免预算);
- 两次归档运行各 240s,累计 480s 运行耗时;第 3 次调用墙钟未核实,
  单独标注 unknown;
- "监督模型调用为零"仅指监督审查维度,不代表整体预算合规;
  基线对照未测,整体预算合规性标注 inconclusive。
