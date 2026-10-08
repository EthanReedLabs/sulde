# R33 current-session installation — candidate evidence

Historical checkpoint: R33's rollback below remains valid. Current installation
status is superseded by R34-HOOK-TRUST-REPORT.md: a NEW transaction committed and
the same-session live pre-execution proof was verified. Do not treat the following
old-generation readback as the current installed version.

Status: source repair independently reviewed and merged into dev `6bf08ea`;
production promotion attempted, failed at native Hook readiness, and independently
verified rolled back. Codex is NOT newly installed. Claude remains 0.8.11.
Baseline: `09c934438a2eb7d81e6464f1473644cac4ffc412`.
Authority and stop conditions: [frozen task](R33-LIVE-INSTALL-TASK.md).

## Design and authority

`sulde-live-cache-handoff-v1` is distinct from the existing maintenance-window
schema. The retained host owns the exact approved worker; other sessions need
not be described as exited. Source catalog, candidate receipt, artifact bytes,
prestate CAS, canonical installation roots, bounded deadline and one-use claim
remain mandatory. A local filesystem exchange probe precedes promotion
consumption. No Guardian policy changes, automatic human decision or signals.

Forward transaction seals a rollback snapshot, prepares normalized retired trees
and protected bridge files, publishes the stable entry, atomically exchanges old
real cache directories for aliases, verifies those aliases, then uses the
official marketplace remove/add and plugin add commands. It does **not** call
plugin remove, which can delete the whole plugin cache.

Precommit/crash recovery retains the failed new candidate as a verified alias
outside real-directory enumeration; atomically restores original old directories
and prior aliases; restores the old marketplace through the official CLI; and
independently verifies old registry, original snapshot and journal before cleanup.
No hand editing of Codex registry/configuration is used. Unsupported exchange,
unknown cache bytes or identity drift retain recovery evidence rather than use
an unlink/copy fallback. Displaced directories are retained outside enumeration
for forensics, not automatically garbage collected by this change.

Postcommit inverse migration remains its separately authorized maintenance
workflow; this report does not claim a same-session live downgrade implementation.

## Why the isolated CLI probes mattered

Evidence root: `/private/tmp/sulde-s3c-r24.mqyXRi/r33` (archive pending).

| Probe | Observation and consequence |
| --- | --- |
| `cli-cache-hgxkenuk` / `cli-cache-nd78pf7b` | Removing only marketplace or keeping the same source does not preserve old real cache directories on plugin add. |
| `cli-cache-ghwcjees` | Old external-target aliases survive official update; tiny polling sample is discovery, not complete continuity proof. |
| `cli-cache-qipgsp0c` / `cli-cache-1rk10lhh` | 1,500-file stress probe catches missing old paths during rollback plugin add, even after restoring the old directory. This invalidated the first rollback approach before production use. |
| `cli-cache-u9u6qh7x` | Market-only restore preserves paths but still reports the new real cache version: path survival alone is insufficient. |
| `cli-cache-9ndmmkvy` | Retain new version as alias, restore old directory, restore market only: official registry returns old 1.0.0, all 43,151 sampled old-path reads succeed. |

Atomic exchange uses `renamex_np(RENAME_SWAP)` on macOS or
`renameat2(RENAME_EXCHANGE)` on Linux. No unsupported-platform fallback.
Polling supplements this atomic-operation guarantee; a finite sample is not
proof against arbitrary uncoordinated external mutation.

## Layered verification

1. Atomic exchange, injected failure, owned-host/no-drain identity, immutable
   claims, failed-candidate identity, journal restore and idempotence: scoped
   tests passed. Final consolidated log is recorded by the regression runner.
2. Real installer + official Codex CLI 0.160.0 registry in isolated roots:
   **4/4 passed**, 135.676 s, no input drift, zero model calls. Cases are successful
   installation with live host, crash after alias exchange before record/prune,
   crash after registry addition and recovery, and failed trust with a prior
   controlled alias. Concurrent reads of the old manifest remain byte-identical.
   Evidence: `live-final-1791439739493205000/evidence.json` and `output.log`;
   log SHA-256 `d4ba582d0d819ac3c3962c2b52ddcc82dc1906bd36fa06fd741c1ea270385242`.
3. Earlier affected installer/maintenance/memory/migration batch: 87 tests,
   passed with 2 platform skips (`regression-installer-1791439801608218000`).
   Candidate/atomic/journal/recovery batch: 49 passed via the official isolated
   runner (`candidate-isolated-1791440220542449000`). These bind the earlier
   r33 inputs, not the subsequent retention fix. The final retention-fix batch
   runs the affected atomic/journal/recovery consumers: 31 passed in 115.496 s,
   no input drift (`missing-target-fixed-1791449826875427000`). No full
   3,003-test rerun; the unchanged default-profile regression is prior evidence,
   not a claim that all earlier batches tested the final source.
4. Independent consolidated review found one P1: rollback must retain published
   targets held by resolved-path/directory-fd readers. Sealed output identities
   now preserve only exact retirement targets/records, not arbitrary outputs.
   Follow-up found missing published targets incorrectly inherited the original
   snapshot's `missing` success rule. Restore and verification now check targets
   unconditionally after the durable publication boundary. Records may remain
   absent after an exchange-before-record crash. The same two permanent tests
   were one red/one green before the fix, then both green:
   `missing-target-baseline-1791449208379361000` and the final 31-test batch.
   Reviewer `/root/r33_independent_review` returned `review_passed` after
   read-only recheck of this same P1; no additional ad-hoc destructive probes.
   Production installation and same-session live Hook acceptance remain pending.
