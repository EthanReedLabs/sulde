# release-2026-09-16 bounded blocker repair

## Frozen control

- Base dev: `b40c0a3b3edfc80dd357c895cff7cf26a4f148eb`.
- Scope: six categories below; no new features, production installation, ledger edits, or adjacent cleanup.
- Native r3 receipt: `66e38b52f1a67943f4cdce23de8de7301f627ba903a5edd14fd0c93775582eef`.
- Original gate: 2393 tests; 8 failures, 1 error, 27 skips. Original log SHA256
  `c95e2953579b2755fd8361b4ff6119d8128a19421b9393337e374c18487f72c4`.
- Original archive, stash, and failed evidence stay in dev `.sulde/public-export/release-20260916/`
  and stash `c386dc41ec15857d24dbe95d1f1526f543e0c9ba`; never commit or upload them.
- Stop line: unrelated discoveries remain deferred; safety or acceptance changes need explicit review.
- Integrate only green source/evidence into dev, verify integrated release and clean worktrees before main;
  then create new annotated `release-2026-09-16` and atomic non-force push of dev/main/that tag only.

## Frozen acceptance checklist

| ID | Blocker | Required repair/evidence | State |
| --- | --- | --- | --- |
| RB1 | Exporter assumes old private repository name | Exact approved old/new URL mapping; unknown metadata rejected; export negative tests | accepted |
| RB2 | Two direct shell split calls | Shared parser with explicit POSIX semantics and cross-platform tests; no new exemptions | accepted |
| RB3 | Delayed imports / back dependencies | Low-level storage/fence and native binding boundaries; no delayed/dynamic imports; acyclic graph and real native recovery regressions | accepted |
| RB4 | Old AST invariance vs two accepted changes | Assert exact retirement and Git review deltas, normalize only those, retain strict remaining AST equality and behavior tests | accepted |
| RB5 | state/recovery over 3000 lines | Extract real persistence/native-decision responsibilities; preserve public seams, no threshold change or whitespace reduction | accepted |
| RB6 | 30 missing subprocess encodings | Add explicit UTF-8/replace only to identified text subprocess boundaries; original guard unchanged | accepted |

## Validation and findings

All six frozen blockers are accepted. Raw checks are retained under the registered dev
worktree's `.sulde/public-export/release-blockers-20260916/`; failed and passing runs are separate.
This repair did not reinstall the production plugin.

- RB1: map only the two reviewed private manifest URLs to the existing public URL;
  reject unknown URLs and scan both historical/current private names.
- RB2: both Git proof parsers use the canonical splitter with explicit POSIX semantics;
  Windows still cannot take the POSIX-only proof path.
- RB3/RB5: extract storage/fences, native request fingerprints and late proposal classification.
  Historical native retirement now has one historical-domain owner, with compatibility exports.
  Ledger writers depend on the low storage layer, not relocation execution.
  Extracted primitives retain their implementation ASTs; the streaming snapshot only substitutes
  explicit budget parameters, whose defaults, wiring and unchanged remaining AST are asserted.
  Public entrypoints and the controller's original capacity/chunk-size configuration remain available.
- RB4: retain the original AST baseline; independently assert and normalize exactly the accepted
  historical-retirement guard and Git stdin-review proof. Changed/duplicated guards and unrelated
  changes remain detectable. Policy/resources source is not edited.
- RB6: fix exactly 30 text subprocess boundaries in six tests. Original scanner is unchanged.
- `focused-01`: 59 tests passed, no skips, 14.792 s.
  Log SHA256 `d80b435f8c613045bc540115c3c29196c74434d55c8ffde7215276c037a2576a`.
- `recovery-01`: deliberately interrupted after two installed-fixture errors and discovery of
  an import-hoisting name collision; not accepted evidence. Isolated runner returned 254 after
  136.431 s; original log retained, SHA256
  `b6c0d931adb9be5eb2874de5a024b81a686eb3584f78375faae2a7a3f555d76e`.
  Before retry, register the three new runtime modules in Git's tracked inventory (the packaging
  fixture uses that inventory), and alias the historical review function explicitly because
  `native_decision_context` already has a local `review` variable. The interrupted run did not
  print its final exception summaries; omission from the packaging inventory is an inspected
  explanation, not a preserved traceback claim.
- A read-only patch-generation snippet was denied by the installed Guardian's object-type proof.
  It made no writes. Subsequent edits used explicit approved file paths via normal patch tools;
  no installed runtime, ledger, or approval state was edited to bypass that denial.
