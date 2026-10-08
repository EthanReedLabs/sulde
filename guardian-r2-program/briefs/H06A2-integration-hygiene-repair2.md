/model
选择:gpt-5.6-sol（若当前可用列表无此型号，选择 deep 档或更高的 Codex 模型）
/reasoning
选择:high 或更高
执行任务文件:guardian-r2-program/task-definitions/H06A2-integration-hygiene.json

# H06A2 integration hygiene — repair2 report closure

You are `guardian-r2-worker-h06a2`. Continue the exact repair1 candidate in the
same isolated full clone. This repair is report closure after an independent
coordinator test. Do not reset, discard, rebuild, commit, install, touch
dev/main, access external systems, change task authority, or modify a path
outside the frozen nine-path H06A2 definition.

## Frozen authority and accepted coordinator observations

- Base: `1b793c6ba8b76acd069510ed893de77228d581c6`.
- Task-definition SHA-256:
  `e04be7e6f3e1abf078549613d8439f346b77d1406b5e0a5ee3cf360608555d57`.
- Preserve all eight current code/test deltas. Independent review found no
  code-level blocker and authorized the coordinator formal test.
- Coordinator formal wrapper SHA-256:
  `8598f825c27c334c97ea80cc39dd04f2b1dbaef6c00f7783f69a0798956c2051`.
- Exact coordinator command:
  `/private/tmp/sulde-codex-01491.8Oc2Dm/run-h06a2-formal-with-audited-codex.zsh`.
- Verified result: temporary sealed `codex-cli 0.149.1`; formal cursor
  `/private/tmp/sulde-h06a2-formal-cursors.GvGO32`; 439 tests in 95.211 seconds,
  all `OK`; the real-CLI authority positive, help stderr drift negative,
  executable/version negatives and generation/profile/broker negatives all ran;
  no production-write violation and no concurrent-production-state diagnostic
  appeared; wrapper then printed `RESTORED codex-cli 0.150.1` and retained the
  cursor. A later independent readback again observed global 0.150.1.
- The formal result closes only H06A2 test acceptance. It does not make 0.150.1
  the installed audited authority. FR2-H06-001 remains open for H06B.

## Durable report repair

Rewrite the existing report without changing its six-heading contract. It must:

1. State that H06A2 candidate verification is complete and ready for the
   coordinator's append-only task evidence/state transitions, while explicitly
   not claiming H06 or program acceptance.
2. Include the exact coordinator formal command above as an evidenced check,
   exit 0, 439 tests `OK`, production guard clear, exact cursor, and the restored
   0.150.1 readback.
3. Preserve historical truth by referencing append-only findings and managed
   run artifacts. Do not repeat historical nonzero exit tokens in the current
   success report: the strict report contract treats every such token as a
   current failure. Do not call an unresolved required check successful.
4. Use the exact mapping:
   - FR2-H06-003: delayed import plus recovery/resources line limits, fixed.
   - FR2-H06-004: four UTF-8 subprocess calls, fixed.
   - FR2-H06-006: original H06 lacked authority for predecessor paths; H06A2
     owns the repair but does not retroactively widen H06.
   - FR2-H06-007: H06A lacked the report path; H06A2 includes it.
   - FR2-H06A2-001: managed outer Seatbelt cannot run the nested formal runner;
     resolved by the coordinator single-layer 439-test run.
   - FR2-H06A2-002: authority positive used isolated HOME/weaker help checking;
     fixed with `SULDE_PRODUCTION_KB_HOME` and production-isomorphic preflight.
   - FR2-H06A2-003: report mappings/provenance were wrong; fixed here.
   - FR2-H06A2-004: repair brief reused an immutable run slug; already resolved
     by a new slug with unchanged task authority.
   - FR2-H06A2-005: historical nonzero text invalidated repair1 report; fixed by
     keeping exact history in append-only findings and current proof in report.
   - FR2-H06-009: provision/run Git layout mismatch; resolved with the physical
     full clone and does not alter the task code result.
   - FR2-H06-002: the current quiet formal run observed a clear production
     boundary and supplies evidence for coordinator resolution.
   - FR2-H06-001 remains open and transferred to H06B.
5. Count four unchanged read-only control projections: original brief, repair1
   brief, this repair2 brief, and task definition. They are not task output.

## Verification

- Re-run the eight worker-safe focused architecture/UTF-8/version/help negatives,
  AST compile, `git diff --check`, nine task deltas plus four unchanged control
  projections, recovery/resources nonblank-line preservation, and no-pyc check.
- Run `task_report_verdict` against the final report and require `passed=true`
  with no failure reasons before returning.
- Do not rerun the real installed positive or formal suite inside this managed
  provider sandbox; the exact coordinator evidence above is authoritative.
- Keep the exact heading order: `## 结果`, `## 过程`, `## 遇到的问题`,
  `## 解决方式`, `## 遗留风险与建议`, `## 沉淀候选`.

No commit, push, install, Claude, Windows, scheduler, rollback or release claim.
