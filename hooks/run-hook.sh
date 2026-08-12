#!/usr/bin/env sh
set -eu

HOOK=${1:-}
case "$HOOK" in
    pre-tool-use) SCRIPT=pre_tool_use.py ;;
    user-prompt-submit) SCRIPT=user_prompt_submit.py ;;
    session-start) SCRIPT=session_start.py ;;
    *) echo "usage: run-hook.sh {pre-tool-use|user-prompt-submit|session-start}" >&2; exit 2 ;;
esac

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
        PYTHONIOENCODING=utf-8 PYTHONUTF8=1 exec "$candidate" "$SCRIPT_DIR/$SCRIPT"
    fi
done
if command -v py >/dev/null 2>&1 && py -3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
    PYTHONIOENCODING=utf-8 PYTHONUTF8=1 exec py -3 "$SCRIPT_DIR/$SCRIPT"
fi
echo "sulde: Python 3.10+ is required; hook skipped" >&2
exit 0
