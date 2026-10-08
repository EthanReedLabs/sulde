# One-time independent maintenance host

Date: 2026-10-06. Scope: r15 design and isolated backend-protocol verification.
This is a proposed production integration, not a shipped maintenance command.

## Decision

Use a separately owned, short-lived Codex maintenance host for the first legacy
migration, rather than teaching the old runtime a new action before it can be
installed. Its home/config/workspace is separate; it does not load the production
Sulde plugin or copy its contracts, approvals, rules, auth or pending effects.
That isolation must be explicitly approved as a maintenance boundary, never
silently used to retry ordinary actions denied in a business session.

This host is a one-operation installer executor, not another autonomous Agent or
general recovery controller. Prefer the official interactive CLI's human decision
surface over building a custom approval client. An Agent may prepare/start the
exact maintenance host; the person must make its real one-shot native decision.
No copied phrase, digest or terminal command is an approval interface. A fixture
client responding `accept` is useful only in tests and is forbidden as production
human authority. The interactive CLI/UI handoff is not yet tested in this revision.

The app-server protocol supports a server request scoped to thread/turn/item and
client decision, independently of Sulde Hooks. Local tests now exercise that
backend with no plugin. This removes the need to *assume* that a new Sulde recovery
action is already installed; it does not establish the human UI or full migration.
Source: [official approvals protocol](https://learn.chatgpt.com/docs/app-server#approvals).

## Minimal integration boundary

1. The current coordinator freezes a maintenance bundle and saves task references.
   The readable card states that this **one** maintenance host lacks Sulde Hooks,
   while normal hosts/config remain unchanged. This is not a global disable flag.
2. A private temporary home/workspace starts the pinned official CLI with the
   intended approval/sandbox policy and no inherited execution authority. A bounded
   local deterministic input emits only the frozen worker command; no paid model,
   dynamic repair reasoning or arbitrary command selection is needed. The provider
   or launcher may request approval but must not respond for the person.
3. The real maintenance host asks the person to approve that exact operation once.
   Do not relay an approval from the coordinator or another thread, use permanent
   prefixes, or claim its source-task receipt approves the worker. If the host's
   genuine interactive approval surface cannot be made available, do not execute.
4. The worker validates its immutable input/executable identities, old installation
   CAS, approved cohort identities and deadline, then waits for that cohort to
   exit. Waiting is bounded. The initial worker has no process-signalling power.
   Saving/stopping user work is a separate exact approved action; no `killall`.
5. Immediately before production writes, under the existing deployment lock,
   revalidate the inputs/CAS/cohort/deadline and atomically claim the one-use
   operation in existing durable machinery. Observe new/unknown callers as a
   violation of the agreed maintenance window, not as global drain proof.
6. Invoke the existing installation transaction using an internal typed
   legacy-maintenance context. Preserve old bytes and recovery identity; never
   fabricate fresh lineage or expose a generic `--force` flag.
7. Record `verification_pending` until real host trust and Hook positive/negative
   proof bind both loaded_module_generation and artifact_generation. Physical
   commit is not operational ready. Failure retains a same-transaction recovery
   entry and original unknown effects, never blanket debt cleanup.
8. Once independently verified or safely aborted, close only the maintenance host
   and remove its disposable derived state; preserve authoritative records.

## What native approval does and does not bind

The observed native request carries a rendered shell command and cwd plus request,
thread, turn and item identities. It does not by itself freeze the bytes at paths
inside that command. The production worker therefore needs exact frozen bytes,
content digests, canonical paths/no aliases, ownership, expiry and atomic use.
Do not hash a script and then reopen a mutable path to execute it: use a verified
immutable bundle/held content and validate dependencies through the existing
generation machinery. The small test worker is not this production implementation.

Persist the exact **observed execution** and independent effect verification; do
not mint a transferable `human_approved=true` file. Tests proved only simulated
client decisions against a real host backend. Human identity, live UI, stable
installation transaction, crash recovery, cohort handling and Windows remain
separate obligations.

## Implementation task to follow, without another feasibility round

One bounded source task should implement the exact launcher/input bundle/worker
and internal maintenance context together, reusing installer locking/journal and
recovery. Begin with a real interactive **isolated** native decision and benign
effect; a new permission surface or host configuration expansion requires explicit
scope, not an improvised automated client response. Then cover normal migration,
late/unknown caller, stale bytes/CAS, duplicate use, expiry, crash before/after first
write, missing trust and rollback through the actual transaction. Run affected
regressions and one consolidated review; full regression only for actual shared
release impact. Production installation and user-process actions remain a later
exact approved operation. Do not rerun the unchanged M1/M2 feasibility matrices
unless their fixture or dependency inputs change.

Benefit is presently qualitative: one supported first-maintenance execution path
would remove dependence on installing its own approval adapter first. No measured
time/Token gain, zero-interruption promise, or all-host admission proof is claimed.
