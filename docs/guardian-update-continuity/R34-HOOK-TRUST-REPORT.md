# R34 — exact native Hook trust transition

Status: scoped implementation/tests and independent review PASSED; merged into
dev `f533712`. Codex installation COMMITTED and same-session pre-execution proof
verified. Claude 0.8.11 installation re-read and byte-verified. This is installation
completion, not all-host interactive/Claude MCP acceptance. See final readback below.
Baseline `6bf08ea`; historical pre-install checkpoints are retained below.
Authority: [R34 task](R34-HOOK-TRUST-TASK.md), current-session revision 34.

## Change and boundary

The explicit `sulde-live-cache-handoff-v2` context extends only the approved
first-migration operation. Its old-cache continuity origin is unchanged; v1
inputs and historical journals remain readable. Preparing a context/plan creates
no authority: the held-source production command and exact six definitions must
still receive the current host's native human decision before execution.

`codex_hook_trust.py` uses short-lived official app-server configuration RPCs,
never model/thread creation, a trust-bypass flag or a direct config file edit.
The plan binds the artifact tree, canonical config path, native definition hashes,
commands, event keys, matcher/timeout/context settings and six previous hashes.
Production discovery must equal those reviewed definitions before any trust edit.
Source paths alone are normalized relative to the exact plugin root; command text
and native hashes are not rewritten. This first-migration profile requires six
existing user-layer trust hashes; it does not claim generic fresh-install trust.

The immutable install descriptor retains previous/desired values before mutation.
The hash-chained `hook_trust_write_started` stage precedes native atomic
`config/batchWrite(expectedVersion=...)`; independent config and Hook readback
precede `hook_trust_written`. A missing reply is not success. Recovery checks the
actual six values and durable write intent, compensates only the exact intended
state with a fresh CAS, and retains the transaction on conflicting/mixed values.
Unrelated settings are never restored from a file snapshot. The existing
separately approved, drained-host inverse also restores these six values; this
does not introduce a same-session postcommit live downgrade.

Detailed readiness failures are retained beside the transaction, instead of
discarded behind the aggregate exception. Native discovery evidence contains
only Sulde Hook definitions plus discovery diagnostics, not other plugin command
bodies or the full user configuration.

## Evidence available

All paths below are beneath `/private/tmp/sulde-s3c-r24.mqyXRi/r34/`. Each test
record contains before/after source identities, raw output digest, return code,
elapsed time and model-call count. No source drift or model calls in these runs.

| Run | Result and scope |
| --- | --- |
| `probe_native.py` | Official CLI user-layer version read; atomic config update succeeds; stale version rejected with `configVersionConflict`; readback correct. Isolated temp home only. |
| `trust-injections-1791454829139395000` | 48 passed, 0.90 s wall clock. Normal trust/restore, no v1 authority expansion, stale definition/prestate, CAS/API failure, lost reply, crash before/after write, conflicting rollback, malformed discovery, real native config API; legacy context and journal compatibility. |
| `trust-native-hooks-1791454927464128000` | 2 passed, 0.75 s. Official CLI installs a minimal isolated plugin; actual discovery/trust/restore and real write with injected lost reply. No fake host trust. |
| `install-native-normal-1791455168954089000` | 1 passed, 38.65 s. Actual installer + official CLI registry, discovery and configuration succeed through v2. Process/cohort/receipt/scheduler remain fixtures; not production approval evidence. |
| `install-native-negative-1791455733193915000` | 2 passed, 57.72 s. Unchanged v1 trust omission is refused and detailed failure retained; crash after v2 trust write restores old native values through actual recovery entry. |
| `trust-affected-1791455962612702000` | 88 tests, 87 passed / 1 fixture failure. Native inverse fixture used source version instead of its forward fixture version; identified and corrected in test only. Includes candidate/journal/cache/context regressions; failing log preserved. |
| `inverse-native-1791456206006477000` | 1 passed, 45.75 s. Actual separately authorized inverse restores original native trust values; frozen old marketplace and consistent fixture version. |

An early wrapper run was refused by nested sandbox setup before tests. It is not
a product failure. Two other fixture setup errors were retained (missing CLI
`--json`; reusing a method with zero-argument `super()` on a non-subclass), then
corrected without changing product acceptance. After aligning the inverse fixture
version, its next failure exposed a second fixture defect: the historical helper
used one mutable staging path as both new and old marketplace. The real native
CLI correctly installed the manifest it found there (the new version), unlike
the old fake registry. The fixture now freezes the original cached plugin into a
separate immutable old marketplace before binding the migration. Native inverse
then passed. Neither failed fixture is claimed as a new product defect.

