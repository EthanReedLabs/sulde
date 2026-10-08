# {{frontend_name}} — Flutter frontend (sulde-cc)

This directory contains the Flutter frontend for the project. `/sulde-init` populated it from `${CLAUDE_PLUGIN_ROOT}/template/flutter/`.

## Quick start

```bash
# Install pre-commit hooks once
bash scripts/pre-commit-installer.sh

# Verify environment + build
flutter doctor
flutter build apk --debug
flutter install
flutter run
```

## OS compatibility

### macOS
✅ Full support — build for both Android + iOS targets.

### Linux
✅ Android target supported. iOS target requires macOS.

### Windows
✅ Android target supported via WSL2 or PowerShell. iOS target requires macOS.

In all cases, run `git commit` via Git Bash on Windows so pre-commit hooks (bash) execute correctly.

### Python dependency

```bash
pip install -r ${CLAUDE_PLUGIN_ROOT}/hooks/requirements.txt
```

## .ai-workspace/ layout

| Dir | Purpose |
|---|---|
| `tasks/` | Coordinator-drafted task-mds |
| `handoff/` | Dev → coordinator post-execution docs |
| `baseline/` | Pre-task evidence snapshots |
| `session-resume/` | Long-context continuation docs |
| `diag/` | Diagnostic outputs (flutter logs / DevTools exports) |
| `screenshots/` | UI verify captures |
| `ui-audit/` | Audit subagent reports |

## See also

- `${CLAUDE_PLUGIN_ROOT}/skills/dev/assign/SKILL.md`
- `${CLAUDE_PLUGIN_ROOT}/skills/dev/handoff/SKILL.md`
- `<docs-hub>/00_shared-rules/`
