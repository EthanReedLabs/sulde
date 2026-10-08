/model
选择:gpt-5.6-sol（若当前可用列表无此型号，选择 deep 档或更高的 Codex 模型）
/reasoning
选择:high 或更高
执行任务文件:guardian-r2-program/task-definitions/H06I-R2-interruption-authority.json
执行任务SHA256:55ebd49197d5c940394fd405224b2814d28b290a81e3cd481c4c5d4bcac377c2

# H06I-R2 — Amendment-005 continuation-only repair

## 续接规则

- 继续同一 `H06I-R2-interruption-authority` candidate ordinal 4。Amendment-004 的 provider 已超时，其留下的当前 diff 是本轮输入；不得重建计划、重扫历史、删除工件或重做已接受任务。
- 开始时只读确认五个输入 SHA-256 精确匹配 Amendment-005。只读查看当前 diff、旧报告和本 brief 已记录的 FR2-014 超时事实，然后直接补齐未完成项；不要因控制端红工件未投影到 candidate 而扩大搜索。
- 行为代码只能修改 `scripts/kb/agent-runtime.py`、`tests/test_agent_runtime.py`；报告只能重写 `guardian-r2-program/reports/H06I-R2-interruption-authority.md`。
- `scripts/kb/native_agent_broker.py` 与 `tests/test_native_agent_broker.py` 必须分别保持 SHA-256 `0393e1bb5c2cee278f06eb3c2ca2a068aba481cff82beacb28ae0205a0af39c7`、`0ed8ced54a46fe6fbcbb1ee746aa6dec33692ba1ef644d1d4d38bce679f88850`。
- 不安装、不写生产 descriptor、不改 scheduler、不提交、不合并、不推送、不启动 H06J。失败即停，不重试、不新建后继任务。

## 本轮只完成这些缺口

1. 审查 preserved diff 是否已完整关闭 FR2-H06I-R2-009..013；若有实质缺口，只做最小修正并补对应测试。
2. 运行 11 个 review-repair focused tests；时间允许时再运行 `tests/test_agent_runtime.py` 和冻结的 `tests/test_native_agent_broker.py`。不要运行 fresh clone、默认 macOS TMPDIR、显式 `/private/tmp`、self-host 或全历史复审，这些由外层协调器完成。
3. 重写旧报告，删除互相冲突或重复的 current-success claims，但保留历史 finding、失败尝试和恢复事实。FR2-H06I-R2-014 必须如实记录为 Amendment-004 provider 超时，不得抹去。
4. 报告中的每个 `✅` current-success 行只能出现一次，并使用精确格式：实际反引号命令、`exit 0`、可观察结果、`candidate_sha256`、当前 `.codex-agent/<slug>.task-binding.json` 的 `execution_binding_sha256`、`environment_sha256`、实际命令字节的 `command_sha256`、`count`。命令摘要必须等于反引号内 UTF-8 命令的 SHA-256。
5. 最终回复必须与 durable report 字节一致，且正常到达 provider terminal。不要在回复中宣称外层环境矩阵、stage boundary、self-host、accepted、integrated、installed、H06J 或 R2 完成。

## 当前技术验收点

- production Codex natural completion 在 `RunHandle.settle` 前选择并规范化唯一 output-last-message bytes；ledger、durable report 和 receipt 摘要不得分叉。
- descriptor-relative reader/writer 将 lexical root、opened root dirfd 和返回前 pathname/parent chain 绑定；swap、symlink、hardlink、oversize、invalid UTF-8、empty、ctime drift 与外部逃逸必须 fail closed。
- production `provider=codex,test_mode=false` 的 `paused/awaiting_human/timeout` 属于授权的 local interruption，可以 final output absent，但必须有 exact ordered ledger evidence、broker receipt 和 quiescence；natural completion 仍要求 canonical output。
- `/var/folders` 与 `/private/var/folders` 身份在单一规范层比较，不能依赖 wrapper 注入 TMPDIR。外层环境矩阵由协调器裁决，本轮不得提前投影通过。
- report validator 拒绝重复命令、冲突 count、错误 command hash、缺绑定或 execution binding 漂移。

## 报告结构

- 仍且仅保留一次 `## 结果`、`## 过程`、`## 遇到的问题`、`## 解决方式`、`## 遗留风险与建议`；只有确有新知识候选时才增加一次 `## 沉淀候选`。
- `## 结果` 只描述本次 continuation 的当前 candidate 与实际运行命令。协调器尚未执行的检查必须放入遗留项，不能写为绿色事实。
- `## 遇到的问题` 逐项保留 FR2-H06I-R2-009..014 的证据状态；不要把历史失败命令写成 current-success `✅` 行。
- 沉淀候选只写当前任务 handoff，不写跨项目知识库。
