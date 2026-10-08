# Dual-host installation continuation

Current status (2026-10-04): installed on both hosts. The preparation blocker
below is historical and resolved by the reviewed dependency recovery. Final
installation results and remaining evidence limits are at the end of this file.

Source repair 4e4388a fast-forwarded into dev; main unchanged. User requested
the next stage on 2026-10-04. The source-only stop line is now amended to permit
version preparation and isolated artifact validation. Exact production changes
require native approval of the sealed installation proposal, separately.

capability_tier: deep

Frozen impact: Claude product version 0.8.9 (installed rollback 0.8.8), official
Codex cachebuster, release evidence and this report only. No further runtime
fixes, no remote commands, no historical debt mutation, no main merge or push.
Re-use 4e4388a regression evidence only after exact input digest readback.

Sequence: version/evidence preparation -> merge preparation into dev -> exact
cachebuster/install proposal -> candidate prepare/verify -> promote -> Claude
official stage/CLI update -> installed byte/entrypoint checks -> independent
release review. An unavailable true live-host condition remains disclosed; a
synthetic Hook process never proves live host behavior. No model API calls.

Rollback: retain the current Codex generation and Claude 0.8.8 artifact/cache.
Candidate failure leaves production unchanged. Stop on identity mismatch,
missing authority, unbounded verification or unapproved scope expansion.
After two failures without new evidence change diagnostic method, not budget.

Integration accepts the known unchanged encoding-guard baseline only as a
disclosed pre-existing failure, not a whole-repository green release claim.
Runtime protection changes require both installed consumers checked before any
new historical-recovery event is used in production.

## Preparation result — installation blocked (2026-10-04)

Dev and task branch integrated repair `4e4388a` and preparation `c070300`.
Main remains `f932ca8`; no push. Production installation has not started.

- Release tests: 36 run, 35 passed, 1 skipped (`test_stage_plugin` and
  `test_host_capabilities`). Output is in the coordinator session, not a separate
  raw test archive. Prior source regression evidence is reused; not rerun.
- Official Claude staging produced 839 files / 390 corpus documents for 0.8.9.
  Eight changed modules match source byte-for-byte; isolated Hook subprocess
  checks allow Read and deny direct/wrapped SSH writes and remote deletion.
  No remote command was executed. Artifact content was unchanged by validation.
  This is synthetic entrypoint evidence, not live-host acceptance.
- Sealed installation proposal creation failed before authority/grant creation:
  `official plugin cachebuster helper is unavailable`.
  `_codex_plugin_cachebuster_binding` in `intent_guardian_parts/state.py` requires
  the exact `skills/.system/plugin-creator/scripts/update_plugin_cachebuster.py`
  beneath Codex home; that local system skill is absent. An arbitrary alternate
  path is explicitly rejected. This is a confirmed missing local dependency plus
  fixed-path coupling, not proof that the upstream helper has been discontinued.
- No cachebuster execution, Codex candidate promotion, Claude CLI update or
  production debt recovery occurred. Current contract remains preparation r4,
  with no pending proposal, verification, open event or integrity breach at
  checkpoint readback. Historical business debt remains outside this task.

Evidence under Optimus `Sulde/tasks/guardian-effect-recovery-20261004/release/`:

| Record | SHA-256 |
| --- | --- |
| `20261004T034830.998401Z-before.json` | `f31a71d8ee18f132f3ff218ea5de96fe6c12cab41d8e198bc1651bd0fb1b28b5` |
| `20261004T034943.215462Z-candidate-claude.json` | `650eef4ba2f529c812f5259a48d03d5fdf9b9c6a25de92ec9f5acfc0dc0afd14` |
| `20261004T040452.118724Z-final.json` | `79d90df778a515ba2046232322a0211980062b63667113a9194d38692565cd6b` |

Before/final inventories and shared deployment/runtime-owner/launcher/scheduler
file hashes are identical. Installed versions remain Codex
`0.2.5+codex.20261003135300-b04b6d9` and Claude `0.8.8`, both enabled.
The staged 0.8.9 candidate is not the installed version.

Next authority decision: restore a verifiable official dependency or authorize
a bounded dependency-resolution compatibility repair, then regenerate the exact
sealed installation proposal and continue dual-host verification. Do not fabricate
a helper, hand-edit immutable caches, substitute ordinary write authority or
mark installation accepted. Further runtime fixes are outside this frozen scope.
Keep the task worktree while installation is incomplete; do not repeat tests to
work around the missing dependency.

## Final dual-host installation (supersedes preparation blocker)

