# M2: owned-host maintenance rehearsal completed, production adapter not implemented

Date: 2026-10-06. Intent completion:6514aef628e75bf2049c2c4e revision 13.
Tested HEAD: 483537eb1f99001448ae5e10c924cdc56f324476.
Status: bounded-independent-review-passed for the r13 tests/docs scope only.

The user selected a one-time maintenance direction, then approved r13 through the
native decision surface. Receipt bc8b4f0f99d19a7ffc7f49d656f6868bf3c6a2ea034f860832f2b3fd60831fad.
No product source, legacy migration gate, actual user process, dev/main, production
installation/config/cache/scheduler or business/effect ledger was changed.

## What is now established

Two real Codex app-server processes, sharing a temporary home and synthetic plugin,
can stop within a test-owned maintenance cohort, update through the official plugin
CLI, restart with new PIDs and **resume their original thread IDs** with new callbacks.
The local deterministic Responses fixture performs only `printf m1`, no model service.

| Case | Observable result | Proof boundary |
| --- | --- | --- |
| Legacy normal controls | A and B each produce five 0.0.1 callbacks and command exit 0 | Real host, synthetic Hooks |
| Only A exited | Test driver refuses switch; registry_changes=0; B still calls old Hook | Driver-owned guard, NOT a shipped installer barrier |
| A and B exited | Owned process-group cleanup confirmed; official add succeeds | Owned cohort only, global_drain_verified=false |
| Reopen A/B | New PIDs, original thread IDs, five 0.0.2 callbacks at cache-external script; command exit 0 | No transfer of production Guardian authority tested |
| Omit new trust | hooks/list marks six definitions modified; no callbacks/completion notifications, command exit 0 | Correct negative control: not ready, not a host denial |
| Cold rollback | Exit validation host; official add old version; resume same thread; five old callbacks actually execute | Plugin CLI/host recovery, NOT Sulde transaction rollback |

Normal A: PID17907 -> 17971, thread 01a1108e-d2c0-7c20-bdee-5df61b8f4041.
Normal B: PID17920 -> 17992, thread 01a1108e-d30e-7a42-b7f8-98bc3efbe706.
Rollback: PID17813 -> untrusted17843 -> restored17868, thread
01a1108e-c051-7972-bf8b-5ce8e33193d7 unchanged.
Callback assertions bind event/version/session/script SHA and actual path. The raw
host stream carries thread/turn identities, command completion and Hook outcomes.

The rehearsal uses the existing owned-fixture lifecycle helper. Its bounded process
group cleanup may escalate for test-owned children only; this does not authorize
forced shutdown of user work. No unowned process discovery/termination was attempted.

## Evidence and test selection

Official record `.codex-agent/s3c-m2-evidence/formal/20261006T093230.030668-fc805fb201c9.json`
and matching `.log`; log SHA256:
`5df01abc67bb16950bca0ec9d68d14a428f17630e8cdd8b4a3a9e763c85b1eb2`.

4/4 checks completed in 13.080s (unittest body 12.635s), input_drift=false.
Four means two real-host scenarios and two encoding checks, not four production
acceptance cases. The fixture provides a normal control before each negative path.
There is no product fix, so no fabricated old-red/new-green claim. No product diff
under scripts/integrations/hooks/tools relative to 20f6104; the existing M1 helper
is imported unchanged. No full-suite rerun was warranted for tests/docs-only changes.
The official planner's risk field remains an overbroad refactor classification for
new test files; explicit selected scope records full_suite_satisfied=false.

Installed host reports codex-cli0.160.0. Launcher identity is codex.js SHA256
61b0194f3bb6534439c8d26a3ed57d0805f84b884588b761795323eeb92fcf70,
not a complete native dependency seal. Exact callback source hashes are separately
recorded. No paid/external model calls; coordinator reasoning/token cost unmetered.
No failed experiment run preceded this record. Read-only investigation slips are
listed in M2-DESIGN; they are not product defect evidence.

The separate update_review agent independently read the code, official record and
raw log, recomputed its SHA256, checked the cohort/identity/return-path assertions,
then reviewed this report. No blocking finding, no test rerun. Review acceptance is
limited to the tests/docs outcome above, not the subsequent product implementation.

The host again reported retaining an exact native approval command prefix despite
no prefix_rule being requested. It was not reused as authority or changed. Keep it
on the existing separate host-approval audit queue, not in this migration verdict.

## What this does NOT establish

- No actual Sulde legacy-to-stable transaction or maintenance capability exists from
  these changes. The existing gate continues to reject legacy migration.
- Fixture cohort membership is known by construction; it is not an inventory of all
  user's hosts. A scan cannot prevent a new non-participant process from starting.
- Synthetic automatic trust is not production human trust. PermissionRequest and
  real Guardian PreTool denial with loaded_module/artifact identities were not tested.
- Real task persistence, approvals/effect debt after production thread continuation,
  detached worker authority, crash-safe migration, concurrent nonparticipant arrivals,
  production rollback and Windows remain unverified. Original-thread resume here
  proves host session continuity, not inheritance of production task permissions.
- The design's full future fault matrix is **planned**, not completed by these two
  scenarios. No product success/ready flag was written.

## Next bounded implementation, not another feasibility loop

M2-DESIGN fixes the recommended operational boundary. Subject to a new source-change
scope, implement one exact maintenance executor/profile in the existing installer and
typed authority machinery: durable identity/approval before stopping any real host,
legacy transition provenance distinct from fresh install, existing journal rollback,
live verification before ordinary work resumes. Do not reuse launcher-repair grants
for process control: currently supported recovery actions are only repair_launcher
and repair_generated_bytecode.

The full unit/injection/entry/affected-regression/review chain belongs to that one
implementation task. Production shutdown/install remains a later exact approved
operation. If a truthful operational scope or independent recovery route cannot be
established, fail before mutation and report it; do not add a force flag or universal
process-control subsystem. Keep unrelated fence-corruption and historical debts on
their existing queues.

## Sedimentation candidate

Context: plugin definition changes across a one-time controlled maintenance window.
Verified host facts: old threads can resume after new process creation; modified
Hook trust can suppress callbacks despite successful commands; official cold rollback
can restore callbacks in a controlled fixture. Product migration remains inconclusive.
Routing positive: exact owned-cohort scope and explicit trust verification. Routing
negative: installed/exit0 alone or substituting managed-run fence for all native hosts.
Execution positive: same-thread callbacks after restore/restart. Execution negative:
withheld trust gives zero callbacks; a surviving owned host prevents the driver's
switch. Not written to the formal KB.
