# {{frontend_name}} — HarmonyOS NEXT frontend (sulde)

This directory contains the HarmonyOS frontend for the project. `/sulde-init` populated it from `${CLAUDE_PLUGIN_ROOT}/template/harmony/`.

## Quick start

```bash
# Install pre-commit hooks once
bash scripts/pre-commit-installer.sh

# Build + install
./hvigorw assembleHap --mode debug
hdc install -r build/default/outputs/default/{{hap_file}}.hap
hdc shell aa start -a {{ability_name}} -b {{bundle_name}}
```

## OS compatibility

DevEco Studio supports all three:

### macOS
✅ Full support. DevEco Studio macOS native.

### Linux
✅ Full support. DevEco Studio Linux package available.

### Windows
✅ Full support. `hvigorw.bat` for builds, PowerShell or Git Bash for `hdc`. Run `git commit` via Git Bash to ensure pre-commit hooks (bash) execute.

### Python dependency

```bash
pip install -r ${CLAUDE_PLUGIN_ROOT}/hooks/requirements.txt
```

## Tooling notes

- **DevEco Studio**: required for project setup, ability scaffolding, signing config. CLI builds (`hvigorw`) work fine for CI / day-to-day after initial setup.
- **HarmonyOS device**: real device strongly preferred over emulator for media + perf work.
- **hdc pair**: first-time setup needs `hdc pair` (wifi) or USB-debug enable. See Huawei developer docs for device-side opt-in.

## .ai-workspace/ layout

| Dir | Purpose |
|---|---|
| `tasks/` | Coordinator-drafted task-mds |
| `handoff/` | Dev → coordinator post-execution docs |
| `baseline/` | Pre-task evidence snapshots |
| `session-resume/` | Long-context continuation docs |
| `diag/` | Diagnostic outputs (hilog, hidumper, SmartPerf traces) |
| `screenshots/` | UI verify captures |
| `ui-audit/` | Audit subagent reports |

## See also

- `${CLAUDE_PLUGIN_ROOT}/skills/dev/assign/SKILL.md`
- `${CLAUDE_PLUGIN_ROOT}/skills/dev/handoff/SKILL.md`
- `<docs-hub>/00_shared-rules/`
- Huawei developer docs: <https://developer.huawei.com/consumer/cn/doc/harmonyos-guides/>
