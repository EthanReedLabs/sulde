# Guardian S1-C policy feedback candidate

Status: scoped source candidate, awaiting coordinator integration and independent
review. Baseline: `ac5dc9c16527e41ef959ebbcef88593b71548e83`. Provider: Codex.
No production install, policy activation, ledger/KB write, merge, push, or live
model call was performed. The named child worktree was authorized by parent
contract r3; no approval receipt was inherited or manufactured, and no separate
host binding gate was encountered.

## Changes and consumer

- `guardian_policy_review.py` builds and explicitly records retrospective feedback
  in the existing `experience/agent.jsonl`; no second truth store or queue.
- `agent-experience.py` permits strictly validated policy metadata. All policy
  observations remain `inconclusive`, including false-denial and valid-protection
  candidates. They cannot enter verified recall strategy or verified sedimentation.
- `governance-report.py` collects daily dedup/rolling weekly projections through its
  existing collector and appends deterministic candidates with source hashes to
  the weekly report. Optional model failure does not remove this appendix. The
  existing `com.sulde.governance-weekly` template already invokes this consumer.
- 11 dedicated tests cover persistence, evidence classification, identity,
  privacy, replay, recurrence, lack of execution authority, CLI, and weekly output.

Fingerprint material is `(rule_id, rule_version, reason_code, scope_digest)`.
Unique event hashes define recurrence. Replayed observations and later assessments
of the same event do not inflate recurrence or move its earliest daily bucket.
Evidence is a bounded regression/replay claim, explicitly not a signature or a
verified external effect. Matching fingerprint + passed evidence + observed deny
classifies the candidate by expected allow/deny. Missing, unknown, mismatched or
conflicting evidence remains unconfirmed; 12 repeated denials alone do not prove
a false denial. Review suggestions are retain/review_fix/collect_evidence only.

Only codes, digests and fixed summaries are retained. Raw commands, paths and
extra authority fields are rejected. Scope digest is reported as
`scope_digest_only`, not proof of a unique endpoint. Every projection has
`execution_authorized=false` and `production_policy_changed=false`.

## Interface

```python
build_feedback(*, rule_id, rule_version, reason_code, scope_digest,
               event_digest, occurred_at, assessment=None) -> experience_record
record_feedback(home: Path, row: dict) -> persisted_experience_record
project(home: Path, *, now=None, window_days=7) -> daily_and_weekly_projection
```

Codes must match `[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}`; scope/event digests are
lowercase SHA256; occurred_at must have a timezone. Optional assessment fields are
exactly `kind` (regression_test/bounded_replay), `outcome` (passed/failed/unknown),
`expected_decision`, `observed_decision` (allow/deny/unknown), `source_sha256`, and
`fingerprint`. Caller retains original evidence and supplies its content hash.
The candidate is not an independent verification of caller-supplied evidence.

```text
python3 -B scripts/kb/guardian_policy_review.py record --home ISOLATED_HOME --input feedback.json
python3 -B scripts/kb/guardian_policy_review.py project --home ISOLATED_HOME --now 2026-10-04T12:00:00Z
```

The record command consumes the redacted experience record produced by
`build_feedback`, not arbitrary raw denial events. This is a retrospective and
maintenance entry. Existing experience recording scans/rewrites its store under
a lock; callers must not add it to ordinary pretool classification or denial hot
paths. This module does not import execution/approval/kernel code.

## Validation evidence

1. Existing normal control: `tests.test_agent_experience`, 4 passed on baseline.
2. Same new persistence test failed on baseline because the policy-review entry
   did not exist (`FileNotFoundError`); it passes on candidate. This is missing
   feature evidence, not a claim of a preexisting classification regression.
3. Final ordered normal + injected checks: 5 passed, then CLI + weekly writer:
   2 passed. Negative controls include forged verified outcome, metadata stripping,
   conflicting assessments, raw-command fields and changed scope/version/reason.
4. Full affected command:

   ```text
   python3 -B -m unittest tests.test_guardian_s1_policy_review tests.test_agent_experience tests.test_governance_report tests.test_governance_review tests.test_experience_recall_drives_predictions
   ```

   Result: 57 passed in 1.188 seconds. Existing governance SQLite tests emitted
   ResourceWarning for unclosed connections; no assertion failures. The deliberate
   optional-model failure emitted two `offline fixture` errors and correctly
   persisted the deterministic policy appendix. No live provider was called.
5. Actual child CLI processes use temporary homes. Read-back proves only input,
   `experience/agent.jsonl`, and its existing lock were present; no policy/grant or
   effect store was created. Weekly writer test uses the real report writer with
   source/environment/model/notification dependencies isolated.
