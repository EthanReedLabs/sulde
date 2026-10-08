# release-2026-09-21 — blocker triage

> Corrected 2026-09-23: the historical suite was not fully passing. The earlier
> Darwin/Seatbelt write-escape diagnosis is withdrawn; the recorded failure
> does not establish that a forbidden file was created. See the
> [evidence correction record](release-evidence-corrections-20260923.md).

## Scope carrying this release

- `17b1c31` fix(distill): rejected annotation samples no longer stall the pipeline.
- `ce62ec9` fix(mem-sync): increase scheduled exponential backoff to 62 seconds;
  this is a bounded mitigation, not proof that every opposite-phase run fits.

## Suite evidence

Integrated tree (dev `ce62ec9`): full suite 3 failed / 2384 passed / 26 skipped /
2334 subtests passed in 1144.44s (PYTHONDONTWRITEBYTECODE=1, kb venv 3.10,
`-p no:randomly`). The same three test names failed on the unmodified `dev`
baseline (`1defc75`): no additional failing test names were observed in the recorded
comparison. This does not establish identical causes, absence of every
regression, or a fully passing release-level verification.

## Blocker triage

| # | Test | Verdict | Evidence |
| --- | --- | --- | --- |
| 1 | `test_native_control_composition::test_real_safe_batches_negative_and_partial_failure` | Path/environment-sensitive; underlying cause inconclusive | Recorded Guardian child lock access fails with EPERM under `/var/folders`. The baseline rerun passes with relocated `TMPDIR`; this establishes a workaround for that run, not an OS root cause or universal safety. |
| 2 | `test_native_session_continuity::test_denied_call_does_not_lock_the_following_ordinary_call` | Path/environment-sensitive; underlying cause inconclusive | Fails in the baseline comparison and passes with relocated `TMPDIR` alongside #1. A shared permissions cause is plausible, but not independently established by the summarized trace. |
| 3 | `test_isolated_test_runner::test_os_boundary_blocks_non_python_write_before_file_appears` | Preflight exception-text assertion failed; underlying cause inconclusive | Session tool receipt L1150 identifies baseline line 783. At `1defc75`, that line is `assertIn("write denial", str(error))`; line 782 first asserts the target does not exist. This rerun failed while interpreting a preflight exception, before the subsequent write probe. It does not prove a file appeared or a Darwin/Seatbelt protection regression. |

## Boundaries

- No product behavior was changed to make #1/#2 pass; the workaround is a test
  environment variable only, documented here rather than encoded.
- All three historical failures remain unresolved in this record. Baseline
  reproduction is not an acceptance waiver. The earlier phrase "accepted open
  blocker" is withdrawn: this evidence does not establish release-level passage
  or an independently recorded exception approval.
- Capture complete preflight stderr, the exact command/interpreter/environment,
  and the target's before/after state to diagnose #3. Do not infer safety or
  vulnerability from the test name or the truncated assertion summary.
- Live-install acceptance for `release-2026-09-21` is a separate record; this
  document covers the dev-integration verification only.
