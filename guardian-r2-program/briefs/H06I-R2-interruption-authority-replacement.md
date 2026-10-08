/model
选择:gpt-5.6-sol（若当前可用列表无此型号，选择 deep 档或更高的 Codex 模型）
/reasoning
选择:high 或更高
执行任务文件:guardian-r2-program/task-definitions/H06I-R2-interruption-authority.json

# H06I-R2 replacement — 最后一次 interruption/report authority 收口

## Authority

- exact base：`10ad8d876d74fe5c4dea8e3b1cc27e178078bdc2`。从该提交的 fresh、无 hardlink full clone 独立实现；不得复制或提升 H06I、H06I-R1、H06I-R2 run1 候选代码。
- provider：Codex deep/high；不得调用、等待或依赖 Claude。
- 原冻结：`guardian-r2-program/SCOPE-FREEZE.json`，SHA-256 `40bd0ba4bcb342209302bb1c71166fbd9136a655c5df6088f2b6abb50e5bccc8`。
- 人类确认的最小解冻：`guardian-r2-program/SCOPE-FREEZE-AMENDMENT-001.json`。该 append-only amendment 只允许同一 `H06I-R2-interruption-authority` 的 replacement ordinal 2；本次失败后立即停止，不得创建第三候选、新 task identity 或扩大路径。
- task definition 必须保持 SHA-256 `55ebd49197d5c940394fd405224b2814d28b290a81e3cd481c4c5d4bcac377c2`，只允许修改其中五个 exact paths：
  1. `scripts/kb/native_agent_broker.py`
  2. `scripts/kb/agent-runtime.py`
  3. `tests/test_native_agent_broker.py`
  4. `tests/test_agent_runtime.py`
  5. `guardian-r2-program/reports/H06I-R2-interruption-authority.md`
- 禁止 commit、install、scheduler、production intent/KB、push、merge、dev/main、网络副作用和其他路径写入。文件修改只用原生 `apply_patch`；禁止 heredoc、重定向写文件、`sed -i`、`perl -i` 或 Python 写文件。

## Required knowledge

- 直接阅读全文 `/Users/eric/.codex/plugins/cache/sulde-local/sulde/0.2.5+codex.20260826044342/runtime/knowledge/anti-patterns/0224-verification-environment-differs-from-runtime.md`；不得只读索引 excerpt。
- 验证环境必须模拟 fresh clone：测试不得读取、搜索或依赖任何 sibling worktree、外部 `.codex-agent`、机器特定路径或已运行候选的 mutable artifact。

## Frozen run1 evidence and findings

- H06I-R2 run1 status/events/native-receipt-file/native-receipt-self/last/durable 摘要依次为：
  - `37dfc4ac55847abbc533384dcd54b3dcb961ece6649c8b289814794dadd30811`
  - `7acb8fd39e48b69640267135393cfbdbafe5d59604593826d9383bad5ce1717c`
  - `d046941a63a7178dc903a3f23ccbfecae2b709016589b1c071b0811d293f1774`
  - `8885858f7a1413391f2170465958f8f7a60843ac0d7454745f14e5475a324a38`
  - `2a34348cb9e0a9beee319241af259dd684f02d682d5417cd8f204f73a2a8bdc1`
  - `1785f77e927a56a633ccd5b2a61e11c5b34010eca0b24a71d9010d9340227413`
- `FR2-H06I-R2-001`：首次受管启动在 provider 前暴露 `agent-runtime` 对 control root basename `guardian-program` 的既有要求；协调器随后同时提供 byte-identical `guardian-program` runtime authority 投影与 `guardian-r2-program` 模型路径投影。报告必须记录这项本轮事实及解决方式。
- `FR2-H06I-R2-002`：Codex `--output-last-message` 产物比 durable task report 少一个 terminal LF，receipt 因而绑定两份不同 report authority。
- `FR2-H06I-R2-003`：run1 测试读取 sibling `r2-h06h-final-fullclone/.codex-agent`；clean-clone 模拟出现两个 `FileNotFoundError`。
- `FR2-H06I-R2-004`：报告把 `FR2-H06H-001` 的临时文件/heredoc write-shape 误归类为 reason authority。
- `FR2-H06I-R2-005`：报告遗漏 `FR2-H06I-R2-001` 与 dual-projection resolution。
- `FR2-H06I-R2-006`：报告遗漏本轮真实问题/恢复类别：digest scan 无匹配、错误的 `apply_patch --help` 探针、`py_compile` cache 写拒绝，以及随后正确的原生 `apply_patch` 与只读 AST 验证。
- 保持既有正确实现目标：一个共享 immutable exact reason authority；`external_effect_outcome_unknown` 只映射 `awaiting_human`；未知/非字符串/空白/大小写漂移 fail closed；runtime 与 production broker 保留唯一数量、run_id、顺序、strict int returncode、quiescent disposal、reason/stop equality 与 ledger digest 约束；乱序反例使用 `[3,2,4]` 或 `[2,4,3]`，不得混入 duplicate。

