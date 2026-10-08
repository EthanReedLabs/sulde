# Guardian memory consistency — local release

Date: 2026-09-10
Status: LOCAL INSTALL VERIFIED / LIVE HOOK AND SCHEDULER READY / BACKGROUND WARNING RETAINED
capability_tier: deep

## Scope and authority

Revision 8 was approved through this session's native permission surface.
Receipt: `223646c0ba23e241766676d9fa4aed7ff74613eb30b001dc1d4b7c742bd201a9`.
The release may preserve evidence, commit the accepted task, merge it into dev,
prepare/verify an isolated candidate, obtain exact one-shot maintenance bindings,
install locally and verify the actual runtime. No remote push is authorized.
This supplements the development-only PLAN.md; REPORT.md and EVIDENCE.json remain
the immutable-at-release-start development acceptance baseline, not installation
claims. Preserve main, existing user changes, other tasks and all authority logs.

## Evidence reuse

Before any release edit, the semantic tree was independently reread as
`de7c530bccf80acad037e244284e69cb5d4f9e66ce44d205a0a88f4f2539168f`, matching the
final integrated run before/after and its stored log SHA256. That run completed
2,079 tests: 2,054 passed, 25 skipped, no failures/errors. It includes real isolated
CLI/Hook/MCP continuation, Allow/Deny, memory recovery and destructive Pre denial.
The final warmed read-path benchmark is bound to the same source.

Do not rerun the full suite for this release note or a version-only cachebuster.
Verify the exact source delta instead; run affected checks if code changes or dev
advances, and independently verify the newly staged/installed artifact. Never
reuse a stale receipt merely because an earlier test command exited zero.

## Sequence and terminal checks

1. Commit only this task's accepted source/tests/docs, excluding private raw logs.
2. Merge only if dev still descends compatibly from the recorded base; require
   exact integrated content and preserve other worktrees. Do not touch main.
3. Validate the installed local marketplace, Python dependencies and release
   entrypoints. Prepare exact cachebuster/install maintenance grants before effects.
4. Stage and verify the new candidate in isolation; preserve current production
   until the candidate passes. Promote only through the transaction installer.
5. Read back generation identities, scheduler/launcher status, MCP and real Hook
   evidence, and independently settle each maintenance effect. Unknown is not ready.
6. Retain all test evidence outside any directory selected for removal before
   releasing a clean merged task workspace. End Skill frames, use the registered
   completion transition, then remove only the exact merged task branch/worktree.

If candidate verification fails, keep production unchanged. If promotion fails,
use the installer's transaction recovery and retain failure evidence. No blind
effect replay, ledger removal, force push, or automatic merge into main.

Windows-native tests remain Windows-owned; existing platform/retired-policy skips
are not successful tests. Static Skill catalog pickup and live Hook evidence are
separate acceptance domains.

## Current results

- Development acceptance: passed, as linked above.
- Source commit / dev merge: `f40f696`, fast-forward with no content differences.
- Candidate / production install / runtime verification: pending.
- Remote push: excluded.
- Raw evidence retention: 113 files / 1,091,388 bytes independently hash-verified
  in two local-only Git archives. Metadata/benchmark results are in
  `refs/sulde/evidence/guardian-memory-consistency-20260910` at
  `8a6fd252514bbfb4a79e18d033d47d186354b375`; raw logs are in the corresponding
  `-logs` ref at `56d5fe0af05c5782a7c14818d82d91eea3eb5820`.
  Each stash archive's third parent contains the original relative paths. Neither
  archive is part of dev or a remote push. Local fixed refs protect retention.
- Workspace cleanup: wait for installation/effect settlement, not user session closure.

## Release execution observations

- `stash --include-untracked` omits ignored `*.log` files. Independent inventory
  comparison caught the incomplete archive before cleanup. All 54 logs remained
  on disk and were archived with an exact-directory `--all` operation. The two
  disjoint archives now cover every original file with equal SHA256 and size.
  This was an Agent archiving mistake, not a Guardian product defect or lost data.
- Pre-install production is still `0.2.5+codex.20260909091120-48e0594354`.
  Its scheduler has 16 loaded actors but eight nonzero last-exit statuses:
  auto-sediment, codex-harvest, heartbeat, life-cycle, mem-sync-export,
  mem-sync-import, memory-embed and status-notify. This predates the candidate.
  Interactive doctor readiness does not prove scheduler readiness. Record the
  installed result independently; do not silently expand into unrelated repairs.
- The local marketplace is `sulde-local`; official identifier and plugin
  structure validation passed with the supported Python, without global installs.

## Additional branch request and installation hold

The user additionally requested `task/guardian-receipt-consistency-20260910`.
Read-only inspection finds its HEAD still at `3d4df54`, with five modified runtime
files and three untracked tests. All five runtime paths overlap this task; the
receipt-tail changes in recovery.py/native_decision_journal.py require semantic
integration with the new selected-task continuation. Its composition dependency
extraction also overlaps work already accepted here. A plain branch merge would
not include the uncommitted files. Ownership/stable handoff must be confirmed
before modifying that worktree; no changes were made to it in this session.

