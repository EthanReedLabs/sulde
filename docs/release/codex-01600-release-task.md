# Codex 0.160.0 local release

Base dev: b04b6d9aec003bc9765e6f1374e724c87b029546. Capability tier: deep.
Task branch/worktree: task/codex-01600-release-20261003.
Date: 2026-10-03. Current provider: Codex. No model calls.

## Outcome and staged authority

Publish the independently reviewed 0.160.0 compatibility repair locally, without
changing runtime logic or weakening Guardian. Revision 2 native receipt
`b87182bb0c5ff19606548c24024b457be40ea9fa9a31d00121f0dfda1f99c9d4`
authorizes only the exact source manifest version change and release documentation,
commit and local dev integration. Installation requires a separate fresh sealed
install-only proposal after this source is committed. No old grant is reused.

The helper at `~/.codex/skills/.system/plugin-creator/scripts/update_plugin_cachebuster.py`
is absent. Official [packaging guidance](https://developers.openai.com/plugins/build/plugins)
supports author-maintained manifests; it does not require that private script path.
Actual CLI 0.160.0 exposes `plugin add/list/marketplace/remove` as its normal plugin
interface. The repository transactional installer remains the only promotion path.
This bounded manually approved source edit does not restore or impersonate the
helper, modify installed caches, or remove exact maintenance-entry checks.

## Frozen verification

1. Only JSON version changes to `0.2.5+codex.20261003135300-b04b6d9`; all other
   source manifest values and scripts/tests are byte-equivalent to reviewed dev.
2. Structural manifest check and diff check; reuse scoped reviewed tests with
   explicit input identity proof. No automatic full regression.
3. Once newly authorized: prepare isolated candidate -> verify -> exact promotion.
   Recheck CLI effective version, wrapper/native-payload identities; preserve old
   generation/transaction rollback snapshots. Never promote a failed candidate.
4. Read back installed generation, independent install verifier, scheduler and
   current-session real PreTool denial with both generation identities. Preserve
   unverified or degraded domains rather than claim complete global health.
5. Record exact evidence and install outcome; integrate only passing release
   records into dev. No main merge, remote push, Claude installation, historical
   debt recovery or real-Agent model run. Evidence destination after authorization:
   `/Volumes/Optimus/Sulde/tasks/codex-01600-release-20261003/`.

Continue within authorized stages without per-test handoffs. Stop for denied or
missing authority, identity drift, unsafe promotion, or absent external prerequisite.
After two same failures without new evidence change diagnostic method, not tests.
Model budget zero; no unrelated control-plane redesign. If promotion fails, use
the transaction's recovery; do not hand-edit production to imitate success.

The durable replacement of the missing-helper dependency is a separate product
decision. This release uses explicit human source-edit authority plus the existing
sealed installation profile, not a general autonomous substitute for that helper.
