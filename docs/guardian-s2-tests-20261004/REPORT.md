# S2 U09 tests/evidence candidate

Input: `aa9ffc147c189a5a18c9209c2edec2e8e538d2e1`. Branch: `task/guardian-s2-tests-20261004`.
Status: scoped candidate, not accepted. No install, production maintenance, merge, push, paid-model run, or authority fabrication.

## Implemented boundary

- Installer fixtures: extract exactly four unchanged helpers into a non-TestCase mixin. The three concrete classes retain their own 62 test methods and POSIX skip. A permanent AST/loader test proves unchanged 62 bodies, four helper bodies, helper object binding and the mapping of 108 duplicate inherited IDs to retained base bodies. Discovery is 62 instead of 170; no runner filtering and no installer protocol edits.
- Evidence reuse: require explicit complete/pass/zero, nonpartial status, aware ordered nonfuture/unexpired timestamps (maximum 30 days), matching before/after input identities and safe single-link matching log bytes. Newest same-key failure/incomplete evidence vetoes old success; tied newest rows must all pass. Legacy records remain readable history but incomplete legacy proofs are cache misses.
- Input identity includes source/fixtures/dependencies, runner, selected tests/risk, interpreter/platform and one digest of the entire environment. No environment variable values or per-variable hashes are recorded; volatile exclusions are empty, intentionally preferring misses. Pre/post drift preserves the runner exit code but returns nonzero/inconclusive and cannot be reused as success.
- Selection takes the maximum of requested and inferred risk, unknown executable changes choose full, and journal/fence consumers are mapped. Experience recall passes the existing `ttl_seconds=30*86400`, can add tests only, and cannot replace full selection.
- `evidence_root(kb_home=None)` shares CLI/LIFE precedence: `SULDE_TEST_EVIDENCE_HOME`, then explicit home or `SULDE_KB_HOME` parent/test-evidence, then `SULDE_HOME/data/test-evidence`. Root resolution alone creates nothing. Parent owns LIFE hookup.
- Derived details keep existing plan/quarantine/readback, with exact plan/root/digest/path validation and independent metadata protection at readback. No delete or second GC. Experience owner owns producer/maintenance at `home/experience/derived-details`, versions `sulde-agent-experience-v1` / `sulde-experience-maintenance-v1`, 30 days / 250. Authoritative logs, pending candidates, unresolved effects and verified aggregates remain protected.

## Verification and preserved failures

Interpreter: `/Users/eric/.sulde/data/kb/venv/bin/python -B`. Formal modules use `scripts/kb/run-isolated-tests.py`, temporary stores/real local fixture subprocesses, UTF-8 and explicit decoding error behavior. No production data involved.

1. Original evidence/details modules before changes: 12 passed, 0.206 s.
2. New paired regressions against baseline: 7 tests, 13 failures + 2 errors, 0.170 s. Exact examples: omitted result/partial/identity accepted; corrupt log accepted; later failed record did not veto old pass; requested small downgraded inferred refactor; post-run input drift returned zero. The fixture-mixin absence and naive-time TypeError were the two errors. Tool output was truncated; this is a truthful result/excerpt record, not a claimed complete raw transcript.
3. First candidate: 7 passed. Expanded existing modules: 18/19 initially; existing Codex integration prefix was incorrectly considered unknown. Restored recognition of that existing mapped prefix; 19/19 passed. Then 22/22 isolated passed, 0.692 s.
4. Environment-change regression before environment binding: 1 failure, 0.050 s (equal keys despite changed environment). Added whole-environment binding; subsequently 24/24 passed, 0.942 s. Sensitive-named variables were initially excluded during implementation, then corrected before final freeze; final test proves their changes invalidate too.
5. Final expanded run initially 25/26: new directory test expected macOS `/var` rather than canonical `/private/var`. Corrected only the expectation to `.resolve()`; final isolated three modules: **26 passed, 1.103 s**.
6. Full deduplicated installer module: **62 passed, 349.623 s**. Fixture and installer bytes stayed fixed throughout this run. Evidence helper/environment/root and dedicated evidence tests were refined while installer ran; this is scoped installer evidence, not a final whole-tree frozen result. Parent still owns final integrated source-freeze full run.
7. `git diff --check`: passed.

Commands:

```text
python -B -m unittest tests.test_test_evidence tests.test_derived_details
python -B scripts/kb/run-isolated-tests.py tests.test_test_evidence tests.test_derived_details tests.test_guardian_s2_evidence
python -B scripts/kb/run-isolated-tests.py tests.test_codex_plugin_install
```

Actual entry coverage includes derived-details CLI dry-run→quarantine→separate readback, test-evidence CLI plan, and `run_plan` launching a real local child fixture (normal→reuse→input drift). That local runner fixture is not claimed to execute the entire business suite. The installer module executes the real temporary installer fixtures, including crash/recovery cases. Capacity250 is exercised with251 valid rows plus invalid/protected manifests, approved-plan metadata drift rejection, reversible quarantine and other original bytes unchanged.

## Final source identities (SHA-256)

```text
610c57f6a6e60df28de68026d7f3dafdc671880c3d971a12ace2f62f75e1fa98 scripts/kb/test-evidence.py
6f4eac529fa9ed8aa0237b780f8c54e54672b2d1fecbb52775e1b3df5a81a0b4 scripts/kb/derived-details.py
6ba55b97969903edb0fe36c986d41e6789916cfd793c0a3c99d483aa2c0fb66c tests/test_codex_plugin_install.py
ce4e8cdd32abb6ffa6958315484ce8a845d4c284a46311a64847f7720bc8fbff tests/test_test_evidence.py
11a47beb203e73f6d59c76709371a4f973fbd35866cf0a0c91b42c382ed44119 tests/test_derived_details.py
a0ad617beb0edb117e9ca92403286160d02b76406ca3aa987d3a3c82c95bc1ef tests/test_guardian_s2_evidence.py
59a07c574ca887d72f695b926e17953fafab251e2c941802c164f0d86872ee55 scripts/release/install_codex_plugin.py (unchanged)
c2e7cca6235d233523dda09b695ecb084dfeb4c6f1bea2e1f710372d6b73d596 scripts/kb/run-isolated-tests.py (unchanged)
```

