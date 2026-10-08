# S0/S1 integrated implementation

Current update: the following is the preserved first-batch report. Its U01/U18
open implementation gates are superseded by [NEXT-REPORT](NEXT-REPORT.md):
frozen `122b7af` full run 2908 tests, zero failures/errors, 29 skipped. Source and
integration verified; still not merged, installed or production verified.

Status: `candidate / verified-scoped / release-gates-open`; not accepted,
merged, installed or production verified. Final tested code: `e5a2cc8b63aa511840aa01ff46dea258e0913072`.
Baseline: `ac5dc9c16527e41ef959ebbcef88593b71548e83`.
Branch: `task/guardian-unified-s1-20261004`.

## Delivered scope

| Item | Implemented result | Evidence and limits |
| --- | --- | --- |
| U01 | Installer WIP disposition, not copied | [Triage](U01-TRIAGE.md); proper journal/fence recovery design remains a prerequisite to a subsequent installation |
| U02 | Trusted exact help, bounded sed file operands, proven datetime receiver calls, closed SSH metadata grammar | [A report](../guardian-s1-semantics-20261004/REPORT.md); no arbitrary help/SSH exemption, no SSH executed |
| U03 | Exact literal SSH mkdir identity and one residual-risk grant authenticated inside the effect ledger | [B report](../guardian-s1-recovery-20261004/REPORT.md); one old unknown/verifying attempt only; unsupported verification stays unsupported |
| U04 | Missing/ambiguous/expired/foreign card diagnosis; current-risk card through existing native broker | `test_guardian_s1_grants.py`; exact subject/session/epoch/action/resource/policy, one consumer; old unknown retained |
| U05 | Audit-only policy disputes, bounded retrospective ingestion, existing governance weekly report | [C report](../guardian-s1-policy-20261004/REPORT.md); not a policy writer, not execution authority |

Three isolated module branches self-tested before cherry-pick into this single
integration branch. Shared files were coordinator-owned; four A semantic regions
in resources.py were explicitly transferred before editing. No installed cache,
remote server, dev/main branch, old dirty worktree or `.ua` file was changed by
this batch. Historical production effect records were not edited or settled;
normal current-task authorization and Hook audit records can still be appended.

## Integration and independent review

- Scoped official isolated run at `521acb4`: 159 tests passed, 6.755 seconds.
- Actual `hooks/pre_tool_use.py` subprocesses prepare a risk card, then admit
  exactly one isolated native-protocol receipt; no SSH is executed. The new
  attempt is dispatched and still requires verification; old unknown remains.
  This is **not** a real human/native UI or remote-effect acceptance claim.
- Independent semantics reviewer re-ran 33 grant/recovery tests and injected a
  forged dispatch and a two-debt case. Both reject without false approval hints
  or rewriting history; no new blocker on the reviewed `521acb4` risk chain.
- Review caught and this batch repaired: native long-path truncation hid the
  residual risk; the prompt now retains complete scope and mandatory warnings.
  The newly introduced delayed policy import was moved to the existing top-level
  import. Tests cover both Allow and Deny descriptions with a 1600+ character path.
- The integration run first reproduced an outer/inner mismatch: a consumed card
  passed policy but begin_attempt still blocked. The fix is independently reading
  the durable broker receipt inside ledger mutation, **not** a skip-barrier flag.
- Policy review additionally found fixed-prefix log starvation and a cleartext
  metadata-label privacy gap. These are tracked to this batch's narrow fixes,
  not relabelled as baseline failures.

The final policy review passed eight directed checks, including producer ingestion,
privacy, fairness and bounded coverage. Independent Pre/Post checks additionally
used isolated simulated success/failure results: the old attempt stays unknown;
new success stays verifying and failure unknown when verification is unsupported.
Broker replay works in a new process. These are real Hook processes with simulated
provider results, not actual SSH effects or human UI approvals.

## Final test results and failure disposition

