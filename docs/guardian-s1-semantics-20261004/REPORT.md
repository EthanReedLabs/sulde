# Guardian S1-A candidate evidence

Status: source/protocol candidate verified, not independently accepted. Baseline `ac5dc9c16527e41ef959ebbcef88593b71548e83`. Task/run: `guardian-s1-semantics-20261004`, 2026-10-04 08:34–08:42 UTC; provider Codex.

Owned scope: bounded help/sed/datetime/SSH semantics. Coordinator explicitly transferred only the four semantic glue regions in `resources.py`; no other shared-region edits are included.

Evidence is local source/protocol/real help CLI execution, not installed runtime or live SSH execution. No production install, remote connection, dev/main merge, push or external settlement is authorized or performed.

## Frozen local performance ceilings

After baseline run 1 and before candidate measurement, P50 ceilings are baseline + max(0.15 ms, 20%); P95 ceilings are baseline + max(0.30 ms, 30%). Each round has 150 observations per case after 20 warmups. These are single-call normalization budgets, not Agent latency or Token budgets. Background machine load is uncontrolled; paired alternating rounds are retained.

| Case | P50 ceiling ms | P95 ceiling ms |
| --- | ---: | ---: |
| ordinary_read | 5.846625 | 7.195066 |
| ordinary_write | 4.406025 | 5.353238 |
| help | 6.290975 | 7.640697 |
| datetime | 5.436175 | 6.436191 |
| ssh_probe | 8.528900 | 10.247792 |
| denied_shape | 5.869300 | 7.079041 |

## Implementation and same-assertion evidence

The KB search hit `ap-0250`; its full source was read. Its receiver-proof and invalidation boundary informed the datetime helper. No KB source was modified.

- Trusted Guardian metadata: only an existing digest-trusted launcher, unchained exact top-level help or known-action plus help. `intervention-resolve --help` receives the ordinary read agent route, while the original command and argument fingerprint remain unchanged. Arbitrary help data, extra action arguments, unknown launchers, writers and shell redirects do not gain a blanket exemption.
- Maintenance metadata: repository-resolved candidate-controller exact top/subcommand help and existing installer help support one harmless `-B` interpreter flag. Actual argparse help is executed after Pre allow in the test. Writer args and copied scripts are negative controls. This reuses the existing repository-path trust boundary rather than inventing authority from a basename.
- Sed: a bounded `-n` numeric/range print expression may have literal file operands, with `--` required to disambiguate option-looking operands. Write commands and additional executable sed options remain rejected in control compositions.
- Datetime: bounded straight-line exact imports/factories establish datetime receiver facts; `fromisoformat`, value `replace` and `isoformat` may be proved. Unknown calls, rebinding, mutation, delayed scope, unsupported flow, deep/oversized AST and custom timezone objects do not gain proof. File replacement and independent effectful calls retain their classification.
- SSH: the effect-only proof requires explicit account and literal IP, `-F /dev/null`, exact `BatchMode=yes`, `PermitLocalCommand=no`, `StrictHostKeyChecking=yes`, `UpdateHostKeys=no`, and a fixed absolute `stat` or `ls -ld` invocation with one canonical absolute path. It returns endpoint/path/operation plus evidence and explicit limitations. Other options, aliases, wrappers, content reads, dynamic expressions and compounds are not proved. `remote_execution` remains present; only the proved read avoids `remote_execution_unresolved`. No SSH command was executed.

The same `tests/test_guardian_s1_semantics.py` selects a full `git archive` of baseline through `SULDE_S1_SOURCE_ROOT`. Normal controls and negative boundaries pass in both versions. Baseline has six intended failures in five test methods: SSH unknown; datetime unresolved destructive receiver; Guardian help routed human; candidate promote help rejected; installer `-B --help` rejected; sed file composition unknown. Candidate passes all 10 tests. These are actual production normalizer/GuardianSession assertions, not replacement classifiers. Help, Python and sed positives execute locally only after an allow, followed by completed observation; denied cases never execute.

Commands (all with `PYTHONDONTWRITEBYTECODE=1`, `-B`):

```
SULDE_S1_SOURCE_ROOT=/private/tmp/guardian-s1-baseline.528Dgg <python> -B tests/test_guardian_s1_semantics.py -v
<python> -B tests/test_guardian_s1_semantics.py -v
<python> -B -m unittest tests.test_guardian_s1_semantics tests.test_control_composition tests.test_guardian_data_methods tests.test_guardian_string_flow.GuardianStringFlowTests tests.test_intent_guardian_resources -q
```

Final functional run: 64 tests passed, 3.288 s. Interpreter: existing `/Users/eric/.sulde/data/kb/venv/bin/python`, Python 3.10.7. No dependency installation occurred. Local raw logs: `semantics-baseline.log` (exit 1, six target assertions), `semantics-candidate.log` (exit 0), `final-functional.log` (exit 0). Logs are intentionally local/ignored.

## Native regression and failed-run disposition

Two existing isolated artifact/native tests passed through actual Codex app-server/unified_exec and a localhost mock provider: `GuardianStringFlowNativeTests` and `NativeControlCompositionTests`, 37.189 s, tool session `37409`, exit 0. Evidence reports external model requests 0, real Pre denial of Path.replace/destructive operations, preserved text write, safe batch execution, short-circuit behavior, and sibling/symlink sandbox denials. These establish compatibility of those existing native scenarios, not new SSH execution or production acceptance. Their candidate artifact was staged before the final helper AST-count loop was tightened to stop early; final source functional/performance verification covers that tiny change, while integrated artifact verification remains coordinator-owned.

