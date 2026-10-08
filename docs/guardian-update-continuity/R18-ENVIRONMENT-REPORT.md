# r18 isolated macOS environment checkpoint

Date: 2026-10-07. Status: incomplete; legacy scheduler installation blocked.
Source HEAD: `7e854770839edcb5217c1c752bfde208ee07e513`.
This supersedes r17's environment-not-created status, not its safety requirements.

## Authorized outcome and boundaries

The current-session revision 18 authorizes creation of the exact standard test
account `suldeverify`, its home and user bootstrap domain, isolated installation
and the complete maintenance entry. Actual CLI/install processes must run as the
ordinary test UID. Administrator use is limited to account/environment setup,
ownership and launching exact privilege-dropping scripts. No production install,
existing user-host shutdown, main change, push, cachebuster change, VM download,
paid model calls or account deletion is authorized. Evidence and failed state
must remain available.

Environment preparation is bounded to 40 active minutes and the full task to 150
active minutes, excluding human authentication/decision waits. No reliable
continuous active-time counter was retained across interruptions; do not report
wall-clock time as measured active time or claim a precise remaining budget.

## Verified environment scope

- Standard account UID 502, primary GID 20; no admin group membership.
- GeneratedUID: `025B11A2-1162-4B20-AA0D-B025D2CC32F9`.
- Home `/Users/suldeverify`, owner 502, mode 0700. Interactive authentication is
  disabled, verified using `pwpolicy -authentication-allowed`, not inferred from
  a legacy AuthenticationAuthority marker.
- A real child process reported UID/EUID 502, correct HOME and launchctl
  manageruid 502; its actual same-UID Codex cohort was empty.
- Codex CLI 0.160.0 and a copied Python 3.10.7 venv with PyYAML 6.0.3 were checked.
  The Python base remains `/Users/eric/.pyenv/versions/3.10.7` and system/shared
  libraries; this is user/process isolation, not a self-contained VM.
- Source exports exactly matched the original tracked Git trees: candidate
  `e5d5da0d9d5cfa0e5f65525709b76cbe8780b5be`, historical source
  `28a23b3273eccffaa737675c9163f317438342f1`.
  Tracked repository content was copied; live production knowledge/memory,
  credentials and approval state were not copied. PyYAML alone was copied from
  the existing environment's dependency package.

Environment evidence remains at `/Users/suldeverify/s3c-environment-result.json`
and `/Users/suldeverify/s3c-r18/toolchain-result-resume.json`. The initial incomplete
toolchain result is retained alongside its successor. The source export manifest
is under `.codex-agent/s3c-user-environment/20261007T055037.940343Z/inputs.json`.

## Actual install outcomes — neither is candidate acceptance

1. Historical installation using a custom test data root failed in 4.696 seconds.
   The smoke subprocess discarded SULDE_HOME and resolved the wrong launcher root.
   The installer reported rollback. No historical code was patched to pass.
2. A new attempt used the test user's canonical `~/.sulde` layout. It passed the
   earlier boundary, then failed in 22.857 seconds loading quiescent scheduler
   definitions. The installer reported rollback. Readback found neither an active
   transaction nor deployment-generation.json in the canonical KB root.

Logs and phase records are retained separately in
`/Users/suldeverify/s3c-r18/entry-preparation/` and
`/Users/suldeverify/s3c-r18/entry-preparation-canonical/`, each with a hash manifest.
Missing active/deployment files alone are not proof of exhaustive rollback or
absence of every residual service/file. Do not delete the retained environment.

No third installation was started. Candidate prepare/verify, maintenance draft,
interactive worker approval, migration and release-level validation remain pending.

## Diagnosis boundary

The historical scheduler calls `launchctl load` without an explicit session type.
The local launchctl manual distinguishes a user domain (can exist without login)
from a GUI/login domain and documents Aqua as the default legacy load session.
Therefore UID/manageruid success is not sufficient proof that this scheduler can
run in a login-disabled account. The manual is a diagnostic lead, not proof of
the particular failure's complete cause.

