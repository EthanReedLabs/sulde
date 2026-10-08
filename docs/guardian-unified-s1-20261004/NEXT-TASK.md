# U01/U18 bounded closeout

Baseline: ef5e7d6. Provider: codex. capability_tier: deep.
Status: implementing under current-session human-approved revision 4.

## Outcome and authority

Repair installation recovery identity/integrity and formally dispose of the open
release guards without weakening policy or testing. Original S1 source remains
the candidate, not an accepted release. No dev/main merge, push, production
install, SSH, historical effect settlement, paid model experiment or old-worktree
cleanup. Preserve dirty WIP and .ua. Normal task authorization/audit may append.

Three repair lanes are created from dev and populated with the frozen S1 commits
solely as their repair input. Module patches return to the existing integration
branch after their scoped checks; no failed candidate is merged into dev.

## Exclusive ownership

- U01: scripts/release/install_codex_plugin.py, install_transaction_journal.py,
  scripts/kb/generation_fence.py if necessary; own dedicated recovery test and
  existing installer tests needed for changed recovery semantics. Own docs under
  docs/guardian-u01-recovery-20261004/. Do not refactor unrelated installer logic.
- U18 architecture: intent_guardian_parts resources/state/policy and minimal
  extraction helper; test_control_composition_architecture and
  test_intent_guardian_state plus dedicated architecture tests. Own docs under
  docs/guardian-u18-architecture-20261004/. Do not modify installer or test fixtures
  owned by another lane. Public AST freezes require exact reviewed deltas or
  stronger invariant tests, not an arbitrary new baseline accepting all changes.
- U18 test hygiene: eight existing subprocess encoding violations in four
  predictive tests; distill-conflict failure diagnosis and smallest necessary fix
  in its producer/test. Own docs under docs/guardian-u18-tests-20261004/. No
  weakening product contracts or changing unrelated snapshots. Notify coordinator
  before any shared-file need. Installer duplicate-suite optimization is deferred
  (U09), not folded into this lane.
- Coordinator: shared task/report/plan, integration, read-only independent review,
  actual entry and final combined evidence; tests/test_isolated_test_runner.py
  nested-Seatbelt diagnostic fixture and dedicated regression (U18 environment
  error already recorded last batch). Production OS isolation is unchanged;
  mandatory native evidence may never skip. No concurrent writes to owned files.

## Frozen acceptance

U01: reuse authoritative hash/sequence/schema/identity journal reading. Missing
journal alone never proves no production effect. Legitimate interruption before
production mutation needs positive durable evidence and idempotent recovery.
Test same/foreign identity, missing/corrupt journal/fence, hash mismatch, before
and after durable journal publication, committed/rolled-back postconditions,
repeated recovery, concurrent admission. Preserve observe/block semantics and
short lock scopes. Use actual installer path and isolated state, not mocked
success in lieu of recovery. Design before editing; review publication ordering.

U18: close new/old guard failures without resetting freeze to current bytes.
Preserve component DAG, no facade import, <=3000 component lines, explicit text
encoding. Verify refactoring equivalence and mutation-sensitive tests. Distill
fixture must represent actual accepted producer protocol; an invalid fixture is
not proof of product failure. Capture original failing behavior first.

## Continuous execution and evidence

Each owner establishes normal control, captures the target failing assertion on
the frozen baseline, makes minimal fix, runs injection/entry/module checks and
returns one coherent commit/report. No repeated user-mediated micro-rounds.
After two attempts without new information change the diagnostic method. New
unrelated issues are follow-ups, not silent completion criteria.

Use /Users/eric/.sulde/data/kb/venv/bin/python -B; no source bytecode. Test files
also fix encoding/errors from the start. Evidence stays in owned task artifacts;
no external-disk writes or production paths without explicit scope. Keep failed
outputs and source/test identities. No hidden reasoning or raw private prompt
capture. Budget: deterministic local tests only, one consolidated full run after
integration, then impact-driven reruns; no real-model paid experiment. Whole-task
Token/performance benefit stays unknown unless measured.

Consolidated independent review after modules are integrated and targeted checks
pass; do not self-accept. Full regression is required for this combined recovery
protocol + architecture refactor. Actual host tests use candidate artifact and
local fake provider; distinguish that from production installation and human UI.

Stop for missing authority, unresolved safety choice or external dependency;
otherwise complete this bounded outcome. Completion report separates old defect,
candidate correction, fixture error, environment failure and unresolved release
gate. It must not declare production fixed.
