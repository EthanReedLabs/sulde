"""Exact POSIX Hook transport contract; this module never grants authority."""

from __future__ import annotations

import json
from pathlib import Path


EVENTS = {
    "PreToolUse": "pre-tool-use",
    "PermissionRequest": "permission-request",
    "PostToolUse": "post-tool-use",
    "Stop": "stop",
    "SessionStart": "session-start",
    "UserPromptSubmit": "user-prompt-submit",
}
PROTOCOL = "stable-v1"
COMPLETION_PREFIX = "sulde-hook-entry-complete-v1:"
MATCHERS = {"PreToolUse": ".*", "PermissionRequest": ".*", "PostToolUse": ".*",
            "SessionStart": "startup|resume|clear"}


def stable_hook_command(event: str) -> str:
    hook = EVENTS[event]
    # The shell command itself lives in the host's registration snapshot.  It
    # must not first execute a script under PLUGIN_ROOT.  A missing bootstrap
    # cannot be represented by a nonzero hook exit: some hosts continue tools.
    root = (
        'sulde_entry_root="${SULDE_HOME:-${HOME}/.sulde}"; '
        'if [ -z "${SULDE_HOME:-}" ] && [ -n "${SULDE_KB_HOME:-}" ] '
        '&& [ "$SULDE_KB_HOME" != "${HOME}/.sulde/data/kb" ]; '
        'then sulde_entry_root="$SULDE_KB_HOME"; fi; '
        'sulde_entry="$sulde_entry_root/bin/sulde-codex-hook"; '
    )
    if event == "PreToolUse":
        failure = "printf '%s\\n' '" + json.dumps(
            {"hookSpecificOutput": {
                "hookEventName": "PreToolUse", "permissionDecision": "deny",
                "permissionDecisionReason":
                    "Sulde stable Hook entry unavailable; this action was not executed.",
            }}, separators=(",", ":"),
        ) + "'"
    else:
        failure = ":"
    failure += "; printf '%s\\n' 'sulde: stable_entry_unavailable; coverage_blind_spot' >&2"
    return (
        root + 'if [ -f "$sulde_entry" ] && [ ! -L "$sulde_entry" ] '
        f'&& sulde_output=$(/bin/sh "$sulde_entry" {hook}); '
        f'then case "$sulde_output" in {COMPLETION_PREFIX}*) '
        f'sulde_output=${{sulde_output#{COMPLETION_PREFIX}}}; '
        '[ -z "$sulde_output" ] || printf \'%s\\n\' "$sulde_output";; '
        f'*) {failure};; esac; '
        f"else {failure}; fi"
    )


def is_stable_hook_document(document: object) -> bool:
    if not isinstance(document, dict) or set(document) != {"hooks"}:
        return False
    hooks = document.get("hooks")
    if not isinstance(hooks, dict) or set(hooks) != set(EVENTS):
        return False
    for event in EVENTS:
        rows = hooks[event]
        if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
            return False
        expected_keys = {"hooks", "matcher"} if event in MATCHERS else {"hooks"}
        if set(rows[0]) != expected_keys or rows[0].get("matcher") != MATCHERS.get(event):
            return False
        commands = rows[0].get("hooks")
        if not isinstance(commands, list) or len(commands) != 1:
            return False
        command = commands[0]
        if (not isinstance(command, dict) or command.get("type") != "command"
                or command.get("command") != stable_hook_command(event)
                or type(command.get("timeout")) is not int or command["timeout"] != 120
                or set(command) - {"type", "command", "timeout", "statusMessage"}
                or ("statusMessage" in command and not isinstance(command["statusMessage"], str))):
            return False
    return True


def validate_registration(plugin_root: Path) -> dict[str, str]:
    """Report transport only. A file is NOT proof of old-session migration."""
    path = plugin_root / "hooks" / "hooks.json"
    try:
        if path.is_symlink():
            return {"protocol": "unknown", "reason": "hook document is a symlink"}
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"protocol": "unknown", "reason": "hook document unavailable"}
    if is_stable_hook_document(document):
        return {"protocol": PROTOCOL, "reason": "exact cache-independent command surface"}
    hooks = document.get("hooks") if isinstance(document, dict) else None
    if isinstance(hooks, dict) and "PLUGIN_ROOT" in json.dumps(hooks):
        return {"protocol": "legacy", "reason": "cache-dependent command surface"}
    return {"protocol": "unknown", "reason": "unrecognized command surface"}