## Independent review correction (supersedes recovery claim above)

The earlier successful cases did not establish native-write ownership. Review
found two P1 categories: CAS-rejected writes could compensate another writer's
identical values; terminal rollback replay could undo a later user re-trust, and
completion lacked the corresponding final readback. The original normal control
passed and three unchanged counterexamples failed in
`review-baseline-1791457032129968000` (exit 1). This is a candidate defect, NOT a
second production installation or rollback failure.

The candidate now requires a validated, durable native write acknowledgement
bound to the exact transaction, descriptor, request and config target. Explicit
RPC rejection is recorded separately from unknown transport outcomes. A lost
reply or crash before persisting acknowledgement leaves ownership unproven even
if the current values match; recovery retains the transaction without overwriting
those values. The earlier lost-response/crash tests expecting automatic
compensation were wrong and are explicitly superseded, not evidence of a passed
ownership guarantee. Acknowledged-write crash recovery remains supported.

Terminal rollback replay is read-only. First rollback verifies the previous
trust values both before appending the terminal stage and after independent
journal readback; drift keeps recovery active. The three original defect
assertions and the complete HookTrustTests passed in
`review-fixed-1791457693376436000` (0.516 s, no drift, zero model calls).
Additional acknowledgement-corruption and late-readback cases bind the same
requirements. Actual native/installer final rerun and follow-up review remain
pending; no production mutation has occurred in this correction.

`ownership-native-1791457959045976000` then passed all injected cases but failed
three actual native cases before RPC: patching inherited `object.__new__` in the
recovery fixture left Python's constructor slot altered on restoration. This is
a test-isolation defect, not a host API failure. The fixture now substitutes
only client initialization/call/close transport boundaries, preserving class
allocation; the failing run remains archived and requires a complete rerun.

Consolidated independent follow-up requested from `/root/r33_independent_review`.
Final affected entry rerun binds the corrected immutable-marketplace fixture;
no unrelated full-suite run is requested.

## Final scoped verification

- `ownership-native-fixed-1791458016764495000`: 44/44, 1.158 s, actual native
  API observed. Includes unchanged three P1 assertions, acknowledgement corruption,
  acknowledged versus unacknowledged crashes, late rollback readback drift, actual
  native discovery/commit/restore/CAS and lost-reply retention. Log SHA-256
  `a702749427a94ac66c1312d07bbb7a3b8e36499e1a842dad53478cad81c82a1d`.
- `release-final-1791458047529339000`: 59/59, 163.609 s, actual official CLI
  observed. Legacy typed contexts, journal, atomic handoff, candidate consumers,
  v2 successful installation, unchanged v1 missing-trust refusal/detail retention,
  confirmed-write crash/recover-only and separately authorized inverse. Log
  SHA-256 `951093de981ee8d563e689b13ad2f942ef71133a97a7622dcccf869374d46788`.
- Both runs bind before/after code and test inputs, report no drift and zero model
  calls. No full-suite rerun. Tests retain synthetic process/cohort/scheduler
  boundaries, and do not create production approval or live-host evidence.
- Independent reviewer returned `review_passed` for the same two P1 fixes after
  reading the original red and corrected green evidence. The final expanded
  evidence and transport-fixture correction were returned for the same review's
  closeout; no new unrelated review scope.
- Final closeout: `/root/r33_independent_review` independently verified both
  complete logs and digests, current production code equivalence and the transport
  replacement boundary. Result `review_passed`: dev integration and new candidate
  preparation may proceed; exact native approval/live acceptance remain required.

## Historical pre-installation status (superseded by final readback)

Production Codex still uses the independently restored Oct 5 generation. Failed
r33 candidate/transaction are untouched and must never be reset or promoted again.
A NEW candidate and exact native approval remain required after consolidated
review and dev integration. Main, remote and production trust have not changed.

Official `claude plugin list --json` was re-read this turn: `sulde-cc@sulde`
0.8.11, enabled, user scope, same installed path. This is installation/registry
evidence, not proof of a new-generation live Claude Hook or MCP connection.
The r32 source/artifact/installed equality record remains available; its missing
Claude MCP declaration/live capability is not silently promoted to ready.

