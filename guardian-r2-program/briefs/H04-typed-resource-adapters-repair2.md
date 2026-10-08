/model
选择:gpt-5.6-sol（若当前可用列表无此型号，选择 deep 档或更高的 Codex 模型）
/reasoning
选择:high 或更高
执行任务文件:guardian-r2-program/task-definitions/H04-typed-resource-adapters.json

# H04 repair2 — repair apply_patch transport and finish semantic acceptance

Continue the same H04 worktree and preserved four-file candidate. Do not clean,
revert, rebuild the plan, repeat accepted tasks, or start H05/H06.

Repair1 `run-35dd7801a1964c0f80d62276` ended naturally and strict runtime verify
passed, closing FR2-H04-004/005, but its own final report correctly states H04
is incomplete. FR2-H04-006 remains open: the nested Codex native `apply_patch`
tool adapter rejected three legal payloads before execution. No repair1 file
change occurred. The original four partial source paths remain AST-valid.

## Authorized apply_patch transport repair

`apply_patch` must remain the only file editor. Try the direct native tool once
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

The sandbox still limits writes to the seven frozen owned paths. If neither
direct tool nor the exact apply_patch-stdin transport works, stop naturally and
report the blocker; do not invent a third path.

## Semantic completion gates

1. Re-audit and finish strict typed Git, delete, workspace, Figma and device
   resources with canonical identity, exact action/constraints, current-world
   state and independent verifier.
2. Ensure linked-worktree gitdir/common-dir parsing, exact literal add plus
   approved commit/merge, read-only Git independence, exact recursive delete,
   cross-project grant, Figma fileKey/node/page/mutation/readback and device
   serial/package/artifact constraints are actually consumed by hook routing.
3. Preserve all negative boundaries: main, broad pathspec, direct `.git`,
   parent/symlink substitution, workspace siblings, purchases, data clear,
   original user data and unresolved real external writes.
4. Add and run `tests/test_resource_adapters.py` plus scoped
   `tests/test_intent_guardian.py` cases for I04/I09/I14/I15/I17/I19 and failure
   axes. Run adjacent H01/H02 composition, AST, `git diff --check`, exact
   seven-path scope and no-generated-bytecode checks.
5. Write the durable H04 report. It must record FR2-H04-001..006 with root
   cause, resolution/evidence or an explicit open disposition, exact commands
   and counts, requirement/incident traceability, changed paths, limits and
   `沉淀候选` positive/negative samples.
6. Do not commit, merge, push, install, call real Figma/devices/network, delete
   real data, mutate production, or claim H05/H06/release acceptance.

Only the seven paths in the frozen task definition may change. Read-only H01
and H02 projections remain immutable.

The final response must include each heading exactly once: `结果`, `过程`,
`遇到的问题`, `解决方式`, `遗留风险与建议`, `沉淀候选`. Include at least one
`✅ 完成检查：` line with a backticked command, `exit 0`, and a concrete
observable result. Do not return success if any semantic gate above is absent.
