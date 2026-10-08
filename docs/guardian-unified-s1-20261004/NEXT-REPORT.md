# U01/U18 closeout evidence

Status: source_verified / integration_verified for U01/U18; no production release acceptance.
Frozen input: ef5e7d6. Task: NEXT-TASK.md. Scope: human-approved revision 4.
No dev/main merge, push, production installation or effect settlement.

## Design decisions before implementation

U01 uses journal-before-fence publication: the durable descriptor, snapshot,
active pointer and prepared stage precede the short fence critical section and
first guarded production mutation. Snapshot preparation must not hold the fence
admission lock. A newly published fence binds the transaction and descriptor
digest. Recovery of a fence without active pointer must use the authoritative
journal reader, exact identity and terminal postconditions; file absence is not
proof that nothing happened. Clearing must compare the same observed fence under
its lock. Legacy ambiguous or foreign fences remain evidence, not deletion targets.

This replaces the old normal-case claim that a missing journal proves an orphan
is safe. It does not silently change the older damaged-fence admission fail-open
policy, which is separately disclosed and not claimed fixed.

U18 architecture retains module size limits and dependency restrictions. A change
to a historical whole-file freeze needs review of the exact changed obligations,
not simply a new expected digest. Extraction should preserve function ASTs and
call-site semantics; new review gates must reject meaningful negative mutations.

U18 distill baseline investigation found a potential fixture/environment mismatch:
the fixture mocks connect(temp_db), while the real CLI first checks a home-derived
database path. A temporary initialized home must feed both operations. This is a
diagnostic finding pending the owner's isolated reproduction, not an accepted
production annotation-protocol defect.

## Process and evidence rules

The first proposal command failed in zsh before execution because unquoted path
globs referred to not-yet-created worktrees. No proposal was created by that
command. Quoting the exact allowed path patterns fixed the invocation; revision 4
was then approved through the native decision surface. Host saved an exact command
prefix despite no prefix_rule request; it is not reused as authority.

Knowledge search did not find a directly applicable installer protocol article.
The read article ap-0210 reinforces matching persistent state to completion claims;
its device/UI-specific acceptance does not apply to these pure functions. Tests
must verify real recovery postconditions, not merely a success message.

Module commits, baseline counterexamples, entry results, combined regression and
independent review will be appended without erasing failures. Historical S1 full
and impact-run records remain in REPORT.md, bound to their original code trees.

## U18 test hygiene integrated

Module `42a8495` integrated as `274f20b`. Independent coordinator inspection found
no product source changes: eight explicit text decodings and a full temporary
home for the distill CLI fixture. Actual child CLI tests prove exit 0/created,
then exit 3/conflict, with original entity/type and one receipt retained.
Integrated distill/encoding/new OS diagnostic suites: 17 tests pass, 3.070s.
The module report preserves baseline failures and its 14/46-test runs.

## U18 OS environment fixture

The previous full suite's `sandbox_apply: Operation not permitted` failure is
the unavailable nested Seatbelt diagnostic. The old fixture recognized only an
unanchored `sandbox_init` substring. The revised fixture recognizes exactly the
two complete initialization-error messages; an escaped write or unknown error
must re-raise, and SULDE_REQUIRE_NATIVE_OS_EVIDENCE=1 always re-raises.
No production isolation runner code or protected path list was changed.

New boundary-injection test initially reproduced sandbox_apply ERROR on the
baseline. An injected escape-like message also exposed an overbroad old substring
skip; final regression explicitly fails if a required/error case returns SkipTest.
Four candidate diagnostic/escape tests pass (0.071s). Actual mandatory native OS
positive/negative test plus the three diagnostic cases passes 4/4, zero skips,
0.480s outside the outer sandbox. Independent read-only review repeated 5 related
checks and mandatory 4/4 (0.527s), no new blocker. This does not mark skipped
nested checks as native success; real evidence is the separate mandatory run.
Times and output summaries here were transcribed from tool results, not labelled
as archived raw stdout. The later official integrated record will persist logs.

## Final module integration and independent review

U18 architecture `80971b2` integrated as `09fbb9b`: memory helpers extracted
without body changes; original BASE remains fixed. Exact AST obligations,
imports, reexports and meaningful negative mutations replace whole-owner
exemptions. Module 31/31 and affected 120/120 passed; both independent reviewers
repeated the 31 checks without blockers. Resources now has 2942 lines.

