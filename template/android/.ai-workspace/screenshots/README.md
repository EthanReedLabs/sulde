# screenshots/ — UI capture for verify + audit

Screenshots taken during Dev verify (§5 of `skills/dev/assign/SKILL.md`) and during coordinator UI audit subagents.

## Naming

```
{YYYY-MM-DD}-{task-slug}-{before|after|baseline}.png
```

Optional variant suffix for multi-state captures:
- `*-state-loading.png`
- `*-state-error.png`
- `*-state-empty.png`

## What to include

Each Dev verify screenshot should pair with the corresponding design-truth `.png` so the coordinator can diff them.

## What does NOT go here

- Asset images (icons, logos) → those live in the design-source MCP and get copied into the source tree by Dev during implementation
- Generic UI references → those live in `<docs-hub>/design-truth/{page-id}.png`
