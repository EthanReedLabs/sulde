# Sulde — Agent Harness

Sulde connects an Agent's task intent, tool execution, verification and local
knowledge workflow. This full-Harness source candidate includes Guardian,
LIFE supervision, knowledge and memory engines, task tooling, and Claude Code
and Codex integration. It also retains the standalone Community CLI and
project extension scaffolds.

This checkout is a review candidate, not an accepted release or production
installation receipt. Check `docs/PUBLIC-DATA-BOUNDARY.md` before contributing
data or publishing a derived package. The existing repository LICENSE applies.

## Code is shared; operational data is not

The distribution begins with an empty knowledge corpus and no project memory.
Formal knowledge documents, indexes/vectors, project/session memory, production
ledgers, installation receipts, private task reports and private Git history
are not bundled. Runtime state is local to each user's configured Sulde home.
Tests must construct synthetic data.

## Source layout

- `hooks/`, `skills/`, `commands/`: host entrypoints and task workflows.
- `scripts/kb/`: Guardian, LIFE, installation and verification components.
- `tools/kb-index/`, `tools/kb-mcp/`: knowledge/memory engines and MCP service.
- `integrations/codex/`: Codex adapters and platform-specific package inputs.
- `templates/`, `template/`: schemas and empty project scaffolds.
- `bin/sulde`, `scripts/sulde.py`, `extensions/`: standalone project toolkit.

## Local checks and packaging

Use Python 3.10–3.14. Hook dependencies are in `hooks/requirements.txt`.
KB bootstrap declares `fastembed`, `jieba`, `cryptography` and `pyyaml` in
`scripts/kb/bootstrap.sh`; FastEmbed supplies its numerical/model dependencies.
There is no separate KB requirements file. Keep a task-specific data root when
testing; do not run a candidate against an existing production home. Bootstrap
without `--dry-run` can install dependencies, download models and initialize data.

Build self-contained packages from a clean source checkout:

```sh
python3 -B scripts/release/stage_plugin.py --target claude --output ../sulde-claude-candidate
python3 -B scripts/release/stage_plugin.py --target codex --platform posix --output ../sulde-codex-candidate
python3 -B scripts/release/stage_plugin.py --target codex --platform windows --output ../sulde-codex-windows-candidate
```

Each output must be new. Packaging and manifest validation do not establish
live host readiness. Installation, native approval, Hook enforcement and
scheduler checks require a separate isolated acceptance run. Windows package
generation alone is not Windows execution evidence.

Codex installation selects its executable through the installer's `--codex`
input, then binds the resolved absolute target, exact audited CLI version,
file digest and help observation into the deployment identity. Managed tasks
use that verified identity; they never reselect a CLI through PATH or
`SULDE_CODEX_EXE`. This candidate's audited protocol is `codex-cli 0.154.0`.
Changing the executable requires a new verified installation. Identity format
v1 is not silently upgraded to v2 by a task runner.

Real CLI regression gates take an explicit `SULDE_TEST_CODEX_EXECUTABLE`
absolute path. An absent value leaves those gates unverified, not passed.
That test input cannot select the executable for a managed production task.

See `docs/intent-guardian.md`, `docs/dual-runtime-contract.md` and
`docs/event-observability.md` for capability contracts. Older Community guides
describe the standalone toolkit; their smaller capability inventory does not
describe the full Harness.

## Test evidence boundary

Public source synchronization is not a production release acceptance. Tests
that compare against private Git commits or private release reports require
those inputs and are not portable public regression gates. Their unavailability
must not be reported as a pass, and private history must not be imported to run
them. In particular, historical baseline cases in
`tests/test_control_composition_architecture.py` and
`tests/test_control_composition_performance.py` retain that limitation.

The SELF template starts without operator goals or verified local capability
state. Governance reports bundle no historical human decisions. Neither a
template nor successful packaging transfers the publisher's approval authority.
