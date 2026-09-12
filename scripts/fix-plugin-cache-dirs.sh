#!/usr/bin/env bash
# RETIRED: whole-tree Codex cache symlink repair violated version isolation.
#
# Historical plugin versions must keep their own static bytes. Only the two
# Hook entrypoints may be rebound by the transactional Codex installer after
# each tree is snapshotted and verified (ap-0181). This compatibility
# entrypoint intentionally performs no cache mutation, so a still-loaded
# com.sulde.codex-cache-repair actor cannot resurrect whole-tree symlinks.

set -eu

TOMBSTONE=${SULDE_CACHE_REPAIR_TOMBSTONE:-"$HOME/.sulde/state/codex-cache-repair.retired.json"}
if [ ! -f "$TOMBSTONE" ]; then
  mkdir -p "$(dirname -- "$TOMBSTONE")"
  temporary="$TOMBSTONE.$$"
  trap 'rm -f "$temporary"' EXIT HUP INT TERM
  printf '{"schema_version":1,"status":"retired","label":"com.sulde.codex-cache-repair","replacement":"transactional_hook_entrypoint_bridge"}\n' > "$temporary"
  chmod 600 "$temporary"
  mv "$temporary" "$TOMBSTONE"
  trap - EXIT HUP INT TERM
fi

exit 0
