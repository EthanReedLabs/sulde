# Sulde Community

Sulde Community is a mobile-first coordination skeleton for Claude Code projects. It provides
deterministic hooks, project templates, task/handoff conventions, extension scaffolds, and an
empty knowledge-growth kit. You bring the team rules, domain knowledge, and project-specific
workflows.

**Current release:** `0.3.0`
**Runtime contract:** Python 3.10+, PyYAML 6.0+, Git, and Claude Code plugin support.

The public edition is intentionally a framework and a set of ideas—not a populated engineering
brain. It contains no private corpus, project memory, vector database, background Agent, L2/L3/L4
governance loop, or autonomous execution system.

## What ships

- Five core skills:
  - `coordinator/writing-task-md`
  - `coordinator/configure-sulde`
  - `coordinator/multi-source-review`
  - `dev/assign`
  - `dev/handoff`
- Eight `/sulde-*` setup and maintenance commands.
- Three opt-in Claude Code hook entrypoints for task, handoff, navigation, identity, skill-trigger,
  performance, and session-start checks.
- Four mobile project skeletons: Android, iOS, Flutter, and HarmonyOS.
- `sulde doctor` for source-checkout and clean-install diagnostics.
- An extension SDK for adding a project skill, hook, doctor check, or knowledge container.
- An empty project-owned knowledge kit with deterministic add, dedup, redact, lint, index, search,
  and light sediment commands.

## What does not ship

- A pre-populated incident or anti-pattern library.
- User, session, or cross-project memory.
- Embedding models, hosted search, MCP servers, or paid API calls.
- Autonomous governance, self-repair, task approval, publishing, commit, or push behavior.
- Claude Code/Codex dual-host runtime parity. This public release is a Claude Code plugin skeleton;
  its methodology and generated artifacts can still be adapted by downstream projects.
- Private or commercial Sulde implementation details.

These exclusions are product boundaries, not missing dependencies. A clean Community install must
work without another Sulde repository or another Agent host.

## Install

### Claude Code marketplace

```text
/plugin marketplace add EthanReedLabs/sulde-cc
/plugin install sulde-cc@sulde-cc
```

Install the one Python dependency used by the enforcement hooks and knowledge kit:

```sh
python3 -m pip install -r "${CLAUDE_PLUGIN_ROOT}/hooks/requirements.txt"
```

The plugin is opt-in per project. Hooks remain silent until an ancestor directory contains
`.sulde-config.yaml` with `enabled: true`.

### Local fork

```sh
git clone https://github.com/EthanReedLabs/sulde-cc.git
cd sulde-cc
python3 -m pip install -r hooks/requirements.txt
./bin/sulde doctor
```

Then add the local checkout as a Claude Code marketplace.

## Runtime and OS contract

- Python `3.10+` is required because the source uses modern type syntax.
- PyYAML `6.0+` is required for active project enforcement and knowledge validation.
- All Python file I/O and command output use UTF-8 explicitly.
- `hooks/run-hook.sh` discovers `python3`, `python`, or `py -3` and verifies the minimum version
  before dispatching a hook.
- macOS and Linux use a POSIX shell. Windows uses Git Bash or WSL2 for Claude Code's hook command;
  `hooks/run-hook.ps1` and `scripts/sulde.ps1` provide native PowerShell launchers for manual use.
- If Python or PyYAML is unavailable, enforcement hooks disclose the missing dependency and avoid
  blocking unrelated Claude Code work. `sulde doctor` reports it as an error.

Run diagnostics at any time:

```sh
sulde doctor
sulde doctor --project /path/to/project
sulde doctor --json
```

On Windows PowerShell:

```powershell
./scripts/sulde.ps1 doctor --project C:\path\to\project
```

## Start a project

In Claude Code, run:

```text
/sulde-init
```

The guided setup creates `.sulde-config.yaml`, copies the project and selected stack skeletons,
installs project pre-commit hooks, and starts the configured grace period. See
[`docs/GETTING_STARTED.md`](docs/GETTING_STARTED.md) for the first task/handoff loop.

The project template now includes an empty `knowledge/` directory. It belongs to the adopting
project and grows only when its maintainers add reviewed content.

## Extend a fork

Generators update `extensions/registry.json` and refuse to overwrite an existing file or registry
entry:

```sh
sulde add-skill release-review --description "Review release evidence"
sulde add-hook ticket-gate --event PreToolUse --matcher "Write|Edit"
sulde add-check repo-policy
sulde add-knowledge-container domain-notes
```

Review generated code before enabling it. A Skill or hook is procedural code; it does not grant an
Agent new write, publishing, or network authority. See [`docs/EXTENDING.md`](docs/EXTENDING.md).

## Grow project knowledge

The kit is deterministic and local:

```sh
sulde kb init --root /path/to/project
sulde kb dedup --root /path/to/project "symptom description"
sulde kb redact --root /path/to/project incident.md --output safe-incident.md
sulde kb sediment --root /path/to/project \
  --source safe-incident.md \
  --container anti-patterns \
  --title "Recurring failure title" \
  --summary "Reusable, de-identified lesson"
sulde kb lint --root /path/to/project
sulde kb index --root /path/to/project
sulde kb search --root /path/to/project "same symptom in different words"
```

`sediment` creates a draft; it does not mark the knowledge active, commit it, or publish it. See
[`docs/KNOWLEDGE-KIT.md`](docs/KNOWLEDGE-KIT.md).

## Supported project stacks

| Stack | Template | Primary verification tools |
|---|---|---|
| Android | `template/android/` | Gradle, adb |
| iOS | `template/ios/` | xcodebuild, ios-deploy/xcrun |
| Flutter | `template/flutter/` | flutter CLI |
| HarmonyOS NEXT | `template/harmony/` | hvigorw, hdc |

The framework can be forked for other stacks through the extension and template mechanisms. The
public repository does not claim those variants are pre-validated.

## Safety model

- Installing the plugin does not opt a project in.
- Generators preserve existing content and reject unsafe relative paths.
- Diagnostics report error types without printing full project payloads or credentials.
- Knowledge additions fail on deterministic redaction findings and likely duplicates.
- Indexes are derived artifacts; Markdown and Git remain the source of truth.
- No command in the Community toolkit commits, pushes, publishes, or calls a remote model.

## Development and release checks

```sh
python3 -m unittest discover -s tests -v
./bin/sulde doctor --strict
git diff --check
```

Maintainer exports from the private development tree use a reviewed, digest-pinned manifest and
stage validation before touching this repository. Directory-wide `rsync` is not part of the release
path.

## Documentation

- [`docs/GETTING_STARTED.md`](docs/GETTING_STARTED.md) — first install and task loop
- [`docs/ONBOARDING.md`](docs/ONBOARDING.md) — new/legacy/offline adoption
- [`docs/EXTENDING.md`](docs/EXTENDING.md) — fork extension SDK
- [`docs/KNOWLEDGE-KIT.md`](docs/KNOWLEDGE-KIT.md) — project-owned knowledge loop
- [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) — coordination model

## License

Version `0.2.0` and later use the [Business Source License 1.1](LICENSE), with Change Date
2030-05-25 and Change License MIT. The `0.1.x` MIT license is retained in
[`LICENSE-v0.1.0-MIT-archive`](LICENSE-v0.1.0-MIT-archive).
