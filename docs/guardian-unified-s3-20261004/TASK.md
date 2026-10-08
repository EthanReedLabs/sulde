# S3-A isolated publication preparation

capability_tier: deep

Authorized revision 6, current Codex coordinator; approved 2026-10-05 local.
Native receipt e0027317faaa537467a0eacca0d4b529da24aaf7b7d1ec2b533606a413d37f4e.
Outcome: prepare and verify the S1/S2 artifact without production mutation;
only after scoped independent review, fast-forward the verified branch into dev.

## Frozen identities and expected impact

- Start dev: ac5dc9c16527e41ef959ebbcef88593b71548e83, clean.
- Input S2: 7ca26f8a5d83b8e23c8b349eaa71611fdbd29392, clean.
- Full-tested code: 4be6e31374537c3ae6c9085798c0b45bda7833e9.
- Main: f932ca8ca6b3ecdff01d03065981a4f7447e1fe7, protected.
- Branch/worktree: task/guardian-unified-s3-20261004 /
  .worktrees/guardian-unified-s3-20261004, created from dev then FF to S2.
- Expected product diff from S2: zero. Only task/report/evidence tooling may be
  added. Do not repair runtime, alter a validator, or relax a gate in this phase.
- Existing manifest version is deliberately retained for isolated evaluation.
  This artifact cannot be called production-promotable: official cachebuster,
  fresh sealed install authority and exact publication validation remain later.

## Continuous sequence and evidence

1. Recheck full-run JSON/log hashes, before/after identities and code/test/config
   equivalence. Documentation changes do not trigger another full run.
2. Official candidate CLI prepare/verify in task-local .tmp/s3-candidates;
   no promote/discard. Full isolation includes candidate homes and no paid model.
   Preserve native state/receipt and timings. Source must be committed and clean.
3. Check candidate source/artifact/cache consistency, Pre denial's two generation
   identities, positive execution and negative nonexecution, MCP and scheduler
   dry-run. Native approval UI/live scheduler are separate, not silently passed.
4. One consolidated independent read-only review; then FF into clean exact dev.
   If dev advanced, inspect actual diff first; no merge of a failed candidate.
5. Record outcome and independently copy/hash explicit evidence into a unique
   /Volumes/Optimus/Sulde/tasks/guardian-unified-plan-20261004/S3/ run directory.
   Missing mount means local retention, never a replacement directory.

Use input S2 formal evidence in its original worktree. Local new records live in
.codex-agent/s3-evidence. Authority journals and production logs are not copied.
Public report contains bounded facts and evidence hashes, not credentials.

## Boundaries / recovery / stop conditions

No main edits, push, production promote/install, cachebuster, SSH/deploy, paid
Agent calls, history-debt settlement, formal KB writes or old resource removal.
Unrelated worktrees and pending unknown effects remain untouched. Own candidate
resources are retained for review; no automatic production cleanup.

Budget: one prepare and one verification (90 minutes overall ceiling); one
diagnostic retry only if new facts establish an environment/fixture cause. No
repeated full suite. Two failures without new evidence change diagnosis, not
timeouts or scope. Stop on missing authority, CLI/source drift, live-state drift,
product defect, exhausted budget or an unsafe external prerequisite. Candidate
failure leaves production unchanged and forbids dev integration; retain evidence.

Source/integration/candidate/installed/live/business status remain separate.
U07 true-Agent, U08 active-run live upgrade/rollback, Claude live session, Windows,
remote business effects and S4 queue are not prerequisites to this bounded
candidate result and are not certified by it.

## Initial process observations

Installed old Guardian denied a combined help-only inspection as a context
mutation. No subcommand executed; separate read-only help calls succeeded.
No installed rule was changed. Host again reported saving an exact native
approval prefix although none was requested; it is not reused as authority.

### One permitted fixture retry (2026-10-05)

Initial candidate guardian-s3-20261005-660d5df used .codex-agent/s3-candidates.
Both normal writes were denied by the unchanged protected-control-path rule:
their resolved ancestors included .codex-agent. This was coordinator fixture
placement error, not an S1/S2 regression. Failed state and native audit remain
intact (live_preserved=true); destructive negative was independently denied.
The one diagnostic retry uses the already ignored .tmp/s3-candidates within
the same authorized worktree, with a new candidate ID. No source, assertions,
guard policy, timeout or approval boundary changes. Evidence itself may stay
in .codex-agent; a normal business-write fixture must not be placed there.