Local cachebuster commit `a4631e5` changes only the version to
`0.2.5+codex.20260910102014-67940a9372`; dev remains at `77c5929` while integration
is paused. Revision 9 was natively approved with receipt
`e26c746c0d626c0d400057a974e33b4940e333755655221cce810d825485bc46`.
The official helper returned success and its content diff was read back, but the
subsequent contract read showed no continuation-use rows. Do not claim that this
proved grant consumption or independently verified settlement. Audit this
observation before further maintenance; do not replay the helper to make a row.

No candidate preparation/promotion or production installation has run. The
existing install binding is not authorization for the future combined tree;
discard its use for that purpose and prepare a fresh exact binding after the
additional branch is complete, integrated and verified. This release-note change
also changes its tracked-tree precondition. Production remains unchanged.

## Combined release preparation (revision 12)

Native receipt `f4ada8a11a4f0c5ad59e38528268fe6206ee00f728a10369bfe0f7ef0e0bcbd0`
approved preparation only; no installation or push. The preceding hold is
historical: receipt-consistency is now accepted on dev `2386e930944efbe66eaaa70e0107938d77da6314`.
The release task preserved the existing note in `1f856a8` and merged that exact dev
without conflicts at `7c1417c8c78e4ec69530c544489e7c0a7e2b379b`.
Compared with accepted dev, only this release note and the official cachebuster
manifest differ. Runtime, Hook, release and test source bytes are identical.

Reuse revision 11's explicitly accepted combined evidence: 2,093 passes,
25 skips and one encoding-gate failure in the complete run; the test-only gate
repair then passed all 123 impacted checks. This is not an all-green full rerun.
See `../guardian-receipt-consistency/REPORT.md` and `EVIDENCE.json` for the immutable
source snapshots, log hashes and real isolated CLI/Hook/MCP cases. Do not rerun
the complete suite for the version and this document. Candidate and installed
runtime verification remain mandatory and are not replaced by that test reuse.

Explicit Python 3.10.7 passed the release dependency probe with PyYAML 6.0.3;
no package was installed and no default interpreter was silently substituted.
The selected binary digest is
`821824635f10f06dace33486e71ad7b520d633b0e4b1f6f150cfaffc1b0dc1b7`.

The R9 audit contains the helper-time started/completed event as `effect=unknown`,
with no typed continuation use or independent verification. The absence of a
current debt is not proof of successful sealed consumption. Preserve this
historical classification anomaly without rewriting its ledger. The existing
manifest bytes/version are retained as source input; neither R9 grant is reused.
Before promotion, require a fresh exact-tree install-only grant and confirm its
canonical invocation is recognized as material maintenance. Stop on an unknown
classification, missing consumption, or unresolved installation result.

Production still uses the September 9 generation. Its previously observed eight
nonzero scheduler exits remain the pre-install baseline, not failures caused by
this source merge. Main, dev, other worktrees and evidence refs were not changed
by this preparation. Candidate verification, production installation, remote push
and workspace cleanup have not run.

## Final local installation (revision 13)

Native receipt `b93a57282ed4f775406c8128f492ebc231972a47a64dbb97f81bd72291a9a376`
approved the exact install-only scope. Source HEAD at preparation and promotion:
`1ed22d3c7039827c585ad09e067838aa2b30d7d7`; Git tree:
`c63e909616b10f5ab1f92b0dc629cd4a811900b5`.
The final result below supersedes the historical pending/hold observations above.
This final evidence update does not change any runtime source or the installed
source commit and does not require repeating installation.

- Version: `0.2.5+codex.20260910102014-67940a9372`.
- Generation: `0.2.5+codex.20260910102014-67940a9372:ffb168348ea693b5322047a49d470ec7a9634be89b0caff0552d39430d688507`.
- Loaded Guardian module generation:
  `4eebf26591f75d8100704ecbbde2df0d8e0eae472688067be63ceee05ccc87d0`.
- Candidate: `guardian-consistency-20260910-1ed22d3`, under
  `$SULDE_HOME/candidates/codex/`; state is `promoted`, promotion consumed once.
- Candidate receipt:
  `1cecd1e618e0e7853662b305a153b513dae101cc272c4759c7de75f51c3762cd`.
- Candidate, canonical artifact and installed `generation.json` have identical
  SHA256 `fcc968f037fab2943c217aa7c414e81e2218059015badb05dc7041bed702c87d`.
- Deployment is `generation_verified`; runtime owner is `active`. Both store
  `operational_ready=true` after live verification. Launcher generation agrees;
  shared scheduler activation ID is `684126d08a0e4631925c3745645ed5b9`.

### Authority and actual host evidence