| Layer | Exact code / result | Scope |
| --- | --- | --- |
| Official isolated full suite | `0b54cdf1f97a5c802341d5dce16385565c9a275f`: 2886 tests, 12 failure records, 1 error, 28 skipped; 2063.883s wrapper | Not green; immutable failure evidence retained |
| Narrow correction and independent review | `e5a2cc8`: parser delegation, imports, pure Decision-construction extraction, eight new encoding calls and two obsolete awaiting-human assertions | Review: no new blocker; 24 new-process import permutations pass; constructor arguments AST-equivalent and authority checks unchanged |
| Official impact-selected rerun | `e5a2cc8`: 346 tests, 17 skipped, exit 0; 35.868s wrapper | Six suites selected against the full-tested tree; no reuse; not a second full-suite claim |
| Final static guards | `e5a2cc8`: 30 tests, 7 failure records, exit 1 | Exact unresolved architecture/legacy encoding gates below; parser guard now passes |
| Final candidate native entries | `e5a2cc8`: two tests pass, 34.419s | Actual Codex CLI app-server / unified_exec / candidate Hook processes; local fake provider, zero external model requests |
| Native OS protection | Required real-OS single test passes, 0.471s, outside the outer test sandbox | Temporary protected/alias paths denied and allowed path succeeds; does not erase the full-run nested Seatbelt error |

Full-run evidence (local task artifacts, not public knowledge):
`../../.codex-agent/s1-evidence/20261004T085536.518077-d1db40d32c6b.{json,log}`.
Log SHA256: `e2d357bcfe22f1925660e77fb189302aa358ac448044bba8747203b6a468acc8`.
Workspace fingerprint: `8bae32f8d4cdc88c6835efc4c28f6434005437f3253eafe3bd4c7700ff668108`.

Impact-run evidence:
`../../.codex-agent/s1-evidence/20261004T093628.873763-f3538f3de073.{json,log}`.
Log SHA256: `046a26626e21aa2129e66d72e247d9ed45cee1694e7e1378a16dad236910829d`.
Workspace fingerprint: `963515adc54c110497994c32de5cd39aa7c3935f237772a141a5b6b3553ab74e`.
Both official runs recorded zero source bytecode files/directories removed.

Final native-entry facts (summary transcribed from tool output, not claimed as
an archived raw transcript): artifact generation
`0.2.5+codex.20261004042610-d1eeed94b5:3af3cbd8d86b3596454173fe3f236a5d76d4d692ee17a4aef3ff3a3ab5a7ec5b`;
loaded module generation
`7b657856e6292a0193ad95d80d79a2445844ed4e6554d3909e03a40cb17141e0`.
String-flow proof `b3b68ed5662f8221a665e5e386306cc91ef7436cb024617a83f9df01db04ed93`
records actual text-write/key-transform success and pre-execution denial of
destructive/path-replace controls, with marker absent. Composition records four
completed safe batches, one destructive Pre denial (`candidate_native_2`),
preserved short-circuiting and a subsequent permitted write. This run uses the
official outer OS test guard; its inner canary reports dangerFullAccess and does
**not** prove sibling/symlink sandbox rejection. The separate native-OS test above
provides its own narrower evidence. These artifact checks do not exercise a real
human risk-acceptance card or remote SSH operation.

Failure ownership is not inferred solely from identical test names:

- **New and fixed here:** three direct shlex parser calls, two delayed imports,
  eight unspecified subprocess encodings, policy's newly exceeded line budget,
  and two tests expecting a human-pending state without a real card. Updated
  assertions still require denial and `effect_barrier_denied`. The constructor
  extraction moves no policy checks; final policy is 2991 lines. A non-TestCase
  shared fixture removes six accidentally inherited duplicate diagnostics.
