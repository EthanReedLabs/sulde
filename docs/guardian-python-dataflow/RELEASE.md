# Python data-flow local release

Status: INSTALLED AND VERIFIED. Capability tier: deep.
The preparation section records the pre-install plan; final results below supersede
its historical production-unchanged statement.

## Frozen next-stage scope

Following the user's next-step request, propose a native-readable release card:
merge the accepted repair into dev, update only the plugin manifest version with
the official sealed helper, prepare and verify an isolated candidate, and promote
that candidate once through the transactional installer. No remote push, main
changes, business-project changes, policy widening, or unrelated runtime repairs.
The new card must replace the development-only R2 before installation.

Keep the task worktree as the physical authority source until installation and
independent effect verification finish. Fast-forward the registered dev worktree
only if clean and still at the reviewed base. Never reuse an old grant or receipt.
If candidate preparation or verification fails, retain the existing production
generation; promotion failure uses the transaction's rollback/recovery evidence,
not a blind reinstall. Stop for a new scope decision if code changes are needed.

## Reusable acceptance and protected evidence

Reviewed dev base: f034452def541d2f63660a19ec5725b87b9362e1.
Accepted repair: e4e50affd7dc5de1a7bb72881dc364daf7cd15e5.
Acceptance report: c4d05ba7c4c25cb2d77cc98359fefb2efa2f07b4.
The latter adds only evidence/report documentation. The 390-test impact run
contains 373 passes, 17 skips, and no failures; its exact source/log digests and
native CLI positive/negative evidence are in EVIDENCE.json and REPORT.md.
Do not repeat the full suite for this release-document/manifest-only transition.
Recheck exact implementation bytes, manifest structure, candidate verification,
and the new installed generation instead. Any code drift invalidates this reuse.

All 30 raw evidence files (121,016 bytes), including ignored logs and failed runs,
were archived with git stash --all for the exact task evidence directory.
Every archived path, byte count, and SHA-256 matched the live pre-archive inventory.
Local recovery ref: refs/sulde/evidence/guardian-python-dataflow-20260911.
Object: f7f4a4f116c5610413f71f13fd2f9875e282c67d; raw files are in its third parent.
The local evidence ref is private and must not be pushed. No evidence was discarded.

## Installation acceptance

- Official no-bytecode cachebuster and install profiles, one verified use each.
- Candidate source committed and clean, matched to integrated dev code.
- Candidate prepare/verify leaves production untouched before promotion.
- Installed source/artifact/runtime bytes and generation identities agree.
- A current-session real local string read/replace/write positive executes inside
  docs/guardian-python-dataflow/live-canary/; an official real out-of-scope negative
  is rejected before execution with no marker and matching generation identities.
- Read back deployment, launcher, scheduler and effect ledger. Separate existing
  background semantic degradation from release/scheduler readiness.
- End Skill frames and use the registered completion/workspace release protocol
  before removing a clean, merged task worktree and branch. Preserve evidence.

## Final local result

Native R3 approval applied the release scope. The accepted repair, release plan
and official cachebuster were fast-forwarded into dev at `09cfdb5` before candidate
preparation. Candidate `guardian-python-dataflow-20260911` was verified and promoted
once; production stayed unchanged throughout prepare/verify. Version:
`0.2.5+codex.20260911023102-9ad36bd2ad`. Deployment is generation_verified and the
runtime owner is active; both operational_ready values are true. The artifact,
installed runtime and tested source have identical repair bytes. Candidate,
canonical artifact and installed generation files also have identical bytes.

The actual current-session string read/replace/write command exited 0 and produced
`after` in the retained harmless canary fixture, plus the expected transformed keys.
Its real started/completed audit pair is local_write/allow, with both module and
artifact identities matching the new install. The actual destructive negative was
denied by PreToolUse; finalize independently verified its untouched marker and
removed that isolated marker. This is not a claim that ordinary out-of-plan local
writes are denied. Proof ID:
`81d98737f9f54fd790b666a0ee79b5a522f1afdf60d9abc2aa7f06ab05e855c8`.

Both exact continuation grants were consumed once and independently settled by
their content verifiers. No open event, pending verification, integrity breach,
pre-execution gap or current-lane Hook failure remained at readback. Current-session
interactive readiness is ready; scheduler is ready with 16/16 loaded and no failed,
missing or retired labels. Session/prompt continuity was verified across the hot
rebind, not fabricated as fresh SessionStart/UserPromptSubmit events. The current
thread proved the new Hook behavior without restarting. MCP kb_status responded;
its separate background snapshot remains degraded, as before this release, and
is not reported as repaired by this work.

The canonical candidate promotion adapter accepts `python -B candidate...`, whereas
the cachebuster-v2 helper requires the explicit no-bytecode environment prefix.
An initial promotion command with that extra prefix was rejected before execution;
the recognized exact adapter invocation then consumed the same valid grant once.
No rule was bypassed or modified. Sandbox-denied candidate preparation and an
incorrect reconciliation positional argument also had no installation effect;
the native filesystem request and documented --contract form resolved those setup
errors. This release did not repeat the complete test suite.

Recorded execution times: preparation 2.244 s, isolated verification 18.254 s,
promotion 39.846 s. Installer internal total was 39.712 s, including 19.158 s for
snapshot/prepare; these exclude model/approval/inspection time and are not a claim
of overall turn speedup. Full bounded release evidence is in RELEASE-EVIDENCE.json.
This final report/canary fixture changes no runtime bytes and requires no reinstall.

Main remains `bd216b3` with its original .ua edits; no business files, remote refs,
or shared knowledge were changed. Private evidence remains recoverable from the
local ref above. Temporary task cleanup follows the formal completion anchor after
this report is committed and merged; the completion receipt is the cleanup truth.

## Sediment candidate

Verified: bounded receiver proofs and opaque-call invalidation permit proven
string transformations while preserving unknown/destructive receiver safeguards.
Routing positive: concrete read_text/string replace with an explicit write target.
Routing negative: a method name alone is not receiver-type evidence.
Execution positive: actual CLI positive plus matching dual-identity Pre denial.
Execution negative: aggregate test success or a returned installation READY alone
does not establish the current human session's live behavior. The existing
development report contains the full case and retained limits; no duplicate KB
entry or optional memory write was attempted under the install-only effect scope.
