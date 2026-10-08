# Project scripts (sulde-cc)

This directory holds **coordinator-side** automation scripts. They run at the project root (not per-frontend) and surface session-start context for Claude Code through the SessionStart hook.

## Files

| Script | Purpose | Hook integration |
|---|---|---|
| `coordinator-baseline.sh.template` | One-shot snapshot of cross-frontend state: recent commits, active handoffs, archived handoffs, branches. Emit ~50 lines to stdout. | Read at SessionStart via `.sulde-config.yaml: session_baseline.baseline_script`. |
| `health-check.sh.template` | Drift detection: declared scaffolds vs. actual files, page-relation diff, infrastructure status. Emit ~40 lines. | Read at SessionStart via `.sulde-config.yaml: session_baseline.health_script`. |

## Naming

Templates here ship with `.template` suffix to make `/sulde-init` copy semantics explicit. After init they are renamed to `*.sh` and `chmod +x`'d.

## Customising

These templates assume a typical sulde-cc layout (`{frontend}/.ai-workspace/handoff/` etc.). Adapt to your repo by editing the `FRONTENDS=` array at the top of each script — `/sulde-init` does that automatically from `.sulde-config.yaml: frontends[]`.

## Running outside Claude Code

You can call them manually:

```bash
bash scripts/coordinator-baseline.sh > .ai-workspace/baseline/latest.md
bash scripts/health-check.sh > .ai-workspace/health/latest.md
```

These outputs are also what the SessionStart hook injects as `additionalContext` for the next Claude Code session.
