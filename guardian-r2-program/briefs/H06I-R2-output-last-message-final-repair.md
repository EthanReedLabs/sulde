/model
选择:gpt-5.6-sol（若当前可用列表无此型号，选择 deep 档或更高的 Codex 模型）
/reasoning
选择:high 或更高
执行任务文件:guardian-r2-program/task-definitions/H06I-R2-interruption-authority.json

# H06I-R2 — Codex output-last-message 最终自举修复

## Authority

- 本轮是 `SCOPE-FREEZE-AMENDMENT-003.json` 授权的最后一个实现 repair stage，不是新 task identity；任务仍为 `H06I-R2-interruption-authority`，task definition SHA-256 仍为 `55ebd49197d5c940394fd405224b2814d28b290a81e3cd481c4c5d4bcac377c2`。
- 以现有 replacement clone 中已冻结候选为输入，不从 R1/run1 复制实现。行为代码只允许修改 `scripts/kb/agent-runtime.py` 与 `tests/test_agent_runtime.py`；`guardian-r2-program/reports/H06I-R2-interruption-authority.md` 只允许追加本轮真实证据。其他两个 owned paths 必须保持：
  - `scripts/kb/native_agent_broker.py`：`0393e1bb5c2cee278f06eb3c2ca2a068aba481cff82beacb28ae0205a0af39c7`
  - `tests/test_native_agent_broker.py`：`0ed8ced54a46fe6fbcbb1ee746aa6dec33692ba1ef644d1d4d38bce679f88850`
- 输入 runtime/test/report SHA-256 依次为 `d8d7406595174dc9379c998327a0b6665aac09128840d95471df6e9eca9082a9`、`59533ccdcf701ccd72c0b1e3882a2b4e839a99b7a56e6254d13fe7c78f2795f6`、`f8d1e5a984870c81cd8bb659254c820840ded41ef0ea0ce1fe45f76b2efccf18`。
- 只用原生 `apply_patch` 修改三个允许文件；禁止 commit、install、scheduler、production intent/KB、push、merge、dev/main、网络和其他仓库写入。
- 当前父 runtime 正是待修复的旧候选，故 provider 完成后父 receipt 会继续暴露 `FR2-H06I-R2-008`。该唯一已知自举终态由 amendment 明确隔离：不得绕过、重试或将它误报为修复失败；协调器只在 provider 单次完成、三路径 diff 合规、测试真实通过时冻结 stage 输出，随后必须用修复后的 runtime 做唯一 self-hosted final verification。

## Source authority

- 官方 Codex non-interactive 文档说明 `--json` 输出 `thread.started`、`turn.started/completed` 与 `item.*`；最终助手消息是 `item.completed` 的 `agent_message`，不是 `type=result`：`https://developers.openai.com/codex/noninteractive/`。
- 同一官方文档与 CLI reference 明确 `-o/--output-last-message <path>` 把助手最终消息写入文件，供下游脚本使用：`https://developers.openai.com/codex/cli/reference/`。
- 本轮真实红证据 `FR2-H06I-R2-008`：events SHA-256 `9ce65c43dbb53bfb00ce92ef2ffbaf5e018ccddf4c33869c4cf5f9cb3f12c8a1`；事件类型只有 `thread.started`、`turn.started/completed`、`item.started/completed`；agent message 为 `item_3`，而 runtime 仅在 line 1807 识别 `type=result`，导致内部 final message 为空。
- `.codex-agent/r2-h06i-r2-selfhost-verification.last.md` 已证明 `--output-last-message` 产物 SHA-256 `4b5bd947c36d4fe5de2caacd7e600fbbb64eba2b74e38e206128cec90122484d`、10588 bytes；它与 durable report 只差一个 terminal LF，正是现有 canonicalizer 已允许的输入。

## Required implementation

1. 在 Codex 非 test-mode 的 provider 进程完全退出、stdout reader 已结束后，且在 `RunHandle.settle(...)` 之前，从 runtime 自己规划并传给 `--output-last-message` 的 `.codex-agent/<slug>.last.md` 读取 raw bytes。
2. 读取必须复用/扩展现有 descriptor-relative 安全入口：拒绝缺失、symlink、非 regular file、hardlink、超过固定大小、读取中 metadata 漂移、无效 UTF-8 与空消息。不得用普通 `Path.read_text()` 作为 production authority。
3. strict UTF-8 解码后的精确文本覆盖任何 JSONL 推导的 `final_message`，再传给 `handle.settle(output=...)`。`--json` 事件只保留进度/副作用观测用途，不再决定 Codex final output authority；伪造或陈旧 `type=result` 不得覆盖 output-last-message 文件。
4. 之后继续使用现有 `_canonical_provider_final_bytes`：允许无 terminal LF 或恰好一个 LF，拒绝 CR terminal 与多 LF；durable report 必须与 canonical bytes 完全相等，然后 `.last.md`、run ledger output、native receipt `output_summary`/`report_summary` 绑定同一内容。
5. Claude/test-mode 行为保持原状；不得降低 broker 的 output/report equality、task report verdict、quiescence、scope 或 native authority 门。

## Required tests

- 新增真实 Codex 0.150.1 JSONL 形状：无 `type=result`，含 `item.completed/agent_message` 与 `turn.completed`；同时写入受控 output-last-message。断言 runtime 在 settle 前使用该文件，run ledger output present，canonical receipt 两个 summary 相同。
- 注入一个与文件内容不同的旧式 `type=result`，证明 output-last-message 文件胜出。
- missing、symlink、non-file、hardlink、oversize、invalid UTF-8、empty 与 readback drift 全部 fail closed，且不能生成成功 receipt。
- 保留并通过 canonical LF/CR/content drift、H06H self-contained evidence、broker equality 与 managed terminal 现有测试。
- 运行 focused、完整 `tests/test_agent_runtime.py`、完整 `tests/test_native_agent_broker.py`、组合两模块与 fresh-clone gate；报告只记录本轮真实成功命令。

## Report update

- 保持现有五个一级标题各一次，不新增标题；在相应章节追加 `FR2-H06I-R2-007`、`FR2-H06I-R2-008`、官方 output authority、修复方式和本轮成功检查。
- 报告不得出现历史非成功返回码数字，也不得出现单词 `partial` 或 `blocked`。stage1 父自举终态只在 controller ledger 记录，报告陈述 content-addressed finding 与解决方式。
- 最终回复只包含更新后的 durable report 完整正文，不加前后说明。

## Terminal rule

- provider 若未完成、超出三路径、测试未通过或冻结的 broker/broker-test 发生变化，立即停止，不得进入 self-host verification。
- stage 输出通过协调器冻结后，不得再修改；下一步只能执行 amendment 授权的唯一 final self-host verification。该验证失败后不再重试、返修或创建新任务。
