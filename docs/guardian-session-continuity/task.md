# Guardian session continuity and false-pause repair v1

Status: ACCEPTED / R5 supplement released under R6; current old-session lifecycle, native pre-denial and production scheduler verified. See release-r6.md. Temporary-resource exit is finalized through the native completion receipt.
Base: dev `1b38b304b3fe22fffb30bf6fc13988bbd82d9f32`.
Branch: `task/guardian-session-continuity`.
capability_tier: deep

## Outcome

Reduce avoidable interruptions, do not expand safety authority, and do not slow
ordinary execution. User approved this acceptance on 2026-09-08. Native proposal
revision 2 applied in the current Codex session. Production stays unchanged until
an exact candidate passes and separate sealed release authority is obtained.

## Scope

### R5 supplemental boundary (2026-09-08)

The current session approved revision 5 against dev `a2d6010`. Recover only
completed historical release pairs whose closed source and completion anchor
agree on provider/session, exact resources, canonical digests and ordering.
Keep signed current-mapping handoff evidence; an Allow/prepared target alone is
not proof of a committed historical handoff. Missing evidence stays inconclusive.
Reconstruction is explicit, bounded, locked, CAS-checked and idempotent; it does
not edit original contracts, logs, routes or authority. Lifecycle facts from
different runtime generations are selected independently, with a real current
Pre/Post pair; a same-session Stop invalidates prompts across workspaces.

R5 verification: affected regressions, real isolated CLI release/cleanup/handoff
and historical reconstruction, dual-generation PreTool denial, and the existing
fixed performance budgets. R4 full-suite evidence remains historical baseline,
not an exact-R5 full-suite claim. Release needs fresh sealed authority; no R4
grant reuse. No production repair before candidate verification.

### Original scope

1. Persist bounded, per-provider/session lifecycle evidence outside the global
   observation tail. Original signed observations remain the truth. Provide an
   explicit, resumable migration; doctor stays read-only. A damaged projection
   is observation degradation, not permission and not a global task pause.
2. Prove workspace continuity using committed, verified handoff/release evidence,
   together with a real current-runtime Pre/Post pair bound to both module and
   artifact identities. Never synthesize SessionStart or transfer grants/debt.
3. Correct bounded Python receiver classification: data `str.replace` and
   `list.remove` are not filesystem deletion. Keep real filesystem effects and
   unresolved receivers distinct. Do not implement a general Python interpreter.
4. Separate pre-execution rejection, persistent safety pause and effect outcome.
   Correct historical false pauses only for exact, evidenced lane/cause using
   the established native recovery route; keep the original audit and real debt.
5. Two small offline TLA+ models plus executable regressions, real isolated host
   and candidate tests, same-host before/after performance, persistent evidence.

## Acceptance matrix

| Property | Required evidence |
| --- | --- |
| Fewer interruptions | SessionStart older than the 4 MiB tail remains discoverable; valid worktree/runtime transitions retain truthful continuity; rejected malformed call does not prevent the next ordinary call |
| No wider authority | Different provider/session/workspace without verified transition rejected; deletion/subprocess negatives retained; index/corrupt history cannot create authority or success |
| No slower normal execution | Same environment/fixtures before and after, median and p95; no full history scan, global lock, model checker or extra human question in the per-action path |
| Crash/rollback | Append-before-index crash, duplicate/out-of-order delivery, corrupt index, old schema, rollback and interrupted migration; original audit retained |
| Live chain | Real Codex CLI/unified executor/Hook/new candidate process, not fabricated proof; exact module/artifact identities; old current session release test when authorized |
| Isolation | Two sessions in the same project; production ledgers and unrelated worktrees unchanged by isolated tests |

## Execution sequence

Performance bounds fixed before measurement: same-host fresh workers, 80 warm
samples per operation/profile; median increase <= max(5%, 1 ms), p95 increase <=
max(10%, 2 ms). The absolute floor is measurement noise tolerance, not a claim of
zero overhead. Report every measured increase; these microbenchmarks alone do
not prove end-to-end host latency or cold installation performance.

- [x] Read skills and KB; verify dev/main and unrelated worktree state.
- [x] Create independent worktree; native workspace handoff with zero authority transfer.
- [x] Native revision 2 authorizes scoped development and isolated validation.
- [x] Capture baseline and failing regressions.
- [x] Implement classification/pause repair and targeted regressions.
- [x] Implement lifecycle projection/migration/continuity and targeted regressions.
- [x] Check bounded models and fault/concurrency cases.
- [x] Run real isolated host/candidate and performance comparison.
- [x] Run integrated suite once on the frozen source; rerun only affected
      evidence if the source changes, never reuse evidence from a different tree.
