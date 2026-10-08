# M2 decision: one-time maintenance, not a universal hot-migration promise

Date: 2026-10-06. capability_tier: deep. Provider: current Codex.
Source checkpoint: 20f61046ec04712fe8e16b0134ab5d963059fdda.
Dev observed: 3012363a50be1d73e8f7f6f415e650d4ae9f3b9c.
Intent: completion:6514aef628e75bf2049c2c4e revision 13, design and isolated rehearsal.
Native receipt: bc8b4f0f99d19a7ffc7f49d656f6868bf3c6a2ea034f860832f2b3fd60831fad.
Status: maintenance direction chosen; product implementation remains pending.
This document does not authorize implementation, production changes, or process termination.

## Decision and why

M1 has finished. Do not repeat its update/reload matrix. A zero-interruption hot
first migration is not justified: it requires control over callers that this
installer does not currently own. Prefer an explicitly approved, one-time maintenance
window, with a precise operational boundary and honest residual risk. Keep normal
stable-to-stable updates separate from this legacy bootstrap operation.

This is a change in the proposed acceptance model, not a newly proven host ability:
an operator-maintained window is an operational assumption, not a machine-proven
global admission barrier. If the user still requires arbitrary new native hosts to
be mechanically prevented from starting, retain the current install and gate until
such a supported capability exists. Do not silently weaken that requirement.

## Additional source/capability facts

1. `scripts/kb/agent-runtime.py:5905` chooses the shared admission fence only for
   provider codex, non-test mode and installed authority. That call publishes a
   managed-run lease. Independently launched native CLI/Desktop processes do not
   become participants just because the installer writes a fence.
2. `scripts/kb/generation_fence.py` permits the switch target and does not stop
   already-running leases; damaged input currently reads as no fence. That known
   separate issue remains on the inventory, not silently included in this task.
   Even repairing it would not make non-participating native hosts acquire the lock.
3. `scripts/release/install_codex_plugin.py:1894` accepts fresh-origin stable
   lineage, not a legacy transition. It is checked before writes and again before
   prune. A maintenance operation needs a distinct validated transition, not an
   override flag, empty-directory relabelling or fabricated fresh-origin receipt.
4. The installed 0.160.0 CLI help exposes app-server stdio/unix/ws transports,
   daemon/proxy tools and plugin add. The inspected plugin-add surface has no
   no-prune option. These surfaces are not a registry of every existing process or
   an all-caller drain acknowledgement. No daemon was started/stopped/contacted.
5. The existing version-generated ClientRequest schema exposes runtime-config
   reload; M1 proved it for owned connections only. The official documentation
   describes selecting a transport when starting a server, not retroactively
   attaching to arbitrary existing stdio owners. This is a capability gap in the
   evidence, not a claim that no host-internal alternative can ever exist.
6. Hook installation and trust are separate. Fixture auto-trust is not a supported
   production human-review substitute. New exact definitions need the host's real
   trust procedure and live acceptance before reopening ordinary work.

