# r17: full entry requires process isolation, not just private directories

Superseding execution order: r19 LAYERED-ACCEPTANCE-TASK.md separates isolated
acceptance from real-host migration. This r17 finding remains historical evidence;
it no longer requires extending an OS-user/VM environment before L0/L1/L2 work.
No migration or production gate is declared passed by this change.

Date: 2026-10-07. Status: blocked-before-full-entry; not accepted.
Source baseline: `4698b1e45f1cd8aafa4f92a8f30d5f638267f99e`.

## Frozen outcome and authority

The current-session r17 proposal was applied through the native human decision
surface. Its outcome is complete isolated prepare-draft → interactive host →
human one-shot decision → frozen worker → installer → independent readback,
followed by release-level validation and conditional dev integration. Budget:
150 active minutes, excluding human wait. Minimal fixture/product repairs within
the original task branch are allowed; production installation, user-host stops,
main, push, release-version changes and production-ledger changes are not.

Normal controls precede boundary injection and affected regression. Existing
component evidence is reusable only for its original scope. A complete-chain
claim cannot be assembled from the earlier benign approval and synthetic-host
installer tests. Full regression and one consolidated review precede any dev
merge. New authority/environment decisions are genuine stop conditions.

## Read-only preflight result

`legacy_maintenance.process_inventory()` was called without replacing its
implementation. The first sandboxed call could not execute `/bin/ps`
(`PermissionError: Operation not permitted`). An approved outside-sandbox retry
succeeded. The first error is an outer sandbox limitation, not a product defect.

At observation time, the actual producer selected seven same-UID process
identities by executable basename containing `codex`. Two selected processes
were ancestors of the current coordinator's tool process:

- PID 4110, start `Sat Oct 3 19:55:52 2026`.
- PID 82057, start `Tue Oct 6 03:45:45 2026`.

The observation read process names/start times/parent IDs, not arguments,
environment contents, credentials or session text. It did not stop any process.
These PIDs are historical observations, never permission to stop a future PID.

Code facts at the frozen baseline:

1. `process_inventory()` selects the operating-system UID via `os.getuid()`;
   private HOME/CODEX_HOME does not change this UID.
2. `prepare_draft()` includes every matching same-UID Codex process in `cohort`;
   it does not filter by candidate or installation root.
3. `check_processes()` requires the exact maintenance host and worker ancestry,
   rejects newly observed unknown Codex callers, and raises `CohortAlive` while
   any original cohort identity remains alive.
4. `wait_for_cohort()` waits until that condition clears or the deadline expires.

Consequently, a new private directory under this same login cannot complete the
full chain while preserving these existing user processes. This is a consequence
of the actual preconditions, not an observed installer failure: no complete
maintenance worker or draft was launched during this preflight. There was no
candidate preparation, candidate verification, full-suite rerun or installation.

## Classification and corrected planning assumption

This is an existing conservative process-scope constraint conflicting with the
proposed same-user isolated acceptance environment. It is not an r17 regression:
`git diff f8a66f2 HEAD -- scripts/release/legacy_maintenance.py
scripts/release/independent_maintenance_host.py` was empty before this report.
Whether the product should eventually use narrower proven caller ownership is a
separate design question; this evidence does not establish that such filtering
would be safe.

The coordinator's plan assumed disposable directories were sufficient isolation.
That assumption was incomplete. Do not solve the fixture by clearing the cohort,
mocking process inventory, excluding the coordinator without ownership proof, or
silently killing user hosts. No product safety predicate was modified.

## Required decision, then continuous execution

Preferred: authorize a genuinely separate OS-user/VM test environment, preserving
the current user sessions. Its process inventory must be real; it must run the
official interactive host and the unchanged complete maintenance entry, with
disposable legacy installation/candidate roots and a real human one-shot choice.
Provisioning availability, owner, platform and bounded setup cost must be checked
before promising this route. A Linux container is not macOS host acceptance.

Alternative: separately authorize an exact maintenance window that saves work
and closes identified affected hosts. This changes the r17 no-user-host-stop
boundary, may end the coordinator itself, and needs an independently owned
executor plus a durable handoff. A generic “all closed” assertion is not proof.

Do not begin either expanded operation under r17. After an authorized environment
exists, continue the frozen full-entry → recovery checks → frozen full suite →
consolidated review → conditional dev merge outcome without per-test handoffs.
Production installation still requires a later exact decision and live checks.

## Outcome this turn

Only this report and the status pointer changed. No product code/tests, dev/main,
production runtime, release version, user processes or historical ledgers changed.
No new all-green or installation claim. Existing r16 evidence remains scoped and
unchanged. The remaining full-entry and release gates are pending.
