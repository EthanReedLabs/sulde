# Guardian receipt consistency — integration report

Date: 2026-09-10
Status: R11 ACCEPTED / SOURCE INTEGRATION COMPLETE

## Original source preservation and validation

The user stopped the previous writer and authorized takeover/commit/merge.
ORIGINAL.json preserves the original eight-file input against dev@3d4df54.
Production runtime, main, prior local evidence refs and the memory release
worktree remain unchanged. No install or remote push is part of this phase.

Original scoped run `20260910T103154973567Z-original-scoped-r2`:
104 passed, no skips/failures/errors, 10.225 seconds (11.009 with wrapper).
Semantic source before/after:
`adc38656b8ca9448f7882e8c5b57d5f3aff4c4e4d67c6c77a3dc294e5e08cc85`.
Log SHA256: `06c847bce4f518d1f3ade71098caa8f386b0b3df5851cf63ef44209b2bcc422b`.
This is the original source task, not evidence for the upcoming combined tree.

The first run failed during test import. Two new files used bare sibling test
imports incompatible with the supported module runner; package-qualified imports
fixed this without changing runtime behavior. The Agent also named a nonexistent
architecture module; that command-selection mistake was removed, not skipped.
Original receipt and composition runtime implementations remain preserved here.
Both failed and passed run logs are retained locally.

## Integration with dev

Original task commit: `8ffb86165ec5f9caf8510d2899de42133d468ccd`.
Integration parent: `77c5929d7a69ffada7b205d431db82e24bd4e87c`.
The composition, resources and policy modules retain the accepted dev bytes,
including CompositionServices and canonical host-call identity. The original
branch's duplicate dependency-interface extraction and unused-import cleanup are
preserved in its parent commit, not layered on top of an equivalent dev design.
Architecture regressions now compare against the explicit accepted dev baseline;
they still enforce callback-only dependencies, no cycles/delayed imports, frozen
services, ordinary-call fast path, public exports and the policy line budget.

Receipt-only tail entry and contract-applied recovery now use the existing
ordered native decision lock. For selected-task continuation it holds the
current contract, source contract and session mapping, not just one contract.
New tests use a fresh subprocess to attempt each real file lock at effect,
contract and anchor boundaries. Each interruption releases all three locks;
recovery reacquires them, commits once, and creates no duplicate receipts or
copied grants/authorized/open/pending/continuation-use state. These are disposable
state-machine tests, not a substitute for actual host evidence.

Combined scoped run `20260910T104116015149Z-integrated-scoped`:
166 passed, no skips/failures/errors, 14.905 seconds (15.909 with wrapper).
Semantic source before/after:
`6d8bcf79def14c4624f9e8648db053ee2db0f45279243d547e965a06d6620701`.
Log SHA256: `5f8ca58c0ae900520a4296b8d3f81db1f7b2f0bb7217395aed6b3bbbed8e9834`.
Actual interpreter recorded by the runner: Python 3.14.6, macOS 26.3 arm64.

The first full attempt `20260910T104250006805Z-integrated-final-full` was
interrupted (exit 254, 432.730 seconds), not passed. The Agent invoked PATH's
Python 3.14.6 without PyYAML. Two isolated installer failures reproduced this
same dependency-preflight error, not a receipt correctness failure. Log SHA256:
`a0efff8d78b8969e2f6da7b789e4a466ce77e4530ebbd16705d67646c800db85`.
Reproduction log SHA256:
`6492aea7401eca1dc852f90d2d0f7dcea0be1673a8c9e378de7bd1f3554a86fe`.

The task-local runner now invokes the existing release Python preflight before
launching tests and records the interpreter/dependency identity. There is no
dependency install, fallback interpreter search or production-runtime change.
The same wrong invocation now stops before any suite runs in 0.173 seconds
(expected exit 3, `20260910T105046443990Z-wrong-python-preflight`).
The already available explicit Python 3.10.7 has PyYAML 6.0.3. Its targeted rerun
and complete full-suite result, followed by R11 acceptance, are recorded below.
All failed/interrupted evidence remains non-reusable.

## Final acceptance (native R11)

The full supported-environment run completed 2,119 cases in 1,180.067 seconds:
2,093 passed, 25 skipped, one failed static encoding gate. All runtime, native
CLI/Hook/MCP and performance cases passed. Its failed exit code is retained;
this report does not relabel that original run as green.

Native revision 11 receipt
`721658f984668f319ac0a341f195b3b980bca0633af94feda03fde3ed851cbda`
approved impact-bounded acceptance. The only executable delta after the full run
is explicit UTF-8/replace decoding on five subprocess calls in three test files.
The all-repo encoding guard, changed modules, their importer/fixture dependencies
and a fresh real PreTool candidate test were rerun: **123 passed, zero skipped or
failed**, 29.730 seconds (30.683 with wrapper). Final semantic source:
`fcd6147b6dff476190d38fcecf8c6395d799fe836d1dbe1ddc538d92619476fb`.
Final log SHA256:
`bae001e87137c5626f42b66e315b766ddd498e81d50bf1af3ad4e855addd404d`.

The full-run source tree `b06270a92546c0dcceae32bcee10a97bc8841e20`
is retained by `refs/sulde/evidence/guardian-receipt-consistency-full-20260910`.
Independent replay of its 1,586 non-evidence Git blobs/modes exactly matches the
full run's semantic source SHA. The post-full diff contains only those three
test files plus task plan/report/evidence. Product source is unchanged.
EVIDENCE.json retains all nine run identities, independently rehashed logs,
the exact test-only patch, performance samples and native observations.

Fresh final candidate and full-run candidate identities match:

