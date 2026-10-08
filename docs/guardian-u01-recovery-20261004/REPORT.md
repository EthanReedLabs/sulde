# U01 bounded recovery candidate

Baseline: `ef5e7d68556cee9122d422f1074fd1bdaeff2e7e`. Branch:
`task/guardian-u01-recovery-20261004`. This is a repair candidate, not acceptance
or a production-fix claim. No production install, remote operation, receipt
copying/self-approval, dev/main merge, push, or historical cleanup was performed.

## Defect and correction

Old recovery treated a missing transaction directory as proof that no production
mutation had occurred and deleted its fence. External loss after a real installer
crash disproves that inference. Simply rejecting every missing journal would
strand the old legal fence-before-journal crash window.

The candidate changes publication order to durable snapshot + descriptor + empty
journal + active pointer + prepared record, then fence publication and final lease
recheck under the existing short fence lock, then the first guarded generation-
switch mutation inside `_install_locked`.
Snapshot work remains outside the fence lock. A crash before active publication
has no fence and no guarded generation-switch mutation; a crash after active publication uses
the existing verified rollback path, including an empty journal.

This ordering claim is limited to the guarded generation-switch chain.
`install()` already performs separate home migration, memory reconciliation and
identity-map effects before `_install_locked`; this lane does not make that
entire outer workflow transactional.

New fences add `transaction_descriptor_sha256` alongside transaction ID, exact
old/new generation identities and unique token. `load_transaction` reads a
specified, externally bound descriptor digest using the same authoritative
schema/hash/sequence/snapshot validators as active recovery, additionally checking
root, transactions and snapshots directory metadata. It never recreates active
authority. Installer fence publication refuses an existing unresolved fence.

After active cleanup, only a bound terminal journal can enter detached recovery:
committed recovery independently verifies current registry, installed tree,
deployment, launcher and scheduler postconditions; rolled-back recovery verifies
the exact restored snapshot and old registry. Deletion is an exact fence-state
CAS under the existing fence lock and durably fsyncs the containing directory.
The normal commit retains the original postconditions → final launcher re-pin
ordering (another host probe after re-pin can itself refresh system helpers).

Legacy fences without the new digest, foreign identities, missing/corrupt
authority, a detached nonterminal journal and changed tokens remain intact.
Observe installs continue preserving pre-existing fences. Repeated recovery
does not convert absence or prior refusal into authority.

## Evidence

All tests use the repository venv interpreter with `-B`, real installer CLI and
isolated fake Codex/launchctl/ps fixtures. Fault injection uses existing external
hard-exit failpoints and temporary fixture-file mutation; it does not mock
successful recovery. New subprocess text reads inherit explicit UTF-8/errors
from the existing fixture.

1. Baseline normal control before source edits: journal owner/snapshot/monotonic
   test + real block install/commit fence lifecycle: **2 passed, 20.744 s**.
2. Baseline defect: `test_missing_journal_is_not_positive_premutation_evidence`
   first performed normal recover-only, then a real block install exit 86 at
   `normalization.before_publish`; moved its real 32-hex-ID transaction directory
   and active pointer aside, preserving originals. Same final assertion failed:

   ```text
   AssertionError: 'orphaned_fence_cleared' != 'recovery_required'
   Ran 1 test in 4.389s
   FAILED (failures=1)
   ```

   Candidate keeps the fence byte-for-byte for that same assertion. The expanded
   test also proves an intact nonterminal journal without active cannot recreate
   authority.
3. Direct candidate journal + dedicated module: **12 passed, 52.166 s**. Includes
   7 hard-exit publication boundaries, before/after active and prepared, terminal
   commit/rollback active-cleanup windows, actual registry/deployment/launcher/
   scheduler and rollback-snapshot drift, legacy/foreign/token mismatch, and
   journal malformed/nonobject/schema/sequence/hash plus directory mode/symlink
   rejection. Every drift subcase restores original evidence and proves the
   corresponding valid recovery succeeds.