Install grant `14ea6d6cbc4fb76bbd9347d8da5ae6dff73db8d6e5e5424096c31ddf20f72b7f`
was consumed exactly once as `codex-plugin-install-v2`, `external_write`, before
execution (event `c1e007830b29363029e7af49`). The independent content verifier
settled attempt `att-e0bedfae35f92d2007789291` through
`tool:codex_plugin_install_verify`, `system_verification`,
`local_codex_install_read` at `2026-09-10T13:24:17.935006+00:00`.
Final reconcile: zero pending verifications; doctor: zero blocking effect debt,
zero open interventions, zero open events and zero pre-execution gaps.
The historical R9 cachebuster observation remains unchanged and is not described
as verified by this separate installation receipt.

Candidate verification ran the real Codex CLI app-server and unified executor:
positive action executed; ordinary outside-plan local write executed as intended;
destructive action was denied by PreToolUse; its marker was absent. Both module
and artifact generation were bound to the denial. MCP initialization passed.
Candidate scheduler validation was an isolated entrypoint dry-run, not a claim
that production launchd or native human UI was observed inside that sandbox.

After promotion, this existing human session exercised an actual native tool
denial, then successfully continued with read-only commands and doctor. No session
restart was needed for the Hook. Production proof:
`4b366d4e794ca0d3a5012651ef498c8e4801932a82cca5fb420dce6373f85b71`,
event `0ae2e0bfe2dee7e1db72670c`, verified at
`2026-09-10T13:25:13.320377+00:00`; module and artifact identities both match.
Doctor reports interactive readiness `ready`, verified hot runtime/workspace
continuity, and all 16 scheduler actors loaded with no failed, missing or retired
labels. This is a point-in-time process check, not proof that every periodic
business job has completed a full cycle. The six installed Hooks are enabled,
trusted and unique. The transaction's initial `live_host_unverified` result was
superseded by this later actual-session evidence, not edited into a success.

### Timing and retained limits

| Stage | Observed time |
|---|---:|
| Candidate prepare | 2.238 s |
| Candidate verify | 19.323 s |
| Promotion controller | 57.768 s |
| Installer internal total | 57.621 s |
| Installer deployment lock / recovery scan | 23.236 s |
| Installer snapshot / prepare | 16.890 s |

Substage measurements are diagnostic, not additional time to add to their parent
total. These are one release's measurements, excluding time awaiting human
approval; no percentage speedup is claimed. No complete test rerun occurred.
Release evidence remains in the candidate state and verification receipt, with
the earlier full/impact test evidence in the receipt-consistency report.

The MCP tool was actually callable after installation, but `kb_status` returned a
fresh **degraded background snapshot** generated at `2026-09-10T13:24:32.025600+00:00`
(71 seconds old at readback). It reported 381 KB documents, one pending embedding,
and a harvest age of approximately five hours. This is not a failed MCP startup;
the background warning's cause is not established by this release. Do not label
the entire LIFE/knowledge pipeline healthy or expand this installation into a
background repair. The current doctor and scheduler domains are separately ready.

The official installer removed three regenerable `.pyc` files from the preceding
cache generation; names, hashes and sizes are retained in candidate
`state.json`'s `promotion_result.legacy_cache_restorations`. No user source or
audit history was deleted. Old static catalogs remain available through the
controlled retired aliases. A new thread is needed to load updated static Skills;
this is separate from the already-verified live Hook hot update.

Main/user `.ua` changes, dev `2386e930`, other task worktrees and local evidence
refs are preserved. No remote push or task worktree/branch cleanup was performed.

### 沉淀候选（Layer1；不直接写入事实知识库）

- 问题类型：workflow / performance。
- 任务与预期：在已验收源码上完成一次安全本地发布，避免为版本/文档差异
  重跑全量测试，也不能用旧 helper 的成功输出冒充新安装授权。
- 可观察症状：旧 R9 helper-time 事件为 unknown、无 continuation use；本次
  canonical promote 被正确识别为 external_write 并由独立 verifier 结算。
- 已确认根因：旧 R9 的具体分类根因仍为 inconclusive；不能从本次成功反推已修复。
- 证据状态：本次 grant→执行→独立结算、双身份 live denial 和阶段耗时为 verified；
  背景 degraded 的原因以及 recovery scan 的内部成本分布为 inconclusive。
- 已排除假设：本次没有缺 PyYAML、没有重跑全量、没有复用 R9 grant；不代表
  其他宿主环境也不存在这些问题。
- 路由正例（observed，apply）：已验收代码仅追加版本/发布记录；复用源码证据，
  再独立验证新 artifact，必要条件为 exact source delta 可证明。
- 路由反例（constructed，skip）：runtime 或依赖内容变化；旧测试不能覆盖新输入。
- 执行合格例（observed，pass）：唯一 material grant 在 Pre 绑定，verifier
  独立结算，实际 denial 的两种身份一致；四项证据均可回读。
- 执行失败例（observed，fail）：只凭旧 helper exit 0/no-current-debt 宣称 grant
  已验证；缺少消费与独立效果证据。
- 上浮边界：泛化个人路径、项目/任务名、提交、session/grant/receipt 标识；
  建议 work-model，消费者为发布流程与验收 checklist；由协调单写者判重。
