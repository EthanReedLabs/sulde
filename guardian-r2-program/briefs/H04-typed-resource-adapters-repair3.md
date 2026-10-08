/model
选择:gpt-5.6-sol（若当前可用列表无此型号，选择 deep 档或更高的 Codex模型）
/reasoning
选择:high 或更高
执行任务文件:guardian-r2-program/task-definitions/H04-typed-resource-adapters.json

# H04 repair3 — correct independently observed failures and restore truthful evidence

Continue the same H04 worktree and preserve the seven-path repair2 candidate.
Do not clean, revert, rebuild the plan, repeat accepted H01/H02 work, or start
H05/H06. The coordinator rejected repair2 semantic completion even though its
patch bytes landed.

## Verified repair evidence

- `run-58f50a4e63584a458c0774d9` ended `paused`, not successful. Its one patch
  command was misclassified as destructive after writing the seven approved
  paths, so no test command or natural final report followed.
- Independent execution of the exact report-claimed suite ran 22 tests and
  failed with 10 errors and 2 failures. `git diff --check` and six-file
  `py_compile` passed.
- Most failures share a fixture bug: macOS returns temporary roots through
  `/var`, while strict production classification canonicalizes them to
  `/private/var`. Legal positive fixtures were therefore presented as lexical
  aliases. Fix test fixture construction by using canonical resolved temporary
  roots; do not weaken production rejection of user-supplied aliases, symlink
  traversal, parent substitution, release branches, broad pathspecs, device
  data clear or real external debt.
- Recheck the two resulting route failures (local recursive operation missing
  action and device classification rejected) after fixture canonicalization.
  If they remain, repair the implementation rather than changing expectations.
- The current durable report's claim that 22 tests passed is false and must be
  replaced with evidence from commands actually executed in this run.

## Findings and completion gates

Address and report all findings FR2-H04-001..009. In particular:

1. FR2-H04-006 is resolved only if the real `apply_patch` executable applies
   the correction and readback/diff prove exact bytes. The same finite
   `shutil.which("apply_patch")` plus `subprocess.run([exe], input=patch,
   text=True)` transport remains the sole fallback; no direct Python file I/O,
   temp writer, heredoc, redirection, pipeline, PTY, base64, `cat`, `tee`,
   `sed -i` or Perl.
2. FR2-H04-007 is an installed-runtime observation, not permission to weaken
   repository policy. This repair runs Guardian in shadow while the sealed
   file sandbox still permits only the seven task-owned paths. Record the
   misclassification as open for H06/system acceptance unless candidate code
   plus an executed regression proves it fixed.
3. FR2-H04-008 closes only when the exact 22-test command exits 0. Run the
   three adjacent literal-Git tests too, then AST/compile, `git diff --check`,
   exact seven-path scope and generated-bytecode checks.
4. FR2-H04-009 closes only when the report contains actual commands, exit
   codes and counts observed after repair. Never copy intended results into the
   completion line.
5. Re-audit the implementation against I04/I09/I14/I15/I17/I19, H01/H02
   authority consumption and all failure axes. Do not treat test-only fixture
   normalization as proof that production canonical boundaries are correct.

Update only the frozen seven owned paths. The report must retain the exact
headings `结果`, `过程`, `遇到的问题`, `解决方式`, `遗留风险与建议`, `沉淀候选`
once each, include the complete FR2-H04-001..009 table, changed paths, limits,
requirement/incident traceability and positive/negative sedimentation samples.
At least one `✅ 完成检查：` line must cite an actually executed backticked
command, `exit 0`, and concrete output. If any gate fails, report failure
truthfully and stop naturally.

Do not commit, merge, push, install, call real Figma/devices/network, delete
real data, mutate production, or claim H05/H06/release acceptance.
