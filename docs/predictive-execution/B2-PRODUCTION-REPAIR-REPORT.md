# B2 未恢复反馈覆盖修复

状态：candidate-awaiting-independent-review，仅本次有界修复；不自行 accepted。
实现提交：d1a72963773c30ba8d2b52c90907350dfc4d18ec。
基线：7fb4c5367c3ff63922a56bcadbb0658e02116d64。
用户在明确生产修复请求后确认继续；授权边界见 B2-PRODUCTION-REPAIR-TASK.md。

## 结果与修改范围

仅一个生产文件 scripts/kb/prediction_feedback.py：completion 读取当前待反馈请求和现有
registry。当 exact request 仍在 send_unconfirmed 且未恢复，保留工件原字节与身份，
不以新 run_id 衍生的请求覆盖它；新观察仍由已有 record_check 追加记录，disclosure
显式记录 preserved_send_unconfirmed 和 deferred_request_id。

没有新队列、全局锁、审批门或 Guardian 策略；不删除历史、不自动恢复或继承权限。
不同任务/不同请求的不确定记录不阻塞本任务生成反馈；坏 JSON/类型/身份显示 degraded，
保留原工件。新预测修订不静默绑定旧反馈；原请求恢复后，旧版本仍被现有 load 校验拒收。
as_predicted 与无待反馈工件路径不增加 registry 读取；未单独进行性能基准，不量化提速。

## 验证：同测试旧红新绿

| 相同入口场景 | 基线 7fb4c53 | 候选 d1a7296 |
|---|---|---|
| B1 真实 stdin 断管 | 通过 | 通过 |
| B2 未恢复继续运行，收尾不覆盖请求 | 失败：原请求被覆盖 | 通过：原 payload 完整保留、再次预览仍阻断 |
| 紧接 B1 的显式恢复 | 通过 | 通过 |
| B2 阻断运行之后再显式恢复 | 未到达（此前断言已失败） | 通过：消费原 request、独立探针 ok 2 |

两侧同一驱动、断言和合成 provider，独立进程/源码/数据根，真实 CLI parser、run_task、
monitor_process 和原回调。只有进程/管道边界插桩；不冒充真实模型或生产权限链验收。
源码实际路径/摘要及运行后不变校验保留，禁写 pyc。失败证据没有删除或改写。

运行命令（任务 worktree；均 PYTHONDONTWRITEBYTECODE=1）：

1. `python3 -B -m unittest tests.test_r3_injection_baseline_r2 tests.test_prediction_feedback -q`
   → 41/41，10.708s。包含新增 7 项边界回归与 4 项实际入口；候选 B2 不再 skip 或倒置断言。
2. `python3 -B -m unittest tests.test_r3_real_entry_chain tests.test_r1_behavior_evidence tests.test_impact_prediction tests.test_incremental_facts -q`
   → 32/32，5.336s。覆盖正常无反馈、正常送达、无送达不自动修好、错任务、预测与事实消费者。
3. `python3 -B tests/test_r3_injection_baseline_r2.py --baseline 7fb4c5367c3ff63922a56bcadbb0658e02116d64 --candidate d1a7296 --pair <证据目录>`
   → 汇总 exit 0；旧 worker exit 1（仅 B2 目标失败），候选 worker exit 0。
4. `shasum -a 256 -c sha256.txt` → 654 项全部通过，exit 0；清单不含自身。
5. `git diff --check` → 通过。

两组定向回归共 73 项（不把双版本运行再重复计入）。改动小且消费者明确，故不跑全量；
普通正常驱动/共享 fixture 未改，旧正常证据仍保留；新生产源码的正常入口另已实际复跑。

## 持久证据

`/Volumes/Optimus/Sulde/tasks/predictive-execution/injection-verification/20260928T120000-b2-repair/`

目录名为唯一归档标识，实际时间以账本为准。包含源身份、驱动/helper、命令/原始输出/退出码、
断管边界事实、原工件、收尾与恢复前后状态、预览、消费记录、独立探针与清单。

| 项 | SHA256 |
|---|---|
| 测试驱动 | 825d4ed6ca511421b4ae0d7fec36a53790b7e747c88220082bda1b7ac6c3bc98 |
| sha256.txt | 03bf36796b321865df44ea2953e3699505c36f01dc0b82a12f3c7349a403c6b6 |

前轮 20260928T113000-b1-b2 失败档案原样保留；本次没有写生产合同或账本。
总 Token 未计量（unknown）；真实模型调用 0。不宣称正常性能量化收益。

## 收益、代价与未验收

收益：未确认发送状态不再因后续 run 换号而丢失保护；原请求既不会误标已消费，
也可以在明确恢复后继续送达。失败状态的完整链路已有永久回归。
代价：旧请求未恢复前，新观察只入原 check 账本、不会覆盖唯一投递工件；这不是丢观察。
同一任务新预测下仍保留未解决旧请求，需要明确处置；不会自动把旧反馈赋给新预测。

本次验证串行 managed 任务路径，未新增并发原子协议或证明多写者竞态安全。
mark_feedback_recovered 的生产 launcher/人审接线仍未验收，局部调用不等于该通道上线。
真实 Agent、生产 Hook/安装、A 的 C 层、历史债务、多样本与 Windows 均未因本次升级为通过。
未合并、推送或安装；前轮与本轮非作者独立复核仍待完成。

## 沉淀候选（未写知识库）

verified：恢复门控使用请求身份时，生产者必须保护该未决请求，不能通过覆盖工件换号。
路由正例：单工件槽 + run 派生新 ID + registry 精确旧 ID；反例：不同任务独立工件不应全局阻塞。
执行正例：真实失败→继续运行→收尾→再次预览仍阻断→明确恢复→独立探针；
执行反例：只测试首次 load，忽略后续 producer 覆盖。来源为本次同驱动双版本归档。
知识检索技能的“实际链路而非测试名”规则用于选择验证范围；未扩建控制面。