6. Normal validator paired local microbenchmark: seven repeats of 10,000 calls.
   Baseline median 4.694 microseconds, final candidate median 4.983 microseconds.
   Budget frozen before implementation: baseline x 2 + 10 microseconds (19.387).
   Candidate passes. This measures normal experience validation only, not host
   throughput or end-to-end Guardian latency. No ordinary path scan/model call
   was added. `git diff --check` passed.

One intermediate hardening change rejected the builder's own incomplete reserved
record. It was corrected by passing policy metadata into the canonical builder
before validation; the normal control caught this candidate regression. No test
assertion was relaxed.

## Limitations and remaining integration

- Source/protocol and isolated CLI/report behavior are verified. Real Agent,
  installed host, installed scheduler and production effects are unverified.
- Explicit retrospective ingestion and automatic extraction from the existing
  workspace/session Guardian audit sources are connected; see follow-up below.
  Other/custom audit destinations are outside this adapter's declared coverage.
- Daily grouping and rolling seven-day candidates are computed during existing
  maintenance consumption. No new daily/live scheduler was added or installed.
- This phase has no policy decision acceptance/activation API. Independent human
  review and a separately authorized maintenance/release remain required.
- Original feedback history is retained. Aging outside the rolling report window
  is not resolution, deletion or historical effect settlement.
- Source evidence hashes aid independent read-back but do not authenticate the
  evidence author or make a caller claim verified. No generic human claim field
  can turn into execution authority.
- Integration/full suite/independent review belong to coordinator; this scoped
  green suite is not release or production approval.

## 沉淀候选：Layer1 问题卡

任务与意图：`design-decision`；把 Guardian 拒绝争议变成可回读的周期复核
候选，同时保留当前拒绝和人工生产变更边界。用户预期以冻结任务为依据。

观测与证据：现有经验库的 verified 会参与策略和沉淀，不能把“有测试支持的
误拦候选”直接映射为 verified 经验。证据状态 `verified` 仅指本地合同测试：
`test_unknown_never_becomes_verified_or_execution_authority` 与 57 项受影响
测试；生产状态 `inconclusive`。已排除“累计拒绝次数即可证明误拦”，12 次
无证据拒绝仍返回 unconfirmed。正确做法是复用原经验库、把分类与权限分开、
固定摘要及哈希引用，并由现有治理消费者生成独立待审投影。

| 样本 | 内容 | 固定预期 | 判定原因 | 来源 |
| --- | --- | --- | --- | --- |
| 路由正例 | 被拒 Agent 提交规则误拦证据并请求周期改进 | apply | 评审观察可能被误当执行授权 | constructed |
| 路由反例 | 已独立授权的发布修改生产规则 | skip | 本卡只处理反馈到权限的混淆，不能替代发布审查 | constructed |
| 执行合格例 | 候选落入经验库、每周可回读，verified recall 不消费它 | pass | 分类与权限隔离且有实际消费者 | observed |
| 执行失败例 | 把候选 outcome 改 verified 或移除元数据后保留争议类型 | fail | 应由 canonical validator 拒绝，不能提升授权 | observed test injection |

上浮边界：泛化项目、分支、路径和提交；可复用内核是“策略反馈分类不等于
执行授权”。建议 `work-model`，候选消费者是经验记录校验和治理报告审查。
由协调端统一判重入库，本执行者未写共享知识库或图谱。

## S1-C follow-up: automatic maintenance ingestion

The normal scheduled `governance-report.py` entry now enables bounded ingestion
before projecting the weekly report. `--dry-run`, `--collect-only`, and direct
read-only collection leave ingestion disabled. No new scheduler or PreTool hook
scan was added. The existing `audit_cursor.py` API is reused unchanged, including
prefix validation, no-follow cursor handling and compare-and-swap persistence.
Cursor files under `governance/policy-review-cursors/` contain derived offsets and
hash checkpoints only; `experience/agent.jsonl` remains the feedback truth store.

Actual producer: `GuardianSession.observe` writes `audit_path(contract_path)` as
`<contract-stem>.events.jsonl`, envelope schema `sulde-guardian-event-v1`, nested
decision schema `sulde-intent-decision-v2`. The adapter consumes started events
with dispatch deny/defer and the actual `event.at`. Rule family uses the actual
`decision_stage`, reason uses `reason_code`, and rule version uses the actual
SHA256 `runtime_generation` (explicitly unversioned if absent), never the intent
revision. Only fixed producer-code grammar and digests reach telemetry. Selected
scope fields and the original row are hashed; commands, targets, reasons and
credentials are never copied. Automatic observations always have no assessment
and remain unconfirmed/inconclusive.

