# Installation dependency recovery (r5)

capability_tier: deep

Approved scope: repair missing dependency from reviewed archived bytes, check
exact binding prerequisites, review, integrate dev, then separately seal the
installation. Baseline `c5e4864`; task branch/worktree unchanged. No main/push,
remote actions, production debt edits, model calls or arbitrary helper discovery.

## Decision and bounded impact

The old host-owned fixed path is absent. Three scripts remain in the isolated
20260927T112231Z-c33d3a774617 candidate. They have been read and their exact hashes
are frozen in `restore_dependency.py`. This is a human-approved recovery of a
reviewed local archive, **not an attestation of upstream freshness/authenticity**.
No source is downloaded or disguised as an official current release.

The official packaging documentation describes Plugin Creator and manual
packaging, but does not establish availability of this exact legacy helper:
https://developers.openai.com/plugins/build/plugins
Plugin-directory discovery returned no matching helper this turn.

Keep existing path/argv/hash/once-only grant rules. Add read-only preflight for
the cachebuster's known local import, not a new authorization route. Restore only
the three absent scripts, reject conflicts/symlinks, verify pins before writes,
exclusive-create and read back. Same bytes are idempotent; partial crash writes
remain conflicts requiring review, never automatically overwritten. The recovery
script is scoped task tooling on this POSIX host, not a cross-platform deployment
framework. Fixed-path coupling remains; this repair restores its prerequisite.

Continuous sequence: normal/injection -> real helper entries -> affected
regression -> independent review -> restore -> dev integration -> exact native
installation card -> candidate isolation -> dual-host installation/readback.
Two failures without new facts change diagnostic method. Stop for mismatched
identities/bytes, missing authority or unavailable host prerequisites. No repeated
full-suite runs for this two-runtime-file preflight change.

## Evidence

`Optimus/Sulde/tasks/guardian-effect-recovery-20261004/dependency/20261004T042142.802989Z.json`
SHA-256 `548f3b827a5ef6f2514e6e6eda608c29be36b9ad89a760ef6c207c2fb3aed246`.
Contains exact source/test/tool hashes, raw outputs, commands and results:

- Old binder: 5 tests, 2 normal/negative controls pass, 3 expected failures.
  Two demonstrate missing/broken companion accepted into a seal; the third is
  missing actionable diagnostics, not absence of old fail-closed behavior.
- Candidate: 312 tests, 295 pass, 17 existing skips, 27.600s.
- Real recovered helper on isolated dummy plugin: exit 0, exact expected version.
- Recovered validator against currently installed plugin: exit 0.
- First fixture run used macOS temporary aliases; strict symlink check correctly
  rejected them. Fixture canonicalization fixed 2 failures/1 error; no product
  protection weakened. Those initial results are session evidence only.

Not established: current upstream version, Windows recovery, removal of all
fixed-path coupling, all imported dependency bytes sealed transitively, production
installation or historical effect recovery. AST preflight is availability/syntax
diagnosis, not code authenticity or proof of every possible runtime import.

Independent read-only review passed: all five tested file hashes and three archive
pins independently matched; no bounded blocking findings. Actual recovery then
completed via native-approved invocation, with all three destination hashes
matching the pins. No other skill files were restored and no installed Sulde
runtime changed. Production installation still needs its separate sealed card.
