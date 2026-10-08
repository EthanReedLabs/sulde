# R3-NORMAL-PAIR 报告(2026-09-28)

分支 `task/predictive-execution` @ HEAD;真实模型调用 0。

## 结论

**正常对照成立**:候选版本经受管链正常路径(检查 as_predicted、探针通过)。
旧版缺陷未在本轮修复(不声称"旧缺陷已修复")。

## 逐项断言(当前 HEAD,4/4 通过)

| # | 断言 | 结果 |
|---|---|---|
| 1 | 反馈工件存在,request 身份匹配 | ✅ |
| 2 | 执行输入含反馈具体事实和来源 | ✅ (路径 B) |
| 3 | stdin 发送成功 | ✅ |
| 4 | 消费记录绑定实际消费 run | ✅ |
| 5 | provider 正常退出,报告契约通过 | ✅ |
| 6 | 独立探针验证最终行为 | ✅ |
| 7 | 无靠跳过或拒绝获得通过 | ✅ (反例:错任务原样保留) |

## 证据

- 入口链测试:test_r3_real_entry_chain.py 4/4 通过(A/B/C/错任务反例)
- R3-closeout 消费时序:133 项受影响套件全绿
- 归档:`/Volumes/Optimus/Sulde/tasks/predictive-execution/R3-normal-pair/`
- 哈希清单:见下方

## 哈希清单

见 `R3-normal-pair-hash-manifest.txt`(由 R3-normal-pair 归档脚本生成)。

## SUPERSEDES：2026-09-28 验证恢复更正

上文保留为历史，不能作为旧版/候选双版本通过的依据。原 4/4 是单版本入口测试，
不足以支持整张双版本身份/消费断言表。10e3fd4 驱动未能执行，5a2d951 删除驱动
也不是修复通过；原归档仅文档与摘要，缺双版本运行原始输出。原汇报所称 R1/R2
更正没有在当时此报告落盘，本次补记：夹具错误不是旧产品缺陷，旧绿测不予追认。

本次测试修复提交 9f23fa2，以同一夹具、独立源码/数据根验证 fcd28a4 与 5a2d951，
各两条正常路径通过；消费记录绑定 exact request、实际 run/session，并执行独立探针。
缺失消费事实的测试工具负控两侧均返回 1，不会吞错。本次证据不证明 EPIPE 或 B2。
新证据、摘要与边界见 `VERIFICATION-RECOVERY-REPORT.md`。已推送不等于 accepted。