5. Final exact-source official CLI rerun after both retention fixes: 4/4 passed,
   129.168 s wall clock, no input drift, actual executable observed, zero model
   calls (`final-official-cli-1791449955399459000`). Log SHA-256
   `f47cc0ee6388e764934787705874cc5f41153f5e0a8261a1b417f093db4de174`.

Layer 2 still uses synthetic scheduler, process observations, host trust and
candidate receipt. It is not a real production Hook/approval/scheduler proof.
Claude 0.8.11 installation and its separately pending live acceptance are unchanged.

## Process corrections preserved

- First atomic snapshot fixture used macOS `/var` aliases; canonical-root guard
  correctly rejected it. Fixture paths were canonicalized; guard not weakened.
- Initial candidate recovery compared release file digest with warm-tree digest
  (different domains). Both fake and real registry chains caught it. Recovery
  now verifies each digest in its own domain; a permanent test asserts the
  distinction and rejects later retained-target drift.
- Early probe sampling missed a rollback gap; bulk uninterrupted reading exposed
  it. No production rollback or installation was attempted with that design.
- One direct unittest batch inherited production environment and failed before
  the intended candidate CAS assertion; the same test passed under the official
  isolated runner. The original 80-test/one-failure log remains retained.
- The isolated runner filters `SULDE_*` variables. A first retention run used
  the fake CLI and overlapped a test-adapter edit; it is explicitly not final
  exact-source/real-CLI evidence (`retained-final-1791440929928798000`). The
  explicit test-only CLI variable plus observed-executable assertion corrected
  this; later real runs retain both the path and the actual output marker.
- Reviewer's temporary destructive injection was denied, pausing this lane.
  The current-session native resume receipt
  `87e68b8f291d145874a07e330c8dfa67f862179fc81bc9490f1e34b93535f8cf`
  restored revision 33 without enlarging its authority. The final missing-target
  regression constructs the state without deleting any existing directory.
- Knowledge recall ap-0181 helped separate static Skill bytes from live Hook
  routing. Its older restore-after-prune sequence is not sufficient evidence of
  uninterrupted reads; the actual CLI stress probes determined this protocol.

## Sedimentation candidates (not written to the knowledge corpus)

Verified: snapshot restoration and continuous-reader restoration are different
contracts. Route apply: a hot-upgrade reader may retain a resolved target or fd;
route skip: no concurrent/pinned reader and only final-state restoration required.
Execution pass: preserve sealed published targets and reject their disappearance;
execution fail: treat every originally absent output as rollback garbage, or
accept its disappearance after publication. Evidence is the paired permanent
tests and the independent P1 review. No general deletion exemption is introduced.

## Remaining release steps

The earlier remaining-steps list has been superseded by the actual attempt below.
Source commit/merge, candidate verification and a native-approved install attempt
are complete; installed new-generation/live acceptance is not.

## Actual production attempt and independent recovery readback

- Source `6bf08ea032571b22912187839db3503e74c5fd8f`, tree
  `cc84e7070f7d4069421f103968d081acca7ae2b7`; candidate `r33-final` receipt
  `89ad1a387468c45ba1d3503f17f0da7265aacc1e061efb49100690065183bb35`.
  Release-only fixes are not part of the Codex runtime staging inventory; the
  runtime/artifact digests consequently match r30. The native worker separately
  seals the complete NEW release-source catalog. No stale candidate was reused.
- Candidate's first verification stopped before mutation because unfiltered
  official `plugin list` spent >30 seconds fetching a remote catalog. Independent
  native output showed remote HTTP 500; local-market query returned promptly.
  After the global native query returned successfully, the same still-prepared,
  unconsumed candidate verified in 19.696 seconds. No state reset or gate change.
- Current-host plan `production-plan-1791450874701127000` binds actual owning
  app-server PID/start/executable, operation `ed99f5b67e2648c3ad22cfabe91c6b15`,
  source bundle `f39b0cdc9f51eddd34a94bd6943415e748fed9926c832f24cbc482759931deec`.
  The exact held-source command was submitted through current native escalation.
  No process drain, host signal, hidden trust write or bypass option was used.
- Installer reached registry and launcher publication, then
  `_smoke_promoted_candidate` rejected: `promoted candidate Hooks are not live,
  unique, and trusted`. That exception discards the detailed projection, so this
  observation alone cannot distinguish untrusted definitions from discovery or
  timeout failures. Do not label an inferred subcause as proven.
- Journal stages ended `rollback_started` → `rolled_back`; independent
  `verify_rollback.py` strictly replayed the descriptor/journal and verified the
  original snapshot, mandatory retained outputs and missing active transaction.
  Production is the original `...20261005134315-d918c7a2ed:6eb2a11f...`.
  `rollback-readback.json` preserves the result. Candidate remains
  `promotion_failed`, `promotion_consumed=true`; never reset or replay it.
- Native read-only Hook inventory after recovery: six unique Sulde Hooks,
  enabled/trusted, zero discovery errors, 0.124 seconds. Evidence:
  `native-hooks-1791451113812514000.json`. This proves old-host readiness, NOT
  new-generation trust. The candidate receipt reports new definitions as
  untrusted before its isolated canary grants fixture-only trust. Its six hashes
  differ from the old production trusted hashes.
- The missing production trust decision/transition was already recognized in
  M2-DESIGN; isolated fixture trust cannot substitute for it. Next scope must
  explicitly retain detailed discovery facts, bind any human trust approval to
  exact candidate definitions, use official host interfaces and rollback owned
  trust changes without touching foreign entries. No automatic trust weakening.

Evidence archive before production: Optimus `r33-1791450307436189000`,
34 files independently verified, manifest
`8ad1a11365b5aa9226abb086025eeb525ffa84a748ddaf59786add441a114bed`.
Post-attempt archive is appended separately; no old evidence is overwritten.