- `native-focus-02`: 54 tests passed, no skips, 154.749 s. This includes six actual
  Codex app-server fixture choices (relocation Allow/Deny, epoch retirement Allow/Deny,
  historical native-transaction retirement Allow/Deny), without production installation.
  Log SHA256 `5df571f831f2b6915c03b7631a293812c47b7e355c162206b8af995252581d2f`.
- `full-01` on clean `8a185a80614d2654d36a5da51a743ba9c3ff1fd6`: rejected.
  The existing `test_relocation_store_capacity.test_per_file_and_total_limits_are_separate_and_inclusive`
  found that a re-exported function no longer read the controller's overridden `MAX_STORE_BYTES`.
  Initial focused selection missed this separate capacity module. Preserve this failure; do not
  modify that original test. The run was interrupted after 1085.237 s, exit 254, clean checkout;
  log SHA256 `14ecfe9b02d5345b1943e140bbb5432c1d84151fdefa5446e5e4a4b73345bea3`.
- RB3 compatibility correction: keep the controller wrapper and explicitly pass per-file/chunk
  budgets into the low-level snapshotter, preserving both original defaults and live configuration.
  No budget increase or ledger/mode/ownership relaxation. The existing capacity suite plus new
  parameter-wiring regression and architecture/export gates passed: `capacity-03`, 57 tests,
  no skips, 12.876 s, log SHA256
  `0675af5425e72ba81c9a206ce1ab2ddc35aa2d9c701288e1ccddf07cb71f7c42`.
- `package-01`: all seven package/manifest/index/lint/Hook/template checks passed for the first
  frozen candidate; package and full gates will be rerun on the corrected source.
- Current installed doctor remained operationally ready, pairing settled and effect debt clear;
  scheduler ready. This is current-session health, not proof that the repair was production-installed.
- The installed guard rejected a combined chain of three lifecycle `--help` commands as a
  context-changing composition. Each single help call succeeded. Record only: no adjacent guard
  rework, no authorization bypass, and no scope extension for this non-blocking behavior.
- Final acceptance is recorded below. Documentation-only acceptance updates must be explicitly
  diff-verified and cannot silently change tested runtime code.
- `full-02` on clean `a4dc82014183611673bf71bb7377d1a4f99b9404`: completed and rejected:
  2401 tests, 7 failures (including four subtest failures), 27 skips, 1335.777 s, exit 1.
  All failures are four existing migration-preflight tests that inject the authoritative native
  journal projection; log SHA256
  `1275583d0b5683d89340bbd14d28da9faacd1696279104cebf24bb69ff90392e`.
  Hoisting a function import captured its callable early, so patching the original journal
  module's reader no longer reached the consumer. This is a callable-binding/injection regression,
  not evidence that real ledger contents were cached, cleared or accepted as settled.
- RB3 correction: keep a static native-journal module import and explicitly call that module's
  reader at all six existing callsites. Retain every preflight rejection and the unchanged fault
  injection tests; no delayed/dynamic import or reflective import workaround.
- `projection-04`: the three initial failing test methods passed unchanged (3 tests, 3.418 s);
  SHA256 `ce122e242d5d77a2dbdba1aa924e3d70a13623441b556c2948563731c1c8c759`.
  The complete affected group, including legacy-diagnostic subtests, must pass before the next
  full release run. The earlier focused selections were insufficient for this refactor; preserve
  both failed full runs as evidence rather than presenting them as successful releases.
- `affected-05`: the complete 16-module affected group passed, 437 tests, no skips,
  556.475 s; SHA256 `3a10431ddb42344f7e2183e1a161ac4dad582769ac685df80bac3d7fd0123308`.
  It includes all original capacity and native-projection fault injection cases, migration
  interruption/installed fixtures, historical retirement, native journal, effect and approval
  truth, Git verification, architecture, encoding, metadata export and promotion identity.
- Final full verification uses the same official isolated runner and frozen clean checkout in
  two disjoint discovery batches (`test_[a-m]*.py`, `test_[n-z]*.py`). Their file union must
  exactly cover default discovery, and their combined actual test-ID multiset and skip records
  must match the completed 2401-test `full-02` inventory. Both exits must be zero. This changes
  scheduling only: no missing test, extra skip or weakened guard is accepted.


## Final acceptance

- Frozen tested code: `02937007ab4e6d18ed420d2458793265cfc7460a`.
- Full suite: **2401 tests, 0 failures, 0 errors, 27 existing skips**.
  Both the actual test-ID multiset and every skipped test/reason exactly match the prior complete
  discovery inventory; all 158 test files are covered once across the two batches.
