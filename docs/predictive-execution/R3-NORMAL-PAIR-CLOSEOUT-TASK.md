---
assignee: existing-dev-session
branch: task/predictive-execution
capability_tier: deep
---

# R3-NORMAL-PAIR 连续收尾任务

## 目标与执行约定

在原会话、原分支和原 worktree 内，一次完成双版本正常对照的脚本修复、
有效断言、实际运行、证据归档与报告更正，再集中交还协调端。
worktree：`/Users/eric/ClaudePlugin/sulde-pro/.worktrees/predictive-execution`。

本任务是原 R3-NORMAL-PAIR 的有界返修，不是重新开始 B 项目。
执行范围内不在“修通导入”“单侧通过”“正常例通过”等中间点停止等待“下一步”。
阶段性消息仅报告进展。明确替代原先按中间测试交还的安排，最终停止点为本文件交付清单。
本轮仍是测试/证据收尾，不开放生产代码修复；发现确切产品阻断时保存最小证据，不能放宽断言。

## 起草前 baseline 实证

- 2026-09-28 协调端回读：HEAD `10e3fd415b09e9b0def66ccb7fc1e614ef6457ae`，工作树干净。
- `git diff af3a614 HEAD -- scripts/` 为空：候选生产源码与 `af3a614` 等价。
- 协调端直接运行 `python3 -B tests/test_r3_normal_pair.py`，exit 1，
  在导入 `prediction_feedback.py` 时缺 `impact_prediction`，尚未进入受管链。
- 同脚本 unittest discover 为 0 tests；不能计入通过数。
- 静态缺口：候选 revision 为 None；pf/TASK/NOW 未定义；仅打印 rc、末尾固定返回 0；
  未实现完整续接/消费/探针断言；所谓 evidence 仅写 TemporaryDirectory 后被自动清理。
- 既有 `test_r3_real_entry_chain.py` 独立复跑 4/4 通过，5.261 秒。这是当前版本入口证据，
  不是双版本证据。复用其中合法 provider、任务身份与正式 retry 的夹具，避免从头另造。
- Optimus 已有 `R3-normal-pair/20260928T060738-A6AC21A4/` 仅四份文档/摘要，
  无双版本原始运行日志。其四项源文件摘要与当前树相符，但不含新增对照脚本。
- 本轮 STATUS 未更新；报告没有汇报所称的 R1/R2 更正块。
- 知识依据：`work-model/schema-fixture-migration-and-real-execution`，已全文回读：
  夹具前置失败不能证明产品缺陷，测试名/编译通过不能代替实际执行。

## 冻结范围与身份

- 旧版：`fcd28a4b93f7d63df6b3e0445ea538e48e51c8c3`。
- 候选生产源码：`af3a614`，运行前解析并记录完整 OID。
- 允许：`tests/test_r3_normal_pair.py`、必要的专用测试辅助文件、
  `docs/predictive-execution/R3-NORMAL-PAIR*.md` 和该目录 `STATUS.md`。
  复用现有入口夹具优先；如需改共享测试 helper，说明消费者并跑相关测试，不能删除既有回归。
- 禁止：修改 scripts/、放宽生产报告契约、改 Guardian/权限、手改生产账本、
  合并 dev/main、push、安装、cachebuster、真实模型调用或真实代际清理。
- 预计影响：仅测试执行与报告，不改变生产行为。收尾比较实际 diff 与该预估。
- 启动时确认分支归属；协调端新增本任务文件属于预期未提交变更，保留并纳入任务提交。
  如其他会话新增改动，先确认归属，不 reset、不覆盖。

## 连续实施与验收

### 1. 修通同一驱动的双版本执行

两侧使用同一测试驱动、夹具逻辑、断言和配置，仅改变被测源码根；分别使用新进程、
隔离数据目录，避免 sys.modules/PYTHONPATH 串版本。记录完整 OID、实际模块路径和文件摘要，
包括 agent-runtime.py、prediction_feedback.py、impact_prediction.py 及测试驱动。
禁止把 None 当 revision。记录实际 Python/环境差异，随机路径/运行 ID 不要求字面相同。
所有 Python 进程禁写字节码，探针使用 -B；不要污染封存源码或旧证据。

