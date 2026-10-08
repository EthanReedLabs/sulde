/model
选择:gpt-5.6-sol（若当前可用列表无此型号，选择 deep 档或更高的 Codex 模型）
/reasoning
选择:high 或更高
执行任务文件:guardian-r2-program/task-definitions/H06A2-integration-hygiene.json

# H06A2 integration hygiene — repair1

You are `guardian-r2-worker-h06a2`. Continue the failed H06A2 candidate in the
same isolated full clone. Do not rebuild the program, reset or discard the
existing candidate, rewrite accepted events, install anything, touch Git
metadata, modify dev/main, access external systems, or change any path outside
the frozen nine-path task definition.

## Frozen authority

- Task: `H06A2-integration-hygiene`.
- Base: `1b793c6ba8b76acd069510ed893de77228d581c6`.
- Task-definition SHA-256:
  `e04be7e6f3e1abf078549613d8439f346b77d1406b5e0a5ee3cf360608555d57`.
- Preserve the valid candidate changes: module-level broker import, blank-line
  only reductions to 2993/3000 lines, and the four explicit UTF-8 subprocess
  decoders. Review them, but do not replace them without evidence.
- The launch wrapper temporarily projects the already audited Codex 0.149.1
  because the installed native authority still seals 0.149.1. The coordinator
  restores global 0.150.1 after every terminal result. This task must not claim
  0.150.1 production compatibility; FR2-H06-001 remains for a later task.
- Exact scope evidence must distinguish nine task-owned deltas from three
  unchanged read-only control projections: the original brief, this repair1
  brief, and the H06A2 task definition. Do not count projections as task output.

## Repair the authority test

Fix only `test_installed_codex_0149_real_cli_contract` so it is production
isomorphic and also works under the supported isolated runner:

1. Locate the deployment descriptor from the runner-provided
   `SULDE_PRODUCTION_KB_HOME` when present; otherwise use the real installed KB
   location for the current user. Do not trust isolated `HOME`, PATH, a caller
   version claim, an arbitrary semver, or a future version.
2. Bind the repository module to the exact installed `agent_runtime_path`, set
   `SULDE_KB_HOME` to that production KB only for the verified load, and call
   `load_installed_native_authority()`. Preserve all runtime tree, generation,
   broker, permission-profile, authority and executable-digest checks.
3. Use only the verified authority's exact executable/version. Call
   `codex_capability_preflight(..., installed_authority=authority)` exactly as
   production does, so help `stdout+stderr`, strict profile and app-server
   handshake drift fail closed. Do not maintain a weaker, duplicate
   stdout-only help hash in the test.
  4. Keep existing synthetic path/version/help/generation negative tests intact.
     Add or extend a focused negative proving that diagnostic stderr changes the
     complete help observation and is rejected against installed authority even
     when every required help token remains present.

## Repair the durable report

Correct the finding mapping and provenance:

- FR2-H06-003 = delayed import plus recovery/resources line limits.
- FR2-H06-004 = four UTF-8 subprocess calls.
- FR2-H06-006 = original H06 lacked authority for the eight predecessor paths.
- FR2-H06-007 = H06A omitted its mandatory durable report path; H06A2 added it.
- FR2-H06-001 = installed authority/CLI 0.149.1 versus restored global 0.150.1;
  it remains open and must not be reported fixed.
- Record FR2-H06A2-001/002/003 and FR2-H06-009, including the full-clone and
  nested-Seatbelt lessons. The earlier worker formal runner launched zero tests;
  the coordinator later ran the single-layer formal runner and observed 438
  tests with one authority-test error plus concurrent external production
  state. Do not reinterpret either observation as a pass.
- Remove the misspelled inherited projection path and ensure every literal
  command shown in a check is actually executable.

## Verification and handoff

- Run the focused architecture, UTF-8 and exact real-CLI tests while the sealed
  0.149.1 projection is active. Also run the existing executable alias/future/
  substring version negative, synthetic incompatible-help negative, and
  installed authority generation/profile/broker drift negatives; a lone
  positive real-CLI test is insufficient.
- Run the affected H01-H05 composition, AST compile, `git diff --check`, exact
  nine-path scope, nonblank-line preservation for recovery/resources, and
  before/after no-bytecode inventory.
- Do not rerun the H00 formal runner inside the managed outer Seatbelt; the
  coordinator will run it once at a single OS-isolation layer after repair1.
- The report must contain exactly once and in order: `## 结果`, `## 过程`,
  `## 遇到的问题`, `## 解决方式`, `## 遗留风险与建议`, `## 沉淀候选`.
  Report repair1 as a candidate ready for coordinator verification, not H06A2
  accepted. Historical failed attempts may be described without forging a
  successful command or hiding their zero-test/no-clear facts.

Stop if any code-level check fails. Do not commit, push, install, run Claude,
run Windows, alter production state, or claim H06/program acceptance.
