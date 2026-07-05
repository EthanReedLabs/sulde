# handoff/ — dev → coordinator post-execution docs

Each `*.md` is the Dev's report after running a task. PreToolUse hook `check_handoff_verify.py` enforces the 5-section format defined in `skills/dev/handoff/SKILL.md`.

## Naming

```
{YYYY-MM-DD}-{slug}-{result|block|selffix|audit}.md
```

| Suffix | When |
|---|---|
| `-result.md` | Task completed successfully |
| `-block.md` | Blocked mid-task; needs coordinator decision |
| `-selffix.md` | Dev-initiated change within `self-fix-boundary.md` allowlist |
| `-audit.md` | Result of an audit subagent run |

## Required sections

- `§ 改动文件清单` — files touched with line refs
- `§ verify` — build / install / log / screenshot evidence
- `§ escalation 候选` — coordinator-decision items (or "本任务无 escalation")
- `§ 时序约束 / 性能数据` — only when task involves perf
- `§ baseline 反向 verify` — only when task-md baseline drift detected

## Archive

Coordinator moves processed handoffs to `handoff/archive/` after follow-up actions are dispatched. Treat `handoff/archive/` as historical record — do not edit.
