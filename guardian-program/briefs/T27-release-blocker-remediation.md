# T27 release blocker remediation

Implement only the frozen T27 task definition. Do not edit production
contracts, JSON/JSONL ledgers, installed plugin caches, LaunchAgent plists or
remote state, and do not run installation or live side effects.

## Required implementation

1. Keep `blocking_attempts()` as the authoritative same-resource safety set.
   Add a separate readiness projection for attempts whose latest intervention
   is already terminal `abort`: keep them visible as quarantined historical
   debt and keep resource matching fail-closed, but exclude them from the
   global current-lane operational gate. Open, acknowledged, retry-authorized,
   reprobe-authorized and unhandled unknown attempts still block readiness.
   Derived pending rows must distinguish authoritative settlement from
   terminal quarantine; never label an aborted unknown as externally settled.
2. In `sulde-status.py`, render a live SessionStart with no fresh prompt as a
   yellow `等待首个提示`; render a previously active session whose prompt TTL
   expired as yellow `空闲，等待下一条提示`. Do not alter the underlying host
   capability gates or synthesize `interactive_ready`. Any serious reason
   outside the narrow waiting set remains red.
3. Add an explicit UTF-8 source declaration to the non-ASCII scheduled
   `auto-distill.py` entrypoint and add a macOS regression that invokes
   `/usr/bin/python3` with the LaunchAgent-style minimal environment and
   `--help` without writing bytecode.
4. Change mem-sync pull to resolve the current symbolic branch plus exactly one
   configured `branch.<name>.remote` and `branch.<name>.merge`, validate both,
   then pass that exact remote/ref to `git pull --rebase --autostash`. Missing,
   detached or multi-valued upstream configuration must fail before pull.
   Add focused unit tests; do not contact a real remote.
5. Update the Codex plugin cachebuster only after source tests pass. Write the
   required task report to
   `guardian-program/reports/T27-release-blocker-remediation.md`, including a
   `沉淀候选` section with Layer1 problem-card fields and route/outcome positive
   and negative samples. Commit only registered owned paths.

## Required tests

- focused intervention/readiness/statusline tests proving aborted debt is
  quarantined globally but the same resource remains blocked across sessions;
- statusline tests for first-prompt wait, idle TTL wait and a real red fault;
- scheduler entrypoint and mem-sync upstream tests, including multi-value and
  detached/missing failure injection;
- relevant existing readiness, intervention, statusline and scheduler suites.

Do not broaden the design if another issue appears. Record it in the report as
an inconclusive finding and stop before changing any unowned path.
