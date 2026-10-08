# Recovery stage release and same-session acceptance

Date: 2026-09-07. Intent completion:6cbefb0ee2086d965bbeb099, revision 4.

## Outcome and merge inventory

The completed recovery repair and its test evidence were committed, fast-forwarded
into dev, installed, and verified through the real existing Codex session.
**The installed release and the specific launcher-recovery Allow journey passed.**
This does not claim that every LIFE/doctor/background health projection is green,
that native Deny was clicked, or that Windows native recovery was verified.

- Repair: `962c6aef61b5d6172c4dfe8ee6c40cf99c806a61`.
- Persistent red/green/impact evidence: `9a62944`.
- Version/source installed: `acf53f36816d2c57e51d396559a82403a5341524`.
- Before installation, task and dev were clean and at that exact source commit.
- Earlier `guardian-recovery-closure` changes at `76fcad3` were already in dev;
  no duplicate merge was needed. No other unmerged task branch was found.
- Harmony sediment worktree has six staged knowledge files, without a located
  completion receipt. User was asked whether that batch is complete; no answer
  was available at this validation boundary, so it was preserved, not committed
  or included. Main's three existing `.ua` changes were also preserved.
- No remote push was requested or performed.

## Installation evidence

- Version: `0.2.5+codex.20260907071718-6e84c50faf`.
- Generation: `0.2.5+codex.20260907071718-6e84c50faf:bcf3ad26c2c63192fa37ecd24c6e387045d9a96f62a23576fdc16b7c2a383852`.
- Artifact: `/Users/eric/.sulde/artifacts/sulde-0.8.4-0.2.5-codex.20260907071718-6e84c50faf/codex`.
- Installed cache: `/Users/eric/.codex/plugins/cache/sulde-local/sulde/0.2.5+codex.20260907071718-6e84c50faf`.
- Candidate: `/private/tmp/sulde-recovery-stage-release/recovery-stage-r4`.
- Candidate source tree: `67d901e7fd8f6e87e12f98b44e74d95c2a4bc4cc`.
- Candidate receipt: `a9221c9c9c95c7f8428ecda3017e83e91bdcd4604c56495591a17d148f559aca`.
- Prepare 1.040 s; candidate verification 12.409 s; transaction install 28.860 s.
  Largest installer phase was snapshot/prepare, 12.598 s. Human wait excluded.
- Existing 72-test evidence was reused only after matching the exact tested source,
  test and log SHA256 recorded in `guardian-recovery-stage-repair.md`. The new
  candidate check and real host verification were additional, not another full suite.
- Official cachebuster helper changed only the manifest version. Plugin validation
  and diff checks passed. The selected existing local marketplace was `sulde-local`.
- Native release approval receipt: `14bb5d9c3342679e145bb8e05ab7694194aae9bb79bfe6696d221f6013e8821f`.
- Cachebuster grant `71e770ec18d03a8fe9ae0bcc249c1d66cd12a1061d8589455a8f57fed6724ef8`
  and install grant `90db648f4554d25f140c5d58a0ab1e919e17e8a86eb2675029937596800aa1cd`
  each consumed once; doctor returned two attempts, both `system_verified`.
- Deployment `generation_verified`, runtime owner `active`, both
  `operational_ready=true`; launcher/deployment/owner activation is
  `6afaa1dea27e45449967f59b711f9748`. Artifact and runtime generation match.
- Scheduler 16/16 loaded, no failed, missing or retired labels. Six Sulde Hooks
  unique, enabled, trusted and runnable. Existing static catalogs were preserved;
  old Hook subscriptions use the current stable bridge.

## Real current-session pre-execution proof

Session `01a04634-318f-7203-ba2d-26fa6ac442b0` was not restarted.
The actual tool submitted the prepared rm negative canary and PreToolUse denied
it before execution; finalize independently verified absence of its marker.

- Probe `b0f20520a6c779005236eaab0dd8cda4`.
- Proof `b3a17cb50b030f6c910b9793e32a2fa9e2671c3e5dedf7e25ae90d6bc5c2124f`.
- Started event `2418b90a6d202fd3f2308928`;
  call `exec-add46117-51e1-4022-a87f-dc5e9bafcdc5`.
- loaded_module_generation `30ebc8b8871c4bc43671215922d2e24be5221259c9289299a619b2cd98831f71`;
  artifact_generation is the new full generation above; gaps_cleared=0.

## Real fault -> native Allow -> repair -> verify -> continue

1. Installed model-dispatch was healthy, regular, mode 0755, SHA256
   `771c837ec0ad4278edbdcb4b1c4574e1262dd2ab3f62d3720b9f7b156ba2dd80`.
