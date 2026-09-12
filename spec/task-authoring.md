# Task authoring and dispatch contract

This is a distribution specification, not a knowledge-base article or a record
of an operator's tasks. It is available when the formal corpus is empty.

## Capability and host selection

A new task records `capability_tier: light|balanced|deep`, not a provider model
name. `light` fits bounded mechanical work, `balanced` ordinary implementation,
and `deep` work needing cross-component or uncertain-state analysis. Select the
tier in the task; resolve a host-specific model only at the execution boundary.

Use the current host for work in this session. For a handoff, identify the
target session's provider explicitly. Having another CLI installed is not
permission to change providers. Use the `dispatch-task` Skill and the
host-neutral `model-dispatch` launcher for rendered instructions.

Ordinary Codex dispatch contains the task instruction and preserves session
settings. Do not require model-state inspection or print `/model` / `/reasoning`
selectors. Model advice is opt-in via `--model-advice`; `capability_tier` alone
does not request that advice. Codex 派单禁止混入其他宿主的控制命令或模型标签。

## Two task representations

- Human-readable briefs use the distributed [brief template](../template/_project/docs-hub/00_shared-rules/task-brief.md.template).
- Managed program tasks follow the [managed task contract](task-contract.md).
  Its exact parser is `scripts/kb/guardian_program.py`.

Neither a brief, a tier nor a completed test creates approval authority. Keep
the user's objective, permitted effects, exact scope, acceptance and recovery
method explicit. A changed scope or high-risk decision uses the current host's
human decision route. Do not instruct people to copy opaque authority tokens.

## Evidence and completion

Bind evidence to the candidate inputs actually tested. Report passing, failing,
skipped and environment-blocked checks separately. Choose test scope from the
changed behavior and its consumers; structural validation does not establish
live host enforcement. A task report cannot turn unknown effects into success.

Retain unresolved findings and useful reproducible evidence in the task handoff.
Any optional knowledge contribution uses its own single-writer workflow. The
existence of a knowledge corpus is not a prerequisite for authoring a task.
