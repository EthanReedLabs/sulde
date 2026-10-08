# R12 — Pro dev integration and local installation

Date: 2026-09-13. Status: approved integration; sealed installation pending.
Current-session native revision 10, receipt `7b2de80e…`, permits integration and
candidate preparation. Formal maintenance needs a fresh exact post-merge card.

## Frozen inputs and scope

- Clean dev worktree: `.worktrees/guardian-v3-dev-merge`, base
  `e61683c08aaf97db3e8e9d105ea3154ec217061c`.
- Accepted task: `task/public-harness-export`, implementation/report head
  `7e5854159863c97fcaccc22c16395adeb044424d`; this plan adds no runtime code.
- Pro changes include empty-memory startup, portable installation-bound CLI
  identity v2, distributed task specifications, explicit 0.154.0 compatibility,
  early candidate rejection and private Claude packaging exclusions. Public-only
  export adaptations remain in the private exporter, not production KB contents.
- Existing installed version: `0.2.5+codex.20260911043115-19fde00701`.
- No public or private remote push, main modification, unrelated repair, direct
  marketplace/cache/launchd editing, user CLI upgrade or production-data deletion.

## Integration evidence

R4 recorded 98 passing private scoped tests; R9 covered installer, candidate and
runtime identity behavior, with its remaining Pro packaging failure fixed in R10.
R10 has 44 passing private targeted tests. Original failures/skips remain intact.
R12 adds 28 Pro integration tests in 1.184 seconds, zero skips or production-write
violations, for empty memory, task authoring/dispatch, synthetic sedimentation,
CLI binding and approval transaction fixtures. No unchanged full suite rerun.
Evidence: `.sulde/public-export/r12-integration-001/results.json` and `tests.log`;
log SHA-256 `e596aac57f6a3d2ff71a41136c1473a13c3c7f8854768357cf35e1ccba0e3382`.

## Execution and stop conditions

1. Commit this plan on the task branch, then fast-forward clean dev. Verify the
   exact commit/tree and preserve main and its three existing `.ua` modifications.
2. Freeze one new readable maintenance card on the merged physical dev workspace:
   official no-bytecode cachebuster and transaction install, each one verified use.
   Never reuse the old public/empty-corpus artifact, grant or production receipt.
3. Run the exact official helper, validate and commit only the manifest version,
   prepare/verify a new full Pro candidate using the approved CLI binding. Keep
   production unchanged until verification passes; retain any failure evidence.
4. Promote once through the official candidate/transaction installer. Independently
   verify installed generation, source/artifact/runtime bytes, effect settlement,
   MCP, current-session real Hook and scheduler state. Separate unobserved domains
   from passed checks; new code needs a new scope decision, not an ad-hoc bypass.
5. Record the result only after the material chain settles. Preserve private raw
   evidence before eligible merged task-resource cleanup; never delete audit facts.

Transaction failure must use its recorded rollback/recovery route, not repeated
blind installation. Windows native acceptance remains with Windows. Static Skill
refresh and live Hook behavior are different acceptance domains; do not demand a
restart merely to compensate for absent runtime evidence.
