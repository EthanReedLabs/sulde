#!/usr/bin/env bash
# sulde-cc pre-commit hook installer (Android frontend).
#
# Installs a `.git/hooks/pre-commit` that sources the 4 sulde checks from
# the plugin install. Idempotent — safe to re-run.
#
# Requires:
#   - bash (Windows: use Git Bash or WSL2)
#   - CLAUDE_PLUGIN_ROOT environment var, OR auto-detection of plugin path

set -eu

FRONTEND_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [ -z "${CLAUDE_PLUGIN_ROOT:-}" ]; then
  # Try the typical user-scope install location.
  if [ -d "$HOME/.claude/plugins/cache" ]; then
    plugin_path="$(find "$HOME/.claude/plugins/cache" -maxdepth 3 -name "sulde-cc" -type d 2>/dev/null | head -1)"
    if [ -n "$plugin_path" ]; then
      CLAUDE_PLUGIN_ROOT="$(dirname "$plugin_path")/sulde-cc/$(ls -t "$(dirname "$plugin_path")/sulde-cc/" 2>/dev/null | head -1)"
    fi
  fi
fi

if [ -z "${CLAUDE_PLUGIN_ROOT:-}" ] || [ ! -d "$CLAUDE_PLUGIN_ROOT" ]; then
  cat >&2 <<EOF
❌ CLAUDE_PLUGIN_ROOT not set and auto-detection failed.

Set it manually:
  export CLAUDE_PLUGIN_ROOT=/path/to/sulde-cc/plugin
  bash $0

Or pass it inline:
  CLAUDE_PLUGIN_ROOT=/path/to/sulde-cc bash $0
EOF
  exit 1
fi

GIT_DIR="$(git -C "$FRONTEND_ROOT" rev-parse --git-dir 2>/dev/null || echo "")"
if [ -z "$GIT_DIR" ]; then
  echo "❌ '$FRONTEND_ROOT' is not a git repository. Run 'git init' first." >&2
  exit 1
fi

# OS detect — emit Windows CRLF reminder if running under msys/cygwin (Git Bash).
case "${OSTYPE:-}" in
  msys*|cygwin*)
    cat <<EOF
⚠️  Windows detected. Ensure .git/hooks/pre-commit uses LF (not CRLF):
   git config core.autocrlf input
EOF
    ;;
esac

HOOKS_SRC="$CLAUDE_PLUGIN_ROOT/hooks/git-precommit"
HOOK_DST="$GIT_DIR/hooks/pre-commit"

mkdir -p "$GIT_DIR/hooks"
cat > "$HOOK_DST" <<EOF
#!/usr/bin/env bash
# sulde-cc pre-commit hook (installed $(date -u '+%Y-%m-%dT%H:%M:%SZ') by $0)
# Sources the 4 sulde checks; any check exit != 0 aborts the commit.

set -e

PLUGIN_HOOKS="$HOOKS_SRC"

if [ ! -d "\$PLUGIN_HOOKS" ]; then
  echo "⚠️  sulde-cc plugin hooks not found at \$PLUGIN_HOOKS" >&2
  echo "    (commit allowed — install sulde-cc plugin to restore enforcement)" >&2
  exit 0
fi

for h in check_branch_protect.sh check_branch_format.sh check_commit_alias.sh check_ai_traces.sh; do
  if [ -x "\$PLUGIN_HOOKS/\$h" ]; then
    bash "\$PLUGIN_HOOKS/\$h" || exit \$?
  fi
done
EOF

chmod +x "$HOOK_DST"

echo "✅ sulde-cc pre-commit hook installed at: $HOOK_DST"
echo "   Plugin hooks dir: $HOOKS_SRC"
echo ""
echo "   Test with a dry commit:"
echo "     touch tmp.txt && git add tmp.txt && git commit -m 'test'  # should be blocked unless on dev/<alias>/<slug>"
