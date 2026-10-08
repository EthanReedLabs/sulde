# R34 — exact native Hook trust as an installation transition

capability_tier: deep

Status: bounded installation completed; see R34-HOOK-TRUST-REPORT.md final audit.
The requirements below are the unchanged frozen contract. Baseline dev/task `6bf08ea`.
Current-session revision 34 native proposal receipt:
`6cc8e2ffd88cc96372aa23dfa82b4615fc6703cea20a51027471863a0d7e5f9a`.
Proposal `ebca4ef4cebd1a4b3944b91b55407846dc2467bf5663daa36c2601d15816a56f`.
This authorizes bounded implementation, not automatic approval of arbitrary
future Hook definitions. The eventual exact production operation has its own
current-host native human approval, as required by the contract.

## Frozen outcome

Finish Codex installation while preserving the current session, old static paths,
and legitimate Hook trust. Revalidate the installed Claude 0.8.11 separately.
Do not weaken Guardian, trust unknown definitions, bypass Hook trust, terminate
live hosts, or overwrite unrelated user/managed configuration. No paid models.
Main, remote, business projects, knowledge corpus and historical ledgers stay
unchanged. Failed r33 candidate and rolled-back transaction remain immutable.

## Confirmed inputs and distinction from inference

- R33 source repair passed independent review, 31 affected tests and four actual
  CLI install/recovery cases, and was merged into dev.
- Production attempt `ed99f5b67e2648c3ad22cfabe91c6b15` failed at the aggregate
  native Hook readiness check. That check discarded its detailed projection;
  the exact failed subcondition was not archived and must remain inconclusive.
- Its rollback is independently verified against the original snapshot; old six
  Hooks are native-discovered enabled/trusted. No active install transaction.
- Candidate inventory showed six new definitions untrusted before fixture-only
  approval. New definition hashes differ from old production hashes. This proves
  a missing production trust transition, not the exact prior exception subcause.
- Global `plugin list` may query an unrelated remote catalog and time out. The
  later unmodified query/verification succeeded; do not widen this task into
  remote-catalog policy changes or weaken cross-market identity checks.

## Required implementation and bounded evidence

1. Preserve the detailed failing native Hook observation (missing, duplicate,
   modified/untrusted, discovery errors, timeout) in durable failure evidence.
   Never infer trust failure merely from the old aggregate exception.
2. Discover exact candidate definitions through the native host in isolation;
   bind six event keys, source/artifact identity, definitions and native hashes
   to a readable one-shot production card. Revalidate the discovered production
   definitions before any trust write. Drift is a refusal, not auto-approval.
3. Only after a matching native human decision, use the official configuration
   interface to change those exact Sulde trust values. Do not write config.toml
   manually, disable Hooks, alter other settings or use bypass flags.
4. Persist previous/desired values before mutation. Use native expectedVersion
   CAS and atomic batch edits. A lost reply/crash requires readback; do not assume
   success. Recovery must distinguish unchanged, owned desired and conflicting
   values, preserve unrelated concurrent edits, and retain recovery authority on
   an unprovable conflict. Never restore the whole user configuration snapshot.
5. Integrate only into an explicitly authorized typed installation transition;
   existing read-only Hook inspection must remain read-only. Existing profile
   behavior and historical claim/journal replay must stay compatible.
6. Normal controls first; then inject no approval, stale definition, config CAS
   conflict, API failure/lost response, crash before/after trust write, rollback
   conflict and successful exact trust/readback. Use actual callback paths and
   the official CLI API in isolated roots; mock only external boundaries.
7. Run affected-module tests and one consolidated independent review. Reuse r33
   evidence only for unchanged inputs. Commit/merge dev after scoped passing
   evidence; prepare a NEW candidate and native installation operation. No
   candidate reset, promotion replay or unrelated full-suite rerun.
8. Independently verify production generation, registry, stable entry/launcher,
   scheduler, MCP and same-session real Hook identities/denial. Distinguish live
   acceptance from fixture proof and static Skill refresh. Claude installation
   readback is required; missing Claude MCP/live capability must be disclosed,
   not inferred from registry presence.

## Interface evidence and stop conditions

Official docs: [Hook trust](https://learn.chatgpt.com/docs/hooks) distinguishes
installing a plugin from trusting its current definition;
[App Server](https://learn.chatgpt.com/docs/app-server) documents atomic
`config/batchWrite`. Local audited CLI 0.160.0 generated schemas at
`/private/tmp/sulde-s3c-r24.mqyXRi/r34/codex-schema/` expose `expectedVersion`,
`filePath`, `edits`, and `reloadUserConfig`. These establish the interface shape,
not that a proposed restoration/ownership algorithm already works. Read actual
config-layer version and verify CAS behavior in isolated normal/negative cases.

Evidence: local r34 directory, then append-only Optimus S3-C-repair archive.
90-minute active-work checkpoint, zero model/API cost. Do not return at each test
stage. Two unchanged failures require a diagnostic-method change. Stop for new
authority, a genuine scope expansion, an unavailable host capability or unsafe
rollback. Do not label a partially installed or untrusted state as ready.
