# R5 historical lifecycle supplement

Status: development acceptance passed on `34aa902`; subsequently released and verified in the original session under R6. See release-r6.md.

## Confirmed defects and bounded correction

- Historical maintenance restored only the current committed transition, not
  completed older release pairs. The explicit history entry now validates both
  the closed source and completion anchor, exact provider/session/resources,
  canonical release/completion hashes and ordered timestamps before publication.
- Rediscovering the Git root of a deleted task directory collapses its identity
  to the enclosing repository. Recovery hashes the already-recorded physical
  worktree root instead. A read-only production dry-run finds the two expected
  historical task-to-dev edges, including the original SessionStart worktree.
- SessionStart and UserPromptSubmit were unnecessarily required to come from
  one historical runtime. Each signed lifecycle capability is now selected
  independently, requiring a real current-runtime Pre/Post pair. Permission
  observations are never carried. A same-session Stop applies across workspaces.

History recovery is bounded by 256 contracts, 4 MiB per file, 64 MiB total and
128 signed edges. It uses nonblocking per-session locking, source/mapping CAS,
atomic publication, deduplication and retries. No original contract/log, route,
grant, pending verification or effect debt is changed. History scans are absent
from the ordinary Hook/readiness path. Missing or invalid evidence remains
inconclusive; an Allow or prepared target alone cannot prove historical commit.

## Evidence boundary

The new native test stages and installs a candidate into isolated roots and
uses actual Codex CLI app-server, unified exec, native Hooks and a fresh candidate
reader. A deterministic loopback model supplies commands without external model
requests. Actual Git/control CLI operations produce the release and cleanup
records; only the disposable derived lineage is removed to emulate a missing
legacy projection. Original records are byte-compared after reconstruction.
The final denial binds both loaded-module and artifact generations. Unit fixtures
for mixed generations are not represented as live upgrade evidence.

The first exploratory fixture deleted the live app-server process/turn cwd.
The host then reported Hook spawn ENOENT (duration 0); a later turn also rejected
an invalid cwd. This failure is retained, not accepted or concealed as successful
continuity. The passing fixture launches the real host from a persistent root,
uses the task root for thread/start, ends the first turn and explicitly selects
the target cwd for the next turn in the same session. Guardian lane handoff alone
does not migrate an operating-system cwd. Automatic deletion of a live host cwd
is a separate cleanup-safety limitation, not repaired by this historical reader.

Other development failures: the first candidate omitted an untracked new module
(fixed by tracking it before staging); the old split-predecessor negative asserted
the behavior intentionally replaced by R5 (updated to assert independent verified
origins and no approval transfer). No production installation was attempted.

## Verification plan

Persist exact-source affected lifecycle/host/readiness/contract/native tests and
the genuine multi-hop test separately. Compare current dev/R4 against this source
with the predeclared median/p95 budgets. Do not rerun the unrelated full suite for
this localized supplement; do not claim the R4 full suite tested the R5 tree.
After pass: merge dev, obtain fresh sealed cachebuster/install authority, validate
an isolated candidate, promote, explicitly recover the current old session,
re-read doctor and a real dual-generation pre-denial, then settle release debt.
No push, no main mutation, and no unrelated Git/Figma control changes.

## Sedimentation candidate

Evidence: verified in read-only production dry-run and isolated native recovery.
Context: historical worktree identity after cleanup.
Routing positive: completed release pair binds the deleted exact physical root.
Routing negative: a missing path must not be rediscovered as its parent Git root.
Execution positive: reconstruct non-authorizing signed lineage from both original
records, retaining their bytes and requiring a current real host roundtrip.
Execution negative: synthesize a SessionStart, infer a committed transition from
Allow alone, or reuse old authority to make readiness green.

No direct knowledge-base write; coordinator single-writer ingestion remains the
only route for this candidate.

## Frozen-source development results

Tested commit: `34aa902473d5f4d83076c7426987751e0ae2319a`.
Tracked input content digest (report directory excluded):
`b33b5b9d7e308c374a40fdc867bb96502f220135cc7067e54948153da290d0a4`.
All four records verify unchanged source before/after execution. Files are in
`.sulde/data/guardian-session-continuity/<run>/`; full logs accompany JSON summaries.

| Run | Result | Log SHA-256 |
| --- | --- | --- |
| targeted-20260908T114847Z-6d1651a0 | 384 tests: 367 pass, 17 existing retired-Git skips; 127.678 s | b63415f27b288786d1129b89d80aec6c28aab5848affb4c5e55c06105a858e0a |
| targeted-20260908T114907Z-063572ed | Real historical multi-hop, original records unchanged, dual-generation denial; 21.616 s | a066c540ec10bab21032b41f11606fe44e26bad798638659e341cb0278958701 |
| targeted-20260908T115123Z-8bb7da1b | Original same-turn positive/negative continuation; 19.611 s | 7bae4f5de0eb4c6e5e3d145506295ac4d7c41a1d9bf2effe7d4c10bdfd99a3d8 |
| performance-20260908T115202Z-f100967d | Both fixed-budget benchmarks pass; 332.717 s | da0ec79cec77f4366255b11706c933e9e4c7cc8b513fa7cfb0a1164e7e007c6f |

Performance baseline is clean dev/R4 `a2d6010`, with 80 samples per case and
quiet / 49,542,455-byte historical log fixtures. Values below are milliseconds.

| Operation | Quiet median before → after | Busy median before → after | Quiet p95 before → after | Busy p95 before → after |
| --- | --- | --- | --- | --- |
| Fresh observation | 3.9066 → 3.8511 | 3.6575 → 3.6950 | 4.2519 → 4.1076 | 3.9786 → 4.0155 |
| Deduplicated observation | 2.2417 → 2.1921 | 2.0977 → 2.1631 | 2.5368 → 2.4690 | 2.1897 → 2.3836 |
| Readiness | 0.4624 → 0.4373 | 0.4405 → 0.4425 | 0.5655 → 0.4513 | 0.4571 → 0.4679 |
| Classification batch | 985.6316 → 960.2470 | 947.4842 → 935.3146 | 1044.6240 → 1055.4857 | 970.0798 → 975.2843 |

The roughly 5.5-minute benchmark duration is predominantly the fixed 80-round
classification batches, not installation or a hidden full-suite rerun. Positive
and negative measurement deltas are both retained; this is budget compliance,
not a claim of zero overhead or end-to-end Agent speedup.
