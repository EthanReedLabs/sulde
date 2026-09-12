#!/usr/bin/env sh
set -eu

HOOK=${1:-}
case "$HOOK" in
    pre-tool-use) SCRIPT=pre_tool_use.py ;;
    user-prompt-submit) SCRIPT=user_prompt_submit.py ;;
    session-start) SCRIPT=session_start.py ;;
    pre_tool_use.py|post_tool_use.py|user_prompt_submit.py|canon_inject.py|session_start.py|pre_compact.py|notification.py|stop.py) SCRIPT=$HOOK ;;
    *) echo "sulde: unknown Hook entrypoint" >&2; exit 2 ;;
esac
if [ "$#" -ne 1 ]; then
    echo "sulde: exactly one Hook entrypoint is required" >&2
    exit 2
fi

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SULDE_HOOK_KB_HOME=${SULDE_KB_HOME:-${SULDE_HOME:-$HOME/.sulde}/data/kb}
for candidate in "$SULDE_HOOK_KB_HOME/venv/bin/python" "$SULDE_HOOK_KB_HOME/venv/Scripts/python.exe" python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -B -c 'import sys, yaml; raise SystemExit(0 if sys.version_info >= (3, 10) and sys.version_info[:2] <= (3, 14) and int(yaml.__version__.split(".")[0]) >= 6 else 1)' >/dev/null 2>&1; then
        PYTHONDONTWRITEBYTECODE=1 PYTHONIOENCODING=utf-8 PYTHONUTF8=1 exec "$candidate" -B "$SCRIPT_DIR/$SCRIPT"
    fi
done
if command -v py >/dev/null 2>&1 && py -3 -B -c 'import sys, yaml; raise SystemExit(0 if sys.version_info >= (3, 10) and sys.version_info[:2] <= (3, 14) and int(yaml.__version__.split(".")[0]) >= 6 else 1)' >/dev/null 2>&1; then
    PYTHONDONTWRITEBYTECODE=1 PYTHONIOENCODING=utf-8 PYTHONUTF8=1 exec py -3 -B "$SCRIPT_DIR/$SCRIPT"
fi
echo "sulde: Python 3.10–3.14 with PyYAML 6+ is required; Hook did not execute" >&2
exit 2