Fresh readback `claude-readback-1791458198926322000.json` confirms the installed
0.8.11 tree and frozen source remain exactly the expected 851 files. The release
artifact now has 87 extra `__pycache__/*.pyc` files; none of its original files is
missing or changed. Thus the historical three-full-tree equality is no longer
current evidence. The installed tree itself has no extra files. No cache files
were deleted/moved, no Claude reinstall or new capability claimed. The bytecode
writer is not attributed from filenames alone; record this separate hygiene
finding rather than broadening this Codex trust repair.

## Sedimentation candidate

Verified at isolated native boundary: installation and definition trust are
different transitions. Route apply: plugin definition changes while old trusted
hashes remain. Route skip: same exact trusted definitions, no identity drift.
Execution pass: native human-bound exact definition review, atomic versioned
per-key update, independent host readback and bounded compensation. Execution
fail: fixture trust used as production authority, whole-config rollback, or an
aggregate readiness error with no retained failed subcondition. Production
acceptance was pending at that checkpoint; the exact installation result follows.
No knowledge corpus or memory graph write performed.

## Final production installation and independent readback — 2026-10-08

Source commit `f5337126ef7476b6023cba6268a872137095802c`, tree
`41e715846795c9e0b3e7ee87ad37005cbaf11818`, was committed on the task branch and
fast-forward merged into dev after scoped independent review. The final report
changes are docs-only; they do not require another installation or test-suite run.

The NEW candidate `r34-final`, receipt
`a669b5125b4822c71beca03ac0fa4a28d352ac6454d9f167f4f41c57d1c3c8e6`, was promoted
once through the exact held-source command and current-host native approval.
Transaction `109d6a2bc71c436faff302c5df481137`, descriptor
`6e266027230831fffd8ec5a2d51618cf602820f04d34315faaa25b44819c05f5`, reached
`hook_trust_written`, `scheduler_reconciled`, `postconditions_verified`, and
`committed`. It contains NO rollback stages; there is no active install transaction.
The failed R33 candidate and its rolled-back journal were not reset or reused.

- Codex version: `0.2.5+codex.20261007132614-423ac8f6e0`.
- Runtime tree: `c1856020660c0e4a4b2a9dcd09b2ea84c2cf217939b0e3efb3067a3e8f6aaaa3`.
- Generation is the version plus `:` plus that runtime tree hash.
- Candidate, persistent artifact and installed plugin tree match
  `c5ba726182af86ca1cfccb79c95a15f38a7e53f233a6cce9da4f85029b70c4f2`.
- Official Sulde-local registry: installed/enabled, exact version and local source.
  Deployment, launcher, stable entry, runtime owner and native executable authority
  independently match the committed descriptor. Retained old outputs verify.
- Native inventory: six required Hooks, unique/enabled/trusted; no discovery,
  missing, duplicate or unrunnable errors. The trust acknowledgement is bound to
  the same transaction and descriptor; no whole-configuration restore was used.
- Scheduler: actual launchctl readback, 16/16 loaded, no missing, retired-loaded
  or failed labels. Runtime owner active, deployment `generation_verified`.
- MCP: official `mcp get sulde_kb --json` resolves the new installed launcher;
  a fresh process from that path completed initialize as `sulde-kb`. Actual
  current-session `kb_status` RPC also succeeded, but its cached background health
  snapshot is NOT used to prove new-process identity or global interactive health.

### Same-session live proof

The officially prepared exact negative canary was refused by the actual host's
PreToolUse before command execution. Finalize at 11:35:47 UTC produced proof
`c0262a6f9e966b8f402ea5cc63d909fec774ea94910d59125ab9821d0a42de78`, probe
`9e18e5f461247be2fe1bf76820465727`, event `17fb67df87d3f8133c7588e2`, call
`exec-7cce3e15-9726-4bc8-9e30-45e5186c3e8b`, session
`01a04634-318f-7203-ba2d-26fa6ac442b0`.

The denial and proof bind loaded module
`df25fe7b0b7558218e27e9d8ceb76d0d2d59f0bebb0aae44da8f79c6ab4ff75e` and the
artifact generation above. These are different identity domains, not hashes that
must equal each other. No retry/bypass of the denied command was attempted.
Current lane readback: no open events, pending verifications, pre-execution gaps,
integrity breaches or blocking effects; native decision pairing settled.

