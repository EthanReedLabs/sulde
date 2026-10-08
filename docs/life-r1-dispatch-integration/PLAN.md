# LIFE R1 + task-only dispatch integration

capability_tier: deep

## Frozen scope

- Intent: `completion:a378a25de95028b90f01d107`, revision 3; current-session native approval.
- Base dev: `f687193bdda541d4651846ed99aa6dbe37475f7d`.
- LIFE R1: `c0fa7a04ffe2194dbf92baedf04d9d21f376ebe4`.
- Task-only dispatch: `3a3b29d625d259efc50776b2cd865c5e11f594ff`.
- Integrated source: `492cf12e0201f6d2b73267011c8119fc3ae639a7`.
- Work only in this independent integration worktree. Preserve source task worktrees, dev/main, user changes and production configuration/runtime/ledgers.
- This stage ends with scoped regression and isolated candidate evidence. Production promotion, dev/main integration and remote publication are later decisions.

## Evidence reuse and test selection

R1's full suite at `8375ac3` has 1,905 passes and 23 skips. Its original log SHA-256 is
`2224386331a601320913e2c531d2ed91e6ade2b932d8ccd841efbb0bbe456bec`.
Relevant production inputs and tests are unchanged between that commit and R1's report commit.
This is a baseline for unchanged components, not a claim that the new integrated HEAD has a full-suite pass.

The dispatch branch has 82 scoped passes. The two branches overlap only in
`scripts/release/install_codex_plugin.py`, at distinct hunks. Integration introduced no hand-resolved source change.

Run the explicit modules in `verification-plan.json` through the repository's supported
isolated test runner and evidence writer. They cover dispatch defaults/opt-in, installed smoke,
candidate receipts, interpreter/dependency identity, Hook adapter compatibility and real native CLI delivery.
Preserve first failures as well as successful records. Report-only edits do not rerun the suite.
Any integration correction must receive affected regression; a core semantic change requires reassessing full-suite scope.

## Candidate boundary

Select the already available Python 3.10.7 / PyYAML 6.0.3 environment explicitly.
Validate plugin structure with the official plugin-creator validator. Use the repository candidate
implementation in an isolated data/config/artifact root; keep exact commit, source digest, interpreter,
dependency and artifact identities in evidence. No global dependency installation or production cachebuster.
OS scheduler fixtures and injected Hook failures must be labelled as such, never production proof.

## Open capability items

Desktop ingress, native Windows execution, unwrapped external Hooks, historical Apollo/iquokka exit-1
attribution and production business acceptance remain open. Report-write misclassification remains
an independent unresolved issue. None is silently marked fixed by this integration.

## Integration blocker discovered during execution

The first integrated run (145 tests; 49 failure entries and one error, including subtests)
rejected identical PyYAML bytes loaded from different venv directories. The selected installed
venv and base interpreter both load PyYAML 6.0.3 with content SHA-256
`cd599dfd54eaa161a07a80ea872158b3849b8a6ab5d21fa9d51e5f5d00e4086a`.
`same_runtime` mistakenly included the dependency's absolute location in cross-venv content equality.

The bounded correction ignores only the PyYAML root in cross-environment equivalence. Exact
receipt validation retains the root, and interpreter bytes/version/base, dependency bytes/version
and SSL identity remain mandatory. A real copied-package positive regression, material-drift
negatives and exact-receipt path-drift regression cover the distinction. This changes the environment
compatibility check, not Guardian authority or runtime control semantics; its two release consumers
are already included in the frozen impact set. Keep the failed integrated run and red/green records.