Earlier runs remain explicit: default Python 3.14 lacked yaml; the first venv package test omitted the untracked new helper because staging uses `git ls-files`; staging the helper fixed that fixture condition. The next native tests hit sandbox denial binding 127.0.0.1. Formal tool escalation for just the two isolated localhost tests was approved and produced the pass above. No installed production directory was changed. Earlier local logs: `affected-venv.log`, `affected-staged-venv.log`; the first Python 3.14 failure and successful native output remain tool-session evidence, not reconstructed raw files.

Architecture test disposition: baseline ac5dc9c itself has four failures against its old `77c5929` freeze: delayed import in state, policy AST, policy exports, resources AST. Candidate has those four plus the intentional composition AST change. Logs: `architecture-baseline.log`, `architecture-candidate.log`; exits 1. No historical assertion was relaxed. This guard requires coordinator/independent-review disposition before integration acceptance. Functional green is not a claim of a green full suite.

## Performance result and limits

Alternating baseline/candidate/baseline/candidate rounds used the same Python, case definitions, 150 samples per case and 20 warmups. All 24 candidate P50/P95 comparisons in both rounds stay below the frozen ceilings. The four JSON files and `performance_probe.py` retain the inputs/results. Ordinary paths gain no model call, network call or history scan. Whole-Agent latency, Tokens and production contention are unknown; no savings claim is made. This timing classifies six synthetic shapes through real normalization, including a denied shape; it does not time decision-kernel/recovery/installer execution.

## Source and fixture identities

SHA-256 at final source verification:

| File | SHA-256 |
| --- | --- |
| control_composition.py | 1503523769d0dc92e7da46a95291a35ec0152fa3b4b017cfb2871dcc6012bdd8 |
| resource_preflight.py | f9f6257f6158876f589d6bdd54111f8fe438512a2c13db16c0a3f58293ab59fc |
| resources.py | d753768a618d2e932bd4f3c0c85c93e45f37acecb56089c9b11d611af043ab99 |
| semantic_proofs.py | a2109727af92956a7b6f9ac59d8714f2050ede1a53790707ea6e5e60b916ad4c |
| test_guardian_s1_semantics.py | 82d61378a8e363b6b50bd87bd28f52b616f2259e61dc228c224621a6b573490a |
| fixture test_intent_guardian.py | 062c991958627eefb892d8b4b514abcfad03bac01ca178b073ffc82a85feed4d |

The standard fixture generates its isolated contract/configuration; no source `.sulde-config.yaml` exists or was modified. Event protocol is `sulde-guardian-event-v1`, control composition `sulde-control-composition-v1`; source provenance is the baseline commit plus the scoped diff, not the synthetic event's claimed loaded generation.

## Remaining boundaries and cleanup

Source/protocol verified; integrated full suite and independent acceptance pending. New semantics are not production-installed. Actual new-shape native host coverage and live remote/business-effect verification remain pending. B/coordinator owns remote resource identity, historical recovery and debt/conflict consumption; an effect proof alone does not grant disclosure authority or establish historical endpoint identity. Windows was not exercised. Local baseline archive `/private/tmp/guardian-s1-baseline.528Dgg` and raw task logs are retained for coordinator review; no old worktree was removed.

## 沉淀候选（Layer1，拟并入 ap-0250）

- 问题类型：bug-fix。任务目标/用户预期：已证明的 datetime 值替换应作为数据处理；文件替换保持风险边界。触发场景：Python 内联诊断把日期解析后补 UTC 时区。
- 可观察症状：旧版 `_python_source_effect` 把 `datetime.fromisoformat(...).replace(tzinfo=...)` 记录为 unresolved destructive receiver。期望 read，实际 unknown。已确认根因：现有证明域只覆盖部分字符串/容器方法，未证明 datetime 接收对象与工厂。已排除假设：有效标准夹具的普通只读控制正常，因此不是所有只读都被拒。
- 证据状态：verified（限定 source/protocol/local Python execution）。一手证据：同一专用测试旧红新绿、64 项功能回归及上述源码摘要。正确做法：只对精确导入和有界顺序数据流增加证明；未知副作用使借用事实失效，参数效果仍独立判定。

| 样本 | 内容 | 固定预期 | 判定原因 | 来源 |
| --- | --- | --- | --- | --- |
| 路由正例 | datetime.fromisoformat 返回值 replace 被拦 | apply | 有精确不可变数据来源而证明域缺失 | observed |
| 路由反例 | Path.replace 或未知工厂返回值 replace | skip | 不存在 datetime 类型证明 | constructed |
| 执行合格例 | 日期替换本地执行成功且文件/未知调用仍不为 read | pass | 数据处理与文件风险边界同时成立 | observed |
| 执行失败例 | 仅按 replace 方法名把所有调用标 read | fail | 无接收对象、参数和事实失效证明 | constructed |

上浮时泛化项目路径/提交/日期。复用内核：同名方法应按有界且可失效的精确接收对象证据分类。建议容器 anti-patterns，候选消费者为静态效果分类与 Hook 回归。仅交协调端判重；没有写入知识库或新增自消费授权。
