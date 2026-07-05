# Getting Started (v0.2.0)

> Go from "I cloned sulde-cc" to "my first Dev session is running a task-md" in about 10 minutes.

This walkthrough assumes you have Claude Code installed, Python 3.6+ available, and a mobile project (or empty directory) where you want to adopt the methodology.

---

## 1. Install the plugin (~ 2 min)

```sh
# Latest v0.2.0 (mobile-first, BSL 1.1, Python hooks)
/plugin marketplace add EthanReedLabs/sulde-cc
/plugin install sulde-cc@sulde-cc

# Python dependency (one time per machine)
pip install pyyaml>=6.0
```

Without `pyyaml` the enforcement hooks degrade gracefully to no-op + a stderr warning. Your workflow does not break, but you lose the gating value. Install it.

After install you should see 5 skills and 8 commands available:

```
/sulde-init                       /sulde-add-frontend       /sulde-add-team-member
/sulde-migrate-from-v0.1.0        /sulde-add-sensitive-file  /sulde-add-scaffold
/sulde-end-grace                  /sulde-add-skill-trigger
```

And the hooks (`PreToolUse`, `UserPromptSubmit`, `SessionStart`) start watching. They stay silent in any project without `.sulde-config.yaml` — opt-in by design.

## 2. Initialize your project (~ 3 min)

In your project root, run:

```sh
cd ~/path/to/your-mobile-project
```

In a Claude Code session there, run:

```
/sulde-init
```

The wizard asks ~8 questions:

1. project name (default = dir basename)
2. role (`coordinator` / `dev` / `both`; default `coordinator`)
3. stacks (multi-select: `android`, `ios`, `flutter`, `harmony`; default `[android, ios]`)
4. design source MCP (`pencil` / `figma` / `sketch` / custom; default `pencil`)
5. team (one alias per frontend at minimum; can defer with `/sulde-add-team-member` later)
6. enforcement level (`strict` / `balanced` / `lenient`; default `balanced`)
7. grace period days (default `7`)
8. language (`auto` / `en` / `zh` / `ja`; default `auto`)

It then:
- writes `.sulde-config.yaml`
- copies `template/_project/*` to your project root (README, .gitignore.template, scripts/, docs-hub/ skeleton)
- copies `template/<stack>/*` to each `frontends[].path`
- installs git pre-commit hooks via each frontend's `scripts/pre-commit-installer.sh`
- drops a `.sulde-grace-started` marker — for 7 days, enforcement runs at `lenient` regardless of your config so first-week mistakes don't block you

## 3. Add team members (~ 2 min)

For each developer in your project, run:

```
/sulde-add-team-member <alias> <name> <email> <frontend>
```

Example:

```
/sulde-add-team-member as-a Alice alice@example.com android
/sulde-add-team-member as-b Bob   bob@example.com   ios
```

This appends to `.sulde-config.yaml: team[]` and creates a per-repo `git as-<alias>` shell alias that sets `SULDE_COMMIT_ALIAS=<alias>` so the `check_commit_alias.sh` pre-commit hook lets the commit through. Plain `git commit` without `git as-<alias>` is now blocked.

## 4. Bootstrap design-truth (~ 5-15 min depending on design size)

If your project has a design tool with MCP support (Pencil / Figma):

```
/update-design                                                  # not yet bundled — see skills/coordinator/
```

For now, manually create `<docs-hub>/design-truth/<page-id>.md` per page using `<docs-hub>/design-truth/_example.md.template` as the skeleton. Each page truth doc should include:

- Node tree (component nesting + style props)
- Visual key attributes (font, color, corner radius)
- Asset reference list (per-stack paths for `cp`)
- Implementation hard constraints (which scaffolds to use)

## 5. Dispatch your first task-md (~ 3 min)

In your coordinator session at project root:

> "Dispatch a task to the android frontend: change the home tab count from 3 to 2."

The `UserPromptSubmit` hook surfaces a `[sulde:writing-task-md]` reminder. Invoke the skill, follow its §0 6-step audit + §0.5 5-step baseline. The skill's enforcement gate (the `check_task_md_baseline.py` PreToolUse hook) blocks Write of any task-md missing the `§起草前 baseline 实证` section.

Write the task-md to `./android/.ai-workspace/tasks/<YYYY-MM-DD>-home-tabs-reduction.md`.

## 6. Execute the task (~ depends on task)

In a **separate** Claude Code session running inside `./android/`:

```
/clear
/model sonnet
/assign .ai-workspace/tasks/<YYYY-MM-DD>-home-tabs-reduction.md
```

The `dev/assign` skill:

