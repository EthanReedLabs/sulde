# Task authoring and dispatch contract

This is a distribution specification, not a knowledge-base article or a record
of an operator's tasks. It is available when the formal corpus is empty.

## Capability and host selection

A new task records `capability_tier: light|balanced|deep`, not a provider model
name. `light` fits bounded mechanical work, `balanced` ordinary implementation,
and `deep` work needing cross-component or uncertain-state analysis. Select the
tier in the task; resolve a host-specific model only at the execution boundary.

Use the current host for work in this session. For a handoff, identify the
target session's provider explicitly. Having another CLI installed is not
permission to change providers. Use the `dispatch-task` Skill and the
host-neutral `model-dispatch` launcher for rendered instructions.

Ordinary Codex dispatch contains the task instruction and preserves session
settings. Do not require model-state inspection or print `/model` / `/reasoning`
selectors. Model advice is opt-in via `--model-advice`; `capability_tier` alone
does not request that advice. Codex 派单禁止混入其他宿主的控制命令或模型标签。

## Two task representations

- Human-readable briefs use the distributed [brief template](../template/_project/docs-hub/00_shared-rules/task-brief.md.template).
- Managed program tasks follow the [managed task contract](task-contract.md).
  Its exact parser is `scripts/kb/guardian_program.py`.

Neither a brief, a tier nor a completed test creates approval authority. Keep
the user's objective, permitted effects, exact scope, acceptance and recovery
method explicit. A changed scope or high-risk decision uses the current host's
human decision route. Do not instruct people to copy opaque authority tokens.

## Bounded continuous execution

Dispatch one bounded outcome, not a sequence of user-mediated test rounds. Before
implementation, freeze the objective, baseline and candidate identities, permitted
paths/effects, expected impact, acceptance cases, evidence destination, execution
budget and genuine stop conditions. Do not silently amend an existing task's
explicit stop line; the coordinator must first issue an authorized amendment.

Within that boundary, one executor owns diagnosis, fixture repair, the minimal
product fix and verification through the agreed review point. A test failure or
one passing stage is a progress update, not a reason to return the task and wait
for another “continue”. Keep the user informed without requiring routine replies.
On context rollover, persist the latest evidence and next action and resume from
that checkpoint; do not restart completed checks or call unfinished work complete.

For code repairs with fault-injection coverage, use this order:

1. Establish a valid normal control on both the old baseline and candidate.
2. Inject at external boundaries while exercising actual production callbacks.
   Use the same test, assertions, fixture and configuration against both source
   versions: the baseline must fail for the target defect and the candidate pass.
   Fixture/setup failures are not defect reproductions. Do not relax the product
   contract, invert assertions, or replace the function under test to obtain green.
3. Once injection passes, continue directly to actual entry-chain verification,
   then affected-module regression. A fake provider proves protocol wiring, not
   real Agent behavior or production permission enforcement.
4. Choose broader testing from actual impact: small changes use targeted checks;
   medium changes include affected consumers; refactors use full regression.
   Documentation-only changes need relevant structural checks, not fabricated
   fault injection. Follow stricter release requirements when applicable.

At logical boundaries compare expected and actual impact (larger, smaller or as
expected). Investigate omissions and unexpected changes without expanding owned
paths or effects. Reuse evidence only when tested inputs and dependencies are
equivalent; bind code, tests, fixtures and configuration, not just a report title.

After two attempts at the same failure without new evidence, stop that approach
and inspect reachability, fixture validity and the first failing precondition.
Change the diagnostic method within scope and budget; do not blindly rerun, create
another micro-task, increase timeouts or weaken acceptance. If no safe progress is
possible, or the budget is exhausted, hand off a precise blocker and checkpoint.

Pause for missing authority, scope/safety changes, unapproved cost, unavailable
external prerequisites, or the user's explicit stop. Continuous execution does
not authorize production installation, publication, destructive actions, approval
bypass or extra model calls. Preserve narrower audit-only/tests-only boundaries.

The coordinator performs a consolidated independent review of the frozen criteria
and returns related blockers together. Do not waive failures to keep review to one
round. Record unrelated findings separately; do not add them to acceptance unless
they invalidate this outcome or its safety, in which case request an explicit
scope amendment. Installation and real-host acceptance stay separate when excluded
from this task; their absence must not be mislabeled as failure of a scoped fix.

## Evidence and completion

Bind evidence to the candidate inputs actually tested. Report passing, failing,
skipped and environment-blocked checks separately. Choose test scope from the
changed behavior and its consumers; structural validation does not establish
live host enforcement. A task report cannot turn unknown effects into success.

For each repair distinguish an old defect reproduced, a candidate fix verified,
a candidate regression, an invalid test and an unverified claim. Link each result
to the actual command, exit/result, source/test identities and durable evidence.
A clean worktree, commit or test count is not completion. Correct inaccurate
reports with an explicit superseding note while retaining the original evidence.
Return candidate-awaiting-independent-review only when scoped checks pass; report
blocked/incomplete otherwise. Never self-assign independent acceptance.

Retain unresolved findings and useful reproducible evidence in the task handoff.
Any optional knowledge contribution uses its own single-writer workflow. The
existence of a knowledge corpus is not a prerequisite for authoring a task.
