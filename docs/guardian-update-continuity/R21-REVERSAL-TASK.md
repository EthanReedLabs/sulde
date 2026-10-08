# r21: exact committed first-migration reversal

Status: bounded L0 source/isolated-entry review passed at b8cdd08;
release candidate rebuild, final full gate and production acceptance pending.
See R21-REVERSAL-REPORT.md. This is not merge/install acceptance.
Task: task/guardian-update-continuity. Baseline cab332a.
Native scope revision 21; receipt 0950be2ee97b4a94c592d7e68198aca595685c8eca8a3b350456137b125b9871.
120 active minutes, no paid models, no production writes or host termination.

## Proven prerequisite gap

The original install transaction can recover an interrupted installation. Once
committed, recover-only verifies the new generation rather than restoring the
previous one. The stable transport gate correctly rejects ordinary downgrade
to a legacy Hook candidate. Retained old files are therefore not a supported
post-commit recovery command. LAYERED-ACCEPTANCE-TASK section 6 overstates this
capability; correct it additively after the running frozen suite completes.

## Frozen outcome and exclusions

Provide one supported, exact inverse of the currently active first migration.
This is not a general force switch, arbitrary historical rollback, garbage
collector, journal editor, or shared two-host transaction. Keep ordinary install
and recover-only behavior unchanged for existing install transactions.

Select the target from current deployment.maintenance_origin_transaction,
not a caller-selected unrelated historical transaction. Verify its committed
journal, descriptor digest, old target snapshot, original maintenance claim,
current complete new postconditions and original old marketplace bytes.
An intervening stable update makes the first-migration inverse ineligible.

The current/new generation is the rollback source; the original transaction's
old generation is the rollback destination. Name these distinctly everywhere.

## Authority and ownership

Use the existing independent native maintenance host and held-source worker.
Initial reversal needs its own exact native decision, not the install receipt.
Bind the complete executable catalog, interpreter/CLI, roots, target original
transaction+descriptor+snapshot, new operation identity, bounded deadline,
observed process cohort and explicit managed lease scopes. Unknown coverage,
live incompatible leases, late/unknown caller or drift refuses before writes.
The worker does not stop processes. No approval keystrokes or synthetic grants.

Only an actually started inverse has durable mechanical recovery authority;
a proposal, draft or retained old install journal is not such authority.
Crash recovery resumes the same destination, not a new arbitrary operation or
another decision about whether to reverse. Expiry before start prevents start;
expiry after a durable start must not permanently strand an authorized restore.
Recovery must remain usable without the newly installed Guardian.

## Journal/active/fence design constraints

Preserve the original committed journal and snapshot byte-for-byte.
Create a separately typed reverse transaction and monotonic hash-chained journal.
Its target snapshot is the original old snapshot, explicitly distinct from any
current-state diagnostic snapshot. Never mislabel a freshly captured new-state
snapshot as the old destination. Older readers must fail closed on the new type.

Use one deployment lock and a single unambiguous typed active owner. Do not add
an independent reverse-active pointer that can race the ordinary active pointer.
The reader must dispatch the typed inverse before interpreting install-v1 data.
Ordinary install refuses a pending inverse before staging/production writes.
recover-only dispatches only an explicitly typed, already started inverse.

Persist and independently reload the full inverse authority before first live
mutation. Publish a new-to-old fence under the existing fence/admission lock,
recheck explicit lease scopes there, and bind fence to inverse descriptor digest.
Failure retains active/fence. Success verifies the old end state, CAS-clears the
matching fence, then clears active. Cover detached terminal fence cleanup.
Do not mutate a committed forward journal to manufacture rollback authority.

## Restore and verify

Use the existing proven registry/snapshot/scheduler consumers, under the new
typed operation rather than invoking private restore functions against production.
Verify and remove only retirement aliases proven by the original descriptor;
the original snapshot consumer rejects symlinks and cannot run before this step.
Restore old registry/cache, controlled launchers/deployment and scheduler state;
verify old registry, exact restored snapshot, loaded labels and absence of active
stable Hook routing. Do not alter intent/effect/approval/business history.
Keep immutable new artifacts and original claims/journals as non-active audit
residue. Never claim every filesystem byte has returned to an earlier time.
Repeat completed inverse returns its verified result, not another execution.
A later first migration requires a new candidate, operation and native decision.

## Verification and publication

Start with one valid real installer fixture: legacy install -> first migration
commit -> exact reverse entry -> independent old-state verification. Fake host
and scheduler boundaries must be labeled; no claim of production approval.
Then inject wrong identity, stale source/artifact, unrelated or updated lineage,
missing/damaged blobs, repeat, concurrent owner, incompatible/unknown leases,
unknown/live caller, and crashes around journal/fence/restore/terminal cleanup.
Each injection needs its normal pair. Test actual entry then affected modules.
An unavailable new command is a missing capability, not a claimed old defect
with a fabricated green/red baseline. Do not relax fixtures to obtain green.

The already-running cab332a full suite keeps its original evidence and input
identity. A source-changing inverse repair needs its own frozen release evidence.
Consolidated review stays in the existing independent review thread.

Production sequence: Codex install -> exact trust/live positive+negative proof;
on failure, exact approved inverse. Only after Codex is verified, update Claude.
Before Claude mutation freeze its exact official CLI previous-version restore
sequence and shared-owner invariants. Do not imply a common two-host transaction.
Production actions, versions and host stops still require exact later authority.