### 2. 补齐并实际执行正常对照

每侧均覆盖两条正常控制路径：

- 无反馈：合法预测 → 范围内修改 → checked/as_predicted → 无反馈工件 → 独立探针通过。
- 正常送达：复用现有入口夹具，首 attempt 产生可重试的受管反馈，随后通过正式
  `--retry --retry-op` 续接；这里首 attempt 的预期失败是夹具准备，不是旧缺陷反例。

正常送达路径逐项断言：

1. 续接发送前实际工件存在，保存 request、任务/预测身份与来源 attempt。
2. 真实 provider stdin 捕获包含对应事实；通过实际 schema 可用的身份/事实关联到源工件，
   不强求生产 prompt 存在未定义的字段，不仅凭一个通用标题断言。
3. 发送成功、无 send_failed；exact request 的消费记录绑定真实消费 run，来源与消费可区分。
4. provider 正常退出且受管任务结论成功、报告解析通过，不能只看 provider exit 0。
5. 独立执行 consumer.py 得到预期输出与 exit 0，不采信模拟报告里写的“验证成功”。
6. 断言不是空集合过滤后的假绿；缺必需字段/无执行/skip/异常均不得算通过。

模拟 provider 报告仅作协议夹具，其占位内容不能冒充真实验证凭据；实际探针单独留证。
让测试入口在任一侧失败时非零退出。若使用独立 CLI 驱动，明确真实执行命令，
不得把 unittest 的 0 tests 当成功；提供一个缺失必需运行事实/失败结果的测试工具负控，
证明汇总器不会吞失败（不修改生产源码、不伪造旧缺陷）。

### 3. 归档与集中收尾

运行输出生成后、临时目录销毁前，归档到：
`/Volumes/Optimus/Sulde/tasks/predictive-execution/R3-normal-pair/<新唯一目录>/`。
保留两侧命令、stdout/stderr、退出码、断言结果、源码身份、驱动/夹具摘要、
必要的运行账本/消费记录、合成任务的 stdin 及独立探针输出。
不采集真实 prompt、密钥或隐藏推理；临时/正式数据根明确隔离。
目录存在即拒覆盖；挂载不可用则说明归档阻塞，不静默换盘或覆盖旧目录。
清单使用归档内可解析路径、不含自身；独立回读验哈希及两侧结论。

更新本轮报告和 STATUS：追加 supersedes 更正，保留原记录，明确原单版本 4/4 不能证明
双版本成功、原归档缺运行日志、原 R1/R2 更正未落盘。报告写精确 revision/命令/结果，
不要以“当前 HEAD”或目录名代替证据身份。

## 验证成本和停止线

- 顺序：最小静态/导入检查 → 双版本正常对照与测试工具负控 → 受影响测试。
  不在前置仍失败时重复跑 133 项或全量；未改共享输入的证据可按等价性复用。
- 实际入口已包含在双版本驱动内，不额外开真实模型；本轮模型调用预算为 0。
- 同一失败两次无新证据，检查首个失败前置并换诊断方法，不盲加 prompt/timeout。
  换方法后仍无法取得新证据，或确需修改生产代码/权限/外部条件时，交还准确 blocker，
  不再以“全部完成”结束。记录实际耗时；不可计量的 Token 标 unknown。
- 上下文不足先保存完成项、证据和下一动作，续接同任务；不重跑已证明等价的步骤。
- 本轮通过只证明双版本正常控制有效，不证明 EPIPE 故障修复、真实 Agent 能力或安装就绪。
  故障注入阶段、历史债务、A 的 C 层、Windows 和多样本不加入本轮验收。

## 最终交付

所有本轮验收通过后提交原任务分支，交还一份集中报告与精确证据路径，状态为
`normal-pair-awaiting-independent-review`；未通过则 `incomplete` 并写精确阻塞。
不自行 accepted。不要每修一个脚本问题提交一份“本轮完成”并等待再次派单。
