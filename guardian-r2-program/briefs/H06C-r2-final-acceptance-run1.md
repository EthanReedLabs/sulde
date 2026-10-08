/model
选择:gpt-5.6-sol（若当前可用列表无此型号，选择 deep 档或更高的 Codex 模型）
/reasoning
选择:high 或更高
执行任务文件:guardian-r2-program/task-definitions/H06C-r2-final-acceptance.json

# H06C run1 — 构建总纲回放与故障注入候选

你在 exact detached validation worktree `f0e845617867c1710b636205c6798d03140d1646` 上执行。控制权仍属于 `guardian-r2-coordinator`；不得写控制账本、不得提交、不得安装、不得修改 scheduler、不得 push/merge、不得调用 Claude、不得操作生产 intent/KB 或中断其他会话。

## 本轮允许输出

- `tests/fixtures/r2-guardian-incidents/**`
- `tests/test_r2_guardian_integration.py`
- `guardian-r2-program/reports/H06C-r2-final-acceptance.md`

任务定义列出的 H06C evidence 文件由协调器独占，本轮禁止创建或修改。其他生产代码路径全部只读；发现缺陷只写入报告的 findings，不在验收任务中顺手修复。

## 必做

1. 完整读取外部控制根中的 canonical H06C brief、task definition、`guardian-r2-program/fixtures/incidents.json` 和 R2 总纲第 5–9 节。
2. 建立机器可读的 I01-I19 回放测试，并覆盖并发冲突、事务阶段进程死亡、receipt tamper、world-state drift、UI 不展示、只读账本、scheduler degraded、rollback、重复 callback、外部内容安全提示分类。
3. 测试必须调用当前集成实现的公共边界，禁止仅断言 fixture 自己；对必须由真实宿主/设备证明的门，使用明确的 deferred/blocked 断言，禁止 synthetic callback 冒充 live PASS。
4. 形成任务报告，逐项记录发现的问题、解决或转移方式、运行命令、退出码、跳过原因、remaining risks 和最终可达到的状态。Claude/Windows/production install/fleet-safe quiet 尚无真实证据时必须保持开放。
5. 先跑 focused tests，再跑无需生产写入的相关 isolated suite。使用 `PYTHONDONTWRITEBYTECODE=1` 与 `python3 -B`；完整日志留在 `.codex-agent`，聊天/报告只保留摘要。

## 终态

成功仅表示生成可复审的本地回放候选，不表示 H06C accepted 或 R2 complete。任何实现缺口、测试失败、scope drift 或宿主 gate 缺失都必须在报告中明确列出，交回协调器登记 finding。
