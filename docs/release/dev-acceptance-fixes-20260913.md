# DVA-01/02/03 bounded repair

Status: SOURCE ACCEPTED; production rollout not performed.
capability_tier: deep. Executor: current Codex session.

## Frozen control

- Base: dev `71a28877c034592c2b4ae7ef38a14bdcc18e5b4d`.
- Only DVA-01 maintenance candidate prefilter, DVA-02 missing-dependency fixture,
  DVA-03 eight UTF-8 subprocess sites; no new program tasks.
- Native revision 3 receipt: `622f290b08d936bf14f371562f20d25680dc605c8ea2678e754a0412b0ddd502`.
- Worktree handoff: `a69d35edbc2dca8f06c3236fa27659ec5ad105ec4e10e33d399dd9b85d370bc3`.
- Preserve previous acceptance report commit `acd562c` and original worktree/logs.
- No change to installed runtime, production ledger, performance assertions,
  baseline SHA, sample counts, timeout, authority rules, or dependency ordering.
- No install/push/main merge. Only a verified candidate may merge to dev.

## Diagnostic measurements before repair

Read-only cProfile on one current `normalize_hook_event` call for source Guardian
`--help` (Python 3.10.7): 0.833 seconds, effect `read`.

| Cumulative function cost (nested; not additive) | Measurement |
|---|---|
| `_codex_plugin_install_binding` | 3 calls, 0.822 s |
| `_workspace_tracked_tree_sha256` | 3 calls, 0.818 s |
| `scheduler_reconcile_candidate` | 1 call, 0.639 s |
| `launcher_refresh_candidate` | 1 call, 0.185 s |

Candidate recognizers currently build sealed bindings before comparing command
shape. Even non-maintenance commands trigger whole-repository scans. Restrict
the change to necessary syntactic rejection before the *unchanged* exact path,
argv and digest verification. No memoized identity or relaxed matching.

The old performance test loads frozen `resources.py` with current sibling
dependencies; therefore a shared preflight regression affects its base variant
too. Confirm by rerunning the original performance test unchanged after repair.

## Acceptance and progress

- [x] Measure before choosing performance fix; check KB perf diagnosis and interpreter preflight lessons.
- [x] New negative test fails before patch; positive/digest-drift regressions remain strict.
- [x] Targeted tests, original performance test, and profile readback pass.
- [x] Freeze source commit and run complete official isolated suite in clean clone with main/history refs.
- [x] Local artifact staging and current runtime identity recorded; skip boundaries explicit.
- [x] Record findings/results, integrate only after green verification; preserve raw evidence.

Evidence directory: `.sulde/public-export/dev-acceptance-fixes-20260913/`.
Source/report changes are limited to the native-approved file inventory.

## Results / sedimentation candidates

Original acceptance remains 2193 tests, 2 failures, 1 error, 27 skips;
no original evidence is overwritten.

- Red regression: 14 tests, 5 failures, exit 1, 3.978 seconds. Includes the three
  new expensive-binding negative tests, original dependency and encoding failures.
- First post-fix scoped run: 357 tests, 1 failure, 17 skips, 86.989 seconds.
  The sole failure is an Agent-authored assertion in the new missing-command
  negative: a missing absolute path is `cannot be sealed`, not the PATH lookup
  error `cannot be resolved`. Corrected only that assertion after completion;
  no production behavior changed and the failed log is retained.
- Original unmodified performance test passed in that run: baseline/candidate
  control median 3.837/3.824 ms, P95 4.082/4.161 ms; 150 samples per case.
- Durable `profile.json` independently repeats before/after source measurements:
  628.783 → 9.420 ms per profiled help normalization, tree-hash calls 3 → 0;
  effect remains `read`. These are single-call local measurements, not an Agent
  end-to-end or production deployment latency claim.
- DVA-01 adds only necessary command-shape checks before unchanged binding and
  `_installed_candidate`; tests cover exact acceptance, wrong paths/runtime,
  malformed/compound commands, file mutation/removal, and binding failure.
- DVA-02 uses a real isolated Python executable identity plus an explicitly
  mocked Codex version response to reach real missing-PyYAML inspection. No
  installed Codex is launched. Source inspection is a fail-on-call sentinel.
- DVA-03 adds `encoding="utf-8", errors="replace"` at the eight original sites;
  the repository encoding guard now passes. No guard exemption was added.
- Final scoped regression: 357 tests, 340 pass, 17 retired Git-policy skips,
  exit 0. Log SHA-256
  `10c30483ee0c17d3c88139f0aee0a31c99381bdd63de272266246c5f223c56dc`.
  Original performance test and production preflight ordering remain unchanged.

Layer1 conclusions are recorded below, not written directly to the shared KB.

## Frozen integrated candidate

Source commit: `ca1911592c035f4f022f51a8f24d2d0157c169d5` (seven tracked files).
Complete runner executed from a fresh local clone of that commit, with
local main and all available historical objects/remote refs, no single-branch
or shallow clone. Final report updates are not changes to the tested source.

Local staging: Codex POSIX 683 files, Claude 814 files, both exit 0 and 387
corpus documents verified. Manifest/index `--check` both exit 0 (387 documents).
New candidate runtime digest:
`bf35a979ae4cb72fbf0cc4ab264d23a893ff85f68cc2e70b984ace8106f43945`.
The manifest version remains the source baseline's version because this is not
a production release: no cachebuster/install has run. The installed R14 digest
is still a separate earlier identity; candidate packaging is not live evidence.

