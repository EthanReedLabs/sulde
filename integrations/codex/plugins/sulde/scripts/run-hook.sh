#!/bin/sh

export PYTHONDONTWRITEBYTECODE=1

case "${1:-}" in
  session-start) SCRIPT="session-start.py" ;;
  user-prompt-submit) SCRIPT="user-prompt-submit.py" ;;
  pre-tool-use) SCRIPT="pre-tool-use.py" ;;
  permission-request) SCRIPT="pre-tool-use.py"; export SULDE_CODEX_HOOK_EVENT="PermissionRequest" ;;
  post-tool-use) SCRIPT="post-tool-use.py" ;;
  stop) SCRIPT="stop.py" ;;
  *) echo "usage: run-hook.sh {session-start|user-prompt-submit|pre-tool-use|permission-request|post-tool-use|stop}" >&2; exit 2 ;;
esac
HOOK=${1:-}
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PLUGIN_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
HOOK_PAYLOAD=$(cat)
if [ -n "${SULDE_HOME:-}" ]; then
  SULDE_ROOT=$SULDE_HOME
elif [ -n "${SULDE_KB_HOME:-}" ] && [ "$SULDE_KB_HOME" != "${HOME}/.sulde/data/kb" ]; then
  # Explicit portable/test KB homes keep their self-contained launcher tree.
  SULDE_ROOT=$SULDE_KB_HOME
else
  SULDE_ROOT="${HOME}/.sulde"
fi
BRIDGE="$SULDE_ROOT/bin/intent-guardian"
if command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
elif command -v python >/dev/null 2>&1; then
  PYTHON=python
else
  if [ "$HOOK" = "pre-tool-use" ]; then
    printf '%s\n' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Sulde PreToolUse cannot start without Python 3; this action was not executed."}}'
  fi
  echo "sulde: failed_closed local hook adapter cannot start without Python 3" >&2
  exit 0
fi

NONBLOCKING_FAILURE_RECORDED=0
record_nonblocking_failure() {
  [ "$HOOK" = "pre-tool-use" ] && return 0
  [ "$NONBLOCKING_FAILURE_RECORDED" -eq 0 ] || return 0
  NONBLOCKING_FAILURE_RECORDED=1
  if [ -f "$SCRIPT_DIR/record-hook-failure.py" ]; then
    "$PYTHON" "$SCRIPT_DIR/record-hook-failure.py" \
      "$HOOK" "${1:-wrapper}" "${2:-nonzero_exit}" "${3:-1}" >/dev/null || true
  fi
}

if [ "$HOOK" != "pre-tool-use" ]; then
  trap 'HOOK_EXIT=$?; trap - EXIT; if [ "$HOOK_EXIT" -ne 0 ]; then record_nonblocking_failure wrapper unexpected_exit "$HOOK_EXIT"; fi; exit 0' EXIT
fi

run_hook_command() {
  if [ "${1:-}" = "$BRIDGE" ] && grep -q '^# sulde-observer-in-process-v1$' "$BRIDGE"; then
    # The generated bridge records the sealed adapter in its existing Python
    # process. Legacy launchers retain the generic child observer below.
    printf '%s' "$HOOK_PAYLOAD" | SULDE_BRIDGE_OWNS_OBSERVATION=1 "$@"
    OBSERVED_EXIT=$?
    if [ "$OBSERVED_EXIT" -ne 0 ]; then
      # Launcher/pre-adapter startup failed: module identity is unknown. This
      # failure-only recorder does not execute the action a second time.
      printf '%s' "$HOOK_PAYLOAD" | "$PYTHON" "$SCRIPT_DIR/_hook_observer.py" \
        --hook "sulde:$HOOK" --record-shell-exit "$OBSERVED_EXIT" >/dev/null || true
    fi
    return "$OBSERVED_EXIT"
  elif [ "${1:-}" = "$PYTHON" ] && [ -f "$SCRIPT_DIR/_hook_entry.py" ] && [ -f "$SCRIPT_DIR/_hook_observer.py" ]; then
    shift
    printf '%s' "$HOOK_PAYLOAD" | "$PYTHON" "$SCRIPT_DIR/_hook_entry.py" \
      "sulde:$HOOK" "${OBSERVER_STAGE:-adapter}" "$@"
  elif [ -f "$SCRIPT_DIR/_hook_observer.py" ]; then
    printf '%s' "$HOOK_PAYLOAD" | "$PYTHON" "$SCRIPT_DIR/_hook_observer.py" \
      --hook "sulde:$HOOK" --stage "${OBSERVER_STAGE:-adapter}" -- "$@"
  else
    echo "sulde: hook_observer_unavailable; coverage_blind_spot" >&2
    printf '%s' "$HOOK_PAYLOAD" | "$@"
  fi
}