## Self-contained H06H evidence

测试必须把以下 1435-byte run ledger 与 136-byte stderr 作为 test-source literal 冻结在两个现有 test files 之一，并同时断言长度与 SHA-256；不得从 sibling 读取。不要把 894187-byte events 复制进仓库，只冻结其可信摘要与 digest。

```jsonl
{"at": "2026-08-27T13:25:31.367588+00:00", "command_sha256": "a157d1129bf498d966ca0609784d41f43fd4c8a9f3356c8a2660cd3809dbb4b0", "execution_binding_sha256": "3db6bc47fe16cd15af56cc88c9f07fbe9a97e9966702d6d8a280cb5c35180545", "parent_death_watchdog": true, "provider": "codex", "run_id": "run-1c18f868428c471e959e751a", "schema": "sulde-run-event-v1", "type": "execution.requested", "workspace_id": "sha256:b84f0fa06b784bc9c93eabda"}
{"at": "2026-08-27T13:25:31.369862+00:00", "parent_death_watchdog": true, "pid": 26837, "provider": "codex", "run_id": "run-1c18f868428c471e959e751a", "schema": "sulde-run-event-v1", "tree_scope": "posix-process-group", "type": "execution.started"}
{"at": "2026-08-27T13:29:30.336465+00:00", "provider": "codex", "reason": "external_effect_outcome_unknown", "run_id": "run-1c18f868428c471e959e751a", "schema": "sulde-run-event-v1", "type": "execution.interrupt_requested"}
{"at": "2026-08-27T13:29:30.373722+00:00", "output_present": false, "output_sha256": null, "provider": "codex", "returncode": 0, "run_id": "run-1c18f868428c471e959e751a", "schema": "sulde-run-event-v1", "stop_reason": "awaiting_human", "type": "execution.result"}
{"at": "2026-08-27T13:29:30.374582+00:00", "error_count": 0, "errors_sha256": null, "provider": "codex", "quiescent": true, "run_id": "run-1c18f868428c471e959e751a", "schema": "sulde-run-event-v1", "tree_scope": "posix-process-group", "type": "execution.disposed"}
```

```text
managed local interruption: awaiting_human
AgentRuntimeError: local interruption evidence is mismatched, out of order, or not quiescent
```

- run ledger：5 lines、1435 bytes、SHA-256 `8f32a901dc01221376b13cae56ed328e4729d21dac91f5ac29b25b363f63b67a`。
- stderr：2 lines、136 bytes、SHA-256 `b38d2df3d6d0624e798a39de46f6b72ef8ebce83bc023ee6c3593b22d1ce61d3`。
- events 可信摘要：`{"line_count":48,"sha256":"cec437d7a1d35307c90f2ceb9d333de7e556fa685c559010221e39e48fc6a62e","terminal_event":"none","terminal_event_count":0,"valid_json_line_count":48}`；原始长度 48 lines / 894187 bytes，SHA-256 同摘要。测试可以验证冻结摘要的 schema/digest 关系，但不得伪造 894187 bytes 原文已存在。
- 必须用这些 self-contained bytes 完成 runtime parser → production `native_agent_broker.build_provider_receipt` → `validate_provider_receipt` roundtrip，且不设置 `SULDE_TEST_MODE`。缺失、重复、唯一项乱序、reason drift、unknown/non-string reason、字符串/bool returncode、non-quiescent disposal 两侧均 fail closed。

## Canonical final report authority

