# 0.8.6 发布分流记录(2026-09-27)

全量门禁:2731 tests,3626s,5 处失败 → 分流如下。

| 失败 | 分流 | 依据 |
| --- | --- | --- |
| encoding guard(3 条) | **已修** | test_incremental_facts.py / test_predictive_shadow.py(本任务)与 test_orchestration_r3_closeout.py(编排 A)漏 `errors="replace"`,机械补齐 |
| isolated_runner OS 边界 ERROR | 先在 | 0.8.5 轮已在 main(43be088)复现同失败 |
| distill conflict FAIL | 先在(顺序) | 两轮单独运行均 OK,仅全量套件顺序下失败 |
| doctor_session_contract ERROR | 环境 | 真实 CLI 子进程在本机重负载下超时(kb-mcp --status >20s);与代码变更无关的时序脆弱 |
| kb_mcp_entry status ERROR | 环境 | 同上,同一 20s 超时簇 |

修复后复验:encoding guard OK(2/2);其余 4 处均为先在/环境,不阻塞本发布。
