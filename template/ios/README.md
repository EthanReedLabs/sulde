# {{frontend_name}} — iOS frontend (sulde)

This directory contains the iOS frontend for the project. `/sulde-init` populated it from `${CLAUDE_PLUGIN_ROOT}/template/ios/`.

## Quick start

```bash
# Install pre-commit hooks once
bash scripts/pre-commit-installer.sh

# Build + install (per docs-hub/00_shared-rules/verify-build.md)
xcodebuild -project {{project}}.xcodeproj -scheme {{scheme}} -destination 'platform=iOS,id={{udid}}' build
xcrun devicectl device install app --device {{udid}} build/Build/Products/Debug-iphoneos/{{app}}.app
```

## OS compatibility

### macOS
✅ Full support. Xcode {{min_xcode}} + iOS {{min_version}} SDK required.

### Linux / Windows
❌ **Not supported** — Xcode is macOS-exclusive.

For CI without Macs: use GitHub Actions `macos-latest` runners or a cloud Mac service (Codemagic, Bitrise, Xcode Cloud).

### Python dependency

The sulde Claude Code hooks require Python 3.6+ with pyyaml:

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
| `diag/` | Diagnostic outputs (idevicesyslog, xctrace, etc.) |
| `screenshots/` | UI verify captures |
| `ui-audit/` | Audit subagent reports |

Each subdir has its own `README.md`.

## See also

- `${CLAUDE_PLUGIN_ROOT}/skills/dev/assign/SKILL.md` — task execution gate
- `${CLAUDE_PLUGIN_ROOT}/skills/dev/handoff/SKILL.md` — handoff format
- `<docs-hub>/00_shared-rules/` — cross-frontend rules
