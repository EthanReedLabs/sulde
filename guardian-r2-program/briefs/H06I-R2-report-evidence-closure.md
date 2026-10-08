/model
选择:gpt-5.6-sol（若当前可用列表无此型号，选择 deep 档或更高的 Codex 模型）
/reasoning
选择:high 或更高
执行任务文件:guardian-r2-program/task-definitions/H06I-R2-interruption-authority.json
执行任务SHA256:55ebd49197d5c940394fd405224b2814d28b290a81e3cd481c4c5d4bcac377c2

# H06I-R2 — Amendment-006 evidence-only report closure

## 唯一目的

- 这是同一 `H06I-R2-interruption-authority` 的 evidence-only closure，不是实现修复、测试重跑或新任务。
- 四个行为/测试文件和当前 durable report 已由协调器冻结；禁止修改任何文件。运行时在 provider 自然终态后写回与最终回复相同的 durable report，除此之外不得产生候选写入。
- Amendment-005 已实际运行 focused 11、runtime 74 和 broker 52，并形成自然终态；它仅因第三条报告命令漏写 `ON` 而 fail closed。那些测试是已保存的前序运行事实，本轮不得重跑、不得重新绑定成当前执行的测试。
- 不重建计划、不查历史、不读知识库、不调用 Skill、不使用 apply_patch、不运行测试、不创建 fresh clone、不切换 TMPDIR、不 self-host、不安装、不提交、不合并、不推送、不启动 H06J。

## 本轮允许的唯一验证命令

逐字运行一次且只能运行一次：

`shasum -a 256 scripts/kb/native_agent_broker.py scripts/kb/agent-runtime.py tests/test_native_agent_broker.py tests/test_agent_runtime.py .codex-agent/r2-h06i-r2-review-repair-continuation.run.jsonl .codex-agent/r2-h06i-r2-review-repair-continuation.last.md .codex-agent/r2-h06i-r2-review-repair-continuation.native-receipt.json`

命令 SHA-256 必须为 `17601e75fdec019993432616592c6808badeb15188333f4dffcfa684ef9c3bee`，七个输出必须依次为：

1. `0393e1bb5c2cee278f06eb3c2ca2a068aba481cff82beacb28ae0205a0af39c7`
2. `9effefc5f477dc7d78a985ad028e9dcf790b548b1d846c7c6a2c46870fb7e740`
3. `0ed8ced54a46fe6fbcbb1ee746aa6dec33692ba1ef644d1d4d38bce679f88850`
4. `a637b37445adad801ae865d83852890b1c40bd24706823ed5c1525d7a40b2b76`
5. `ce11635b7e37c6a043f8280846b02a27e3101e4b54584d083e6a2b447a9b3382`
6. `eacbda95e387e1942ef4082794a89353b1b9d7f63d42bd9e0574479cd0a4f489`
7. `9df254b9468492d699cffb2873787ec7e0f2bb6496819f5c124d3b312a35c398`

任一不符立即失败，不修改报告、不尝试修复。

## 报告与终态纪律

- 当前 `guardian-r2-program/reports/H06I-R2-interruption-authority.md` 已由协调器机械生成并预先绑定本轮 `.task-binding.json`。先只读确认报告中恰有一个 `✅`，其 command、command SHA-256、candidate SHA-256、current execution binding、environment SHA-256 和 `count=7` 均完整。
- 可只读调用当前 runtime 的 `task_report_verdict` 验证该报告；这不是新的 current-success 证据命令，不得把它追加进报告。
- 最终回复必须逐字等于当前 durable report 的完整 UTF-8 内容。不要加前言、后记、代码围栏或摘要，不要改任何字。runtime 会把官方 output-last-message 规范化后写回同一路径，并验证 report contract。
- 不得宣称外层双 TMPDIR、fresh clone、stage boundary、self-host、accepted、integrated、installed、H06J 或 R2 已完成。