Sources: local files above and
[App Server](https://learn.chatgpt.com/docs/app-server),
[plugin Hook trust](https://developers.openai.com/plugins/build/plugins#bundled-mcp-servers-and-lifecycle-hooks).
KB ap-0181 was read in full: preserve old static bytes and distinguish Hook/Skill
lifetimes. Its historical restore-after-prune recipe does not prove that the prune
window is safe; use the more specific M1 evidence for this candidate.

Read-only command slips: one unexpanded shell glob and one incorrect recovery module
path returned nonzero; retried with exact discovered paths. These are investigation
errors, not Sulde product defects. No new experiment or full suite was necessary.

## Options presented to the user

- Recommended: accept designing and isolating a one-time maintenance migration.
  Later production execution separately binds the exact affected hosts and the
  interruption/recovery plan; it must not terminate unrelated work.
- Otherwise: keep the current production installation. Do not repeatedly test the
  same missing capability or implement a second generic process/permissions plane.

The user explicitly selected the recommended direction in the current conversation.
The r13 native Allow authorizes tests/docs and owned isolated fixture processes only;
it does not authorize product changes, production termination or installation.

The immediate bounded deliverable is a real-host rehearsal, not the implementation
task below: same-thread restart across a controlled maintenance window, surviving
owned host refusal, missing-trust negative control and cold rollback using official
plugin CLI. Its cohort guard is test-driver logic, not an installed safety mechanism.
No Sulde legacy gate override or transaction migration is exercised. Budget for this
rehearsal: 30 active minutes, zero paid models, one consolidated independent review.

## Frozen scope for a subsequent implementation task, if selected

Outcome: extend the **existing** transactional installation path with a distinct,
one-shot maintenance transition and isolated proof, not automatic global takeover.
Continue this task branch/worktree after rechecking actual dev delta. Preserve all
M1 evidence and the normal legacy-rejection default.

Expected impact: installer preflight/state transition, candidate verifier consumers,
and focused tests. First inspect the existing typed recovery target and approval
profiles; register only the exact new action if necessary. Do not assume an existing
recovery grant authorizes arbitrary process signals or a detached worker.

Suggested modules (confirm exact functions at amendment time):

- `scripts/release/install_codex_plugin.py`: explicit legacy-maintenance validation
  and existing transaction prepare/commit/rollback postconditions.
- `scripts/release/install_transaction_journal.py`: extend only if current immutable
  descriptor cannot carry the required typed transition; no second journal authority.
- `scripts/release/candidate_codex_plugin.py`: expose candidate proof scope, never
  promote a fixture-owned cohort into production caller coverage.
- Existing recovery/control consumers only if this exact transition requires them;
  a separate amendment is needed before expanding into generic recovery redesign.
- Relevant `tests/` and these task docs. No edits to installed caches or host config
  during development; production deploy, push and dev/main merge remain excluded.

## Transition obligations

| State | What must be true | Failure behavior |
| --- | --- | --- |
| prepared | Exact candidate/old identity; validated rollback bytes; scoped native approval; owned executor identity | Zero production change |
| maintenance-pending | Save/resume references; exact affected cohort and stopping method approved; no unreviewed work | Abort without signalling outside the cohort |
| quiescence-observed | Approved owners stopped/drained with identity-safe checks; rescan immediately before mutation | Unknown/new owner means stop/reassess, not a successful global drain |
| publishing | Durable existing transaction owns changes; old static bytes retained; stable entry verified before registry changes | Existing verified rollback, or recovery-required |
| verification-pending | Host trust complete; controlled reopened host actually calls new entry and denies negative canary before action | No ordinary-work ready claim |
| maintenance-complete | Exact tested installation and approved operational cohort verified; rollback usable | Record bounded completion, not all-host proof |

The operational agreement asks the user not to start other participating hosts in
the window. A process scan can detect some breaches, not prevent all races. Persist
that assumption and coverage honestly; do not write `global_drain_verified=true`.
If this residual risk is unacceptable, the transition is ineligible, even when an
approval exists. Existing unknown effect debts and unsaved business work are never
resolved by a migration receipt.

The currently executing coordinator cannot simply kill itself and continue issuing
commands. Any noninteractive maintenance worker must be approved beforehand with
exact executable/content, transaction, paths, candidate, cohort, deadline, one-use
identity and recovery target. It may finish only that frozen operation. No new Agent
reasoning, broad shell runner, persistent daemon or permission fallback after the
interactive host is stopped. If this exact worker/receipt cannot be implemented
within existing authority machinery, stop before any host is terminated.

Avoid PID-reuse mistakes: bind process identity/start identity and parent/endpoint
when available; do not authorize `killall`, name-wide pkill, or whole-user teardown.
Pause/wait is preferred; forced termination and unsaved-work loss require separate
explicit consent and are not the default. Do not export raw process environments,
credentials or conversation bodies to the maintenance receipt.

Recovery must remain callable without the failed Guardian runtime. Retain its
independent typed decision path and original unknown facts. A file rollback is not
enough: re-opened controlled hosts must observe the restored usable entry before
declaring recovery complete. No indefinite lock/wait; on deadline preserve the
transaction and exact recovery instructions/status for the Agent.

## Verification once implementation is authorized

1. Valid normal control: owned, isolated host cohort and sealed candidate; preserve
   legacy rejection without explicit typed maintenance authority. Reuse M1 only for
   unchanged host behavior, not as proof of new transaction code.
2. Deterministic boundary injection first: new/unknown owner; stale process identity;
   missing cohort approval; candidate/old tree drift; worker crash before and after
   first mutation; trust rejection; partial reload; callback absent despite exit 0;
   restoration failure. Baseline/candidate use identical assertions. Fixture errors
   are not old defects. A late host in the controlled fixture must invalidate its
   scope, not be forcibly killed or ignored.
3. Real entry under official OS isolation: legacy fixture -> approved maintenance
   cohort exit -> real install transaction -> new host exact trust -> true PreTool
   denial with loaded_module_generation and artifact_generation both bound -> no
   marker -> positive call -> verified recovery. A simulated model proves wiring,
   not model capability. Isolated trust helper is explicitly fixture-only.
4. Affected installer/recovery/Hook/candidate tests, then release-level regression
   if the actual shared-chain change requires it. No per-stage user confirmation.
5. One consolidated independent review. Installation readiness, production
   acceptance, Windows and arbitrary non-participant host coverage remain distinct.

Budget proposal: one continuous local development window, 90 active minutes, zero
paid models/remote actions; change approach after two attempts without new evidence.
Freeze a checkpoint on budget or genuine prerequisite failure. No invented wall-clock
completion promise. Evidence in unique Optimus S3-C-repair/M2 runs with input digests,
failed attempts retained, no overwrite. Selective testing for docs-only design now.

## Current closeout and stop line

No product source implementation, user process stop, scheduler change, production trust write,
installation or gate relaxation has occurred in this design continuation. The next
write beyond docs/tests requires a revised readable scope and native decision.
Production remains a later separate exact operation. Do not turn repeated user
“next” messages into unlimited approval or more indefinite feasibility rounds.