- [x] Review acceptance; commit/merge only if all development gates pass.
- [x] Exact candidate release authorization, install and old-session live Hook proof.
- [x] Full historical old-session lifecycle acceptance (verified original release pairs).
- [x] Final report, effect readback and independently verified evidence archive.
- Temporary-resource cleanup is a subsequent native completion transition; its
  authoritative outcome is `workspace_cleanup.status=complete`, not a prewritten checkbox.

No remote push; no main changes. No new Git/Figma management. No broad audit
cleanup, blanket unpause, unknown-to-success conversion or speculative business
incident attribution. Static Skill catalog refresh is distinct from Hook health.

## Problems discovered during execution

- An exploratory `workspace-handoff --help` used a nonexistent command spelling;
  corrected to `prepare-workspace-handoff` after the CLI enumerated its commands.
  No material effect. Status: verified / resolved; not a product defect.
- Native handoff and proposal were invoked without `prefix_rule`, but the host
  reported saving exact prefixes. No prefix was requested by the Agent. Preserve
  as a separate host-surface audit candidate; do not assume it authorizes a future
  proposal or expand this repair into host approval storage changes.
- The quoted forensic-script failure lacks its original command/session. The
  `.replace`/`.remove` implementation defect is confirmed, but attribution of
  that specific historical incident remains inconclusive until exact evidence.
- New test fixture mistakes were corrected, not classified as product incidents:
  `requires_verification` vs `verification_required`; TLC unary minus needs
  `Integers`; download parent directory missing; baseline helper omitted its
  provider argument; the isolated runner correctly removed a `SULDE_`-prefixed
  benchmark parameter; native fixture read the outer isolation marker too late,
  causing nested macOS sandbox failure. No production protection was disabled.
- The old handoff telemetry normalization drops source/no-authority fields.
  Recovery now independently joins asked/decided approval, execution receipt,
  immutable control audit and committed route. Decision receipt and subsequent
  execution receipt are deliberately different identities.
- The new native recovery path did not use the old control-audit exit. Added an
  idempotent exact-cause audit append before native transaction advancement.
- New sibling imports initially prevented runpy-loaded MCP observation. Candidate
  installation smoke detected it; runtime sibling resolution was fixed.
- Actual `python -B -c` did not use the old `python -c` classifier path. Added a
  narrow interpreter-flag parser and positive/destructive/unknown regressions.
- First performance sample failed quiet-profile p95 while native installation
  tests were running concurrently. Do not accept it or hide the observed
  +20.7% p95. Re-measure after source freeze without our other expensive jobs.
- A generic `prepare-proposal --workspace target` follows the current session
  route. The integration fixture must explicitly create and independently apply
  the target proposal, not claim that a source revision is target approval.

## Review findings addressed after first integrated run

- Restored the adjacent Node multiline boundary; Python extra argv still exposes
  its executable body, and shell-expanded source receives no data-method exemption.
- Borrowed literal bindings now reject unknown intervening calls, dynamic attribute
  or namespace writes and nested scopes. Their hard receiver-risk classification
  cannot be laundered into an ordinary unknown execution pass-through.
- Moved component imports to module scope; kept the 3,000-line architecture guard.
- Adapted isolated-run attribution to exact signed per-session index files only.
  Corrupt caches remain rejected; no blanket derived-directory exclusion.
- Corrected a test expectation: a prior allowed local write retains its open event
  when a subsequent pre-execution command is denied. Erasing it would hide evidence.
- First integrated run: 1,997 tests, 6 failures, 24 skips, 697 seconds, source
  `03fbb03e508b17714317d8fb0101236a2cef3e69e43b683e3235224d851c0743`.
  Preserve this failed evidence; it is not acceptance of the revised source.
- Two gate failures independently reproduce on unchanged dev: Community manifest
  still pins the former model-strategy template hash; seven existing text subprocess
  calls omit explicit UTF-8/errors handling. No Community export or model-policy
  change is included in this frozen repair. New files' encoding omissions were fixed.
- Added a separate fresh-call performance sample after reviewing the coverage
  gap in deduplication-only measurements. It passed the same frozen thresholds;
  no production kernel change was required and no full suite was repeated.
- Final live readback retains a current-session local-write start with no matching
  completion (`d33400b1e4182ef727824c94`, started 2026-09-08T09:08:09Z).
  It has no attempt or pending verifier; the lane remains bound and unpaused.
  Missing Post evidence is not proof of no write. No synthetic completion or
  stale-event settlement was issued for this still-active session.

See `report.md` for final source/evidence boundaries and remaining decisions.

## Knowledge constraints

Read in full: ap-0243 (composition denial is not automatically a safety pause)
and ap-0181 (real old-session Hook rebind differs from static Skill refresh).
Apply only within their positive boundaries. New lessons remain problem-card
candidates here, not direct writes to the shared knowledge repository.
