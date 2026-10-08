/model
选择:gpt-5.6-sol（若当前可用列表无此型号，选择 deep 档或更高的 Codex 模型）
/reasoning
选择:high 或更高
执行任务文件:guardian-r2-program/task-definitions/H06I-agent-runtime-interruption-terminal.json

# H06I — 修复受管 awaiting-human 终态证据自相矛盾

## Authority

- exact base：`10ad8d876d74fe5c4dea8e3b1cc27e178078bdc2`。
- provider：Codex deep/high；不得调用或依赖 Claude。
- 只允许修改 task definition 中三个 exact paths；禁止 commit、install、scheduler、production intent/KB、push、merge、dev/main 与网络副作用。
- H06H run1 已 blocked 且零候选输出；不得恢复、改写或删除其事件。只读红证据位于 `/Users/eric/ClaudePlugin/sulde-cc-pro/.worktrees/r2-h06h-final-fullclone/.codex-agent/r2-h06h-final-acceptance-run1.run.jsonl`、同 slug `events.jsonl` 与 `stderr.log`。
- 文件修改必须使用原生 `apply_patch`。禁止 heredoc、重定向写文件、`perl -i`、`sed -i`、Python 写文件或任何依赖未授权临时文件的 shell 原地编辑。

## Verified red evidence

1. H06H run1 ledger 精确顺序：`execution.interrupt_requested(reason=external_effect_outcome_unknown)` → `execution.result(stop_reason=awaiting_human, returncode=0)` → `execution.disposed(quiescent=true)`。
2. 当前 `_LOCAL_INTERRUPTION_REASON_MAP` 不含 `external_effect_outcome_unknown`；最小真实 JSONL 调用 `_run_ledger_local_interruption_evidence` 输出 `MAP_VALUE=None` 并确定性抛 `local interruption evidence is mismatched, out of order, or not quiescent`。
3. runtime 最终写出 `status=awaiting_human ... reason=post_terminal_AgentRuntimeError`，把自身生成的合法 awaiting-human 序列退化成 opaque failure。

## Implementation

1. 在 `scripts/kb/agent-runtime.py` 修复 interruption reason 到 result stop reason 的唯一一致映射；不得放宽事件数量、顺序、returncode 类型或 quiescent 条件。
2. 在 `tests/test_agent_runtime.py` 添加真实 JSONL 红绿测试，至少覆盖：
   - `external_effect_outcome_unknown → awaiting_human` 通过并返回 typed evidence；
   - missing/duplicate/reordered events 拒绝；
   - reason/stop mismatch 拒绝；
   - `returncode` 非 int 拒绝；
   - disposed 非 quiescent 拒绝；
   - managed terminal 保留 awaiting_human，不重复人类决定、不盲重试、不重放外部 effect。
3. 不把 H06H item_25 的 heredoc/temp-file 命令变成合法写法；它仍应被 exact profile 拒绝。这里修的是终态证据一致性与可读终态，不是扩大路径权限。
4. 报告 `guardian-r2-program/reports/H06I-agent-runtime-interruption-terminal.md` 必须且只出现一次 `## 结果`、`## 过程`、`## 遇到的问题`、`## 解决方式`、`## 遗留风险与建议`；记录问题、根因、修复、真实命令/exit/output 和 H06J 转交边界。

## Verification

- 先用修复前真实 run ledger/最小 fixture 证明红，再跑新 focused tests。
- 运行 `PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v tests.test_agent_runtime` 全模块；随后运行与 broker/recovery/installer 相关的必要集成回归。
- 对错误顺序、重复、非静止和理由漂移做独立 failure injection；不得只断言 map 字典值。
- effective diff 精确三个 owned paths；base、task/brief control projection hash、`.git`、`.codex-agent`、`.pyc` 不得进入候选。
- 每条 `✅ 完成检查：` 必须是可字面执行的真实命令。managed success 只表示 H06I candidate，不表示 integrated、H06H/H06J accepted、install 或 R2 complete。
