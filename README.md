# Sulde — Multi-end Claude Code coordination framework (mobile-first)

> **Sulde** (Mongolian: ᠰᠦᠯᠳᠡ, the rallying banner) — a factory-state framework for **mobile** projects where one **coordinator** Claude Code session steers multiple **Dev** sessions across Android / iOS / Flutter / HarmonyOS. Ships as a Claude Code plugin (skills + Python hooks + git pre-commit hooks) plus a project template (root skeleton + 4 stack skeletons + docs-hub).

**Status**: v0.2.0 — mobile-first, 11 enforcement hooks (Python), 4-stack template, 8 commands.

> Earlier v0.1.x releases (MIT) targeted any N-end split. v0.2.0 narrows scope to mobile to honestly reflect what's been battle-tested. Non-mobile users: stay on v0.1.x (`/plugin install skills@sulde-cc@0.1.0`) or wait for v0.3+ N-end re-entry.

---

## What you get

- A **plugin** (`/plugin install ...`) that adds:
  - **5 skills**:
    - `coordinator/writing-task-md` — gates task dispatch through a structured task-md contract (5-step baseline verification enforced by hook)
    - `coordinator/configure-sulde` — 8-mode setup / migration / team-management dispatcher (`init`, `migrate-from-v0.1.0`, `add-frontend`, `add-team-member`, `add-sensitive-file`, `add-scaffold`, `add-skill-trigger`, `end-grace`)
    - `coordinator/multi-source-review` — major-review 4-class triage to prevent single-source misjudgement
    - `dev/assign` — executes a task-md (baseline verify → run → verify-strict → handoff)
    - `dev/handoff` — formalises the 5-section handoff format
  - **11 enforcement hooks** (Python entrypoints + git pre-commit bash):
    - PreToolUse Write/Edit — task-md baseline section, handoff 5-section format
    - PreToolUse Bash — block `cd` into frontend dirs (context-pollution prevention), require `git as-<alias>` commits
    - UserPromptSubmit — skill-trigger reminders, perf-gate (no fixes without measurements)
    - SessionStart — inject CLAUDE.md head + optional baseline / health scripts via `additionalContext`
    - git pre-commit — branch protect, branch format, commit-alias, AI-traces (4 bash hooks)
  - **8 user commands** — `/sulde-init`, `/sulde-migrate-from-v0.1.0`, `/sulde-add-*` (×5), `/sulde-end-grace`
- A **project template** (`template/_project/` + `template/{android,ios,flutter,harmony}/`) — root skeleton + 4 stack skeletons, `/sulde-init` copies them into a new project ~5 minutes.
- A **methodology document** (`docs/METHODOLOGY.md`) explaining the layers the skills sit on.

## What you don't get (by design)

Sulde is **factory-state mechanism**, not populated content. You bring:

- Your design source (Pencil / Figma / Sketch / custom MCP)
- Your anti-pattern catalog (3 mobile examples ship; you accumulate the rest from actual incidents)
- Your team identities (`git as-X` aliases configured via `/sulde-add-team-member`)
- Your domain rules (which files are sensitive, model-selection thresholds, language conventions)

## Community Edition vs Pro Edition

This repository is the **Community Edition** — the complete framework mechanism, free under BSL 1.1. Everything you need to run Sulde on your project is here, and it will stay here.

**Pro Edition** adds the *content* accumulated from 6+ months of real multi-end project work — content that was never in this public repository:

| | Community (this repo) | Pro |
|---|---|---|
| Enforcement hooks (11) | ✅ | ✅ |
| Project template (4 stacks + docs-hub) | ✅ | ✅ |
| User commands (8) | ✅ | ✅ |
| Core skills | 5 (writing-task-md / configure-sulde / multi-source-review / assign / handoff) | 17+ (adds ui-impl, perf-diagnose, crash-fix, code-review, postmortem, parallel-dev, bug-hunt, update-design, coordinator-maintenance, sediment-from-code, curate-to-kb …) |
| Anti-pattern ADR library | 3 mobile-generic examples | **139+ full ADRs** (mobile / coordination / AI-behavior / incident catalog) |
| Engineering case studies | — | 17+ five-section deep dives (Android media & perf / iOS-TCA / cross-end consistency / mobile caching / diagnosis methodology) |
| Knowledge-sedimentation loop | — | Two-layer KB + curation workflow (bugbook → anti-pattern → case study) |

**Pro Edition inquiry**: eric.gao.tech@gmail.com

