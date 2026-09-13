#!/usr/bin/env bash
# sulde — git pre-commit hook: validate governed KB metadata and catalog.

set -u

# The hook only reads repository sources.  Keep its Python validators from
# leaving derived bytecode in the worktree, where release closure checks would
# otherwise reject an otherwise clean commit.
PYTHONDONTWRITEBYTECODE=1
export PYTHONDONTWRITEBYTECODE

root=""
dir="$(pwd)"
while [ "$dir" != "/" ]; do
  if [ -f "$dir/knowledge/SEDIMENTATION-STANDARD.md" ]; then
    root="$dir"
    break
  fi
  dir="$(dirname "$dir")"
done

[ -z "$root" ] && exit 0

if git -C "$root" diff --cached --quiet -- knowledge scripts/kb; then
  exit 0
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "⚠️  sulde: python3 not found; skipping KB pre-commit checks." >&2
  exit 0
fi

lint_output=""
if ! lint_output=$(cd "$root" && python3 scripts/kb/lint-frontmatter.py 2>&1); then
  printf '%s\n' "$lint_output" >&2
  cat >&2 <<'EOF'
❌ sulde: KB frontmatter lint failed; commit rejected.
Fix the violations, then run:
  python3 scripts/kb/lint-frontmatter.py
EOF
  exit 1
fi

sedimentation_output=""
if ! sedimentation_output=$(cd "$root" && python3 scripts/kb/lint-sedimentation.py 2>&1); then
  printf '%s\n' "$sedimentation_output" >&2
  cat >&2 <<'EOF'
❌ sulde: KB sedimentation-v2 lint failed; commit rejected.
Use the matching template under templates/knowledge/, then run:
  python3 scripts/kb/lint-sedimentation.py
EOF
  exit 1
fi

index_output=""
if ! index_output=$(cd "$root" && python3 scripts/kb/build-index-md.py --check 2>&1); then
  printf '%s\n' "$index_output" >&2
  cat >&2 <<'EOF'
❌ sulde: knowledge/INDEX.md is stale; commit rejected.
Rebuild and stage it:
  python3 scripts/kb/build-index-md.py
  git add knowledge/INDEX.md
EOF
  exit 1
fi

exit 0
