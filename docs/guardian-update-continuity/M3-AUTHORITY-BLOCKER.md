# M3: first-maintenance authority prerequisite

Date: 2026-10-06. Status: blocked-before-product-implementation.
Reviewed task HEAD: `2b03715`; branch `task/guardian-update-continuity`.
Revision 14 authorizes bounded source development and isolated verification, not
production installation or stopping user hosts. Native proposal
`873f480f28648cc8bb1ad096a078d0129af71561afcc654dc054d6c3901fd291`, receipt
`11e9406c617b334fff1798e7d153f773b90014a3f787b8ff776eeaa5e59799dc`.

## Outcome

The user has approved the one-time maintenance direction. That approval is not
missing. The prerequisite is a usable first execution-authority path: the installed
legacy control does not expose the proposed maintenance action. Merely implementing
that action in a candidate would not make it callable before its first installation.
Do not label an isolated new-adapter test as completed legacy migration.

No product source was changed, migration gate relaxed, host stopped, production
configuration changed, or installation attempted in this continuation. M1/M2
evidence remains valid for its original scope. No tests were rerun for this
read-only architecture check and documentation update.

## Source facts, independently checked

The coordinator read the task sources and confirmed the decisive restrictions in
the installed runtime `0.2.5+codex.20261005134315-d918c7a2ed`. A separate read-only
architecture reviewer reached the same bounded conclusion.

| Path | Observed restriction | Consequence |
| --- | --- | --- |
| `scripts/kb/production_recovery_targets.py:21` | Production adapters support only `repair_launcher` and `repair_generated_bytecode`. | Neither repair receipt authorizes installation or host control. |
| `scripts/kb/production_recovery_control.py:46` | Recovery command must address the loaded runtime's exact script; execution also checks native prompt/identity. | A new script in a candidate does not become an installed recovery action. |
| `scripts/kb/intent_guardian_parts/resource_preflight.py:592` | Candidate promotion has an exact argv shape. Its existing binding/digest is the install profile; returned candidate metadata is not a typed maintenance capability. | Adding fields to a receipt is insufficient to authorize a cohort/deadline/worker operation. |
| `scripts/kb/intent_guardian_parts/events.py:982` | Continuation matches the declared profile/effect/target/binding and acceptance digest. | Do not reuse a repair or ordinary install grant as an undeclared maintenance grant. |
| `scripts/kb/decision_kernel.py:170` | Ordinary HumanGrant eligibility excludes control-plane and destructive operations. | A generic Allow is not a maintenance bootstrap escape route. |
| `scripts/kb/recovery_lane.py:923` | Existing adapter dispatch is synchronous, with bounded reprobe. | Stopping the approving host does not itself create a durable authorized worker. |
| `scripts/release/install_codex_plugin.py:1894` | Stable candidate accepts fresh-origin or verified stable lineage, not legacy migration. | The existing default must remain closed until a typed transition is actually validated. |

These observations establish a missing supported path in the examined product,
not an impossibility theorem about every Codex host capability. No production
denial was deliberately triggered to manufacture another failed attempt.

## Rejected shortcuts

- Put a maintenance plan in an otherwise valid candidate receipt and silently add
  worker/process-control effects to old installation authority.
- Call a new recovery script as if it were the loaded, approved recovery adapter.
- Introduce `--force`, fabricate a fresh-install lineage, or treat a process scan
  as a global admission barrier.
- First install a legacy-compatible bridge without accounting for the same
  prune/trust window. A legacy candidate may pass the legacy branch of the gate;
  that does **not** prove its first update is safe for existing hosts.
- Stop the coordinator and assume its permission survives as an unrestricted
  detached worker, or change installed Hook policy to permit the current attempt.

## Next decision: first bootstrap, not another host experiment

Before further product implementation, agree on a separately scoped first-bootstrap
mechanism that the current host can actually authorize and execute. Its boundary
must name the exact executable/content, plan, candidate, old installation CAS,
affected cohort, deadline, one-use identity and recovery target. Prefer a bounded
worker that only waits for approved hosts to exit; signalling is not implied.

An independently supervised maintenance host is a possible design direction, not
a verified existing entry. If it requires a temporary host configuration or an
independent execution boundary, disclose and approve that change explicitly. Do
not claim that a native approval card alone overrides the existing Hook. The
Agent should perform the work; no copied approval phrase or user terminal script
is the intended interface. If no such boundary is accepted, keep the old install.

After that prerequisite is settled, implement one continuous scoped task:

1. One typed maintenance target on the existing recovery/installation machinery;
   no general permissions plane or arbitrary shell executor.
2. Candidate, old CAS, deadline and approved cohort rechecked under installation
   locking before the first production write; distinct legacy-maintenance lineage.
3. Existing transaction rollback/recovery. Missing trust or real dual-identity
   Hook proof remains `awaiting_verification`, not operational ready.
4. Valid normal control, boundary injection, actual entry, affected regression,
   then one independent review. Reuse M1/M2 only for unchanged host facts.

This document does not grant that additional bootstrap scope or authorize a
production run. The revision-14 stop line applies: do not expand into an unapproved
production configuration or generic authority redesign.

## Execution friction and sediment candidate

- Planning omission: M2 described the new maintenance action but did not close how
  a legacy installation would first load and authorize it. Verify this prerequisite
  before spending on its adapter, worker and integration matrix.
- Source inspection had one search with nonexistent filenames (exit 2); corrected
  with `rg --files`. This was an investigation error, not a product defect.
- The host announced saving an exact native approval prefix even though the call
  did not request `prefix_rule`. It was not reused as authority; cause remains
  inconclusive and outside this implementation scope.
- No measured Token saving, performance change or new model capability is claimed.

Candidate knowledge status: verified for the inspected bootstrap dependency, not
for a production remedy. Route positive: check old consumers before designing new
authority. Route negative: assume a candidate's new approval adapter is already
available. Execution positive: preserve the gate and exact scope pending an
executable bootstrap. Execution negative: copy a receipt or hide expanded effects
inside an ordinary installation. Formal KB was not modified.
