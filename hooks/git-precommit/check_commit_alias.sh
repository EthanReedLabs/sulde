#!/usr/bin/env bash
# sulde — git pre-commit hook: require commits via `git as-<alias>`.
#
# git aliases set with `git config alias.as-<alias>` end up calling
# `git commit --author=...`. We detect "this commit came through an alias"
# by checking GIT_COMMITTER_NAME against the local default user.name.
# A more direct mechanism: the alias sets a sentinel env var via shell
# trampolines installed by /sulde-add-team-member. Check for it.

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

# Default ON. Override via enforcement.branch.commit_alias_required: false
required="true"
if [ -n "$config" ]; then
  v=$(sed -n 's/^[[:space:]]*commit_alias_required:[[:space:]]*//p' "$config" \
      | head -1 | tr -d '"' | tr -d "'")
  [ -n "$v" ] && required="$v"
fi

if [ "$required" != "true" ]; then
  exit 0
fi

# Solo developer / single-person project support:
# 若 .sulde-config.yaml 的 team: 段为空(没有 - alias: 条目,只有注释),
# 跳过 alias 检查 — 独立开发者无需配 git as-<alias> 也能 commit.
# 多人项目(team 内有 ≥ 1 个真实 alias)继续强制 alias commit.
if [ -n "$config" ]; then
  active_aliases=$(awk '/^team:/{in_team=1; next} in_team && /^[^[:space:]#]/{in_team=0} in_team && /^[[:space:]]*-[[:space:]]*alias:/{print; exit}' "$config")
  if [ -z "$active_aliases" ]; then
    exit 0
  fi
fi

# Sentinel env var set by `git as-<alias>` trampoline (installed by
# /sulde-add-team-member). Falls back to nothing on plain `git commit`.
if [ -n "${SULDE_COMMIT_ALIAS:-}" ]; then
  exit 0
fi

# Allow merge commits / cherry-pick / revert — git fills GIT_REFLOG_ACTION.
case "${GIT_REFLOG_ACTION:-}" in
  merge*|*cherry-pick*|*revert*|rebase*) exit 0 ;;
esac

cat >&2 <<'EOF'
❌ sulde: commit through a project alias is required.

Run via:  git as-<alias> commit ...
Set up aliases: /sulde-add-team-member
Override (temporary): enforcement.branch.commit_alias_required: false
EOF
exit 1
