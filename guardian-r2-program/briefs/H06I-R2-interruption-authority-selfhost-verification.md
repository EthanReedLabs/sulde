/model
选择:gpt-5.6-sol（若当前可用列表无此型号，选择 deep 档或更高的 Codex 模型）
/reasoning
选择:high 或更高
执行任务文件:guardian-r2-program/task-definitions/H06I-R2-interruption-authority.json

# H06I-R2 — self-hosted canonical receipt verification only

## Authority

- 本轮不是实现候选、返修候选或新任务；它是 `SCOPE-FREEZE-AMENDMENT-002.json` 授权的唯一一次自托管验证。
- task identity 仍为 `H06I-R2-interruption-authority`，task definition SHA-256 仍为 `55ebd49197d5c940394fd405224b2814d28b290a81e3cd481c4c5d4bcac377c2`。
- 现有五个候选路径已经冻结；禁止使用 `apply_patch`、禁止创建/删除/修改任何仓库文件、禁止 Git 写入、禁止运行安装器、禁止网络、禁止 push/merge/install/scheduler/production 操作。
- 当前进程由隔离的非生产 self-hosted authority 启动；不得调用或依赖 Claude。

## Frozen candidate

- `scripts/kb/native_agent_broker.py`：`0393e1bb5c2cee278f06eb3c2ca2a068aba481cff82beacb28ae0205a0af39c7`
- `scripts/kb/agent-runtime.py`：`d8d7406595174dc9379c998327a0b6665aac09128840d95471df6e9eca9082a9`
- `tests/test_native_agent_broker.py`：`0ed8ced54a46fe6fbcbb1ee746aa6dec33692ba1ef644d1d4d38bce679f88850`
- `tests/test_agent_runtime.py`：`59533ccdcf701ccd72c0b1e3882a2b4e839a99b7a56e6254d13fe7c78f2795f6`
- `guardian-r2-program/reports/H06I-R2-interruption-authority.md`：`f8d1e5a984870c81cd8bb659254c820840ded41ef0ea0ce1fe45f76b2efccf18`，10589 bytes，恰有一个 terminal LF。

## Exact action

1. 只读核验 durable report 的 SHA-256 和长度；可用一条只读命令：`shasum -a 256 guardian-r2-program/reports/H06I-R2-interruption-authority.md && wc -c guardian-r2-program/reports/H06I-R2-interruption-authority.md && sed -n '1,240p' guardian-r2-program/reports/H06I-R2-interruption-authority.md`。
2. 不执行其他工具，不修改任何文件。
3. 最终回复只包含该 durable report 的完整正文，逐字符保持原样；不要加代码围栏、前言、结语、摘要或验证说明。
4. provider final text 可以无 terminal LF，也可以有恰好一个 terminal LF；self-hosted runtime 会把它规范为恰好一个 LF，并要求 canonical bytes 与 durable report 完全相等，再绑定 `.last.md`、`output_summary`、`report_summary` 和 native receipt。

## Fail-closed rule

- 无法逐字返回、任何路径发生变化、report digest/长度漂移、receipt 两个 summary 不同或 self-hosted authority 不是候选 runtime/broker 字节时，本轮必须失败并停止。
- 失败后不得重试、不得修改候选、不得创建第三实现候选或新 task identity；只保留红证据交回协调器。