2. With the approved bounded rollback, changed only mode to 0644. Original command
   returned exit 126, permission denied (actual output chunk `e192fb`).
3. The installed production recovery CLI prepared a fresh plan bound to this
   session/workspace/generation and exact 0644 prestate (chunk `6c1771`).
4. Submitted returned exact argv and verbatim justification through the host's
   native escalation. Unlike the previous release, PreToolUse reached
   PermissionRequest. Actual Allow executed the protected repair once.
5. Executor returned `succeeded`, `independent_verification_passed`,
   `recovery_verified=true`, `original_task_authority_changed=false` (`688e6d`).
   Actual PostToolUse independently reported the recovery-journal-owned result.
6. Fresh readback verified original bytes and restored mode 0755. The same
   model-dispatch command returned exit 0 (`d59f83`). No rollback was needed.

Identifiers:

- Capability `sha256:263ca09fc578e291955c652f5270ad014fdc8dca46a74e09eaaa88426ef85e97`.
- Run `sha256:d76392503b2b4c1e8e4c7f4e89645885f1d44269371bc3bec3c60a253bdf9f1d`.
- Effect `sha256:ccacdac0c16cec11ebe1750917a788ffb373f7c4056fcd1b0a5d36e8344e0cf1`.
- Verifier receipt `sha256:24d9747ae3c6c62da059423198a25620ca40601635963e35d13b6fdaa22d2a31`.
- Snapshot descriptor SHA `cfb4e0a621e9376570907aad6af6fb6f0288c40c97eb8ab57b27abe5595710e3`;
  launcher manifest SHA `00d33cfba854c9a8dffc81081353fbb570f913aa7052a6951368aa1dd3b00838`.
- Recovery backup manifest SHA `086624bcb0770576577558719184d74b412d29375285b631e23ba2b94e3dea70`.
- Recovery journal SHA at final readback:
  `a34a04af67d82a5b34fc43eea349a353bee94141f1b6b1c441b6eefb63bfd74d`.

Strict read-only journal snapshot: two prepared plans (old failed plan retained),
one real prompt, one human decision, one capability consumption, one dispatch in
`apply` mode, one verifier observation and one success terminal. No duplicate
apply, copied task authority, debt clearing or manufactured approval was used.

## Residual observations, not hidden as green

- MCP `kb_status` actual call succeeded, reporting 381 documents but background
  status `degraded`; call success is transport evidence, not global health.
- Interactive doctor remains degraded for `host_interactive_fresh`, lacking the
  new lane/generation's SessionStart/UserPromptSubmit observation. Current real
  Hook and recovery evidence above is present; no session restart was used.
- Structural `observe_recovery_truth` still returns fixed `human_confirmation=
  unobserved`, `repair_execution=unverified`, `recovery_verified=false`, despite
  the independent journal's verified recovery. This projection does not aggregate
  terminal runs; it must not override the actual bounded run proof or be presented
  as a full capability-health verdict. Projection improvement is follow-up work.
- The maintenance CLI `promote --help` was blocked as an unsealed maintenance
  action. A subsequent native proposal failed because its base material world
  changed. The same scope was freshly bound before any grants were consumed.
  A quoted proposal retry encountered sandbox lock permissions and used normal
  escalation. No authority checks were bypassed and no tests were repeated.
- Native host reported saving exact approval prefixes despite no prefix_rule
  request. No old approval prefix was treated as new recovery authority.
- Doctor final current lane: open events 0, pending verification 0, effect debt 0,
  open interventions 0, Hook failure projection clear.

## 沉淀候选与技能影响

Verified current-session evidence now confirms that moving approval text binding
to PermissionRequest removes the prior before-prompt recovery block while
preserving exact one-shot execution and independent verification. Routing positive:
the actual pre-event reaches its native approval; routing negative: altered
PermissionRequest text remains a denial regression. Execution positive: this real
single-apply verified journey; execution negative: declaring receipt-only or
rollback-only recovery successful. Native Deny remains fixture-covered, not clicked.

Separate candidate: readiness projection and actual recovery truth diverge
(verified observation; product semantics need review). Preserve underlying facts;
derive scoped capability state instead of relabelling unobserved global state.
Private paths, identifiers and project details must be removed before KB promotion.

Intent Guardian scoped the release and rollback. Plugin-creator supplied official
validation/cachebuster and existing-marketplace routing. KB ap-0181 was read fully
and used to preserve static catalogs while verifying the current old-session Hook.
Dispatch-task rendered the exact original-command continuation probe. No direct
fact knowledge-base edits were performed.

This report's later commit changes documentation only; the installed source
identity remains acf53f3. Do not rebuild/reinstall merely to make those hashes equal.
