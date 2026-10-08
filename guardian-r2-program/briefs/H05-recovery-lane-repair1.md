/model
选择:gpt-5.6-sol（若当前可用列表无此型号，选择 deep 档或更高的 Codex 模型）
/reasoning
选择:high 或更高
执行任务文件:guardian-r2-program/task-definitions/H05-recovery-lane.json

# H05 repair1 — finish the preserved recovery-lane candidate

Continue the exact H05 task and its original brief. Do not rebuild the plan,
restart from a clean tree, discard the partial candidate, or start H04/H06.

The original failed run `run-6a34c9ce22be43e68645fde0` is preserved. Its
current worktree candidate contains only new `scripts/kb/recovery_lane.py`
(614 lines). Coordinator readback proves it parses (`AST_OK`), but the other
seven owned paths, tests and report are absent/unchanged. No partial code is
accepted. Inspect every existing byte; retain only what satisfies the original
authority and repair it in place.

## Close the recorded findings

- FR2-H05-004: the first worker invoked a shell heredoc around `apply_patch`.
  The sealed profile correctly denied the heredoc temporary file. The worker
  then promised a native patch but made no progress.
- FR2-H05-005: the coordinator terminated the stuck provider after a bounded
  no-progress window. The wrapper produced result/disposed, but the provider
  JSON stream lacked a natural terminal event, so strict verification failed.
  This repair must finish naturally and emit a complete final report.

## Mandatory write discipline

- For every edit, invoke the native Codex `apply_patch` tool directly as a
  tool call. Do not invoke an `apply_patch` executable through a shell.
- Do not use heredoc/here-string, shell redirection, `cat`, `tee`, `printf`
  pipelines, interactive stdin, PTY writers, base64 writers, `sed -i`, Perl,
  or Python to create/replace files.
- If native `apply_patch` is unavailable, stop and report that exact fact. Do
  not invent another write transport and do not widen TMPDIR/profile access.
- Read/test commands must be finite, noninteractive and individually issued.

## Required completion

Complete the original H05 acceptance and all eight owned paths. In particular:

1. audit the preserved recovery capability/lane for strict schema, sealed
   action, provider/session/workspace/generation/pre-state binding, replay
   resistance and independent verifier;
2. connect the narrow pre-policy recovery route, current status/readiness and
   statusline behavior only through the four owned source files;
3. add deterministic `tests/test_recovery_lane.py` and scoped additions to the
   two existing test modules for every original state/UI/SLA/failure case;
4. run focused and adjacent H02/H03 composition tests, AST/compile checks,
   `git diff --check`, exact eight-path scope and generated-bytecode checks;
5. write `guardian-r2-program/reports/H05-recovery-lane.md` with all
   FR2-H05-001..005, root causes, resolutions/evidence, remaining risks, exact
   commands/counts, state/UI/SLA matrices and `沉淀候选`;
6. do not commit, merge, push, install/uninstall/repair a real runtime, signal
   sessions, write Git, call network/devices/Figma, or claim H04/H06.

Only the eight paths in the frozen H05 task definition may change. Read-only
H02/H03 projections remain immutable.

The final response must include each heading exactly once: `结果`, `过程`,
`遇到的问题`, `解决方式`, `遗留风险与建议`, `沉淀候选`. Include at least one
`✅ 完成检查：` line with a backticked command, `exit 0`, and a concrete
observable result. A progress promise is not a final report.