Dependency repair `9e026a3`, cachebuster `756598f`, both fast-forwarded to dev.
Runtime and manifest tested/installed tree: `756598fdfada8f97b00717182f98165d047a75eb`.
Subsequent report/tooling edits do not alter the installed runtime or manifest.
Main remains `f932ca8`; no push. The dependency recovery and preflight had a
consolidated independent review, 295 passing tests / 17 existing skips and real
helper-entry checks; see DEPENDENCY-REPAIR.md.

### Codex

- Version `0.2.5+codex.20261004042610-d1eeed94b5`, installed/enabled.
- Runtime SHA-256 `4f62781a1a0b461f5647fe0edb6a3a1529b4d63f4382d21f7c9eeb276df4c334`.
- Candidate `effect-recovery-20261004-756598f`: prepared, verified, promoted.
  Verification receipt `6c459be3793fb91780ce7552fdd006f786515b3dc755a8db3bce0e13662aa780`.
- Native r6 proposal approved; cachebuster and install grants each consumed once,
  settled by independent `system_verification`. No pending verification, open
  event, integrity breach or pre-execution gap in this task contract at readback.
- Nine changed modules match installed runtime bytes. Deployment is
  `generation_verified`; current doctor reports ready, scheduler 16/16 loaded,
  no failed/missing labels, current session bound.
- Actual current-session pre-execution negative canary:
  `23427ab56b19d32ca5c5536dd6424f6785513bbe2a88076825f9e794d7f5ff49`.
  Prepared sentinel deletion was refused before execution, event
  `b0c0523ed3efc00f2b65aee7`. Prepare/denial/finalize bind artifact generation
  above and loaded-module generation
  `7b657856e6292a0193ad95d80d79a2445844ed4e6554d3909e03a40cb17141e0`.
  These two identity fields are intentionally different, not compared as equal.
  Finalizer removed its exact sentinel; absence independently read back.
- Installer initially reported live-host unverified. The later current-session
  canary is additional evidence, not a rewrite of that boundary result. No new
  Codex session or real model invocation was created. Static Skill catalog
  refresh still needs a new session; this session's hot Hook dispatch is proven.
- Old Codex generation remains through the installer's controlled retired alias.
  No rollback was invoked.

### Claude

- Official staging from same tree: 0.8.9, 840 files / 390 corpus documents.
  Candidate `/Users/eric/.sulde/artifacts/sulde-claude-0.8.9-20261004-final`.
- Native marketplace add then plugin update returned exit 0, 0.8.8 -> 0.8.9.
  Inventory independently reports installed/enabled. All 840 installed files
  exactly match artifact hashes; nine repaired module hashes match source.
- Actual Hook subprocesses: Read allowed; direct/wrapped SSH write and remote
  deletion denied, without executing SSH. Complete trees unchanged afterward.
  These are **synthetic isolated entry checks using the explicit dependency-full
  interpreter**, not proof of live Claude session behavior or arbitrary project
  interpreter resolution. No new live Claude session was started. Existing
  Claude sessions must restart to load this update, per native CLI response.
- Shared deployment/runtime-owner/launcher/scheduler file hashes unchanged
  across the Claude-only update. Old 0.8.8 cache/artifact retained.

### Persistent evidence (Optimus release directory)

| Record | SHA-256 |
| --- | --- |
| `20261004T062000.294045Z-candidate-claude.json` | `9cb71e635576356821e94747fd88ca2b94e235d82c9aa0fe998000f0525fe7da` |
| `20261004T062124.675295Z-installed-claude.json` | `5c89fc52745a4d2c80e0a017556dddcf213ffa82aced000e833dfe4562303468` |
| `20261004T062243.990123Z-installed-codex.json` | `4904164534ae398bb83d4939fb0a50e91753c4270dc9c909583956c0fc89d28e` |

Installed Codex record includes full candidate promotion result, doctor and this
contract's runtime readback. Earlier records are retained, never overwritten.
Final consolidated read-only review passed: all three evidence hashes, 840 Claude
file matches, nine changed-module matches, 26 shared file hashes, current task
zero-debt readback and same-session proof were independently checked. That review
does not add live Claude evidence or proof about the original remote effects.
Installer total 80.506s: recovery scan 29.337s, snapshot/prepare 31.048s;
candidate verification 20.620s. This explains measured time, not Token savings
or permission to expand into another performance refactor.

### Boundaries and remaining work

Original remote attempt remains unknown: no SSH operation/read, historical debt
settlement or production recovery rebind was performed. New code does not claim
abort proves no effect. Restored archive helpers are not claimed to be upstream
latest; fixed host-path coupling and transitive dependency sealing are not
redesigned. Windows and live Claude-session enforcement are unverified here.
The baseline full-repository encoding failure remains separately disclosed.
This is a bounded repair-and-install delivery, not whole-program acceptance.