run_pre_tool_fallback() {
  FALLBACK_OUTPUT=$(printf '%s' "$HOOK_PAYLOAD" | SULDE_CODEX_FALLBACK_ONLY=1 "$PYTHON" "$SCRIPT_DIR/pre-tool-use.py")
  FALLBACK_STATUS=$?
  if [ "$FALLBACK_STATUS" -eq 0 ]; then
    [ -z "$FALLBACK_OUTPUT" ] || printf '%s\n' "$FALLBACK_OUTPUT"
    return 0
  fi
  printf '%s\n' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Sulde PreToolUse fallback failed; this action was not executed."}}'
  return 0
}

valid_policy_deny() {
  [ "$HOOK" = "pre-tool-use" ] || return 1
  case "$1" in
    *'"hookEventName": "PreToolUse"'*|*'"hookEventName":"PreToolUse"'*) ;;
    *) return 1 ;;
  esac
  case "$1" in
    *'"permissionDecision": "deny"'*|*'"permissionDecision":"deny"'*) return 0 ;;
    *) return 1 ;;
  esac
}

if [ "${SULDE_HOOK_RUNTIME_REBOUND:-0}" != "1" ] && { [ -e "$BRIDGE" ] || [ -L "$BRIDGE" ]; }; then
  if [ -f "$BRIDGE" ] && [ -x "$BRIDGE" ]; then
    export SULDE_SESSION_PLUGIN_ROOT="$PLUGIN_DIR"
    export SULDE_HOOK_RUNTIME_REBOUND=1
    unset SULDE_INTENT_GUARDIAN
    BRIDGE_OUTPUT=$(OBSERVER_STAGE=bridge run_hook_command "$BRIDGE" codex-hook "$HOOK")
    BRIDGE_STATUS=$?
    if [ "$BRIDGE_STATUS" -eq 0 ]; then
      if [ "$HOOK" != "pre-tool-use" ]; then
        [ -z "$BRIDGE_OUTPUT" ] || printf '%s\n' "$BRIDGE_OUTPUT"
        exit 0
      fi
      if [ -z "$BRIDGE_OUTPUT" ]; then
        exit 0
      fi
      if valid_policy_deny "$BRIDGE_OUTPUT"; then
        printf '%s\n' "$BRIDGE_OUTPUT"
        exit 0
      fi
      echo "sulde: failed_closed stable hook bridge returned no valid policy decision" >&2
      run_pre_tool_fallback
      exit 0
    fi
    if [ "$BRIDGE_STATUS" -eq 2 ] && valid_policy_deny "$BRIDGE_OUTPUT"; then
      printf '%s\n' "$BRIDGE_OUTPUT"
      exit 0
    fi
    if [ "$HOOK" = "pre-tool-use" ]; then
      echo "sulde: failed_closed stable hook bridge dispatch failed" >&2
      run_pre_tool_fallback
      exit 0
    fi
    record_nonblocking_failure bridge nonzero_exit "$BRIDGE_STATUS"
    echo "sulde: degraded_to_native_codex stable hook bridge dispatch failed" >&2
    exit 0
  fi
  if [ "$HOOK" = "pre-tool-use" ]; then
    echo "sulde: failed_closed stable hook bridge unavailable" >&2
    run_pre_tool_fallback
    exit 0
  fi
  record_nonblocking_failure bridge unavailable 1
  echo "sulde: degraded_to_native_codex stable hook bridge unavailable" >&2
  exit 0
fi
if [ "$HOOK" = "pre-tool-use" ]; then
  ADAPTER_OUTPUT=$(run_hook_command "$PYTHON" "$SCRIPT_DIR/$SCRIPT")
  ADAPTER_STATUS=$?
  if [ "$ADAPTER_STATUS" -eq 0 ] && [ -z "$ADAPTER_OUTPUT" ]; then
    exit 0
  fi
  if { [ "$ADAPTER_STATUS" -eq 0 ] || [ "$ADAPTER_STATUS" -eq 2 ]; } && \
     valid_policy_deny "$ADAPTER_OUTPUT"; then
    printf '%s\n' "$ADAPTER_OUTPUT"
    exit 0
  fi
  echo "sulde: failed_closed local hook adapter returned no valid policy decision" >&2
  run_pre_tool_fallback
  exit 0
fi
run_hook_command "$PYTHON" "$SCRIPT_DIR/$SCRIPT"
ADAPTER_STATUS=$?
if [ "$ADAPTER_STATUS" -ne 0 ]; then
  record_nonblocking_failure adapter nonzero_exit "$ADAPTER_STATUS"
  echo "sulde: degraded_to_native_codex local hook adapter failed" >&2
fi
exit 0
