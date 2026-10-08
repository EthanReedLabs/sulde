# R33 — current-session first migration

capability_tier: deep

Baseline: dev/task `09c934438a2eb7d81e6464f1473644cac4ffc412`.
Authority: current-session human proposal r33, receipt
`1523d3e79ef39edd4b35f34d589e352caef1ea8d4f3045d2c5be29fdf0c30abf`.

## Frozen outcome and boundaries

Install the accepted new Codex release without terminating this current host.
Do not modify Guardian authorization policy or fabricate session drain. Preserve
every old static tree and a callable Hook route throughout registry update and
rollback. Claude 0.8.11, main, remote, knowledge corpus and production history
remain unchanged. Work only in this existing task worktree, based on current dev.

Scope: release cache-path handoff, installer/candidate/maintenance/recovery
consumers, associated tests and this report. Independent review precedes dev
integration and final candidate preparation. Installation requires its own exact
native approval. Do not reuse a candidate whose source identity changed.

## Evidence-guided design

Real isolated Codex CLI 0.160.0 (no model calls) established:
- A new same-name marketplace source must replace the old source via official CLI.
- Re-add/update prunes old real version directories even without plugin remove.
- Old version symlinks to a retained tree outside cache enumeration survive
  marketplace remove/add, plugin add, and plugin list; old marker remains readable.

Therefore the candidate design uses an OS atomic directory-entry exchange to
publish a protected retained-tree alias before any pruning command. Do not use
unlink/rmtree followed by symlink as a substitute. A new explicit handoff profile
must seal exact source/artifact/prestate and prove aliases before registry writes;
it is not a renamed process-drain claim. For this profile official registry
updates must not remove the whole plugin cache. Restore original directory/link
identities atomically on rollback. Unsupported atomic exchange fails before
production mutation; Windows remains separately unsupported, not silently passed.

## Continuous acceptance

1. Valid normal controls, then injected exchange/alias/registry/rollback failures:
   same old/candidate assertions, distinguish fixture errors from old defects.
2. Real official CLI isolated entry plus concurrent old-path reads, source and
   static bytes, recovery idempotence and cache identity drift negatives.
3. Affected installer/journal/maintenance/candidate suites; widen only for actual
   impact. Existing full release evidence is reused only for unchanged inputs.
4. One consolidated independent review, commit/integrate, exact candidate verify,
   then actual native-approved install and live same-session positive/negative
   Hook evidence. Do not claim complete from mocks, receipts or counts alone.

Evidence: `/private/tmp/sulde-s3c-r24.mqyXRi/r33`, then Optimus S3-C-repair.
120-minute execution checkpoint; no per-test handoff, model/API cost or new host.
Stop on missing authority, unsafe path continuity, an external prerequisite, or
scope expansion. Two unchanged failures require a new diagnostic method, not
another identical run. Retain all failures and exact input identities.
