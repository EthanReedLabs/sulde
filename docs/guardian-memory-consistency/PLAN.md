# Guardian memory registration consistency — frozen scope

Status: FROZEN (implementation not yet accepted)
Date: 2026-09-09
Base: dev@3d4df5412193633b3f26ad1cfa90844068e9489c
Branch: task/guardian-memory-consistency
capability_tier: deep

## Authority and boundaries

Current-session native workspace handoff and revision 7 proposal were applied.
The approved outcome is development, scoped regression, integrated tests,
performance comparison, and isolated candidate/real-host evidence. This task
does not merge, push, install into production, or mutate production memory.
Normal task/Skill/approval audit records remain enabled.

Preserve main/dev, existing user changes, production generation and scheduler,
append-only authority/effect history, Git/Figma policy, and human control over
permission expansion, destructive and control-plane operations. No second task
state service, installer/scheduler refactor, or global graph-ID migration.
Do not replay unknown effects, clear debt to unblock work, weaken verification,
or present synthetic Hook calls as live host evidence.

## Frozen issues and deliverables

1. Remove historical three-use exhaustion as a memory authorization condition;
   distinguish authority, validation, backpressure, and verification failures.
2. Align MCP/CLI/Guardian normalization and provider attribution. Never silently
   attribute a Codex operation to Claude or override a conflicting attribution.
3. Define transactional created/already_present/conflict behavior and consistent
   independent postconditions; preserve original provenance and idempotency.
4. Persist versioned, digest-bound memory verification recipes and recover via
   independent reads after lost Post, transient DB errors, and interruption.
5. Apply the same resource/dependency conflict boundary to execution, proposal,
   and continuation. Unknown/corrupt identities do not become disjoint by default.
6. Preserve the total audit sequence while making approval freshness depend on
   relevant state; a proposal that depends on memory still detects memory changes.
7. Pair completion uniquely by host/session/task/call identity and content shape;
   duplicate/ambiguous/late observations must not settle another execution.
8. Preserve all unsettled state beyond 100 rows; bounded derived history must not
   erase active debt or authorize a replay.
9. Only fall back from direct MCP to CLI for a proven backend-availability case;
   validation/conflict/unknown-commit errors must not blindly execute again.
10. Share graph truth/source validation across explicit and automatic recall.
11. Add source/project and unknown/shared recall guardrails and regressions only;
    global entity namespace/multi-source identity migration is explicitly deferred.

Task facts remain in existing authorized task artifacts. Optional graph
enhancement cannot prevent independent business work; explicitly requested
memory maintenance still requires an honest completion result.

## Implementation sequence

- Capture scoped test/performance baseline and add regressions for confirmed
  writer/verifier and parameter-contract mismatches.
- Implement shared memory normalization and transaction/postcondition behavior.
- Integrate Guardian authority, recovery, pairing, retention, and scoped freshness.
- Align recall consumers and repository instruction templates.
- Run scoped tests during development, then the final integrated suite once the
  semantic code tree is stable. Changes after that invalidate affected evidence.
- Run isolated real-host CLI/Hook/unified-exec/MCP positive/negative and recovery
  canaries with loaded_module_generation and artifact_generation bound in actual
  events. Explicitly distinguish unit/adapter/integration/live evidence.
- Record implementation results, limitations, exact evidence identities,
  performance, and sediment candidates in REPORT.md. Do not mark accepted while
  any required evidence remains missing.

## Acceptance matrix

- Authorized fourth/tenth memory calls work; permission/scope negatives do not.
- Identical retry, changed entity type/confidence/provider, and batch conflicts
  have deterministic truthful results with no unexplained partial writes.
- Missing Post, busy DB, restart and repeated reconciliation are recoverable;
  an unproven outcome remains unknown and is not replayed.
- Two sessions, equal inputs/different call IDs, duplicate and out-of-order Hook
  delivery, task-epoch changes, and >100 outstanding records remain isolated.
- Unrelated typed local work/proposals proceed; related/unknown/destructive/
  external/control-plane debts keep their existing safety boundary.
- Unverified/planned/stale/keyless graph relations are not injected as facts or
  implicit cross-project shared knowledge.
- Read-only hot paths gain no DB writes or full journal replay; freeze a same-
  machine baseline and report p50/p95 with measurement noise, not invented gains.
- Preserve test source/tree identity, command, interpreter/dependencies, result,
  duration, and evidence tier; artifact/host process identity is mandatory for
  real-host claims. Old live processes do not prove newly loaded code.

## Acceptance completion, 2026-09-10

User requested the next step after the open-acceptance report. Complete the
remaining checks without merging, pushing or installing into production:

- Replace the existing resources/composition delayed back-import with explicit
  parser dependencies; keep the architecture gate and all policy decisions.
- Bind native continuity expectations to exact calls: opaque receiver calls and
  destructive compositions remain Pre-denied; exact regular-file cleanup is
  Agent-owned. Do not count an earlier Codex command-rule denial as Hook evidence.
- Exercise native approval and task continuation across optional memory changes
  using a disposable actual CLI/Hook candidate. Fixture human decisions are test
  inputs, not production authority or proof of an actual person clicking Allow.
- Retain both passing and failed evidence, then rerun affected and integrated
  acceptance after the source tree stabilizes.

## Evidence retention

Keep test artifacts under .sulde/data/guardian-memory-consistency/ (or explicitly
scoped temporary roots). Never delete authoritative execution/approval/effect
logs, pending problems, or unresolved evidence. Report-only/cachebuster changes
may reuse demonstrably matching semantic test evidence with affected checks;
they are not a reason to rerun the entire suite by default.

## R2 explicit source selection, frozen 2026-09-10

Revision 7 was approved through the current native permission card; receipt
`d77ba839327d726e751fa3e34c47b6b5c3683092bce7f2911fcc62a778a03af6`.
The failing real-host discovery test exposed incompatible interfaces, not a
reason to remove default per-session isolation. Scope adds only:

- Agent selects an exact source contract in the same physical workspace. Prepare
  creates a read-only review reference in the current contract, not a source lane
  or authority. Native commands remain bound to the current contract/session.
- Native continuation binds both contract worlds, the route predecessor, and
  memory-aware relevant material state. Deny changes no ownership.
- Reuse the native decision journal; use ordered contract locks and route CAS.
  Stage a non-executing target lane before publishing the route. The effective
  route remains the old contract until an atomic source-contract commit makes
  the target lane bound. Recovery never repeats an external action.
- Preserve old same-contract continuation. No grants, events, pending effects,
  debt or approval receipts are copied into the selected task.
- Cover interruption boundaries, replay, concurrent selection, corruption,
  source/destination/route drift, dependent memory and same-workspace rejection.
  Verify actual CLI/Hook/MCP continuation before the final stable-tree full run.

The implementation may update docs/intent-guardian.md in addition to the original
paths. Installation/scheduler/release-script changes remain out of scope.

## Knowledge applied

- knowledge/tech-docs/异步分析不阻塞事实汇总.md: separate independently useful task facts
  from optional enrichment, but not when enrichment is the requested deliverable.
- knowledge/work-model/canonical-byte-authority-self-hosted-verification.md:
  version canonical proof inputs and verify new code in candidate-bound processes.
- knowledge/anti-patterns/0247-human-allow-not-consumed-as-authority.md: consume
  the exact durable human decision once; do not replace native pairing with a
  remembered chat acknowledgement or a reusable approval prefix.
