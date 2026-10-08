# P0 Sulde Local Live Acceptance — Frozen Scope

## Authority and baseline

- Program: `guardian-remediation-r97`
- Coordinator / single writer: `guardian-coordinator`
- Source baseline: `7cbd14378f8124efccf0333c7d414f939b0d1e2c`
- Integration branch: `dev`
- Successor: `T29-sulde-local-live-acceptance`
- Superseded release task: `T27-release-blocker-remediation`
- User boundary decision: after confirming the iquokka task was complete, the user
  rejected further coupling between Sulde release acceptance and that external
  project's live task state, then explicitly requested the next step.

## Frozen correction

T29 changes only the release acceptance boundary. It inherits the verified T27
and T28 source, test, merge, install and scheduler evidence. It does not reopen
or modify product code.

1. The two historical iquokka sessions remain reproduction evidence for the
   original false blocking incident.
2. Their current task epoch, lane or task lifetime is not a Sulde release gate.
3. No T29 step may write, rebind, revise or otherwise operate on iquokka.
4. Current-generation live acceptance is performed in a Sulde-owned workspace
   by a Codex session started after the official plugin install.
5. The canary must use real host hooks and doctor evidence. Synthetic callbacks,
   old receipts and manual production-ledger edits remain forbidden.

## Explicit non-goals

- No source code, plugin manifest, installed cache or LaunchAgent change.
- No repeat of the already passing 1356-test isolated suite.
- No additional decomposition, feature or cleanup task.
- No external project source inspection or business-task execution.

## Completion order

1. Record and resolve the invalid cross-project gate through the append-only
   control plane; supersede T27 with T29.
2. Prove the T27/T28 source ancestry, installed generation and scheduler 15/15.
3. Start one new Codex session in the Sulde repository and collect current
   runtime SessionStart, prompt and supervision truth.
4. Register T29 evidence, merge control records through `dev` to `main`, run the
   program final check, and remove merged stale worktrees only after acceptance.
