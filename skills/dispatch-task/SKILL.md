---
name: dispatch-task
description: Generate host-appropriate task-start instructions for Claude Code or Codex. Use for a “给 Dev 发送” block, task signing/amendment, or when an Agent continues an existing task. Codex dispatch defaults to task-only text; model/reasoning tier advice is optional and only given on explicit user request.
---

# Dispatch Task

Default Codex dispatch contains only the task instruction and acceptance requirements. Keep the
target session's current model and reasoning configuration without showing selectors, model names,
capability checks, or a “no switch needed” preamble. Unknown model state does not block dispatch.

## Resolve the target

1. Read `capability_tier` from the task: `light`, `balanced`, or `deep`.
2. Resolve the provider of the **target execution session**, not the coordinator's machine:
   - use the user's explicit `Claude Code` or `Codex` statement first;
   - when sending to the current session, use the current host;
   - when unknown, ask which host will execute the task and emit no dispatch block.
3. Do not inspect the current model/reasoning for ordinary Codex dispatch. Only collect that
   information if the user explicitly asks for model advice; omit unknown current-state arguments.

Installing another CLI is not evidence that it owns the target session.

## Render the instruction

Use the stable launcher:

```bash
SULDE_MODEL_DISPATCH="${SULDE_HOME:-$HOME/.sulde}/bin/model-dispatch"
"$SULDE_MODEL_DISPATCH" \
  --provider <claude|codex> \
  --tier <light|balanced|deep> \
  --task <task-path>
```

Do not use `--fresh-session` for an amendment or “继续原任务”.

Paste the renderer's stdout verbatim beneath “给 Dev 发送”, then append task-specific prose.
An older installed renderer may still emit model controls. For ordinary Codex dispatch, do not
forward that legacy preamble: write the task path/content directly and preserve current settings.
Do not modify immutable caches or require an installation merely to format a task.

## Explicit model advice only

Only when the user explicitly requests model advice, add `--model-advice` and the available
`--current-model`, `--current-tier`, and `--current-effort` arguments. `--required-effort` is valid
only in this advice mode. A task's capability_tier alone is not such a request.

The current default mapping is:

| capability tier | Codex model | minimum reasoning |
|---|---|---|
| `deep` | `gpt-5.6-sol` | `high` |
| `balanced` | `gpt-5.6-terra` | `medium` |
| `light` | `gpt-5.6-luna` | `low` |

If that exact model is unavailable in the target account, select the same tier or higher from the
target Codex `/model` picker. Preserve a current model/reasoning pair that already meets the floor.
`xhigh` and `max` are reasoning levels, not model names.

Only advice-mode Codex output may use `/model` and `/reasoning`. Codex 派单禁止出现 Claude
model families, Claude thinking phrases, `/mode`, `/assign`, `/clear`, or `ralph-loop`.

## Verify

Before sending, confirm:

- the task file still stores only `capability_tier`, never a provider model name;
- the rendered provider equals the target session provider;
- ordinary Codex output contains no model/reasoning advice or readiness preamble;
- explicit advice output matches the target provider;
- a continuing task stays in the same session unless the user explicitly requested a fresh one.

If advice-mode rendering is unavailable, report that limitation without inventing selector commands.
Ordinary task-only dispatch can proceed without the renderer. This skill controls interactive
handoff text, not model selection by managed background Agent runtimes.