- **Old plus changed candidate surface, still open:** policy/resources AST and
  import freezes already fail on `ac5dc9c`, but S1 adds explicitly reviewed
  differences too. Their historical whole-file freeze is not automatically
  waived or reset. Four composition architecture failures remain. The precise
  S1 composition delta has its own mutation-sensitive guard; this does not
  replace formal disposition of the global freeze.
- **Existing line excess worsened, still open:** resources was 3089 lines at
  baseline and is 3111 now, against 3000. This is not described as an unchanged
  baseline failure. Refactor/architecture disposition remains a release gate.
- **Independently reproduced baseline defects:** delayed `state.py` import
  (reported by two architecture tests), distill-conflict assertion, eight encoding
  violations in four untouched tests. Final static run reports those same eight
  old calls, not the eight corrected new calls. No broad unrelated repair here.
- **Environment:** the full suite's native-OS check errors on nested Seatbelt
  `sandbox_apply`; the standalone mandatory test passes. An earlier runner launch
  (`20261004T085455.779015-fd5f35a1fa36`) also failed sandbox preflight before any
  test ran. The formally approved isolated full run above supersedes that launch,
  not its historical record.

The narrow final correction used equivalent inputs plus the complete affected
suite; unaffected full-suite observations remain tied to `0b54cdf`, not relabelled
as a green full run on final HEAD. Remaining release gates and U01 need their own
bounded disposition before merge/install; this report is not such a waiver.

## Limits and next boundaries

- The SSH grammar requires a literal IP/account/port, disabled user config and
  fixed safety options. Read support is stat / ls -ld; write-risk support is one
  mkdir -p. Arbitrary aliases, deployment scripts, multiple historical blockers
  and an independent SSH effect verifier are **not** delivered.
- A risk acceptance does not declare the historical attempt successful, retry
  it automatically, or transfer authority to later calls. Broker history must be
  retained for new risk-link replay. Effect-only offline archives containing
  these links fail closed without broker proof; self-contained cross-ledger
  archive support is deferred.
- Policy telemetry copies bounded codes and hashes, not raw commands, prompts,
  private paths or hidden reasoning. Assessments remain evidence claims and
  inconclusive candidates even if labelled false_denial. No automatic production
  rule change is possible through this module.
- Automatic policy ingestion covers default workspace/session audit locations.
  Oversized/corrupt sources retain their checkpoint and report degraded. Discovery
  caps expose partial coverage; they do not count omitted files as reviewed.
- S2 execution-method wiring, S3 production/host acceptance and S4 independent
  backlog are not this batch. U01 must be resolved before production installation.
- A's paired normalizer P50/P95 observations stayed within frozen budgets; no
  normal-path model call was introduced. Whole-Agent Token savings, global
  contention and production latency are unmeasured, not claimed.

## Process corrections retained

The first new Hook test expected permissionDecision=ask. Inspection of the actual
entry confirmed it emits deny while a native decision is pending; the corrected
test requires deny plus a real prepared card and the readable confirmation reason.
No SSH was run under either expectation. This was a fixture assertion error, not
a product regression. All tests use `-B`; the official evidence runner handles
derived source bytecode hygiene and records its cleanup.

## Sedimentation candidates (not written to knowledge base)

1. Permission confirmation must fit the complete precise scope and residual risk:
   route positive = long valid scoped grant; route negative = truncated card;
   execution positive = full prompt + exact consumed receipt; negative = authority
   based on hidden or omitted risk. Evidence: verified in isolated tests.
2. Outer policy permission and inner effect admission must consume the same
   durable authority. Route positive = precise risk review; negative = caller-only
   skip flag. Execution positive = independent broker authentication; negative =
   deleting old unknown debt. Evidence: verified source/protocol, no production claim.
3. Bounded maintenance needs fairness and explicit coverage. Route positive =
   later valid log despite corrupt earlier log; negative = fixed prefix forever.
   Execution positive = attempted-source rotation without advancing invalid audit
   cursors; negative = silent empty success for omitted logs. Evidence: module tests;
   large-directory discovery remains a disclosed limitation.