- `full-03-a`: 1617 tests, 24 skips, exit 0, 657.721 s;
  log SHA256 `1d3ed79a5d59100b47437eaf2d5321e06ea6ad6ad0a6616aa271d7f85f2daf41`.
- `full-03-b`: 784 tests, 3 skips, exit 0, 705.525 s;
  log SHA256 `014cd19cb69314ee0dab2b97cb16e38a9ad47051055b767297e55d44fcda9923`.
- Aggregate acceptance JSON SHA256:
  `9932dbe34a7f2b3b22692372b137477b861c7c59f46cd2dea66c18403bbbd33d`.
  The log parser handles unittest's multi-line docstring headers and excludes repeated failure
  reports; it requires exact case counts, not a permissive pass-string search.
- `package-03`: 7/7 checks pass: manifest, index, frontmatter lint, Claude stage, Codex POSIX
  stage, Hook dryrun and template dryrun. Result JSON SHA256:
  `1ca82724cc3d9280b0aa93bf7b2e933628becebd37c419cef2bbbcc1c623d71c`.
- Both validation batches' post-run status checks were clean (the two isolated batches use the
  same immutable source checkout and separate disposable runtime environments).
- State/recovery remain 2986/2965 lines, under the unchanged 3000-line cap.
- Main merge preflight was conflict-free and matched candidate tree
  `784e4999ce4708014e14f47b1b338ceda9196b51`. The final report-only commit must have no
  non-report diff from the frozen tested code; integrated dev/main must retain that equality.
- Final ref publication and cleanup receipts are separate mechanical evidence in the same local
  archive; the annotated release tag binds the release commit to these verification results.
- Limits: local macOS/POSIX and installed-artifact fixtures are verified; the 27 original skip
  conditions are not represented as executed tests. Production remains the previously installed
  generation until a separately authorized installation, with no cache/ledger edits in this task.

## Sedimentation candidates

### Layer1: moving imports is a dependency refactor, not a text-only cleanup

- Problem type: regression / workflow.
- Task/intent: remove release-blocking delayed imports while retaining exact authorization,
  unknown-outcome semantics and recovery behavior; no architecture-test exemption.
- Trigger: a migration controller is imported by low-level ledger writers while importing
  their state/approval controllers in return.
- Observed difference: architecture checks reject delayed imports/cycles; merely lifting a
  function import can also expose a local-variable name collision.
- Confirmed root cause: the dependency points upward; Python also determines function-local
  bindings statically, so a module-level `review` cannot replace a local import when another
  branch assigns `review`.
  Function bodies with identical ASTs are not enough: changing a function's owning module can
  change where capacity constants come from, and hoisting a function import changes when its
  callable is bound. Preserve those dependencies explicitly, including existing injection seams.
- Excluded explanation: the user did not omit an authorization; this is implementation and
  packaging discipline, not permission-policy looseness.
- Evidence state: verified for dependency graph, extracted primitive AST invariance, parser,
  encoding, metadata, native recovery and complete release checks.
- First-hand evidence: frozen base and diffs above; `focused-01`; new
  `tests/test_release_blockers.py`; existing native/historical/relocation regressions.
- Correct method: extract a low-level shared owner; retain compatibility exports; use an explicit
  import alias at the conflicting callsite; include new source files in tracked packaging
  inventory; verify built-artifact native paths as well as architecture.

| Sample | Content | Expected | Reason | Source |
| --- | --- | --- | --- | --- |
| Routing positive | Delayed imports hide state → migration → state dependencies | apply | Same cyclic ownership and import-timing risk | observed |
| Routing negative | Optional third-party import with no state/controller dependency | skip | Requires optional-dependency analysis, not this migration fix | constructed |
| Execution pass | Acyclic static imports, unchanged extracted primitives, native Allow/Deny and recovery green | pass | Structure and actual transaction paths both verified | observed in affected-05 and full-03 |
| Execution fail | Architecture green but imported function is shadowed by a local variable, or package omits its new module | fail | Source-level import checks alone do not prove delivery | observed collision; packaging explanation inspected |

- Upward routing: generalize project names, paths, commits and receipts before publication.
- Reusable rule: prove dependency direction, Python binding semantics, and the built artifact together.
- Suggested container: anti-patterns; consumers: review checklist, test harness and retrieval.
- This is a local candidate only; no shared KB write or memory-graph dependency was introduced.