在 `scripts/kb/agent-runtime.py` 中闭合单一 report authority，不在测试或报告中掩盖差异：

1. 从已验证 task definition 的 `owned_paths` 中确定唯一 durable worker report：必须恰有一个 repo-relative、位于 `guardian-r2-program/reports/` 且以 `.md` 结尾的 exact owned path；零个、多个、绝对路径、逃逸、symlink、非 regular file 均 fail closed。
2. 定义 provider final text 的唯一 canonical bytes：UTF-8 strict；若无 terminal LF，追加一个；若已有恰好一个 LF，保持；CR terminal、两个或更多 terminal LF、编码失败均拒绝。不得 `strip`/`rstrip` 正文、规范化内部换行或做语义等价比较。
3. 在 native receipt 构造之前，读取 durable report raw bytes，并要求它与 canonical final bytes 完全相等；内容或换行任何漂移均 fail closed。
4. 仅在等值通过后，以现有原子写入口把 `.codex-agent/<slug>.last.md` 写成 canonical bytes；立即回读并再次 exact compare。`output_summary`、`report_summary` 与 receipt 必须绑定这同一组 bytes/digest/length，不再允许双权威。
5. report verdict 读取 canonical `.last.md`。缺失 durable report、持久报告变化、final-message 内容漂移、zero/multiple report owned path、extra LF、CRLF/CR terminal、symlink/non-file、原子写后漂移都要有精确 negative tests。

## Managed terminal and clean-clone gates

- managed terminal 用例断言 provider、interrupt、result、disposed、intervention identity、external attempt 各一次；human decision、retry、reprobe、effect replay 与 `post_terminal` 均不存在。
- 全部测试在只含 exact base + 当前五路径修改 + 投影控制文件的 fresh clone 中通过；测试主动断言不存在 H06H sibling 时仍可执行。不得用 skip、环境探测或 fallback 悄悄降低该 gate。
- effective candidate diff 精确五个 owned paths；两组 control projection、`.git`、`.codex-agent`、`.pyc` 与 cache 都不属于候选。

## Worker verification

- 先运行 focused runtime/broker tests，再运行 `tests/test_agent_runtime.py`、`tests/test_native_agent_broker.py` 与二者组合。所有报告中的 `✅ 完成检查：` 必须是本 replacement worker 当前真实成功的命令、`exit 0` 和可观察结果。
- 用只读 AST/文本检查证明 production reason authority 只有一份 immutable map、runtime 引用 broker helper、没有 run1 路径或 sibling dependency。
- 用 fresh temporary clone/copy simulation 删除所有外部 sibling 假设，复跑两模块；该检查必须真实成功后才能写入报告。
- 写完报告后，用当前 `scripts/kb/agent-runtime.py` 的 `report_contract_for_brief` 与 `task_report_verdict` 对实际 replacement brief/report 验证 `passed=true`、空 failures；把成功命令写入报告后再次运行并确认仍通过。

## Report protocol

- durable report 必须且只出现一次：`## 结果`、`## 过程`、`## 遇到的问题`、`## 解决方式`、`## 遗留风险与建议`。
- 报告不得出现历史非成功返回码数字，也不得出现单词 `partial` 或 `blocked`；历史失败只按 SHA-256 与 finding ID 引用。controller append-only ledger 仍保存精确历史。
- `FR2-H06H-001` 必须单独按“临时文件/heredoc write-shape”处置，不得归到 reason authority；`FR2-H06I-R2-001..006` 每项必须逐项出现，并准确记录 dual projection 与本 worker 的真实问题/恢复。
- 报告只声明当前 H06I-R2 replacement candidate。不得声明 coordinator full verification、implemented、task_verified、integrated、accepted、H06J、installation、scheduler、live canary 或 R2 completion。
- worker 最终回复必须只包含 durable report 正文。runtime 将按上述 canonical protocol 绑定 exactly-one terminal LF；最终回复前后不得增加解释。

## Terminal rule

- 本 replacement 若失败，保留红证据并停止；不得重试、修补当前 clone、创建 successor/R3/H06K、修改 freeze 或要求扩大 paths。
- 只有协调器可在候选终止后执行独立全量测试、三路复审、集成、evidence promotion 与 H06J。worker 不得代替协调器宣告这些终态。
