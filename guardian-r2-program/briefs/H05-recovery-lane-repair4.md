/model
选择:gpt-5.6-sol（若当前可用列表无此型号，选择 deep 档或更高的 Codex模型）
/reasoning
选择:high 或更高
执行任务文件:guardian-r2-program/task-definitions/H05-recovery-lane.json

# H05 repair4 — fail closed when recovery truth is unobserved

Continue the same H05 worktree and preserve the eight-path repair3 candidate.
Do not clean, revert, rebuild the plan, repeat accepted H02/H03 work, or start
H04/H06. Repair3 ended naturally and passed 54+12 tests, but independent code
review found FR2-H05-010, so H05 is not accepted.

## Verified finding

`recovery_readiness_projection()` currently evaluates an absent
`recovery_truth` as `{}` and defaults both `lane_available` and
`typed_route_available` to `True`. Therefore ordinary `project()`/`collect()`
can report recovery `ready` and statusline `恢复可用` without any observed or
verified recovery lane. This is false readiness and violates fail-closed
status semantics.

## Required repair

1. An absent, malformed, or incomplete recovery truth must never produce
   `status=ready`. Represent it as `unobserved` or `unavailable`, with explicit
   typed reasons and conservative unknown generation/snapshot/catalog fields.
2. Only an explicit current truth with exact `lane_available is True` and
   `typed_route_available is True` may produce recovery `ready`.
3. Preserve the intended positive behavior: an explicitly verified recovery
   lane remains visible and ready when the ordinary task lane, scheduler,
   launcher or interactive domain is degraded.
4. Add regression coverage for at least:
   - `project(..., recovery_truth=None)` does not claim ready;
   - incomplete/malformed truth does not claim ready;
   - statusline does not append `恢复可用` for absent/unobserved truth;
   - explicit verified true/true still appends `恢复可用` without rewriting the
     primary task/interactive failure label.
5. Rerun the complete H05 suite and H03 supervisor suite; report the new actual
   test counts, not the previous 54 expectation. Run AST/compile, diff, exact
   eight-path scope, report contract and no-new-bytecode checks.
6. Update the durable report with FR2-H05-010 root cause, actual repair and
   evidence. Keep FR2-H05-007 transferred/open for H06 installed-runtime
   acceptance; do not claim it fixed by this repair.

`apply_patch` remains the only editor. The authorized finite
`shutil.which("apply_patch")` plus `subprocess.run([exe], input=patch,
text=True)` transport remains the sole fallback. No direct Python file I/O,
temp writer, heredoc, redirection, pipeline, PTY, base64, `cat`, `tee`,
`sed -i` or Perl.

Only the frozen eight owned paths may change. The final response and durable
report must each use these headings exactly once: `结果`, `过程`, `遇到的问题`,
`解决方式`, `遗留风险与建议`, `沉淀候选`. Include an actually executed
`✅ 完成检查：` command, exit 0 and concrete count. If any gate fails, report
failure truthfully and stop naturally.

Do not commit, merge, push, install/uninstall/repair a real runtime, signal
sessions, write Git, call network/devices/Figma, mutate production, or claim
H04/H06/release acceptance.
