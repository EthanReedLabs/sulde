# Guardian receipt consistency — integration scope

Date: 2026-09-10
Status: FROZEN R11 / IMPACT-BOUNDED FINAL ACCEPTANCE PENDING
capability_tier: deep

The user confirmed the previous writer has stopped and authorized takeover,
commit and merge. Native revision 10 receipt:
`00ffeecba99cd786287737fa12dd2181e672a21fa965f774b23c881c85263984`.
This phase does not install, push, delete workspaces or alter production memory.
Prior revision 9 maintenance bindings are not authority for this combined tree.

## Work

1. Preserve the eight-file original snapshot inventory. Run the original receipt
   concurrency, validation reuse, native journal and architecture tests in the
   repository's production-isolated environment, then commit this source task.
2. Merge the current dev into this task branch, resolve overlapping behavior:
   retain dev's CompositionServices and host-call identity; add receipt-tail
   atomic locking and per-call successful-prefix verification reuse without
   removing explicit source-task selection or its recovery/routing fences.
3. Extend the receipt/selected-task tests where integration adds a contract-lock
   boundary. Test interrupted recovery, supersession, drift, two sessions and
   no authority transfer. Do not add an alternate task-state service or weaken
   canonical receipt checks to pass a test.
4. Run targeted checks during integration. Since this changes shared recovery
   and receipt verification, run the full suite once the combined semantic tree
   is stable. Run the existing actual CLI/Hook/MCP isolated canaries with both
   module/artifact identity, not synthetic proof presented as live evidence.
5. Preserve command, source digest before/after, interpreter, elapsed time, result
   and log SHA. Failed runs remain failed. Only report/evidence edits are excluded
   from semantic identity. Record limits and source/delta identity in REPORT.md.
6. Only after all required checks pass, commit the integration and merge to dev.
   Preserve main and existing user changes, both source workspaces and prior
   local evidence refs. Do not automatically push or resume installation.

## R11 final verification amendment

Native revision 11 approved with receipt
`721658f984668f319ac0a341f195b3b980bca0633af94feda03fde3ed851cbda`.
The full suite completed: 2,119 cases, 2,093 passed, 25 skipped and one failed
static encoding gate. Runtime, performance and actual CLI/Hook/MCP cases passed.
The only code delta afterwards is five explicit UTF-8/replace arguments across
three test files; report/plan/evidence changes are not executable product code.

Final acceptance combines that preserved full result with a passing all-repo
encoding gate, the changed test modules and their importer/fixture dependencies,
plus a fresh candidate PreTool test proving the identical artifact and loaded
module identities. Exact source/diff/log identities must be retained. Do not
claim the failed original full run was green or that all cases ran on the final
test-script bytes. Any runtime/source-authority change would invalidate this
bounded reuse and require reassessment before merge. No installation, push,
deletion or permission expansion is added.

## Acceptance boundaries

- Contract writers cannot interleave between effect/contract/head receipts.
- Noncooperating writers, changed scope/session/permissions or missing sources
  still fail; lock possession does not make an invalid snapshot trustworthy.
- Prefix reuse is call-local, success-only, bounded and invalidated by source
  identity/bytes changes. No persisted/global/TTL authorization cache.
- Selected task continuation keeps its ordered dual-contract/route locking,
  staging, commit linearization, authority-free review and crash recovery.
- Composition parser remains acyclic, callback-only and policy-equivalent to the
  already accepted dev. Ordinary single calls do not build parser bundles.
- Windows native tests remain a platform limitation, not a local success claim.

## Knowledge applied

`knowledge/work-model/canonical-byte-authority-self-hosted-verification.md`:
exact byte identity and fresh candidate-bound verifier processes are separate
requirements. The source report and actual receipts must not disagree on either.

## Handoff

Original snapshot: ORIGINAL.json. Evidence: .sulde/data/guardian-receipt-consistency/.
Independent knowledge candidates remain in the report; no production KB writes.
