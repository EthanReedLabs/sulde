# Intent Guardian Remediation Program

## Authority

- Intent contract: `guardian-p0-supervised-delegation-20260815`, revision 97.
- Coordinator: `guardian-coordinator`.
- Truth: immutable manifest plus append-only `events.jsonl`; generated status is never authority.
- Workers report progress only through their isolated artifact bundle. The coordinator's
  capability-bound single writer records those reports with the worker as the audit actor; workers
  never invoke the master log directly. A worker-authored report may justify progress only through
  `implemented`. Only the coordinator may mark `task_verified`, `integrated`, `system_verified`,
  `accepted`, or complete the program.

## Lifecycle

`planned → ready → running → implemented → task_verified → integrated → system_verified → accepted`

`blocked` and `superseded` are explicit states. An unresolved finding blocks verification. A new
finding must be resolved as `fixed_current`, `transferred`, `new_task`, `deferred_human`, or
`rejected_with_evidence`; these dispositions have mutually exclusive evidence channels, and this
program forbids silent human deferral. A transferred finding becomes a durable obligation of its
target and every later successor.

## Parallel boundary

- The coordinator is the only writer of the master event log, shared Git index, active contract,
  installation generation and final acceptance projection.
- Workers use fixed baselines and exclusive file ownership. They do not edit
  `scripts/kb/intent_guardian.py` or `tests/test_intent_guardian.py`; integration into those files is
  serialized by the coordinator.
- Source must be frozen before staging or installation. Full-suite and live-host canaries are
  serialized after integration.
- Every transition into `running` creates a coordinator-issued verification run and evidence
  floor. Reopened work cannot reuse evidence from an earlier implementation campaign.

## Per-task evidence

Every task records scope, base, changed files, discoveries, evidence, root cause, resolution,
targeted tests, failure injection, residual risk, integration instructions and rollback. Evidence
uses the `sulde-guardian-program-evidence-v1` schema, must carry a passing verdict, concrete facts,
and at least one structured command result or digest-bound artifact. Evidence is bound to the task
baseline and current verification run; conflicting active evidence identities block progress until
the coordinator records an explicit, semantics-preserving supersession. A worker success message
or tool exit code alone is not acceptance evidence.

## Final gate

All manifest requirements and every acceptance clause must be covered by accepted tasks. All
findings and transferred obligations must retain active resolution evidence, and the nine
program-level evidence kinds in the manifest must exist. Native Windows is not a tenth synthetic
kind: its exact artifact identity must be bound by the final task's `system_tests` and the program
`final_traceability` evidence. Completion first freezes every active
evidence document and artifact into an owner-read-only, content-addressed snapshot, then writes a
head-bound prepared record, and only then appends `program_completed`. After that append, the
snapshot—not mutable source reports—is the completion authority. A seen completion event with a
damaged snapshot remains queryable but projects `program_completed=false` and an integrity blocker.
