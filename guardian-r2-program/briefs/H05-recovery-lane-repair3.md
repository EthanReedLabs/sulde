/model
选择:gpt-5.6-sol（若当前可用列表无此型号，选择 deep 档或更高的 Codex模型）
/reasoning
选择:high 或更高
执行任务文件:guardian-r2-program/task-definitions/H05-recovery-lane.json

# H05 repair3 — close compatibility regressions and produce executed evidence

Continue the same H05 worktree and preserve the eight-path repair2 candidate.
Do not clean, revert, rebuild the plan, repeat accepted H02/H03 tasks, or start
H04/H06. The coordinator rejected repair2 semantic completion.

## Verified repair evidence

- `run-ff6623629170412097a1ae62` repair1 ended naturally but incomplete.
- repair2 wrote all eight approved paths, then its patch command was classified
  as destructive and the lane paused before any post-patch test or natural
  final response. The installed-runtime event is FR2-H05-007.
- Independent execution of
  `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_recovery_lane
  tests.test_operational_readiness tests.test_sulde_statusline -v` ran 54 tests
  and failed exactly three assertions:
  1. the legacy exact readiness-domain set does not yet account for the new
     additive `recovery` domain;
  2. `test_status_cli_surfaces_share_projection_and_nonzero_exit` expected
     `交互未就绪` but received `任务未就绪:contract_active·恢复可用`;
  3. `test_non_waiting_interactive_fault_remains_red` expected
     `交互未就绪:artifact_generation_ready` but received
     `任务未就绪:artifact_generation_ready`.
- `tests.test_sulde_supervisor` ran 12 tests, all passed. `git diff --check`
  and seven-file `py_compile` passed.
- The durable report declares completion but uses non-contract headings and
  records an expected 54-test result rather than an executed passing result.

## Repair requirements

1. Reconcile the additive recovery domain with the existing readiness-domain
   contract. If the new separate domain is required, update the adjacent exact
   set expectation with explicit semantic justification; do not remove or hide
   recovery availability to make the assertion pass.
2. Preserve the existing primary status label for non-waiting interactive
   faults (`交互未就绪`). Recovery availability is an additive suffix/secondary
   fact and must not rewrite a task or interactive failure category. Keep task
   lane failures distinct from host-interactive failures.
3. Rerun the exact 54-test suite until exit 0, then the 12-test H03 supervisor
   suite. Run AST/compile, `git diff --check`, exact eight-owned-path scope and
   generated-bytecode checks. Record actual counts and exit codes only.
4. Re-audit sealed recovery capability/card, exact native UI outcomes,
   provider/session/workspace/generation/action/pre-state binding, replay,
   bounded reprobe, append-only settlement, H03 progress/terminal integration,
   5/30-second projection, duplicate-wait suppression and all failure axes.
5. Address FR2-H05-001..009 in the durable report. FR2-H05-006 closes only if
   the actual `apply_patch` executable applies and readback proves exact bytes.
   FR2-H05-007 remains an installed-runtime observation for H06 unless an
   executed regression proves the candidate itself fixes it.
6. This repair runs Guardian in shadow while the file sandbox remains sealed
   to the frozen eight paths; that operational choice is not evidence that the
   misclassification is fixed.

`apply_patch` remains the only editor. The previously authorized finite
`shutil.which("apply_patch")` plus `subprocess.run([exe], input=patch,
text=True)` transport is the sole fallback. No direct Python file I/O, temp
writer, heredoc, redirection, pipeline, PTY, base64, `cat`, `tee`, `sed -i` or
Perl.

Update only the frozen eight paths. Rewrite the durable report so these
headings appear exactly once: `结果`, `过程`, `遇到的问题`, `解决方式`,
`遗留风险与建议`, `沉淀候选`. Include state/UI/SLA matrices, complete
FR2-H05-001..009 dispositions, actual commands/counts, requirement traceability,
changed paths, limits and positive/negative sedimentation samples. At least one
`✅ 完成检查：` line must cite an actually executed backticked command,
`exit 0`, and concrete output. If any gate fails, report failure truthfully and
stop naturally.

Do not commit, merge, push, install/uninstall/repair a real runtime, signal
sessions, write Git, call network/devices/Figma, mutate production, or claim
H04/H06/release acceptance.
