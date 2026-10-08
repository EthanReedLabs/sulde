# S2 experience candidate

Input: `aa9ffc147c189a5a18c9209c2edec2e8e538d2e1`; human-approved revision 5.
Candidate only: coordinator integration, cross-consumer verification and independent
review remain required. No production data, factual KB, scheduler installation,
paid model, dev/main merge or push. Runtime/LIFE/evidence/derived-details source
remain with their assigned owners.

## Delivered interface

`experience_maintenance.record_run_retrospective(home, *, task_id, run_id,
project_id, session_id, task_instance_id, occurred_at, status, returncode,
stop_reason, report_passed, quiescent, findings_count, open_effects,
evidence_sha256)` writes one bounded owner-only inbox file. There is no historical
experience scan on the task completion path. It returns `queued`, `duplicate`,
`degraded`, or `non_run`, with `task_status_changed=false` and
`execution_authorized=false`. Errors disclose exception types, never source text.

The coordinator must supply actual final status AFTER report/invariant resolution.
The inspected producer is `execution_backend._event`, type `execution.result`,
field `at`; `replay_run_ledger().result` retains that field. `RunResult` itself has
no timestamp. Missing run gives a non-run diagnostic; missing/naive/future time
degrades. Evidence keys are exactly terminal/status/report/binding/output/summary,
each containing a SHA-256, never prompt/output text. Identities are hashed.

Even a clean final success (completed, rc=0, passed report, quiescent, no open
effects/findings) is only `inconclusive` / `managed_run_no_issue`: a bounded
observation, not verified strategy. Failed/timeout/paused/awaiting-human or
contradictory facts remain unresolved. The inbox and canonical experience identity
is stable by task/run/task-instance; changed terminal time/body conflicts rather
than creating a second canonical run. Repeating after successful merge is safe.

`maintenance(home, *, apply=False, now=None, max_batch=250, max_entries=4096)` is
for the EXISTING LIFE actor. Dry-run creates no directories or files and changes
no mtimes. Apply validates at most 250 discovered inbox objects of at most 16 KiB
each; directory enumeration stops at 4096 entries. Corrupt sources rotate via
transport-only mtime, without changing terminal fact time. Partial discovery and
backlog are explicit; unseen entries are not claimed covered.

The existing canonical `experience/agent.jsonl` remains the only experience truth.
`record_many` uses the existing lock, one batch rewrite, independent full-row
readback and canonical directory fsync before transport acknowledgment. Merge
failure retains inbox; a crash after persistence but before acknowledgment replays
without duplication. Historical work is off the hot path and bounded to 16 MiB;
larger history degrades without deleting records. This is eventual consistency,
not a synchronous persisted-retrospective claim on runtime return.

## Maintenance, privacy and retention

- Daily and rolling-seven-day weekly projections are regenerated from canonical
  rows, capped at 250 groups with explicit completeness. Review projections are
  not pending-candidate settlement; original history remains. The existing weekly
  governance collector and deterministic report section consume this projection,
  including when optional LLM output fails.
- The LIFE helper reuses U05's existing bounded ingestion and projection. Managed
  worktree audit discovery is explicitly `unavailable_no_authoritative_registration`:
  no new global registry, arbitrary-root scan or invented authority. Existing
  home workspace/session coverage is unchanged. Runtime terminal counts are not
  per-tool dispute attribution.
- Generic optional recommendation/component fields now reject raw private paths,
  credential assignments, nonlists, nonstrings, excess lengths/counts and control
  text on direct writes/readback, not only through the builder. Existing policy
  audit-only validation remains intact.
- Recall accepts only nonnegative integer TTLs and aware reference times. Future
  verified rows cannot drive strategy, even when no expiry TTL was requested;
  they are counted as `future_verified_excluded`. Unresolved history stays intact.
- The self-repair retrospective failure boundary logs a redacted degraded warning
  without changing its already persisted outcome. A closed diagnostic stream is
  also contained. Existing scoped-acceptance verified behavior is unchanged.
- Only redundant no-issue inconclusive renderings are produced under explicit
  `home/experience/derived-details`. Their source experience IDs and day allow
  rebuilding from retained canonical history. They are NOT authoritative JSONL,
  unresolved rows, pending review candidates or verified aggregates. Other statuses
  never enter this detail store. Existing `review.json` stays outside cleanup.