**Full-suite: 2198 tests, 2171 pass, zero failures/errors, 27 skips, exit 0;
785.142 seconds.** The source clone remains clean; no `.pyc`/`.pyo` found.
The old acceptance's 27 skip cases and reasons are retained unchanged: 17
retired Git-policy cases, 5 Windows cases, 2 explicitly enabled CLI cases, 2
explicit-baseline benchmarks and 1 nested Seatbelt case. No new skip/exemption.
The runner's production-KB native write-denial preflight passed; its separate
nested non-Python denial test still skipped, not relabeled as verified.

Original performance test, unchanged: base/candidate single-control median
4.418/4.500 ms, P95 4.558/4.680 ms. All original budgets pass at 150 samples per
case. Source normalization retains the same effects and strict maintenance
binding checks. No original timeout/baseline/sample count was modified.

| Finding | Resolution | Final evidence |
|---|---|---|
| DVA-01 | Cheap necessary syntax exclusion before expensive bindings | New zero-binding-call negatives, exact-binding/digest positives and negatives, profile 3→0 scans, original performance test and full suite pass |
| DVA-02 | Dependency fixture reaches actual dependency gate; separate command-failure ordering regression | Both negative branches pass, no source/candidate creation, production order unchanged |
| DVA-03 | Eight explicit UTF-8/replace callsites | Encoding guard, affected functionality and full suite pass |

Evidence SHA-256 (under `.sulde/public-export/dev-acceptance-fixes-20260913/`):

| File | SHA-256 |
|---|---|
| `red.log` | `fda3606df28a31864311ae6abfc681eb723c7e6580daa872282d90a05728862e` |
| `scoped.log` (preserved failed assertion) | `56dd9279be3e5bedace9925745fd89bbfc3e9757a6c58f14e6f4c438d3d0fa6d` |
| `scoped-final.log` | `10c30483ee0c17d3c88139f0aee0a31c99381bdd63de272266246c5f223c56dc` |
| `full.log` | `1147a2422dd4ad854858e076e0f0d649c8376b94a95e1e1164348a44bc27f0d9` |

`*-execution.json` records interpreter, command, exact source head, exit and
post-run status; `summary.json` stores all skipped cases and performance data.
`profile.json` records both source-path identities and the instrumented calls.
These are local test artifacts, not exports of real session logs.

Linux Python 3.11, native Windows, missing explicit
CLI/baseline gates, and fresh Claude production live are not implied by this
macOS Python 3.10.7 acceptance. Old global ledger/LIFE warnings are not in scope.

## Integration and lifecycle record

After full acceptance and clean-worktree checks, dev fast-forwarded from
`71a28877...` to report commit `869966a`. Its diff against tested source
`ca191159...` contains only this acceptance report, not runtime/test changes.
This final lifecycle note is likewise documentation-only and follows the same
task-to-dev fast-forward path.

The entire task evidence directory (including failed logs, clean test clone,
staged artifacts and generation descriptor) was copied to long-lived dev at
`.sulde/public-export/dev-acceptance-fixes-20260913/`; recursive comparison is
identical. Paths recorded inside receipts remain historical provenance, not
reusable execution authority. The original failed acceptance branch/worktree
and `acd562c` report remain untouched.

Only this newly merged task worktree/branch is eligible for the Guardian's
completion-anchor and ordinary Git cleanup; retained dev evidence is the
recovery source. No cleanup of other tasks, main, user `.ua` changes, production
installation, scheduler, or historical ledgers is included. Main is unchanged
and still has the pre-existing user work; no remote push has occurred.

## Layer1 sedimentation candidate

- Problem type: performance / regression / workflow.
- Task goal and user expectation: close only three integrated acceptance failures,
  keep scope stable, retain evidence, do not weaken the Guardian.
- Trigger and symptom: normal read/local command classification built installed
  maintenance bindings and scanned the tracked source tree three times; the old
  shared-dependency benchmark exceeded its 180-second wall-clock guard.
- Confirmed root: scheduler/launcher candidate recognition computed bindings
  before eliminating syntactically unrelated commands. Profiler evidence and
  zero-call regression establish the avoidable cost. Dependency fixture ordering
  and the eight encoding-policy omissions are separately confirmed above.
- Excluded explanations: missing parent PyYAML (3.10.7/6.0.3 verified), missing
  historical main/base refs (present), need to increase benchmark timeout (the
  original test passes unchanged), need to disable digest checks (matching and
  tampering regressions preserve them).
- Evidence status: verified for source behavior and this host's local tests;
  production latency and untested hosts remain inconclusive/unverified.
- First-hand evidence: hash-bound logs, source commit, profile JSON and tests
  cited above. One Agent-authored error-message assertion was corrected and
  independently rerun, with the first failure retained.
- Correct handling: cheap *necessary* syntax guards reject impossible candidates;
  positive matches still run full exact identity/path/argument/digest validation.

| Sample | Input/action | Expected | Reason | Source |
|---|---|---|---|---|
| Routing positive | Ordinary normalization repeatedly scans a repository to reject unrelated maintenance commands | apply | Same measured eager-binding cause | observed |
| Routing negative | An actual matching maintenance command needs its current sealed identity | skip | Full validation is necessary and must remain | constructed |
| Execution positive | Unrelated commands produce zero binding calls; exact matching works and changed bytes fail | pass | Saves work without granting any new authority | observed |
| Execution negative | Cache binding digests, remove tamper checks, or raise timeout to turn a test green | fail | Hides stale identity or loses the acceptance invariant | constructed |

Before Layer2, remove local paths, commits, runtime labels and audit IDs.
Reusable core: reject impossible candidates before expensive proof construction,
while keeping proof mandatory for positive matches. Suggested container:
anti-patterns/case-studies after coordinator dedupe. Consumers: performance
review and candidate-router tests. No shared KB or memory graph write performed.
