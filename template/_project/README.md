# sulde — project root template

This directory is the **project root scaffold** that `/sulde-init` copies into a new sulde project. After running `/sulde-init`, your project root will look like:

```
your-project/
├── .sulde-config.yaml          # filled by /sulde-init from .yaml.example here
├── .gitignore                  # merged from .gitignore.template here
├── .sulde-grace-started        # 7-day grace marker (auto, gitignored)
├── docs-hub/                   # coordinator-owned docs (skeleton from this template)
├── scripts/                    # baseline + health scripts (templates here)
└── {frontend-dirs}/            # one per `.sulde-config.yaml: frontends[]`
                                # each copied from template/{stack}/
```

## What lives here

| Path | Purpose |
|---|---|
| `.sulde-config.yaml.example` | Full annotated config; `/sulde-init` walks the user through filling it. |
| `.gitignore.template` | Conservative project gitignore — covers `.sulde-grace-*` markers + `.claude/` (no AI traces in git) + general OS / editor noise. Your existing `.gitignore` is **appended**, not overwritten. |
| `scripts/` | Coordinator-side automation: `coordinator-baseline.sh.template` + `health-check.sh.template` (renamed to `.sh` during init). |
| `docs-hub/` | Coordinator-owned documentation root. Sub-skeletons for `00_shared-rules/` (P3 fills), `design-truth/` (you fill from your design source), `ADR/` (P3 ships 3 mobile examples). |

## What does NOT live here

- **Per-frontend scaffolding** lives in `template/{android,ios,flutter,harmony}/` and is copied into each `frontend[].path` separately.
- **The hooks themselves** ship in `${CLAUDE_PLUGIN_ROOT}/hooks/` and are loaded from the plugin install — not from this template.
- **Skills** are loaded from the plugin install at `${CLAUDE_PLUGIN_ROOT}/skills/` — not from here.

## Post-init checklist

After `/sulde-init` runs, the coordinator should:

1. `pip install pyyaml>=6.0` (Python hook dependency)
2. Run `/sulde-add-team-member` for each developer
3. Read `<docs-hub>/00_shared-rules/*` and adapt the defaults to your project
4. Bootstrap `<docs-hub>/design-truth/` from your design source (Pencil / Figma / etc.)
5. Either let the 7-day grace period expire naturally, or `/sulde-end-grace` to switch to `enforcement_level: balanced` immediately

## See also

- `${CLAUDE_PLUGIN_ROOT}/docs/V0.2.0-DESIGN-v2.md` — full spec
- `${CLAUDE_PLUGIN_ROOT}/docs/GETTING_STARTED.md` — user-facing walkthrough
