# sulde-cc — project root template

This directory is the **project root scaffold** that `/sulde-init` copies into a new sulde-cc project. After running `/sulde-init`, your project root will look like:

```
your-project/
├── .sulde-config.yaml          # filled by /sulde-init from .yaml.example here
├── .gitignore                  # merged from .gitignore.template here
├── .sulde-grace-started        # 7-day grace marker (auto, gitignored)
├── docs-hub/                   # coordinator-owned docs (skeleton from this template)
├── knowledge/                  # empty, project-owned reusable knowledge kit
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
| `docs-hub/` | Coordinator-owned documentation root with shared-rule, design-truth, and historical ADR skeletons for the adopting project to complete. |
| `knowledge/` | Empty schema and containers for the adopting project's de-identified reusable knowledge. |

## What does NOT live here

- **Per-frontend scaffolding** lives in `template/{android,ios,flutter,harmony}/` and is copied into each `frontend[].path` separately.
- **The hooks themselves** ship in `${CLAUDE_PLUGIN_ROOT}/hooks/` and are loaded from the plugin install — not from this template.
- **Skills** are loaded from the plugin install at `${CLAUDE_PLUGIN_ROOT}/skills/` — not from here.

## Post-init checklist

After `/sulde-init` runs, the coordinator should:

1. Install Python 3.10+ and `python3 -m pip install -r "${CLAUDE_PLUGIN_ROOT}/hooks/requirements.txt"`.
2. Run `sulde doctor --project "$PWD"` and `sulde kb lint --root "$PWD"`.
3. Run `/sulde-add-team-member` for each developer.
4. Read `<docs-hub>/00_shared-rules/*` and adapt the defaults to your project.
5. Bootstrap `<docs-hub>/design-truth/` from your real design source when one exists.
6. Let the grace period expire or use `/sulde-end-grace` after a verified task/handoff loop.

## See also

- `${CLAUDE_PLUGIN_ROOT}/docs/V0.2.0-DESIGN-v2.md` — concise historical design record
- `${CLAUDE_PLUGIN_ROOT}/docs/GETTING_STARTED.md` — user-facing walkthrough