- Retention consumes the assigned owner's existing plan -> reversible quarantine
  -> independent readback API, with TTL 30 days / capacity 250, sourceVersion
  `sulde-agent-experience-v1`, generatorVersion `sulde-experience-maintenance-v1`.
  Dry-run precedes every move. No candidates means no quarantine creation.
  Quarantine is retained; no automatic permanent deletion is introduced. Corrupt
  or protected manifests remain and are disclosed. This is housekeeping only,
  not a readiness/authorization gate.

## Evidence and original failures

All Python commands used `/Users/eric/.sulde/data/kb/venv/bin/python -B`, explicit
UTF-8 for subprocess text, and disposable homes. No whole-repository suite here.

1. Original normal control: `tests.test_agent_experience`, 4/4 passed, 0.017 s.
2. Baseline optional-field injection: 8 subcases failed at unchanged
   `assertRaises(ExperienceError)` on direct `record()` (secret/path/type/length,
   both optional fields). Candidate passes the same assertions.
3. Candidate affected module run: 103/103 passed, 2.880 s.
4. Formal isolated affected modules: 121/121 passed, 7.508 s before the final TTL
   boundary addition. Final run is recorded below and in handoff.
5. Requested TTL baseline counterexample: aware `+00:00` reference with a future
   verified row incorrectly selected verified strategy, with TTL 30 days and
   TTL omitted (two failing subcases). The unchanged strategy assertion now
   passes; added invalid TTL/reference tests and unresolved retention checks.
6. Final formal isolated run of all eight modules: **123/123 passed, 7.496 s**,
   exit 0. Production-write-denial preflight passed; no production-write attempt
   was reported. `git diff --check` passed. No paid model operation was invoked.

Formal command (same modules for the final run):

```sh
/Users/eric/.sulde/data/kb/venv/bin/python -B scripts/kb/run-isolated-tests.py \
  tests.test_agent_experience tests.test_guardian_s2_experience \
  tests.test_guardian_s1_policy_review tests.test_governance_report \
  tests.test_governance_review tests.test_self_repair \
  tests.test_experience_recall_drives_predictions \
  tests.test_subprocess_text_encoding_guard
```

New cases cover successful/no-issue and failed/timeout/pause terminal facts,
provider-zero/contradictory stop reason, no-run/missing time, privacy, idempotency
before/after merge, no hot-path historical reads, write/readback/fsync/ack failure,
corrupt-source fairness, bounded discovery, dry-run bytes/mtime identity, fresh
process producer+maintenance -> existing experience CLI, actual weekly main with
offline optional model, and actual produced detail TTL quarantine with authority
and unresolved records byte-identical. Coordinator owns actual runtime -> LIFE
glue and paired timing evidence; these are NOT claimed by this helper-only lane.

Fixture mistakes retained: the first optional-field probe reused an existing
experience ID and was rejected by collision rather than privacy. Distinct IDs
exposed all eight baseline failures. A readback fault initially patched runpy's
returned mapping rather than function globals; it did not inject the failure.
Patching `record_many.__globals__` made the intended readback failure observable;
the assertion was not relaxed. Expected existing offline-LLM and malformed-draft
negative-control diagnostics are not suite failures.
The first future-time probe used a `Z` reference that Python 3.10's old direct
fromisoformat path rejected; switching its reference to aware `+00:00` isolated
the actual future-authority defect. Candidate normalizes both representations.

## Skill use / sedimentation candidate

Dispatch-task's bounded continuous-execution discipline retained control ->
injection -> actual entry -> affected tests. KB search returned two unrelated
hits and `work-model/idempotent-registration-verifier-contract`; its complete
source was read and its matching boundary applied: shared stable identity,
independent readback and replay without elevating observations into authority.
No KB or memory write was made.

Layer1 candidate (coordinator dedup only): terminal observations must not change
business status, and transport acknowledgment must follow durable canonical
readback. Evidence status: verified in isolated fixtures, not production.
Route apply: bounded local retrospective queue with stable run identity;
route skip: unknown external side effects requiring human authority.
Execution pass: write/readback/fsync before ack, immutable retry collision,
failure leaves unresolved/diagnostic state. Execution fail: provider rc=0 promoted
to verified or inbox removed after an unverified/no-op canonical write. Preserve
this distinction when applying the pattern elsewhere.
