#!/usr/bin/env bash
# sulde pre-commit hook installer (Android frontend).
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
  # Prefer the current plugin ID; retain discovery for existing installations.
  for plugin_name in sulde sulde-cc; do
    for marketplace_dir in "$HOME"/.claude/plugins/cache/*; do
      plugin_path="$marketplace_dir/$plugin_name"
      [ -d "$plugin_path" ] || continue
      plugin_version="$(ls -t "$plugin_path" 2>/dev/null | head -1)"
      candidate="$plugin_path/$plugin_version"
      if [ -d "$candidate/hooks/git-precommit" ]; then
        CLAUDE_PLUGIN_ROOT="$candidate"
        break 2
      fi
    done
  done
fi

if [ -z "${CLAUDE_PLUGIN_ROOT:-}" ] || [ ! -d "$CLAUDE_PLUGIN_ROOT" ]; then
  cat >&2 <<EOF
❌ CLAUDE_PLUGIN_ROOT not set and auto-detection failed.

Set it manually:
  export CLAUDE_PLUGIN_ROOT=/path/to/sulde/plugin
  bash $0

Or pass it inline:
  CLAUDE_PLUGIN_ROOT=/path/to/sulde bash $0
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
# sulde pre-commit hook (installed $(date -u '+%Y-%m-%dT%H:%M:%SZ') by $0)
# Sources the 4 sulde checks; any check exit != 0 aborts the commit.

set -e

PLUGIN_HOOKS="$HOOKS_SRC"

if [ ! -d "\$PLUGIN_HOOKS" ]; then
  echo "⚠️  sulde plugin hooks not found at \$PLUGIN_HOOKS" >&2
  echo "    (commit allowed — install sulde plugin to restore enforcement)" >&2
  exit 0
fi

for h in check_branch_protect.sh check_branch_format.sh check_commit_alias.sh check_ai_traces.sh; do
  if [ -x "\$PLUGIN_HOOKS/\$h" ]; then
    bash "\$PLUGIN_HOOKS/\$h" || exit \$?
  fi
done
EOF

chmod +x "$HOOK_DST"

echo "✅ sulde pre-commit hook installed at: $HOOK_DST"
echo "   Plugin hooks dir: $HOOKS_SRC"
echo ""
echo "   Test with a dry commit:"
echo "     touch tmp.txt && git add tmp.txt && git commit -m 'test'  # should be blocked unless on dev/<alias>/<slug>"