The current coordinator's sandbox denied user/502 inspection and returned an
unsupported-action error for gui/502. These initial sandboxed results alone did
not establish the domain's actual state. The completed administrator-mediated
diagnostic now records separate exit codes/stdout/stderr: root and the actual
UID-502 child both see user/502 successfully and gui/502 returns exit 125
(`Domain does not support specified action`). The child reports manageruid 502
and managername Background. Its actual launchctl list contains no com.sulde
labels. This establishes the absence of a usable GUI domain in these probes and
that the test user is executing in the Background domain; it does not establish
that changing this one condition alone guarantees installation success.
The installer retained only the tail of scheduler stderr, so the exact initial
launchctl load diagnostic is not established by the error summary alone.

Do not make this fixture pass by mocking launchctl, skipping scheduler validation,
running the installer as root, modifying old source, copying receipts, or borrowing
the active user's domain. Enabling GUI login/new platform provisioning requires
an explicit scope decision if confirmed necessary.

## Classification and follow-up

- Setup helper errors (home initially absent, obsolete disabled-user marker
  assumption, ignored tracked files during snapshot Git initialization) were
  fixture defects; corrected without weakening identity/tree checks.
- Historical custom-root smoke failure is a reproduced setup/old-source
  compatibility limitation, not a new candidate regression.
- Scheduler load failure is reproduced. Background-domain/legacy-Aqua mismatch
  is supported by source, local manual and independent domain probes; the exact
  original load diagnostic and sufficiency of a GUI-session remedy remain
  unverified. Do not claim a fully proven single root cause.
- No new candidate product defect or completed migration is claimed.
- Production, dev and main have not been changed by this environment work. The
  task worktree contains new bounded setup helpers and this checkpoint only.
- Account/home and failed installation artifacts are intentionally retained;
  cleanup requires a separate explicit decision. IDs here are observations, not
  future permission to stop processes or delete resources.

No full-suite rerun is justified while this prerequisite is unresolved. Continue
only after an explicitly approved supported environment exists, then resume
complete-entry acceptance, frozen release tests and consolidated review. Enabling
test-account GUI login is not included in the current login-disabled setup.

## Final diagnostic archive and process correction

Archive (12 files, independent local/archive hash readback passed):
`/Volumes/Optimus/Sulde/tasks/guardian-unified-plan-20261004/S3-C-repair/r18-environment-20261007T090318.911165Z/`.
Manifest SHA256:
`9fd9552fb1955b5d7a12cf74843c801c52e4d96ea8a0573b01504785a7e8df54`.
The manifest excludes itself. The private handoff directory remains
`/private/tmp/sulde-s3c-r18-environment-20261007T090318.911165Z/`.
Executed diagnostic helper SHA256:
`7d9e69172c786e1b45150cdbc29bc1c783de2f09682e19273e44c0f47ae121e3`.

The initial diagnostic helper collected facts but failed to create its external
archive with EPERM. Administrator privilege did not provide that process with
external-volume access. No privacy settings were changed: the corrected helper
hands off allowlisted files locally, and the approved ordinary-user copy writes
Optimus. Both helpers' source versions/failure context remain in this report;
no successful first-archive claim is made. Exact OS privacy attribution beyond
the observed EPERM is not independently verified.

The user's repeated-authentication concern is justified. Splitting provisioning,
inspection and evidence handling into numerous administrator invocations created
unnecessary interactive overhead. Later work should:

1. Freeze a complete, bounded privileged-operation bundle before prompting;
   use administrator privileges only for the steps that actually require them.
2. Keep execution and archiving under their intended ordinary user; preflight
   the real scheduler domain, supported interpreter and destination access first.
3. Reuse unchanged input-bound evidence. Run only newly affected checks during
   repair, then one frozen integration/release gate; do not use full regression
   to diagnose a missing operating-system prerequisite.
4. Record failures before attempting archival so an archive error cannot hide
   already collected diagnostic facts. Do not make a broad persistent root broker
   or suppress native authentication to reduce prompts.

These are task-process corrections, not changes to production Guardian policy
or a claim that future macOS authentication can be eliminated. Structural checks
on the five helper scripts and diff hygiene passed; no new product tests or
installation ran during the final read-only diagnostic continuation.