4. Formal isolated impacted-suite run: **31 passed, 159.196 s, exit 0**. It includes the
   dedicated modules, existing R3 recovery/observe/concurrent two-process
   admission tests, fence mutual exclusion, real installer rollback, system-skill
   re-pin and matching/foreign/repeated recovery. Full-suite execution belongs
   to the coordinator after integration. The runner proved its OS-enforced
   production-write denial before launching tests and reported no attempted
   production KB writes. Exact commands are in `TEST-COMMANDS.md`.

   ```text
   Ran 31 tests in 159.196s
   OK
   ```

Non-product failures retained: first committed-recovery fixture lacked the
original install's `SULDE_TEST_MODE` and fake launchctl state, so the real verifier
correctly rejected the fake Codex version. Restoring the same fixture environment
made it pass without relaxing verifier logic. An initial direct import of the
base TestCase accidentally expanded unittest collection; that run was interrupted
and excluded. The dedicated fixture now uses module-qualified composition;
existing duplicate-suite optimization remains deferred (U09). The existing
quota-concurrency test emitted an unclosed-file ResourceWarning; it passed and
was not modified by this lane. `git diff --check` passed.

## Limits and independent review

- Damaged-fence admission **still fails open**, as documented by the preexisting
  `generation_fence` consumer. Recovery preserves damaged bytes and diagnoses
  them; this change does not claim to repair that separate policy risk.
- Old v1 fences lacking descriptor digest require explicit recovery work; they
  are not guessed bound merely because IDs happen to match.
- Lost active authority for a nonterminal journal is not automatically rebuilt.
- No live-host UI, production installation or real server behavior is claimed.
  Formal host/receipt acceptance remains with the coordinator and human; no
  descendant receipt was synthesized or inherited.
- Tests measure local deterministic correctness, not token/performance benefit.

## Post-commit cleanup follow-up

Independent reviewer reproduced an ordinary directory-fsync error scoped to
`generation_fence.clear_fence` after the real unlink, on initial candidate
`0d46aff1f72cec79b8586da58fa4862489405383`: the generic exception handler still
performed registry/snapshot rollback despite the durable committed record,
then no active/fence remained. Hard-exit-only tests did not exercise that route.

A permanent external bootstrap fixture reproduced the same old branch before
this correction (1 failure, 22.067 s):

```text
AssertionError: 'post-commit cleanup incomplete' not found in
'SULDE CODEX INSTALL: FAIL: install did not verify and was rolled back:
fixture fence fsync EIO; rollback issues: durable transaction rollback:
rollback journal did not read back independently'
```

The follow-up adds a verified-commit boundary and `CommittedCleanupError`.
After independent committed-journal readback, ordinary cleanup exceptions cannot
authorize registry/snapshot rollback, including the outer home-migration handler.
Failure remains a nonzero CLI outcome with an explicit cleanup diagnosis and no
operational-ready claim. This exception does not assert that cleanup succeeded.

The common completion helper now removes the exact fence and fsyncs its directory
**before** clearing active authority. CAS mismatch is a hard cleanup failure.
Both install and active recovery use that ordering. If unlink succeeds but fsync
fails, real active committed authority survives without manufacturing a fence;
the next recover-only independently checks actual new-generation postconditions
and completes active cleanup. Pre-unlink lock failure retains both records.

The committed/rolled-back detached tests now explicitly move active aside after
a real terminal hard-exit to simulate the old active-first cleanup window. New
normal transactions no longer create that window. Original bytes are retained
in the disposable fixture; detached recovery remains strict and never recreates
active authority. The rollback snapshot drift and new-generation live drift
counterexamples remain unchanged.

