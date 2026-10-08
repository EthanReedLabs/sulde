# B1/B2 有效验证交付

历史报告：其中 B2 未修复状态已由 B2-PRODUCTION-REPAIR-REPORT.md 的候选修复证据取代。
以下失败事实和当时 tests-only 边界保留，不改写为旧版本通过。

状态：incomplete — 候选 B2 产品不变量失败，按 tests-only 边界停止。
基线：task/predictive-verification-recovery-20260928@fd02cce。
本轮接手的是已停止 Dev 任务，未另建分支。正常对照作者亦为本执行者，
前轮独立复核仍待非作者完成；不得用此次接手冒充独立 accepted。

## 交付与边界

替换原 tests/test_r3_injection_baseline_r2.py 的无效夹具与断言，仍保留三个原场景，
新增显式恢复场景。复用未修改的 _Chain 与正常双版本驱动工具函数。
scripts/、Skill、生产账本、安装均未修改，无真实模型调用、合并或推送。
不是生产故障修复提交；失败测试不 skip、不 expectedFailure、不倒置成通过。

## 可观察结果

| 场景 | old fcd28a4 | candidate 5a2d951 |
|---|---|---|
| 正常无反馈/正常送达 | 复用已归档正常双版本证据 | 同左；当前正常例亦复跑通过 |
| B1 实际 stdin 失败 | 失败：误消费、删工件，无失败事实 | 通过：失败事实 + send_unconfirmed，未消费、工件字节保留 |
| B2 未恢复后继续运行 | B1 前置已违反，不称 B2 被测通过或失败 | 失败：收尾覆盖原待恢复请求 |
| B2 显式恢复后续接 | 同上；源码没有恢复 API，不伪造兼容接口 | 通过：原 exact request 消费绑定新 run、独立探针 ok 2 |

被测精确提交：
- old：fcd28a4b93f7d63df6b3e0445ea538e48e51c8c3。
- candidate：5a2d951a50cea246d52cbc827e0ef63c0053fd7e。
- 当前分支 scripts/ 与 candidate 等价；按 commit 提取到不同临时目录、新 worker 进程和隔离数据根。

### 注入真实性

实际首 attempt 产生合法反馈，request 与源运行账本精确关联。
仅在 subprocess.Popen/真实 stdin 边界插桩：实际 provider 关闭 fd 0 并退出，
等待整个 managed wrapper 退出（上限 5 秒），再由原 run_task/monitor_process 写入并关闭。
stdin observer 只转发 write/close，记录真实 OSError 后原样抛出，不制造异常。
实际捕获 close → BrokenPipeError errno=32；未依赖 >64KB prompt 或随机 sleep。
run_task、monitor_process、回调工厂和消费函数均使用该版本原实现，不替换。
子入口通过 runpy 运行原 agent-runtime.py 的 __main__，使用真实 CLI parser/run 路径。

这是插桩入口 + fake provider 的协议证据，不是未插桩真实宿主或生产权限链证明。
test_mode 与合规模拟报告的边界沿用已披露 _Chain；最终行为由独立 probe 验证。

## B2 确定根因及边界

1. B1 在候选真实产生 send_unconfirmed[old_request]，工件保留。
2. load_pending_feedback（scripts/kb/prediction_feedback.py:125）按 request_id 查 registry，
   正确返回 send result uncertain；下一真实 attempt 的新 stdin 确实不含反馈。
3. 该 attempt 没修复越界结果，收尾再次 record_completion_feedback。
4. 同文件 :367 把新 run_id 纳入 request_id，:369 仅按新旧 request 相等去重，
   :388 写同一个 task 工件路径，覆盖仍未恢复的旧请求。
5. registry 只保护旧 ID；对新工件再次实际调用 load_pending_feedback 得到 delivered。
   证据为 blocked-preview.json 与 next-preview.json；未将这个预览升级为“又实际发送一次”。

因此这是生产者覆盖策略与消费者恢复门控的接线缺陷，不是 B1 修复失效，
也不是权限/审批越权的证明，更不是本轮 tests-only 改动引入的新回归。
直接显式恢复路径通过不能掩盖“未恢复→运行收尾→请求换号”的失败路径。
无关任务工件在该失败前独立断言字节不变。

## 证据与命令

正式归档：
`/Volumes/Optimus/Sulde/tasks/predictive-execution/injection-verification/20260928T113000-b1-b2/`。

- `PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test_r3_injection_baseline_r2.py --pair <上述目录>`
  → exit 1。summary.json 分别记录失败/通过/not_reached_b1_failed，不把前置失败合并成多个产品缺陷。
- `PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest tests.test_r3_injection_baseline_r2 -v`
  → 4 项，3 通过、1 失败，8.307s；唯一失败为 B2 pending request overwritten before recovery。
- `shasum -a 256 -c sha256.txt` → 596 项全部通过，exit 0；清单不含自身。
- `git diff --check` → 通过。生产/Skill diff 为空。

归档含两侧源码实际路径与摘要、相同驱动副本、命令与 stdout/stderr、错误同步事实、
原 request、失败后及运行收尾后合成账本、stdin、恢复结果与独立 probe。
源三个模块运行后重新哈希相同、无 pyc；旧目录未覆盖，普通测试仅写临时目录。

| 文件 | SHA256 |
|---|---|
| test_r3_injection_baseline_r2.py | ead01bd6ee99cab7f98580d95b4fa165ae3858ee18c4381aebfeaa8000e46ad5 |
| sha256.txt | fc2e7850e0e4c847334cdbfdf9a3d90fd0b9bcca3660e93f612a26a426aad099 |

正常双版本驱动/共享 helper 未修改，沿用 R3-normal-pair/20260928T111000-recovery/ 的有效证据。
生产缺陷已被实际入口复现，未再跑全量或无关模块凑通过数。局部测试增加为 4 项，
符合预估的测试/报告范围；总 Token 未计量（unknown），真实模型调用 0。

过程披露：首次技能登记将合同路径手误拼错，纠正为宿主给定路径后登记成功；
首次 apply_patch 因同路径删除/新增格式被工具拒绝，随后分步替换；均非产品根因。
首轮双版本诊断目录 /private/tmp/sulde-injection-check-20260928-a 仅临时诊断，
正式归档将旧版 B2 的前置失败明确标为 not_reached，未重造旧成功证据。

## 下一步建议（待扩大生产修复授权，不自动实施）

仅修复 prediction_feedback.py 的生产者/消费者一致性：当同任务仍有精确未恢复
请求时，后续 completion 不得把唯一待恢复工件覆盖为新请求；保留旧事实并明确披露
本次新观察的处置。恢复必须精确绑定原 request，不靠全局放行或删除 registry。
优先复用已有生命周期，不新建 Guardian 门禁；考虑新预测修订/不同任务不被误绑。
先使本报告 B2 反例转绿，再跑直接恢复、B1、正常链及受影响模块。
若需要新增跨任务协调或更大 schema 变更，应单独提出，不能在此测试轮偷改。

## 沉淀候选

verified（仅上述协议）：逐函数通过不能保证未确认状态跨运行保持。
路由正例：恢复标识按 request 记账，而生产者每轮改 request 并覆盖同路径；
路由反例：新任务/新预测与旧事实有明确隔离且历史请求不会丢失。
执行正例：失败→下一实际运行→收尾→再次读取的完整状态路径；
执行反例：只给 registry 塞一行、工件不存在就断言 None，或以空 consumed 判未误消费。
来源为上述归档与源码定位；未写正式知识库。
