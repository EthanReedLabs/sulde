#!/usr/bin/env bash
# sulde-cc — git pre-commit hook: block AI traces in staged content.
#
# Two layers:
#   1. forbidden paths — staged files that should NEVER enter git history
#      (.claude/, CLAUDE.md, .ai-workspace/, .sulde-grace-*, .sulde-config.yaml)
#   2. forbidden keywords — staged diff lines containing markers like
#      "AI generated", "Claude", "auto-generated" (configurable).
#
# Both lists overridable via .sulde-config.yaml: enforcement.ai_traces.

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

# Defaults (kept conservative — paths only; keywords disabled by default
# because diff scanning can have false positives).
default_paths=".claude/ CLAUDE.md .ai-workspace/ .sulde-config.yaml .sulde-grace-started .sulde-grace-ended"

paths_cfg=""
keywords_cfg=""
if [ -n "$config" ]; then
  paths_cfg=$(sed -n 's/.*forbidden_paths:[[:space:]]*\[\([^]]*\)\].*/\1/p' "$config" \
              | head -1 | tr -d '"' | tr "'" ' ' | tr ',' ' ' | tr -s ' ')
  keywords_cfg=$(sed -n 's/.*forbidden_keywords:[[:space:]]*\[\([^]]*\)\].*/\1/p' "$config" \
                 | head -1 | tr -d '"' | tr "'" ' ' | tr ',' ' ' | tr -s ' ')
fi
paths="${paths_cfg:-$default_paths}"

staged="$(git diff --cached --name-only 2>/dev/null)"
[ -z "$staged" ] && exit 0

violations=""
for p in $paths; do
  [ -z "$p" ] && continue
  # Trailing slash means dir; match `path/` prefix. No trailing slash:
  # match exact name OR as dir prefix.
  if echo "$staged" | grep -Eq "(^|/)${p%/}(/|$)"; then
    violations="${violations}${violations:+, }$p"
  fi
done

if [ -n "$violations" ]; then
  cat >&2 <<EOF
❌ sulde-cc: refusing to commit AI traces / sulde state files.
   forbidden paths matched: $violations

These belong in .gitignore. To unstage:
   git restore --staged <path>
Override (NOT recommended): enforcement.ai_traces.forbidden_paths: []
EOF
  exit 1
fi

# Optional keyword scan over staged diff.
if [ -n "$keywords_cfg" ]; then
  diff_added="$(git diff --cached --no-color --unified=0 | grep -E '^\+' | grep -Ev '^\+\+\+')"
  for kw in $keywords_cfg; do
    [ -z "$kw" ] && continue
    if echo "$diff_added" | grep -Fqi "$kw"; then
      cat >&2 <<EOF
❌ sulde-cc: AI-trace keyword '$kw' found in staged diff.

Remove the line or override: enforcement.ai_traces.forbidden_keywords: []
EOF
      exit 1
    fi
  done
fi

exit 0
