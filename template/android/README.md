# {{frontend_name}} — Android frontend (sulde)

This directory contains the Android frontend for the project. `/sulde-init` populated it from `${CLAUDE_PLUGIN_ROOT}/template/android/`.

## Quick start

```bash
# Install pre-commit hooks once
bash scripts/pre-commit-installer.sh

# Build + install (per docs-hub/00_shared-rules/verify-build.md)
./gradlew :app:assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

## OS compatibility

### macOS
✅ Full support out-of-the-box.

### Linux
✅ Full support. Install JDK 17 + Android SDK Command-Line Tools.

### Windows
⚠️ Required: Git Bash (from Git for Windows) or WSL2.
- Run `git commit` from Git Bash so pre-commit hooks (bash) execute correctly
- Build cmd: use `gradlew.bat :app:assembleDebug` (already documented in `CLAUDE.md`)
- Set `git config core.autocrlf input` to prevent CRLF line endings breaking `.sh` files

### Python dependency

The sulde Claude Code hooks require Python 3.6+ with pyyaml:

```bash
pip install -r ${CLAUDE_PLUGIN_ROOT}/hooks/requirements.txt
```

Without pyyaml the hooks gracefully degrade to no-op + a stderr warning; runs continue.

## .ai-workspace/ layout

| Dir | Purpose |
|---|---|
| `tasks/` | Coordinator-drafted task-mds |
| `handoff/` | Dev → coordinator post-execution docs |
| `baseline/` | Pre-task evidence snapshots |
| `session-resume/` | Long-context continuation docs |
| `diag/` | Diagnostic outputs (logcat, perfetto, gfxinfo) |
| `screenshots/` | UI verify captures |
| `ui-audit/` | Audit subagent reports |

Each subdir has its own `README.md` with naming + lifecycle rules.

## See also

- `${CLAUDE_PLUGIN_ROOT}/skills/dev/assign/SKILL.md` — task execution gate
- `${CLAUDE_PLUGIN_ROOT}/skills/dev/handoff/SKILL.md` — handoff format
- `<docs-hub>/00_shared-rules/` — cross-frontend rules
