/model
选择:gpt-5.6-sol（若当前可用列表无此型号，选择 deep 档或更高的 Codex 模型）
/reasoning
选择:high 或更高
执行任务文件:guardian-r2-program/task-definitions/H05-recovery-lane.json

# H05 repair2 — repair apply_patch transport and finish semantic acceptance

Continue the same H05 worktree and preserved `recovery_lane.py` candidate. Do
not clean, revert, rebuild the plan, repeat accepted tasks, or start H04/H06.

Repair1 `run-ff6623629170412097a1ae62` ended naturally, closing
FR2-H05-004/005, but strict report verification correctly failed because its
own report says H05 is incomplete. FR2-H05-006 remains open: the nested Codex
native `apply_patch` adapter rejected multiple legal payloads before execution.
No repair1 file change occurred. The preserved 614-line candidate remains the
only changed path and is AST-valid.

## Authorized apply_patch transport repair

`apply_patch` remains the only file editor. Try the direct native tool once
with a minimal valid patch whose very first byte is `*`. If the same adapter
validation defect recurs, this repair authorizes exactly one fallback transport:

- issue one finite noninteractive `python3 -c` command;
- use only `shutil.which("apply_patch")` and `subprocess.run([exe],
  input=patch, text=True)` to feed a literal patch string to the real
  `apply_patch` executable;
- Python must not import `pathlib`, call `open`, or write/replace any file;
- the command has no heredoc, redirection, pipeline, PTY, temp file, base64,
  shell substitution, `cat`, `tee`, `sed -i` or Perl;
- use small reviewable patches and require each subprocess return code to be
  zero before continuing.

The sandbox still limits writes to the eight frozen owned paths. If neither
direct tool nor the exact apply_patch-stdin transport works, stop naturally and
report the blocker; do not invent a third path.

## Semantic completion gates

1. Finish the sealed recovery capability/lane, including rejection of future
   issuance time and cryptographic/sealed card identity, exact provider/session/
   workspace/generation/action/pre-state binding, replay protection and narrow
   pre-policy routing.
2. Add execution plus independent verifier, bounded reprobe/idempotency, H03
   progress/terminal integration, UI Allow/Deny/view diff/later, append-only
   historical settlement and zero fixed-text/terminal-command authority.
3. Integrate current truth into `operational_readiness.py`, recovery routing and
   `sulde-status.py`: task-lane failure must not hide recovery availability;
   distinguish stale snapshot, current hook generation and skill-catalog
   restart; enforce 5/30-second stage progress and suppress duplicate waiting.
4. Add and run `tests/test_recovery_lane.py` plus scoped additions to
   `tests/test_operational_readiness.py` and `tests/test_sulde_statusline.py`
   for every original state, UI result, forged/replay/drift negative, SLA and
   failure axis. Run adjacent H02/H03 composition, AST, `git diff --check`,
   exact eight-path scope and no-generated-bytecode checks.
5. Write the durable H05 report. It must record FR2-H05-001..006 with root
   cause, resolution/evidence or explicit open disposition, exact commands and
   counts, state/UI/SLA matrices, requirement traceability, changed paths,
   limits and `沉淀候选` positive/negative samples.
6. Do not commit, merge, push, install/uninstall/repair a real runtime, signal
   sessions, write Git, call network/devices/Figma, mutate production, or claim
   H04/H06/release acceptance.

Only the eight paths in the frozen task definition may change. Read-only H02
and H03 projections remain immutable.

The final response must include each heading exactly once: `结果`, `过程`,
`遇到的问题`, `解决方式`, `遗留风险与建议`, `沉淀候选`. Include at least one
`✅ 完成检查：` line with a backticked command, `exit 0`, and a concrete
observable result. Do not return success if any semantic gate above is absent.