The Community Edition is not a trial — the mechanism is complete and self-sufficient. Pro is for teams that want the accumulated incident library and advanced skills instead of building their own from scratch.

## Prerequisites

- **Claude Code** with plugin support
- **Python 3.6+** with `pyyaml>=6.0` — the v0.2.0 enforcement hooks are Python-based for cross-OS support
  ```sh
  pip install -r ${CLAUDE_PLUGIN_ROOT}/hooks/requirements.txt
  ```
  Without pyyaml the hooks gracefully degrade to no-op + a stderr warning (your workflow does not break)
- **Git** with bash available (Windows: Git Bash or WSL2)
- **Stack-specific build tools** per frontend (Gradle / Xcode / Flutter SDK / DevEco Studio)

If Python 3.6+ is unavailable in your environment, install v0.1.x instead (MIT, no Python dependency).

---

## Install

### As a Claude Code plugin (recommended)

```sh
# Latest v0.2.0 (mobile-first, BSL 1.1)
/plugin marketplace add EthanReedLabs/sulde-cc
/plugin install sulde-cc@sulde-cc

# Or stay on v0.1.x (MIT, generic N-end)
/plugin install skills@sulde-cc@0.1.0
```

### Bootstrap a new project

```sh
cd your-mobile-project
/sulde-init
```

The init wizard asks ~8 questions (project name, role, stacks, design source, team, enforcement level, language, OS target), writes `.sulde-config.yaml`, copies the matching templates, installs git pre-commit hooks, and drops a 7-day grace marker so the first week of enforcement runs in lenient mode.

### Migrate from v0.1.x

```sh
/sulde-migrate-from-v0.1.0
```

Reads existing `.sulde-config.yaml`, dry-runs the schema upgrade to `.sulde-config.yaml.v2-preview`, backs up the original as `.sulde-config.yaml.v0.1.0-backup` once you confirm, and drops a 7-day grace marker for re-acclimation.

### Opt-in per project

Installing the plugin does not affect any project until you place `.sulde-config.yaml` in a project root. The hooks walk up from CWD, find nothing, and exit silently in non-sulde projects.

---

## 4 supported stacks (v0.2.0)

| Stack | Template | Notes |
|---|---|---|
| Android | `template/android/` | Kotlin + Compose / View; Gradle wrapper; `adb` |
| iOS | `template/ios/` | Swift + SwiftUI / UIKit / TCA; xcodebuild + `ios-deploy` / `xcrun devicectl`; **macOS only** |
| Flutter | `template/flutter/` | Dart + Widgets; `flutter` CLI; targets Android + iOS |
| HarmonyOS NEXT | `template/harmony/` | ArkTS + ArkUI; DevEco Studio + `hvigorw`; `hdc` |

React Native demoted to v0.2.1+ (see `docs/V0.2.0-DESIGN-v2.md §0.2 #15`).

---

## 5-minute walkthrough

See [`docs/GETTING_STARTED.md`](docs/GETTING_STARTED.md).

## Why a coordinator + N Devs

See [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) — the 7-layer pyramid (project meta → docs hub → design-truth → tasks → handoff → ADR → cross-session memory).

## OS compatibility

- **macOS** — full support across all 4 stacks
- **Linux** — full support for android / flutter / harmony; iOS requires macOS for Xcode
- **Windows** — Git Bash or WSL2 required for git pre-commit hooks; iOS not supported; Harmony fully supported via DevEco; android / flutter work via WSL2 or PowerShell + Gradle wrapper

## Contribute

See [`CONTRIBUTING.md`](CONTRIBUTING.md). The maintainer accepts PRs in bounded areas: anti-pattern ADR additions, stack-specific examples, docs corrections, i18n. Plugin internals (skill structure, hook protocol, template top-level shape) are author-controlled. PRs require a CLA in line with the Business Source License.

---

## License

**v0.2.0 onward**: [Business Source License 1.1](LICENSE) — Change Date 2030-05-25, Change License MIT.

**v0.1.x and earlier**: MIT — preserved in [`LICENSE-v0.1.0-MIT-archive`](LICENSE-v0.1.0-MIT-archive) for the lifetime of the repository.

## Acknowledgements

Sulde grew out of a real multi-end mobile project (one coordinator + two Dev sessions running for 6+ months). The methodology was distilled from ~100 anti-pattern ADRs accumulated during that work. v0.2.0 ships the structural mechanism and three mobile-generic ADR examples; your project supplies its own incident catalog over time.
