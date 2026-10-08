/model
选择:gpt-5.6-sol（若当前可用列表无此型号，选择 deep 档或更高的 Codex 模型）
/reasoning
选择:high 或更高
执行任务文件:guardian-r2-program/task-definitions/H04-typed-resource-adapters.json

# H04 repair1 — finish the preserved typed-resource candidate

Continue the exact H04 task and its original brief. Do not rebuild the plan,
restart from a clean tree, discard the partial candidate, or start H05/H06.

The original failed run `run-dfe4f09a578940b49952f80e` is preserved. Its
current worktree candidate contains exactly these source changes from frozen
dev:

- new `scripts/kb/resource_adapters.py` (1143 lines);
- modified `scripts/kb/intent_guardian_parts/resources.py`;
- modified `scripts/kb/local_file_operations.py`;
- modified `scripts/kb/command_template.py`.

Coordinator readback proves all four files parse (`AST_OK 4`) and
`git diff --check` is currently clean. No H04 test file or report exists, and
none of the partial code is accepted. Inspect every existing byte; retain only
what satisfies the original authority and repair it in place.

## Close the recorded findings

- FR2-H04-004: the first worker used shell heredoc and interactive stdin/PTY
  writes. The sealed profile denied heredoc temp creation; the stdin writer
  became falsely active. Do not repeat either shape.
- FR2-H04-005: the coordinator terminated the stuck provider after a bounded
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

Complete the original H04 acceptance and all seven owned paths. In particular:

1. audit the preserved adapter for strict schemas, canonical identity,
   world-state binding, exact action constraints and independent verifier;
2. connect Git linked-worktree metadata, exact add/commit/merge, deletion,
   cross-workspace, Figma and device classification only through the four
   owned source files;
3. add deterministic `tests/test_resource_adapters.py` and scoped additions to
   `tests/test_intent_guardian.py`, including all original positive/negative
   and failure-injection cases;
4. run focused and adjacent H01/H02 composition tests, AST/compile checks,
   `git diff --check`, exact seven-path scope and generated-bytecode checks;
5. write `guardian-r2-program/reports/H04-typed-resource-adapters.md` with all
   FR2-H04-001..005, root causes, resolutions/evidence, remaining risks, exact
   commands/counts, requirement/incident traceability and `沉淀候选`;
6. do not commit, merge, push, install, invoke real Git writes outside temp
   fixtures, delete real data, call Figma/devices/network, or claim H05/H06.

Only the seven paths in the frozen H04 task definition may change. Read-only
H01/H02 projections remain immutable.

The final response must include each heading exactly once: `结果`, `过程`,
`遇到的问题`, `解决方式`, `遗留风险与建议`, `沉淀候选`. Include at least one
`✅ 完成检查：` line with a backticked command, `exit 0`, and a concrete
observable result. A progress promise is not a final report.
