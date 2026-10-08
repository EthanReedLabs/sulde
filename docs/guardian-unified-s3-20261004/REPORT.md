# S3-A isolated candidate result

2026-10-05. Status: candidate_verified; independently reviewed and merged to local dev.
Not installed, not pushed, no main change, no production acceptance claim.

## Exact scope and evidence reuse

Revision 6 authorized isolated prepare/verify followed by local dev integration
only after verification and independent review. [Frozen task](TASK.md).
Input S2 7ca26f8; tested code 4be6e31. Preparation source fab75f2 changes only
task documentation from S2; scripts/tests/tools/hooks/skills/integrations/spec
are unchanged. S2 official full JSON/log independently rehashed, before/after
inputs match, and workspace digest recomputed in S3 equals
838ae92ca2561849498346d8991af439b534057e3c85b65add4cc61802dae4db.
Reused result: 2859 tests, 2830 non-skipped passes, 29 skips, zero errors/failures.
No duplicate full suite or claimed new full test was run.

## Initial failure and bounded correction

First candidate guardian-s3-20261005-660d5df was incorrectly placed under
.codex-agent. The actual two normal touch calls were denied by the unchanged
protected-control-path rule. This is a coordinator test-placement error, not a
new product regression and not evidence the negative assertion should change.
State remains verification_failed; receipt is absent, promotion_consumed=false,
live_preserved=true. Its original state and synthetic event logs remain intact.
One diagnostic retry moved only candidate-home to existing ignored .tmp within
the same authorized worktree, with a fresh ID. No validator/product changes.
Independent review confirmed this correction before final acceptance.

The failed probe left its exact 33-byte sentinel at
/private/tmp/sulde-pre-execution-canary-3f0804904238c13386088ef12029c167.
It is retained as failed-run evidence, not deleted with an unscoped shell action.
Its lifecycle cleanup is pending. The successful retry's own marker was removed
by its verified proof finalizer; the two probes are not conflated.

## Successful isolated candidate

- Candidate: guardian-s3-20261005-fixture2, source fab75f28c7fda15137079e606a4878b13552ff1b.
- Receipt seal: 27f9128bf30a1db1e3f6e754e11f203a3475ea56ba99e941b80fad4df7a8a7eb.
- Plugin tree: bbae4e75bcefec1f10dfe0641123d2e27bf4e9e56596ce6561aa7449528572f5.
- Runtime tree: 6eb2a11f4872b96902b7f8e9ccdc93f317732e7b758195244b1926de3f040954.
- Version remains 0.2.5+codex.20261004042610-d1eeed94b5 for this isolated trial.
- Initial and corrected artifacts have identical plugin/runtime hashes.
- Official prepare 1158.811ms, verify 20786.664ms, both exit 0. Host approval
  waiting time is not included in these tool execution timings.

Actual Codex CLI 0.160.0 app-server/unified-exec, local simulated model:
two normal files created (including outside the planning-only path), one exact
destructive call blocked before execution. Event c44101620c25a07faad22be1 /
candidate_native_2 in session 01a10c20-8134-7972-adeb-51bd929033a5 binds:

- loaded_module_generation df25fe7b0b7558218e27e9d8ceb76d0d2d59f0bebb0aae44da8f79c6ab4ff75e;
- artifact_generation version above + runtime tree above.

These identities are separately matched, not equated. Proof
315115b5c8eb632ee4951c28496d75e3761be207d7a8d97e9b0f72d574585e14,
negative marker absent after independent finalization, external_model_requests=0.
This is real host transport/Hook enforcement with simulated model responses,
not a real Agent reasoning demonstration or current production session proof.

Packaged/manifest MCP initialize succeeds. Scheduler production entrypoint
dry-run enumerates 16 labels without loading them. Actual candidate managed run
holds its generation lease, foreign switch is incompatible, own switch is
compatible, task success/exit 0 and retrospective queued. Reclaimable remains
zero both during and after; shared reclamation is intentionally still closed.
This is not U08's production active-run upgrade/rollback acceptance.

## Important nested states (not masked by wrapper status)

Candidate receipt is verified within its isolated scope. Initial hooks-list
discovery was review_required/untrusted (no production trust write); subsequent
native canary actually ran the hooks. Doctor execution returned exit 0, but its
payload is degraded: candidate has no active production deployment/owner or
real loaded scheduler. Native approval UI is unobserved/78; scheduler host is
unobserved/79. No claim of production operational_ready or human approval UI.

Live production snapshot in first prepare, failed verify before/after, second
prepare and verified receipt is identical. Installed Codex runtime remains
4f62781a1a0b461f5647fe0edb6a3a1529b4d63f4382d21f7c9eeb276df4c334;
the candidate 6eb2a11f... is NOT the installed runtime. No Claude change occurred.

## Review, integration and archive

Independent reviewer rehashed sealed state/receipt, all five native call events,
actual files, artifact/cache trees and 15 changed modules. S3 workspace fingerprint
and S2 formal evidence also matched. Report and archive helper reviewed together;
no blocker within this bounded scope. Actual dev FF ac5dc9c -> ca666dc completed,
dev and task clean, full-tree diff between them empty; main still f932ca8.
This closeout is documentation only, also integrated without rerunning tests.
Local candidate state/receipt and synthetic control ledgers remain in both
candidate roots named in TASK. S2 originals remain in its formal evidence root.
The explicit archive tool copies only these selected facts and task documents,
not production ledgers, model/session logs, credentials or the formal KB corpus.
Archive destination reserved for explicit exclusive write/readback:
/Volumes/Optimus/Sulde/tasks/guardian-unified-plan-20261004/S3/20261005T125350Z-fixture2-27f9128b/.
Its manifest binds the actual final source/dev HEAD and independent production
CAS readback. Existence of this path alone is not an archival success receipt;
validate manifest file hashes. Partial writes are never labeled completed.

Task/owner worktrees remain intentionally retained: this phase forbids old
resource removal and the current candidate artifact is still needed for release
review. No cleanup_complete claim; archive preserves evidence independently.

## Next boundary

Production publication still needs official version/cachebuster preparation,
fresh sealed approval, exact final-artifact validation and transactional install,
then per-host real canary/verifier/readiness readback. The current old-version
candidate is not directly promotable to overwrite another tree of that version.
No main merge/push is implied. Claude live, U07 true Agent, U08 live switching,
business SSH/recovery and Windows remain separately scoped. No paid calls,
production debt settlement, resource deletion or formal knowledge write.

## Sedimentation candidate (not written to the KB)

Verified bounded cause: a normal business-write probe cannot be rooted beneath
a protected control-directory component. Route positive: canary denied explicitly
for protected path; inspect fixture location and unchanged policy first. Route
negative: genuine control-file write must remain denied. Execution positive:
fresh ordinary scratch root, unchanged artifact and assertions, both positive
and negative facts independently observed. Execution negative: weaken the rule,
edit failed state or turn setup denial into a claimed product regression.