### Claude and remaining capability boundaries

Fresh official registry plus content readback confirms Claude `sulde-cc@sulde`
0.8.11, user scope, enabled. Its installed tree and frozen source are exactly the
expected 851 files. The fresh release-artifact readback now has 88 extra bytecode
files (previous checkpoint 87); all original bytes are unchanged and the installed
tree has ZERO extras. The writer remains unattributed; no files were deleted.
Do not reuse the old three-full-tree equality assertion.

Claude live Hook/MCP capability remains unverified: the package has no `.mcp.json`
and the checked user-level configuration has no `sulde_kb`. R34 explicitly requires
this disclosure, not a new Claude feature installation. Codex's static Skill catalog
still follows normal new-session discovery. No hosts were stopped or restarted.
After the approval wait, doctor reports interactive freshness degradation (no fresh
prompt observation and expired activity observations); this is not a reverted
installation or a failed durable pre-execution proof. No overall interactive-ready
claim is made.

### Final readback evidence and method correction

Under the r34 evidence root:

- `codex-installed-readback-1791462653947204000.json`, SHA-256
  `bfc2447c84a00b526a8c24f2529ca12b6812423b8c587c80ed4c5adadf688bf7`:
  independently verified exact committed installation, stable entry/launcher,
  native authority, real scheduler/MCP, retained outputs and same-session proof.
- `claude-readback-1791459469938196000.json`: current 851-file installed/source
  verification and the explicit 88-extra-bytecode artifact diagnostic.
- `current-session-mcp-status.json`: actual RPC result; background snapshot scope.

The first readback attempt's native app-server process ended under the restricted
sandbox. Escalated readback then hit the existing all-market `plugin list` remote
refresh timeout twice; both failure receipts and the original v1 script are retained.
After two identical timeouts, the method changed to an independent explicit local
installation audit: official `--marketplace sulde-local --json`, exact bound trees,
native Hook/config readback, actual scheduler, sealed authority and MCP. No fake
CLI response, configuration override or product verifier edit was introduced.
The all-market refresh is NOT claimed to have passed; the successful installer
postcondition journal remains its original evidence. No third identical retry,
new installation, full regression or model call was made during this closeout.

### Completion audit against the frozen R34 task

| Requirement | Evidence and conclusion |
| --- | --- |
| 1: detailed failed Hook observation | Permanent unchanged-v1 failure case retains real native diagnostics; final 59-test log. |
| 2–3: exact definitions and native authorized write | Frozen production plan/held command, six definition hashes, exact descriptor, write acknowledgement and native readback. |
| 4: owned CAS/recovery, unrelated settings preserved | Three baseline red counterexamples, durable-ack/corruption/late-drift tests, actual native API and install recovery/inverse cases; independent review passed. No production rollback required. |
| 5: typed transition and compatibility | v2 only; unchanged v1/legacy journal/atomic/candidate affected tests passed; no ordinary auto-trust. |
| 6–7: scoped verification/review/merge/new promotion | 44/44 plus 59/59 with no input drift, consolidated independent pass, dev f533712, new candidate consumed once. |
| 8: real installed identities, scheduler, MCP, current denial, Claude readback | Final readback receipts and dual-identity live proof above; missing Claude live/MCP and interactive freshness explicitly separated. |

Main remains `f932ca8`; remote was not pushed. No production history, knowledge
corpus or business project was edited. Optional hygiene, all-market timeout and
unverified Claude capabilities remain separate follow-ups, not hidden successes.

Durable completion evidence archive (73 files independently hash-verified):
`/Volumes/Optimus/Sulde/tasks/guardian-unified-plan-20261004/S3-C-repair/r34-1791462851329190000/`.
Manifest SHA-256 `362824705d0fb5f3fa346d7729ad43f337a95b640773a816f3a1c7b6b6ceae32`.
This includes exact committed descriptor/journal and native acknowledgement facts,
readback successes/failures, candidate state, source and report snapshots. It does
not contain the full user configuration or copied production knowledge/memory.
Later docs-only commit/archive does not invalidate the installed code evidence.

Temporary-resource release is performed only after this report is committed and
merged, with a clean source tree and no active Skill/event/effect debt. The
Guardian completion receipt, not this pre-release sentence, proves Git cleanup.
