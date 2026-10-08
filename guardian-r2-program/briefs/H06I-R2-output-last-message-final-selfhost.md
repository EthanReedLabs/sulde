/model
选择:gpt-5.6-sol（若当前可用列表无此型号，选择 deep 档或更高的 Codex 模型）
/reasoning
选择:high 或更高
执行任务文件:guardian-r2-program/task-definitions/H06I-R2-interruption-authority.json

# H06I-R2 — output-last-message final self-host verification only

## Authority

- 本轮不是实现、返修或新 task identity；它是 `SCOPE-FREEZE-AMENDMENT-003.json` 授权且由 `H06I-R2-FINAL-REPAIR-FREEZE.json` 绑定的唯一 Stage 2 自托管验证。
- task identity 仍为 `H06I-R2-interruption-authority`，task definition SHA-256 为 `55ebd49197d5c940394fd405224b2814d28b290a81e3cd481c4c5d4bcac377c2`。
- 当前进程必须由隔离的非生产 self-hosted authority 启动，其 runtime/broker 必须精确来自下列冻结字节；不得调用或依赖 Claude。
- 禁止 `apply_patch`、禁止创建/删除/修改任何仓库文件、禁止 Git 写入、安装器、网络、production descriptor、scheduler、commit、push、merge、dev/main 或 H06J。

## Frozen candidate

- `scripts/kb/native_agent_broker.py`：`0393e1bb5c2cee278f06eb3c2ca2a068aba481cff82beacb28ae0205a0af39c7`
- `scripts/kb/agent-runtime.py`：`df5b6badc657c4f2b57d8c068fc65d3e713afb7a3af906701cd0d90cf04b4d6a`
- `tests/test_native_agent_broker.py`：`0ed8ced54a46fe6fbcbb1ee746aa6dec33692ba1ef644d1d4d38bce679f88850`
- `tests/test_agent_runtime.py`：`215f3a97494f5d9d770d03201d2329f2cc7f13bb24cc7e7a22878c9f11071217`
- `guardian-r2-program/reports/H06I-R2-interruption-authority.md`：`f76718d8fb90b94205afc24971b69b0e5f85f94683b1e039d617eda550b7310a`，18542 bytes，恰有一个 terminal LF。
- Stage boundary：`guardian-r2-program/H06I-R2-FINAL-REPAIR-FREEZE.json`。

## Exact action

1. 只读核验 durable report 的 SHA-256、长度和正文；只运行：`shasum -a 256 guardian-r2-program/reports/H06I-R2-interruption-authority.md && wc -c guardian-r2-program/reports/H06I-R2-interruption-authority.md && sed -n '1,240p' guardian-r2-program/reports/H06I-R2-interruption-authority.md`。
2. 不执行其他工具，不修改任何文件。
3. 最终回复只包含 durable report 的完整正文，逐字符保持原样；不要加代码围栏、前言、结语、摘要或验证说明。
4. 当前 runtime 会在 provider 完全退出且 stdout reader 结束后，从自己规划的 `--output-last-message` 文件取得 final output authority；JSONL 仅用于观测。它会将无 terminal LF 或恰好一个 LF 规范为恰好一个 LF，并要求 canonical bytes、durable report 与 `.last.md` 完全相等。

## Acceptance

- 五个候选路径在运行前后摘要全部不变。
- fresh interpreter 验证隔离 runtime tree 与 native authority；runtime/broker 摘要精确等于冻结值。
- provider 只调用一次并正常完成，cleanup quiescent。
- run ledger 的 `output_present=true`，其 digest 绑定 output-last-message 正文。
- `.last.md` 与 durable report byte-identical，长度均为 18542，末尾恰有一个 LF。
- native receipt 的 `output_summary` 与 `report_summary` 完全相等；task report verdict 与 terminal invariants 全部通过。

## Fail-closed rule

- 无法逐字返回、任何路径或摘要漂移、authority 不匹配、ledger 无 output、report 字节不同、receipt summaries 不同或任一 terminal invariant 不满足，本轮必须失败并停止。
- 本轮没有重试余额；失败后不得修改候选、创建新候选/新任务或启动 H06J，只保留追加式红证据交回协调器。
