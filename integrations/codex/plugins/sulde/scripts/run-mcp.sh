#!/bin/sh

export PYTHONDONTWRITEBYTECODE=1

if [ -n "${SULDE_HOME:-}" ]; then
  SULDE_ROOT=$SULDE_HOME
else
  SULDE_ROOT="${HOME}/.sulde"
fi

LAUNCHER="$SULDE_ROOT/bin/sulde-kb-mcp"
if [ ! -f "$LAUNCHER" ] || [ ! -x "$LAUNCHER" ]; then
  echo "sulde-kb-mcp: stable launcher unavailable: $LAUNCHER" >&2
  exit 2
fi

exec "$LAUNCHER" "$@"
