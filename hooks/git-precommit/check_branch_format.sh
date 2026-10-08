#!/usr/bin/env bash
# sulde-cc — git pre-commit hook: enforce branch naming pattern.
#
# Default pattern: ^dev/[^/]+/.+$  (e.g. dev/alice/feat-login)
# Override via .sulde-config.yaml: enforcement.branch.pattern

set -u

config=""
dir="$(pwd)"
while [ "$dir" != "/" ]; do
  if [ -f "$dir/.sulde-config.yaml" ]; then
    config="$dir/.sulde-config.yaml"
    break
  fi
  dir="$(dirname "$dir")"
done

pattern_default="^dev/[^/]+/.+$"
pattern=""
if [ -n "$config" ]; then
  pattern=$(sed -n 's/^[[:space:]]*pattern:[[:space:]]*//p' "$config" \
            | head -1 | tr -d '"' | tr -d "'")
fi
[ -z "$pattern" ] && pattern="$pattern_default"

# Read enforcement_level — lenient 模式下 branch format 降为 warning 不阻塞
# (brownfield 项目可能用 feature/xxx / bugfix/xxx 等既有惯例,lenient 允许)
level=""
if [ -n "$config" ]; then
  level=$(sed -n 's/^[[:space:]]*enforcement_level:[[:space:]]*//p' "$config" \
          | head -1 | tr -d '"' | tr -d "'")
fi

current="$(git symbolic-ref --short HEAD 2>/dev/null || echo "")"
[ -z "$current" ] && exit 0

# Allow protected branches themselves to skip the format check; the
# branch-protect hook will reject direct commits separately.
case "$current" in
  main|develop|master) exit 0 ;;
esac

if ! echo "$current" | grep -Eq "$pattern"; then
  if [ "$level" = "lenient" ]; then
    cat >&2 <<EOF
⚠️  sulde-cc: branch name '$current' does not match required pattern.
   pattern: $pattern
   suggested: dev/<alias>/<slug>   (e.g. dev/alice/feat-login)

(enforcement_level: lenient — warning only, commit allowed)
EOF
    exit 0
  fi
  cat >&2 <<EOF
❌ sulde-cc: branch name '$current' does not match required pattern.
   pattern: $pattern
   suggested: dev/<alias>/<slug>   (e.g. dev/alice/feat-login)

Rename: git branch -m <new-name>
Bypass: set \`enforcement_level: lenient\` in .sulde-config.yaml to downgrade to warning.
EOF
  exit 1
fi

exit 0
