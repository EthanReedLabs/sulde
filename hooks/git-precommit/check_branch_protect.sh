#!/usr/bin/env bash
# sulde — git pre-commit hook: protect main/develop from direct commits.
#
# Sourced (or invoked) by the project's .git/hooks/pre-commit installed via
# `template/<stack>/scripts/pre-commit-installer.sh`. Reads protected branch
# list from .sulde-config.yaml; falls back to [main, develop].

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

# Default protected branches (kept in sync with .sulde-config.example).
protected_default="main develop"
protected=""
if [ -n "$config" ]; then
  # Tolerant single-line YAML inline-list parser: `protected: [main, develop]`
  protected=$(sed -n 's/.*protected:[[:space:]]*\[\([^]]*\)\].*/\1/p' "$config" \
              | head -1 | tr -d '"' | tr ',' ' ' | tr -s ' ')
fi
[ -z "$protected" ] && protected="$protected_default"

current="$(git symbolic-ref --short HEAD 2>/dev/null || echo "")"
[ -z "$current" ] && exit 0

for b in $protected; do
  if [ "$current" = "$b" ]; then
    cat >&2 <<EOF
❌ sulde: direct commit to protected branch '$current' is not allowed.

Create a feature branch: git checkout -b dev/<alias>/<slug>
Override (temporary): set enforcement.branch.protected: [] in .sulde-config.yaml
EOF
    exit 1
  fi
done

exit 0
