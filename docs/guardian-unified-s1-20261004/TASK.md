# S0/S1 bounded implementation

Status: candidate / verified-scoped / release-gates-open. Provider: codex. capability_tier: deep.
Implementation and scoped verification are recorded in REPORT.md; this is not
accepted or installation-ready, and no release authority is implied.
Baseline: ac5dc9c16527e41ef959ebbcef88593b71548e83.
Plan: ../guardian-unified-plan-20261004/{PLAN,INVENTORY,ACCEPTANCE}.md in the separate plan worktree.

## Outcome and boundary

Implement U02–U05 (semantic classification, remote recovery routing, policy review)
and triage U01 installer WIP. Existing production behavior must not be changed by
editing the installed runtime. No production install, dev/main merge, push,
network deployment, production effect settlement, or old-worktree cleanup.
Keep original event history and high-risk human authority intact.

Human-reviewed contract revision 3 authorizes the four named S1 worktrees plus
the plan documents. It does not transfer approval receipts to child sessions.
Each child may write only its assigned worktree and owned files. If a host gate
requires separate binding, report that boundary; do not self-approve or bypass it.

## Ownership and interfaces

- A (semantics): control_composition.py, resource_preflight.py, a small pure
  semantic helper if needed, tests/test_guardian_s1_semantics.py. No resources.py
  edits: supply exact integration changes to coordinator. Distinguish trusted
  help from arbitrary help tokens; preserve dangerous compound-command handling.
- B (recovery): intervention.py, a small remote identity/recovery helper if
  needed, tests/test_guardian_s1_recovery.py. No resources.py/approval/kernel
  edits: return required integration contracts. Preserve unknown historical
  effects; provide bounded read probes and explicit recovery eligibility rather
  than weakening ordinary grant checks or silently retiring history.
- C (policy review): existing governance/experience code and dedicated helper
  only as needed, tests/test_guardian_s1_policy_review.py. Generate audit/review
  candidates, not executable policy or authority. No actor may relax its current
  production denial; no new hot-path model call/full scan/second truth store.
- Coordinator: resources.py, decision kernel/approval entry glue, installer
  triage, integration test/report, shared interface decisions. Shared file edits
  require explicit ownership transfer rather than concurrent changes.

Result interfaces must state effect, reason/evidence, target identity quality and
limitations. Identity data must not include secrets/raw commands in policy
telemetry. Resource domain is not proof of a unique endpoint. A recovery decision
may accept a precise risk but cannot convert unknown effect into verified success.

## Continuous execution and evidence

Each owner continuously performs inspect -> valid normal control -> same-assertion
baseline red/candidate green -> actual entry -> affected module regression, then
commits its candidate and reports. Fixture failures are not product regressions.
After two attempts without new evidence, change diagnostic method, not assertions.
No per-test handoff. Stop at authority/scope issues, unsafe progress or external
prerequisites, not merely one failed test. Additional live model/provider calls
and production actions are excluded; normal collaboration workers are permitted.

Use python -B/PYTHONDONTWRITEBYTECODE to prevent source-tree pollution. Tests use
isolated temporary state; reports use the owned docs directory. Do not overwrite
historical evidence. Raw test logs remain local task artifacts; archive to Optimus
only through a separately scoped write if required. No hidden reasoning capture.

Integration sequence: module commits -> coordinator integration branch -> combined
entry/security tests -> affected suites -> official full suite -> independent
review. Full-suite environment/baseline failures stay explicit. Do not claim
production/real-Agent behavior from mock provider tests.

Performance: no new model call on ordinary paths, no global history scan added to
ordinary action classification; paired local measurements before/after. Freeze
numeric budgets from measured baseline before evaluating final candidate; report
unknowns rather than inventing savings.

## U01 triage

Read old .worktrees/sulde-orchestration-iteration installer/test WIP without editing
it. Compare with current dev. Missing journal != automatically proved safe; also
test valid pre-transaction fences to avoid introducing a recovery deadlock.
Do not copy the draft journal parser merely because it is stricter. Reuse the
authoritative journal reader and identity protocol where possible. Record a
scoped follow-up if implementing a fix exceeds this frozen batch.

## Delivery

Per module: exact commit, files, baseline counterexample, candidate evidence,
normal and negative controls, entry/module results, remaining risks. Integrated
status distinguishes source, protocol, host-live, install and business effect.
Only independent review may accept. No production work is authorized by a green
suite or this task file.