## Limits / handoff

No scheduler/producer/LIFE code here; those remain independent owners. `gc_records` remains a retention plan, not deletion. Whole-environment digest may cause conservative misses for irrelevant changes. Input snapshots detect before/after differences, not a transient change-and-restore during execution. Local evidence is not cryptographic external authority. No production GC was exercised. No parent receipt was copied and no child grant was manufactured. Dispatch/intent skills constrained work to the approved child scope; the KB derived-cache article informed the independent TTL/version/result checks without modifying the KB.

## 沉淀候选（Layer1，供协调端判重）

问题：继承具体 TestCase 复用fixture会重复收集全部父测试；缓存仅找历史绿色而不审最新同输入结论会掩盖后续失败。
证据状态：confirmed in local paired fixtures; final integrated acceptance pending.
根因：unittest继承发现语义；缓存缺少完整性/日志/时间/输入一致性及失败否决。
路由正例：独立fixture mixin保持原AST覆盖；明确命中依赖图才选小/中范围。
路由反例：未知源码强行降级small；full被经验提示变成targeted。
执行正例：最新完整同输入且日志一致的绿色可复用；251个详情仅隔离最旧1个、保留所有权威原件。
执行反例：新失败后取旧绿色、测试中输入漂移、损坏日志或manifest审批后漂移均拒绝；不删除原始权威记录。
归属建议：现有派生产物缓存双失效/测试证据案例；本子任务不直接入库。

## Independent-review follow-up (same bounded batch)

Parent/independent review found three real gaps in the first candidate. They are repaired together; prior 62 installer results remain valid for unchanged installer and fixture bytes, not a claim that the new counterexamples passed before repair.

- Portability: runtime tests no longer require private Git commit `aa9ffc1`. `tests/fixtures/guardian_s2_installer_ast.json` freezes that original file's SHA, 62 per-owner method AST hashes, four helper hashes/order and skip AST. All original coverage/helper/skip/108 duplicate-ID assertions remain. CLI plan uses a real temporary single-commit Git repository and its own `HEAD`. The historical commit remains provenance only, not a runtime dependency.
- Git framing: NUL-delimited diff/status parsing preserves spaces, Unicode and rename source/destination; committed comparisons use `--no-renames` so both affected paths survive. The real repository fixture covers staged rename, unstaged Unicode modification, untracked Unicode filename and committed base comparison. Unknown executables cannot hide behind quoted Git output.
- Incomplete attempts: before cleanup/launch, atomically write and fsync a same-key pending record. Atomically publish/fsync the terminal record and canonical readback before acknowledging only that invocation's pending transport. Launch error, interrupt, pre/postprocessing error and terminal-publication error leave the pending record; matching pending always vetoes reuse. Malformed/unattributable JSON evidence makes the store a conservative cache miss instead of silently selecting old green. No historical evidence is deleted or auto-settled. A retained failed pending marker can force repeated execution until separately reviewed; this deliberately favors false misses over false success. Evidence retention remains plan-only.

Paired reproduction before these last product fixes: 2 new tests / 5 failures, 0.330 s (one path case and launch/interrupt/postprocess/corrupt-record subcases). Output was truncated; quoted-path and reused-green failure facts were retained here, not represented as a complete transcript. Initial terminal readback incorrectly compared JSON lists to Python tuples, causing 5 normal-control errors in 28 tests; corrected to canonical-byte comparison without weakening the checks. Expanded same assertions plus preprocessor/terminal-write injections then passed. Final official isolated modules: **28 passed, 1.803 s**. The earlier portability-only 26 tests also passed, 1.210 s. Installer was not rerun, as instructed.

Final follow-up SHA-256 (supersedes corresponding first-candidate identities above):

```text
3e859e6f344c3e289d92bab3695c4f32027152d5bafbe51c14dda07aed8967ef scripts/kb/test-evidence.py
012c7ba45df4bce616f6a26de97931bb51b1d486e7b4e16a93e14fd34db2accc tests/test_guardian_s2_evidence.py
e229281a7854080d2e3ff2adf412567d2c678178ab90f2b268dd856f2b2ef5a6 tests/fixtures/guardian_s2_installer_ast.json
```

### Damaged-key completion of the same strict-record boundary

Independent review found a same-schema object could evade the strict scan by omitting/corrupting `evidence_key`, then be skipped as an unrelated key. Added strict pre-filter validation requiring a string of exactly64 lowercase hexadecimal characters; malformed/unattributable keys now cause a global cache miss, while a different valid key remains ignorable. No other passed behavior changed.

New paired test first proves normal green reuse and valid-other-key failure isolation, then deletion/null/invalid string/nonhex64/short63/integer variants. Baseline: 1 test, 6 failures, 0.012 s. Same assertions after the three-line validation: full scoped modules **29/29 passed, 1.770 s**. No installer rerun.

Final replacement identities:

```text
edd322a0e3367b9d54fe42ae7c364600f81ec0bc6011dcab5052b50f2212bc47 scripts/kb/test-evidence.py
17e392bfa8c5d13ff8f49829d0ab06897b7bca095350465582b4e9f3065b48ea tests/test_guardian_s2_evidence.py
```
