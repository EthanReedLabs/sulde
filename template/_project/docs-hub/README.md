# docs-hub — coordinator-owned project documentation

This directory is the **coordinator-side knowledge base** for a sulde-cc project. Dev sessions read from here but only the coordinator writes here.

## Layout

```
docs-hub/
├── 00_shared-rules/       # rules every session reads (P3 fills with mobile defaults)
├── design-truth/          # canonical UI / interaction truth per page (you fill from your design source)
├── ADR/                   # anti-pattern decision records (registry of recurring incidents)
├── coordinator-todos.md   # rolling todo list — what the coordinator is tracking
└── scaffold-map.yaml      # (optional) declared scaffold components + triggers
```

## Ownership rules

| Path | Who writes? | Who reads? |
|---|---|---|
| `00_shared-rules/*` | Coordinator | All sessions (coord + every dev) |
| `design-truth/*` | Coordinator (via `update-design` skill) | All sessions |
| `ADR/*` | Coordinator (via `coordinator-maintenance` skill) | All sessions |
| `coordinator-todos.md` | Coordinator | Coordinator |
| `scaffold-map.yaml` | Coordinator (via `/sulde-add-scaffold`) | All sessions |

**Dev sessions never write to `docs-hub/`.** If a Dev needs something changed here, they open a handoff with an escalation candidate; the coordinator updates it.

## Files shipped with this template

- `00_shared-rules/README.md` — navigation; the 5 rule files themselves are seeded in P3.
- `ADR/INDEX.md` + `_frontmatter.schema.yaml` + `0000-example.md` — registry skeleton + format spec + one demo ADR.
- `design-truth/README.md` + `_example.md.template` — placeholder + example so the dir survives `git add` and shows the expected format.
- `coordinator-todos.md.template` — start-here todo list (rename to `.md` after init).

## After `/sulde-init`

1. Bootstrap `design-truth/` from your design source — `/update-design` reads `.sulde-config.yaml: design_source` and exports per-page truth docs + screenshots.
2. Adapt `00_shared-rules/*` defaults to your team (data sources, self-fix boundary, verify recipe, perf gate, model strategy).
3. Replace `0000-example.md` with your first real ADR once a pattern actually recurs in your project.