U01 `0d46aff` plus correction `c701985` integrated together as `74be9d7`.
Independent review of the first candidate found a real additional failure:
directory fsync raising after fence unlink caused rollback despite committed
journal authority. The original candidate's green tests did not cover this.
Final implementation distinguishes committed cleanup failure from install failure,
prevents both inner and outer migration rollback after verified commit, and
clears the active pointer only after fence CAS and directory synchronization.
Recovery keeps real authority and does not fabricate a fence or success.
The original independent fsync probe now passes: registry/deployment bytes stay
unchanged, real recover-only finishes cleanup, repeated recovery is a no-op.
Independent official cleanup tests 4/4 pass (44.203s), including lock, rollback
recovery and CAS rejection. Owner follow-up isolated 20/20 plus one additional
rollback-recovery case passed. No remaining scoped review blocker.

Combined official isolated run on `74be9d7`: 80/80 pass, 13.089s (journal,
architecture/state, S1 grants/recovery, distill, encoding and OS diagnostic
matrix). Module reports retain the red baselines and intermediate failures.

## Hot-path performance

U18-PERFORMANCE.json contains two sequential alternating baseline/candidate
pairs, each with 20 warmups and 150 samples for six command shapes. Baseline
production source equals ef5e7d6; candidate normalization source equals 09fbb9b
and is unchanged by the final installer correction. All 24 P50/P95 comparisons
fit the existing delta budget and original S1 absolute ceilings. This measures
normalization overhead only, not installation time or Agent token savings.
An initial accidentally overlapping set of probe processes is explicitly
excluded and retained, not used to claim performance success.

## Remaining boundaries

At the code freeze full integrated regression was pending; the final record below
supersedes that pending state. No production release acceptance yet.
The U01 guarantee covers guarded generation-switch, not all earlier outer
home migration/reconciliation writes. Legacy fences without descriptor digest,
nonterminal detached transactions and corrupt facts are retained for explicit
recovery. Existing damaged-fence admission fail-open is not fixed or claimed
safe by this recovery repair. Windows and live production upgrade remain untested.
U09 inherited installer-test duplication is recorded but deliberately unchanged.
The optional AST inspection command denied by the installed receiver classifier
was abandoned, not bypassed; source repairs did not alter installed policy.

## Final integrated evidence

Official full isolated run on frozen HEAD
`122b7aff9fc5a16762793391591b6e425b8a7e43` completed successfully:
**2908 tests, zero failures/errors, 29 skipped** (2879 non-skipped),
2167.596s unittest time / 2171.414s evidence-wrapper wall time, exit 0.
Evidence is complete, not partial or reused. Source bytecode cleanup before/after
removed zero files and zero directories. Working tree remained clean.

Local evidence root: `.codex-agent/s1-evidence/` in this integration worktree.
Run: `20261004T102744.039716-00a0c315ac4b`.

| Record | Independently reread SHA-256 |
| --- | --- |
| JSON | `81332c935e3b43c08e21b95ab0ce16c4b983f72a32598abf3a8e3001a7d748b4` |
| Raw log | `8cc2b2eb46c816d5e728db75da2671ba8113658affd134c57594af4db08ed795` |
| Recorded workspace fingerprint | `0cb6dc5c3a584811b90479b471b407f33e69afd8dbbabef63f9755491291fda1` |

Skipped domains: 17 retired Git-policy tests; 5 native Windows tests; 3 explicitly
enabled CLI-contract tests; 2 explicit-baseline benchmarks; 2 nested Seatbelt
checks unavailable inside the outer sandbox. These are not claimed passed.
Separate mandatory native OS verification is recorded above. Candidate native
memory and continuity fixtures ran in the full suite; they do not authorize or
prove real production historical-effect settlement. The offline-model ERROR
lines belong to intentional injection and their test finishes `ok`.

The previous S1 full failure record remains unchanged; this new run establishes
the repaired tree's result rather than rewriting history. Three module owners
self-tested; separate reviewers checked recovery, architecture and test hygiene;
the coordinator ran the combined and full suites on the unified branch.

Scoped source/integration gates are now closed. This is not artifact promotion,
installation, live production upgrade, Windows acceptance, or closure of all
U01–U20 items. Dev/main and production runtime were not changed. No SSH, paid
model experiment, old-worktree cleanup or production debt settlement occurred.
Remaining boundaries above and S2–S4 in the unified plan remain explicit.

The final report-only commit follows the tested HEAD; no implementation, tests,
fixtures, manifest or configuration is changed in that closeout commit. Reusing
this full result is limited to that exact input equivalence.