1. Reads the task-md frontmatter (assignee, branch, model)
2. Verifies §0 baseline (4-step gate: task md has baseline section, cited symbols still grep, cited design-truth still exists, recent commits don't invalidate)
3. Switches branch + `git as-<alias>` identity
4. Executes the contract
5. Runs §5 verify-strict (build / install / launch+log / screenshot)
6. Writes a handoff at `.ai-workspace/handoff/<YYYY-MM-DD>-home-tabs-reduction-result.md` per the `dev/handoff` skill's 5-section format
7. Stages the diff; **does not auto-commit or auto-push** — waits for your confirmation

## 7. Coordinator reviews + dispatches follow-ups

Back in your coordinator session, the next `/clear` will SessionStart-inject the head of `CLAUDE.md` + optionally the output of `scripts/coordinator-baseline.sh` so you see what the dev produced.

Read the handoff's `§ verify` (build evidence) + `§ escalation 候选` (out-of-scope problems the dev noticed). Decide:
- merge the dev's branch into integration
- or dispatch a follow-up task-md for escalation items

## 8. End the grace period

After ~1 week, you'll have a feel for the hooks. Switch to your real enforcement level:

```
/sulde-end-grace
```

This drops a `.sulde-grace-ended` marker. From here on, hooks enforce at the level configured in `.sulde-config.yaml: enforcement_level` (default `balanced`):

| Level | PreToolUse(Write) | PreToolUse(Bash) | UserPromptSubmit |
|---|---|---|---|
| `strict` | block (JSON deny) | block (exit 2) | reminder |
| `balanced` (default) | block | block | reminder |
| `lenient` | warn (allow) | warn (allow) | reminder |

## 9. Author your first real ADR (when you hit a recurring pattern)

sulde-cc ships three example ADRs (`0001`-`0003`) for mobile-generic anti-patterns + `0000-example.md` for format reference. Once your project hits a recurring incident specific to it, author `<docs-hub>/ADR/{NNNN}-{slug}.md` following `_frontmatter.schema.yaml`. Add a row to `INDEX.md`. Track recurrence over time — the ADR registry is the single most valuable artifact a long project accumulates.

---

## What to read next

- [`docs/METHODOLOGY.md`](METHODOLOGY.md) — the 7-layer pyramid + reasoning
- [`docs/V0.2.0-DESIGN-v2.md`](V0.2.0-DESIGN-v2.md) — hook protocol, schema details, grace mechanics
- `<docs-hub>/00_shared-rules/*` (after `/sulde-init`) — data-sources / verify-build / self-fix-boundary / perf-diagnosis / model-strategy
- `${CLAUDE_PLUGIN_ROOT}/skills/dev/assign/SKILL.md` + `dev/handoff/SKILL.md` — day-to-day Dev workflow

## Migrating from v0.1.x

```
/sulde-migrate-from-v0.1.0
```

Reads existing `.sulde-config.yaml`, dry-runs upgrade to `.sulde-config.yaml.v2-preview`, asks for confirmation, backs up the original as `.sulde-config.yaml.v0.1.0-backup`, and drops a 7-day grace marker. The CHANGELOG has the breaking-change list (Python dependency is the main one).

If you cannot install Python 3.6+ in your environment, stay on v0.1.x:

```
/plugin install skills@sulde-cc@0.1.0
```

The v0.1.0 tag remains MIT-licensed and Python-free in perpetuity.

## Troubleshooting

**The hooks are not running**

```sh
/plugin list                    # verify sulde-cc shows
python3 -c "import yaml"        # verify pyyaml installed (silent = ok; error = pip install pyyaml)
```

If hooks still don't fire, check that `.sulde-config.yaml` exists in your project root or an ancestor (hooks walk up to find it; no file = silent exit).

**Pre-commit hook blocks `git commit`**

Use `git as-<alias> commit ...` (configured by `/sulde-add-team-member`). To disable: set `enforcement.branch.commit_alias_required: false` in `.sulde-config.yaml`.

**Want to disable enforcement temporarily**

Set `enabled: false` in `.sulde-config.yaml` (kill switch). Or drop to `lenient` for warnings without blocking. Re-enable when ready.

**Trigger keywords don't match my project's vocabulary**

Add custom triggers via `/sulde-add-skill-trigger <regex> <skill> [role]`. The `skill_trigger.py` hook merges your additions with the built-in defaults on every prompt.

**A Dev session is touching files outside its frontend**

Check the Dev's `CLAUDE.md` has the "do not edit files outside this frontend" rule (the v0.2.0 templates include it). If yes, the Dev is ignoring it — file an ADR.