- artifact: `0.2.5+codex.20260909091120-48e0594354:ffb168348ea693b5322047a49d470ec7a9634be89b0caff0552d39430d688507`
- loaded module: `4eebf26591f75d8100704ecbbde2df0d8e0eae472688067be63ceee05ccc87d0`

Actual isolated host checks include typed memory writes and attribution denial,
lost-Post recovery without reexecution, separate-session native Allow/Deny,
post-continuation writing without copied authority, composed calls, destructive
PreTool denial before marker creation, and continuation after a rejected call.
CLI/app-server, unified exec and candidate Hooks are real; the model/one-shot
human decisions are narrowly scoped fixture inputs, **not production clicks**.
Ordinary outside-plan local writing remains allowed by the accepted dev policy;
the exercised destructive negative is not presented as a general path firewall.

Final acceptance is a full-run plus proven test-only-delta composition, not a
claim that every case was reexecuted on the final test-script bytes. Windows and
outer-sandbox skips remain unverified platform domains. Merge is authorized;
production installation, remote push and resource cleanup remain paused.

## Performance and remaining boundaries

The request-prefix reuse is successful-validation-only, bounded to 512 entries
and local to one receipt-chain invocation. Tests confirm at most five underlying
prefix verifications for a five-request history in the real tail; a separate
call starts empty. Source append/replacement/truncation/disappearance, same-size
tampering and changes during a replay pass invalidate or reject reuse. This is
not an authorization cache and does not relax exact-byte or noncooperating-writer
checks. No claim is made about a measured percentage improvement in installation
or end-to-end Agent time.

The existing single-call performance gate passed against its fixed baseline:
read median 341.033 → 337.363 ms, local-write 338.278 → 336.913 ms and control
337.545 → 336.168 ms. Control p95 rose 362.978 → 376.125 ms but remained within
the fixed 10%/2 ms gate. This does not establish zero latency change or whole-Agent
speedup; complete measurements are in EVIDENCE.json.

Production install/push/cleanup are out of scope. The memory task's pending
cachebuster receipt observation and uncommitted release note remain preserved;
this merge must not be mistaken for resolution of that separate install gate.

## Candidate knowledge (not production KB writes)

### Layer1 — compose receipt locks with the actual ownership model

Task and intent: regression/integration; merge the stopped receipt task while
preserving accepted new-session isolation and explicit native continuation.
Trigger: a single-contract receipt-tail repair overlaps a dual-contract route
handoff introduced on dev.

Observation: the mechanical merge retained two receipt-tail entries using only
the destination contract lock, while dev's selected-task writer locks both
contracts and the session route. Root cause is an incomplete composition of lock
boundaries, not a missing native Allow or reason to transfer old grants.
Evidence status: verified for the source overlap and isolated regression;
production incident causality remains inconclusive. Evidence: the integration
diff, 166-test run and 18-test supported-interpreter rerun. The original 104-test
single-contract result alone did not cover selected-task ownership.

Correct handling: use the existing ordered native decision lock; independently
probe all three file locks through the receipt tail and interrupted recovery,
then verify one committed transaction/receipt set and no authority copying.

| Sample | Content | Expected | Reason | Source |
|---|---|---|---|---|
| Routing positive | Receipt source spans a selected-task handoff | apply | Multiple authoritative files share one semantic transition | observed source overlap |
| Routing negative | Ordinary read with no receipt/route mutation | skip | No receipt consistency critical section | constructed |
| Execution qualified | Three real locks held at each tested boundary, recovery commits once | pass | Preserves source consistency and ownership | observed isolated tests |
| Execution failure | One-contract success used to claim a dual-contract boundary safe | fail | Omits the source and route writers | constructed; not claimed as a live incident |

Upward boundary: remove local paths, session/receipt IDs and repository commits.
Reusable core: concurrency evidence must cover the ownership model of the
integrated tree. Suggested container: work-model; consumers: review checklist
and integration-test design. Candidate only; no production KB/memory write.

### Layer1 — preflight the chosen test interpreter before a full run

Task and intent: workflow; complete one useful full integration acceptance
without dependency repair loops. User expectation: Agent handles execution and
records its own problems; do not make ordinary tasks wait on avoidable setup.
Trigger: invoking a task wrapper through PATH when another verified Python was
already available.

Observation: many installer samples failed on missing `yaml`; the Agent's
invocation selected Python 3.14.6 without PyYAML. Evidence status: verified.
Two targeted samples reproduced that preflight failure and passed with explicit
Python 3.10.7/PyYAML 6.0.3 without runtime source changes. This excludes receipt
logic as the cause of those two failures, not every possible full-suite issue.
Correct handling: reuse the release environment preflight in the task runner,
record interpreter/dependency identity, fail before the suite, and never silently
install packages or switch environments. Negative preflight took 0.173 seconds;
18 supported-environment tests passed.

| Sample | Content | Expected | Reason | Source |
|---|---|---|---|---|
| Routing positive | Full candidate tests launched with an unverified PATH Python | apply | Candidate requires a particular interpreter dependency set | observed |
| Routing negative | Read-only Git diff without Python execution | skip | Python dependencies do not affect this operation | constructed |
| Execution qualified | Preflight rejects wrong interpreter before suite; explicit verified environment passes | pass | Evidence is bound to the actual executing environment | observed |
| Execution failure | Missing dependency is treated as many unrelated code regressions, or interpreter silently changed | fail | Wastes testing and breaks provenance | observed fan-out; silent switching is constructed |

Upward boundary: remove machine/user paths and local evidence IDs. Reusable core:
an existing environment preflight must be reached by the outer expensive test
entrypoint, not only deep installer cases. Suggested container: anti-patterns;
consumers: task runner and Agent execution checklist. Candidate only.
