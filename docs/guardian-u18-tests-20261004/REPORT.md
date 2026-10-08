# U18 test hygiene and distillation fixture repair

Status: scoped source candidate for coordinator integration and independent
review. Baseline `ef5e7d6`, current-session revision 4. No product implementation,
installer, shared architecture guard or snapshot was changed. No full suite,
production KB/ledger mutation, production install, network/provider experiment,
push or dev/main merge was performed.

## Result

Eight existing text-subprocess call sites now explicitly set `encoding="utf-8"`
and `errors="replace"` in the four assigned predictive-test files:

- `test_experience_recall_drives_predictions.py`: one call.
- `test_r1_behavior_evidence.py`: three calls.
- `test_r3_injection_baseline_r2.py`: three calls.
- `test_r3_real_entry_chain.py`: one call.

The original AST guard remains unchanged, as do its accepted values and test
assertions. Binary archive/tar subprocess boundaries remain binary.

`test_distill_conflict_resilience.py` now binds the entire CLI to its initialized
temporary `SULDE_KB_HOME`. The connect-only mock was removed. The preflight path
check and real SQLite connection consequently observe the same database.

Two checks were added: an absent inherited home cannot affect this fixture, and
the actual `memory.py annotate` child process preserves the successful/conflict
wire protocol and stored state. Each child uses `-B`, explicit UTF-8 decoding and
an explicit temporary KB home; there is no fallback to a production KB.

## Diagnosis and normal/baseline evidence

The baseline distill suite passed with the ordinary inherited environment.
Inspection found that `memory.main()` checks `memory_db_path().is_file()` before
calling `connect()`. The old fixture redirected only `connect()` to its temporary
database. It therefore relied on an unrelated inherited home already containing
`memory.db`, even though no production database connection was made.

Setting inherited `SULDE_KB_HOME` to an absent directory reproduced the original
failure without changing the assertion:

```text
test_cli_reports_a_conflict_with_its_own_exit_code_and_machine_code ... FAIL
  self.assertEqual(first, 0)
AssertionError: 2 != 0

baseline_first_annotate:
(2, 'memory database not found; run kb-index mem-init first\n')

Ran 3 tests in 0.022s
FAILED (failures=1)
```

This is a **test environment dependency**, not evidence of a distillation or
annotation product defect. The request itself is accepted by the real protocol:
declared entity, self-relation, null source entry and explicit Codex attribution.
The first request creates the record; changing only the entity type must return
conflict exit `3` and machine code `memory_annotation_conflict`. A generic
validation/backend failure remains exit `2`. No assertion was changed to accept
the wrong result, and no type-conflict rule was relaxed.

Baseline encoding guard reproduced exactly these eight violations:

```text
tests/test_experience_recall_drives_predictions.py:78
tests/test_r1_behavior_evidence.py:85
tests/test_r1_behavior_evidence.py:132
tests/test_r1_behavior_evidence.py:159
tests/test_r3_injection_baseline_r2.py:127
tests/test_r3_injection_baseline_r2.py:281
tests/test_r3_injection_baseline_r2.py:268
tests/test_r3_real_entry_chain.py:185
text subprocess requires encoding="utf-8", errors="replace"
Ran 12 tests in 2.137s
FAILED (failures=1)
```

These excerpts preserve the original failed outputs; green candidate evidence
does not replace them. The existing malformed-UTF8 normal control still proves
that invalid bytes become visible replacement characters rather than lost output.

## Candidate verification

Interpreter for every run:
`/Users/eric/.sulde/data/kb/venv/bin/python -B`.

1. Distill conflict plus unchanged encoding guard: 14 passed, 2.306 seconds.
2. Supported isolated entry:

   ```text
   scripts/kb/run-isolated-tests.py tests.test_distill_conflict_resilience tests.test_subprocess_text_encoding_guard
   Ran 14 tests in 2.442s
   OK
   ```

   This exercises the real disposable home/config/KB setup. The distill fixture
   explicitly overrides it with its own initialized temporary home, never a
   production location. The guard is unchanged and all eight violations clear.
3. Broader affected modules:

   ```text
   -m unittest tests.test_experience_recall_drives_predictions tests.test_r1_behavior_evidence tests.test_r3_injection_baseline_r2 tests.test_r3_real_entry_chain tests.test_distill_conflict_resilience tests.test_subprocess_text_encoding_guard tests.test_utf8_subprocess_boundaries tests.test_auto_distill_windows
   Ran 46 tests in 14.594s
   OK (skipped=2)
   ```

   The two skips require native Windows PowerShell; they are not passing Windows
   evidence. Predictive entry tests use their existing isolated fake provider;
   no paid model was invoked. UTF-8 consumer tests and conflict/backend negative
   controls remain unchanged and pass.
4. Actual child CLI assertion checks exit 0/created, then exit 3/conflict JSON,
   while the original entity type and exactly one successful receipt remain in
   the temporary database. `git diff --check` passes.

No performance benefit is claimed. Final combined full regression and independent
review remain coordinator-owned. These scoped results do not declare production
fixed or the integrated release accepted.

## 沉淀候选：Layer1 问题卡

- 问题类型：`regression` / 测试环境依赖。
- 任务目标：验证首次标注成功、实体类型冲突有专用退出码。
- 用户真实预期：隔离执行不依赖个人生产数据库。
- 触发场景：CLI 在打开数据库前先检查规范数据库路径是否存在；夹具仅替换
  连接函数，隔离 runner 指定空 home。
- 症状：首次合法标注返回 2，普通本机运行却通过。
- 已确认根因：路径存在性检查和数据库连接使用不同环境来源。
- 已排除假设：合法请求本身无效、冲突码协议退化；真实子进程验证 0/3 和持久状态。
- 证据状态：`verified`，范围为本地测试协议与环境依赖；生产状态未作推断。
- 一手证据：上面的原始失败摘录、正式隔离入口和实际 CLI 测试。
- 正确做法：使用真实初始化临时数据库，绑定整个 CLI 的 home，移除局部连接替身。

| 样本 | 内容 | 固定预期 | 原因 | 来源 |
| --- | --- | --- | --- | --- |
| 路由正例 | 本机单跑通过、隔离 runner 报数据库不存在，夹具只 mock connect | apply | 预检与操作的环境来源不一致 | observed |
| 路由反例 | 临时 home 中存在初始化数据库，真实 CLI 因业务类型冲突返回 3 | skip | 正常产品冲突，不是 fixture 环境遗漏 | observed |
| 执行合格例 | 全入口绑定临时 home，首次 0、冲突 3，原类型及 receipt 数量不变 | pass | 正常与负向协议均由实际 CLI 证明 | observed |
| 执行失败例 | 把首次期望改成 2，或创建个人生产数据库让断言通过 | fail | 隐藏环境缺陷或违反测试隔离 | constructed |

上浮时泛化项目、路径和提交；可复用内核为“fixture 必须绑定完整入口的环境，
包括预检，不只替换最终 I/O”。建议 `anti-patterns`，消费者为测试隔离审查。
知识库检索两次未找到直接匹配条目；未据无关命中修改方案。由协调端判重入库，
本执行者没有写共享知识库或记忆图谱。
