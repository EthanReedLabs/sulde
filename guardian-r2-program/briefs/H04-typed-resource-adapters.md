/model
选择:gpt-5.6-sol（若当前可用列表无此型号，选择 deep 档或更高的 Codex 模型）
/reasoning
选择:high 或更高
执行任务文件:guardian-r2-program/task-definitions/H04-typed-resource-adapters.json

# H04 typed resource adapters

Implement only the already-registered H04 task. Do not rebuild the R2 plan,
repeat H00-H03, start H05/H06, install a plugin, or modify production state.

The full clone HEAD is the frozen
`dev@0eb4fb6553e652b0352750f4bac24aa6bae746d7` baseline required by task
authority. The coordinator projects these accepted dependencies as read-only,
ignored files:

- `scripts/kb/human_grant.py` SHA-256
  `6b5ec257cb4ca0edb446f861aab1aea19f43bec17ff6711804bcb7ecbc0cb2d8`;
- `scripts/kb/grant_broker.py` SHA-256
  `89432ec4808a470c5e48644b5859436c44485349e9379816266c106cbc9be458`.

Read and compose with those exact APIs. Do not modify, stage, replace or claim
ownership of either dependency projection.

Before implementation, consume the full local KB sources already selected by
the coordinator: `knowledge/anti-patterns/0244-explicit-git-add-collapsed-to-repository-scope.md`,
`0242-read-only-mcp-interruption-false-effect-intervention.md`,
`0074-git.md`, and `0192-parallel-git-writes-index-lock.md`. The first two are
verified rules; preserve the explicit safety boundaries in their negative
samples.

## Typed resource protocol

- Define strict versioned resource identities and actions for Git metadata,
  local deletion, workspace/cross-project access, Figma, and devices. Every
  executable capability binds canonical subject, exact action, constraints,
  current world state, grant/dispatch identity and an independent verifier.
- Keep classification, authorization, execution and verification separate.
  Parsing a target is never execution authority; HumanGrantV2 is not a broad
  bypass; a verifier receipt is not reusable authority.
- Unknown, malformed, stale, aliased or substituted identities fail closed for
  the affected resource only. Terminal/quarantined historical debt and an
  unrelated empty target must not become a global blocker.
- Use plain JSON-compatible immutable values, explicit schema versions and
  deterministic serialization. Reject unknown fields where authority-bearing
  data is decoded.

## Git and linked worktrees

- Model the worktree root, linked-worktree gitdir, common gitdir/index/ref
  identity and exact Git action independently from content paths. A `.git`
  file pointing to `<common>/.git/worktrees/<name>` must be parsed and bound,
  not treated as arbitrary direct `.git` write authority.
- A human-approved exact `git add -- <literal files...>` may update index only
  for the enumerated regular files. Reject options, directories, symlinks,
  missing paths, globs, pathspec magic, interactive/update/all forms and
  control paths. Verify the resulting index paths independently.
- Exact approved commit and merge actions may perform only their typed Git
  metadata consequences when expected HEAD/index/parents/message/ref and
  single-writer lease still match. They do not authorize reset, clean, push,
  force, arbitrary ref writes or direct filesystem writes under `.git`.
- Read-only `status`, `diff`, `rev-parse`, `show` and equivalent finite reads
  must not depend on an unrelated task lane being bound/healthy. Preserve
  repository identity and argument safety checks.
- No parallel Git writes may share one common gitdir. Tests must use separate
  temporary repositories/worktrees or deterministic serialization.

## Delete, workspace, Figma and device resources

- Exact deletion binds one canonical existing target, parent directory
  identity, expected type/size or tree digest, allowed effect and postcondition
  verifier. Explicitly approved recursive deletion may remove only that exact
  target; reject root/home/workspace root, unresolved variables, glob expansion,
  parent replacement, symlink traversal and identity drift.
- A cross-project grant may authorize one exact canonical workspace/repository
  outside the session's original project when the readable card names it. It
  must not silently enlarge future task scope or inherit authority to sibling
  repositories.
- `use_figma` must extract and bind `fileKey`, page/node identity, mutation
  kind, constrained payload and independent readback. Read-only calls remain
  read. A missing Figma target blocks only that Figma write. Aborted or terminal
  quarantined historical Figma attempts cannot block an unrelated local
  `apply_patch`.
- Device actions bind provider, device serial, package/bundle, artifact digest,
  exact operation and data constraints. Cover install/read/test-data cleanup
  positive paths while purchase, uninstall/data-clear and deletion of original
  user data remain denied unless separately and exactly authorized.

## Incident and failure matrix

Add deterministic local tests for I04, I09, I14, I15, I17 and I19, including:

1. linked-worktree exact add/commit and read-only Git positive cases;
2. `-A`, directory/glob/pathspec, common-dir substitution, concurrent index
   write, HEAD/index/world-state drift and direct `.git` negative cases;
3. one exact approved failed-package/temp-clone deletion and attacks using
   parent replacement, symlink, home/root, sibling target and changed digest;
4. exact cross-project grant versus sibling/replay/provider/session drift;
5. Figma fileKey/node/page/mutation/readback extraction, read interruption,
   empty target isolation and terminal-quarantine historical replay;
6. device serial/package/artifact binding with purchase, data-clear, original
   data deletion and target-substitution negatives;
7. unrelated safe local patch remains routable when prior external debt is
   terminal; real unresolved external writes remain blocked.

Tests use only temporary local fixtures and fake adapters. Do not invoke Git on
the coordinator repository, Figma, devices, networks, GUI automation, real
deletion targets, or production state.

## Verification, findings and report

- Run focused adapter/guardian tests, adjacent accepted H01/H02 composition,
  deterministic failure injection, AST/compile checks, `git diff --check`,
  exact seven-path scope and no generated bytecode.
- The task report is a mandatory durable record, not a prose afterthought. For
  every problem discovered during implementation or independent review, record
  an FR2-H04 identifier, symptom, evidence status, root cause, resolution or
  explicit unresolved disposition, verification evidence, and remaining risk.
  Do not hide failed candidates or failed commands; preserve them as history.
- The report must include requirement/incident traceability, resource schemas,
  action matrices, verifier matrix, exact commands and observed counts, actual
  changed paths, all findings and dispositions, known limits, and `沉淀候选`
  with problem context, evidence status, and routing/execution positive and
  negative samples.
- Do not claim H05/H06, installation, live-host, Windows, Claude, release,
  push, merge, dev/main or production acceptance.

## Hard boundaries

Only modify these seven paths:

1. `scripts/kb/resource_adapters.py`
2. `scripts/kb/intent_guardian_parts/resources.py`
3. `scripts/kb/local_file_operations.py`
4. `scripts/kb/command_template.py`
5. `tests/test_resource_adapters.py`
6. `tests/test_intent_guardian.py`
7. `guardian-r2-program/reports/H04-typed-resource-adapters.md`

Do not modify read-only dependency projections, task/brief authority, the R2
event log/task graph, other source/tests, installed plugins, production state,
`dev` or `main`. Do not commit, push, merge, delete real data, invoke Claude,
install, or clean pre-existing artifacts.

The final response must include each heading exactly once: `结果`, `过程`,
`遇到的问题`, `解决方式`, `遗留风险与建议`, `沉淀候选`. Include at least one
`✅ 完成检查：` line with a backticked command, `exit 0`, and a concrete
observable result.