Limits per maintenance run: 16 audit files; 256 directory entries; 512 KiB per
source; 4 MiB total source bytes; 256 new rows. Source size also bounds the cursor's
prefix-integrity scan. Discovery is limited to `intent/workspaces` and
`intent/sessions`; custom contract audit locations are not claimed as covered.
Oversized, malformed, unsupported or changed sources and budget exhaustion are
explicit `degraded` diagnostics with hashed source identifiers. Those sources do
not advance their checkpoint. There is no recovery bypass or automatic truncation.
Large logs/backlogs can require a separately scoped recovery/chunking change;
this bounded phase does not promise complete consumption of arbitrary history.

Experience rows persist before the checkpoint CAS. A crash or lost checkpoint
replays the same immutable record and existing experience idempotency prevents
duplicates. A failed cursor operation can leave a recorded experience but no
advanced cursor; diagnostics retain that partial progress without granting any
authority. Production audit bytes are never modified by the consumer.

Follow-up evidence:

- Baseline real-producer test created a normal deny via GuardianSession and
  failed at missing ingestion in the collector; the unchanged assertion passes
  after wiring. No hand-authored fake audit schema was used for this control.
- Real producer -> normal governance main -> scheduled collection -> experience
  -> persisted report passed. Unrelated collectors/metrics, optional model and
  notifications are isolated in that test; the actual ingestion, source wrapper,
  projection, main path and report file write execute. Optional-model failure
  remains visible and does not remove the policy appendix.
- Warm cursor/new append, replay after cursor loss, privacy, corrupt tail,
  invalid producer codes, row/byte limits, no cursor advance on errors and
  read-only collection tests passed.
- `python3 -B -m unittest tests.test_guardian_s1_policy_review
  tests.test_agent_experience tests.test_governance_report
  tests.test_governance_review tests.test_experience_recall_drives_predictions
  tests.test_audit_cursor`: 72 passed in 1.621 seconds, including 15 dedicated
  policy tests. `git diff --check` passed. No live scheduler/provider or production
  data was used.

One fixture initially duplicated sequence 1 and correctly triggered the canonical
cursor's continuity guard; the fixture now asks the real producer for a second
event, so the row-limit assertion exercises a valid source. The cursor's required
grandparent directory was also provisioned before its first safe checkpoint.
These fixes did not weaken integrity checks or assertions.

## Fairness correction after integration review

Coordinator review identified starvation in selecting the same lexically first
`max_files` logs on every maintenance run. Against `8d49003`, two genuine
Guardian-produced audit logs with `max_files=1` still yielded only one experience
after two runs; a corrupt first source kept the second source at zero. Both exact
assertions now pass. A separate oversized-first-source control also passes.

Discovered sources now rotate by their last attempted check time, unseen/oldest
first. Zero-content `<source-hash>.checked` markers in the existing cursor
directory retain only derived attempt timestamps, including unsuccessful source
checks. They are not event/feedback truth and cannot advance canonical audit
offsets. Empty successful scans persist their canonical cursor normally. Failed
sources retain their audit offsets but no longer monopolize the file budget.
Invalid marker files are explicitly reported and excluded from this run, so they
cannot consume every attempted-source slot. No inventory, actor or scheduler was
introduced.

The separate `max_entries` discovery limit intentionally remains bounded. It does
not provide resumable discovery past arbitrary directory sizes. Truncation or
unreadable discovery sets `discovery_complete=false` and
`automatic_coverage=partial`; the weekly report explicitly says discovery is
incomplete and that undiscovered logs are not covered. This limitation was
accepted by the coordinator for this frozen phase; it must not be described as
complete automatic coverage. Fairness is guaranteed within the discovered set,
not outside it.

Final affected run: 76 tests passed, including two-source/max_files=1, warm empty
checks, corrupt-source fairness, oversized-source fairness, and explicit partial
coverage in the weekly report. Existing replay, source cursor-integrity, privacy,
real-producer-to-report and authority-boundary tests remain green.

## Manual-label privacy correction

Independent review reproduced `password:fixture_secret` in manual feedback
labels. Against `565a355`, the new rejection assertion failed for rule_id,
rule_version and reason_code. The common label grammar now permits only ASCII
letters, numbers, underscore, dot and hyphen; colon/equal credential assignments
are invalid. Existing numeric, semantic and SHA256 versions remain compatible.

One dedicated test covers all three fields through builder rejection, direct
record rejection, the actual record CLI, malformed persisted-history injection,
projection rejection and governance source/report handling. Invalid source data
is reported unavailable without echoing the credential. These read-side checks
also reject malformed historical metadata instead of trusting prior persistence.