Follow-up targeted normal/error pairing: **3 passed, 65.235 s**, covering install
fsync EIO after real unlink, cleanup lock timeout, and active recovery fsync EIO.
Each asserts committed journal, no reverse generation change, retained active
authority, and subsequent real recover-only success. The changed-token module
case additionally asserts failed CAS never invokes active cleanup.

Follow-up formal isolation: **20 passed, 171.397 s, exit 0**, plus the subsequently
added rolled-back recovery-cleanup EIO case **1 passed, 3.787 s, exit 0**. Both
used the formal runner's production-write denial gate and reported no production
write attempts. The latter proves a real rolled-back terminal journal and exact
snapshot remain verifiable after cleanup EIO, followed by idempotent old-generation
recovery. No full suite was duplicated; the coordinator owns integrated release
verification. `git diff --check` passed.

Follow-up implementation SHA-256 (unchanged across both formal runs):
`59a07c574ca887d72f695b926e17953fafab251e2c941802c164f0d86872ee55`.
The dedicated test file hash was
`cb6f392811f462b55936f57b5fbe0ef17850a4f7fa1461c6dfe661f2cc4ebba5`
at the 20-test start; adding only the final rollback-cleanup test gives final hash
`5df61e7802b587f950825b28f236f4a14d4c135e026f7b3fda308c6f3708b7aa`.
The source hashes below describe the initial candidate's earlier 31-test run.

## Source identities

SHA-256 at formal targeted-run start:

```text
3a94221803e509233111225e0fe68c3b0cae2436139ead1940d0304cd7aeadfa scripts/release/install_codex_plugin.py
3e1714ed251b8c85a0c74182a5a820990b03a32420cacc9ade802be4fe9a1130 scripts/release/install_transaction_journal.py
93b15f98d1a4ee26ba9b23f679ac070a6482e724b392b945b3476d28b4c5f400 scripts/kb/generation_fence.py
84ede2b677564c5f13528940f2962ea18525d526988cc4756bc6b9dfc8bc1585 tests/test_guardian_u01_recovery.py
0f43eb7990c6960adbbd8a4c86a1c5affde344495bdff4bd0665a7af248b36e7 tests/test_install_transaction_journal.py
1a9d662f26b2e1abc41f0b5533a2230f6b6d39815f6cede5bff42b60b0d0751a tests/test_codex_plugin_install.py
32b8d08a968298ba3e15d281161af35ba89579949a3d5ae155949b61667c27c8 tests/test_orchestration_r3_closeout.py
```

## 沉淀候选（Layer1；不直接写知识库）

- 问题类型：bug-fix / workflow。目标：可恢复且不凭缺失证据释放安装屏障。
- 用户真实预期：合法 pre-journal crash 不死锁，历史未知不被误判无副作用。
- 触发：跨 fence/journal/active 的持久化与清理顺序。
- 症状与根因：missing journal 被当作无副作用证明；fence 先发布使安全拒绝又
  可能阻断合法早期崩溃。证据状态：verified（隔离真实 fixture，不是生产事故）。
- 已排除：不是通过放宽 verifier/伪造成功来恢复；fake-host 环境缺项另列 fixture错误。
- 正确做法：先可核验回滚 authority，再 admission fence；terminal 后仍验当前后置条件。
- 路由正例：安装崩溃遗留 fence 且 journal 缺失，apply；必要条件是持久化身份/顺序
  歧义，constructed + observed fixture。
- 路由反例：普通无持久化副作用的内存缓存失效，skip；缺少恢复 authority，constructed。
- 执行合格例：同一 missing-authority 断言由红转绿且合法 publication crash 可幂等恢复，
  pass；正反均满足，observed fixture。
- 执行失败例：直接删 fence 或仅看 terminal 字样，fail；跳过身份/当前后置条件，
  前者 observed baseline，后者 constructed drift。
- 上浮需泛化项目/路径/提交；可复用内核是缺失证据不等于否定事实及正向恢复顺序。
  建议 anti-patterns，消费者 recovery review checklist。统一判重由协调端负责。
