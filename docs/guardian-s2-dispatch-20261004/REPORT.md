# S2 dispatch/prediction candidate

Status: candidate awaiting coordinator integration and independent review.
Input: aa9ffc147c189a5a18c9209c2edec2e8e538d2e1. Authorized revision 5.
Branch: task/guardian-s2-dispatch-20261004. No self-acceptance.

## Scoped changes

- `incremental_facts.py`: directory/module-prefix drift matches the same
  `match_entry` rule used by the completion producer. Git NUL framing preserves
  filename identity; untracked files are enumerated individually instead of
  collapsing new directories. The full observed name set is counted before
  retaining 200 entries. `changed_count_total`, `omitted_count`, `truncated` and
  `comparison=task_baseline_to_worktree` disclose coverage precisely.
- A partial collection yields `suggested_verdict=None, incomplete=True`.
  `prediction_feedback.py` reports degraded, writes no check/verdict, and does
  not replace pending feedback. No new prediction status/schema/approval gate.
- Complete feedback includes at most 12 outside/untouched relative path labels,
  omitted-detail count and comparison scope. Absolute, parent-traversal,
  control-character, punctuation/whitespace-bearing, overlong or sensitive
  filenames are represented only by short SHA256 labels. Ordinary canonical
  Unicode source names remain useful. These are observations, not instructions
  or authority. Paths in original prediction/source records were not redesigned.
- `execution_method.py::execution_method_prompt()` is pure, bounded static text
  projecting the existing task-authoring rules: original stop/budget/read-only
  limits win, repeated no-new-evidence failures require changed diagnosis, tests
  remain task-authorized, partial evidence is not success. No I/O/model/retry
  counter/new lifecycle. Existing Skill/spec/WIP files remain unchanged.
- Existing `_Chain.run` fixture adds `-B` to its real runtime invocation;
  `_Chain.environment` explicitly binds temporary `SULDE_KB_HOME` and
  `SULDE_TEST_EVIDENCE_HOME` for future retrospective/selection consumers.
  These isolate test state without changing task/provider behavior.

## Coordinator-owned glue

No agent-runtime/LIFE/experience/test-evidence source was edited here.

```python
from execution_method import execution_method_prompt
# In execution_prompt's composed text, before skill/intervention/feedback:
{execution_method_prompt()}
```

Stable heading: `--- Sulde 有界执行方法（不新增权限） ---`.
Coordinator must independently prove this full segment reaches real runtime
stdin. Helper-only tests do not establish that wiring. Suggested fixture:
`tests.test_r3_real_entry_chain._Chain`, captured_prompt(), exact helper text
inclusion plus original read-only/stop/budget task preservation. No model needed.

## Normal / baseline-red / candidate-green

All runs used existing venv Python `-B`; final regression also set
`PYTHONDONTWRITEBYTECODE=1` for descendants. New subprocess use is inherited from
the existing explicit UTF-8 fixtures. No paid provider or SSH executed.

Before product edits, normal exact-file scope fixture passed (1 test, 0.049 s).
Then the six fixed `PredictionScopeTests` assertions ran against aa9ffc1:
one passed, five failed (0.364 s):

1. Directory-prefix in-scope change incorrectly returned divergent.
2. More than 200 paths had no truncation/total/omission disclosure.
3. A declared partial fact collection still returned as_predicted.
4. After a valid ordinary feedback artifact was created, truncated subsequent
   observation still returned checked and appended a check instead of degrading.
5. Larger feedback lacked the specific safe relative outside path.

The first exploratory version of case 4 used an invalid placeholder pending
artifact and failed at that artifact's identity validation. That fixture was
corrected to create real normal feedback through the producer, then all six
cases were rerun red **before any production edit**. The invalid placeholder
result is not claimed as a defect reproduction.

The same six assertions passed on the candidate. Added boundaries cover exact
200 vs 201, nested untracked/Unicode/newline names, redaction and 12-label cap,
method text invariants, and real managed stdin delivery of specific scope facts.

Final affected regression after explicit home isolation: **110 tests passed,
15.316 s** (prior pre-isolation run: 110 passed, 15.560 s):

```text
tests.test_guardian_s2_dispatch
tests.test_r3_real_entry_chain
tests.test_incremental_facts
tests.test_prediction_feedback
tests.test_impact_prediction
tests.test_r3_injection_baseline_r2
tests.test_model_dispatch_contract
tests.test_runtime_provider
```

`InputBoundaryTests.test_real_runtime_stdin_receives_specific_overreach_fact`
uses the existing `_Chain`: actual `agent-runtime.py run`, fake provider stdin,
first attempt overreach, explicit existing retry operation, second input includes
`outside expected: consumer.py` and baseline/worktree scope, independent probe
passes. Existing R3 delivery/uncertainty/recovery/identity controls also pass.
This establishes protocol delivery, not improved reasoning by a real Agent.

`git diff --check` passed. No whole-repository run, production install/data write,
dev/main merge, push, cleanup, real external effect or paid model experiment.
Full integrated testing/performance and the method-heading stdin proof belong
to the coordinator. No claim that this small path filter finds every possible
private semantic name; arbitrary sensitive source identities remain a broader
redaction concern outside the observed relative scope labels.

## Candidate source identities

| Input | SHA256 |
|---|---|
| incremental_facts.py | 54ae028d044c86cda8784906350621823f64be61a66b7581d944ee365bfa9a29 |
| prediction_feedback.py | 3d73c1e7ed2ee9628b4b0c12e754fc3f4f4508671d74a85bd9c88a820dc1ccfc |
| execution_method.py | 6ff3d9f00da99d96177c1a32cfe872280a49cbb1b634bb4dede03f169f756c9c |
| test_guardian_s2_dispatch.py | 3ae1285bd8d67d95960391e4448674c74cb3b416df16b0c72bed7de2633a0412 |
| test_r3_real_entry_chain.py | 9d9a1d315b86090ad9aa62803f627b70c1361d98b884af1613ca3edcd8fc4bfb |

Dispatch-task continuous-execution discipline and source task-authoring contract
were followed. KB symptom search found unrelated matches, not adopted rules.
No knowledge-store write or new reasoning/approval machinery was introduced.
