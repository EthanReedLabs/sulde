#!/usr/bin/env python3
"""Adapt Codex PreToolUse payloads to Sulde's shared guardian/enforcement hook."""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import json
import os
from pathlib import Path
from typing import Any

from _adapter_common import (
    configure_utf8_stdio,
    normalize_codex_session,
    run_runtime,
    runtime_root,
)
from _recovery_defer import payload_requires_fail_closed


configure_utf8_stdio()
ACTIVE_RUNTIME_ROOT = runtime_root()
SULDE_HOOK = ACTIVE_RUNTIME_ROOT / "hooks" / "pre_tool_use.py"


def _payload() -> dict[str, Any]:
    try:
        value = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(value, dict):
        return {}
    if "tool_name" not in value and value.get("toolName"):
        value["tool_name"] = value["toolName"]
    if "tool_input" not in value and value.get("toolInput") is not None:
        value["tool_input"] = value["toolInput"]
    normalize_codex_session(value)
    if "call_id" not in value:
        call_id = value.get("toolUseId") or value.get("tool_use_id") or value.get("callId")
        if call_id:
            value["call_id"] = call_id
    value["client"] = "codex"
    return value


def _valid_policy_deny(stdout: object) -> bool:
    """Accept only an exact structured Codex PreToolUse denial."""
    if not isinstance(stdout, str) or not stdout.strip():
        return False
    try:
        payload = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        return False
    if not isinstance(payload, dict):
        return False
    output = payload.get("hookSpecificOutput")
    return (
        isinstance(output, dict)
        and output.get("hookEventName") == "PreToolUse"
        and output.get("permissionDecision") == "deny"
        and isinstance(output.get("permissionDecisionReason"), str)
        and bool(output["permissionDecisionReason"].strip())
    )


def _fallback_requires_deny(payload: dict[str, Any]) -> bool:
    """Fail closed except for read, Git, and the exact native recovery surface."""
    configured_home = os.environ.get("SULDE_HOME")
    configured_kb = os.environ.get("SULDE_KB_HOME")
    neutral_home = Path.home() / ".sulde"
    neutral_kb = neutral_home / "data" / "kb"
    if configured_home:
        launcher_home = Path(configured_home).expanduser()
    elif configured_kb and Path(configured_kb).expanduser() != neutral_kb:
        launcher_home = Path(configured_kb).expanduser()
    else:
        launcher_home = neutral_home
    return payload_requires_fail_closed(
        payload,
        runtime_root=ACTIVE_RUNTIME_ROOT,
        launcher_home=launcher_home,
    )


def _emit_degraded_deny(reason: str) -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            },
            ensure_ascii=False,
        )
    )


def _degrade(payload: dict[str, Any], detail: str) -> int:
    if _fallback_requires_deny(payload):
        sys.stderr.write(
            "sulde Codex PreToolUse failed_closed: "
            f"policy runtime unavailable. ({detail})\n"
        )
        _emit_degraded_deny(
            "Sulde PreToolUse policy could not complete; this material or unknown "
            "action was not executed. Read-only diagnosis, Git execution, "
            f"and exact recovery commands remain available. ({detail})"
        )
    else:
        sys.stderr.write(
            "sulde Codex PreToolUse degraded_to_native_codex: read/Git or exact "
            f"recovery command remains under native authority. ({detail})\n"
        )
    return 0


def main() -> int:
    payload = _payload()
    requested_event = str(os.environ.get("SULDE_CODEX_HOOK_EVENT") or "PreToolUse")
    permission_request = requested_event.casefold().replace("_", "") == "permissionrequest"
    # The recovery bridge must not import ordinary Guardian contract/policy
    # modules. A broken task ledger is not a prerequisite for this decision.
    sys.path.insert(0, str(ACTIVE_RUNTIME_ROOT / "scripts" / "kb"))
    try:
        from production_recovery_control import route_native_recovery
        recovery = route_native_recovery(
            payload, runtime=ACTIVE_RUNTIME_ROOT,
            event="PermissionRequest" if permission_request else "PreToolUse",
        )
    except (ImportError, OSError, RuntimeError, ValueError):
        recovery = None
    if recovery is not None:
        if recovery["action"] == "deny":
            if permission_request:
                print(json.dumps({"hookSpecificOutput": {
                    "hookEventName": "PermissionRequest",
                    "decision": {"behavior": "deny", "message": recovery["reason"]},
                }}, ensure_ascii=False))
            else:
                _emit_degraded_deny(recovery["reason"])
        return 0
    if os.environ.get("SULDE_CODEX_FALLBACK_ONLY") == "1":
        return _degrade(payload, "stable bridge unavailable")
    try:
        completed = run_runtime(
            SULDE_HOOK,
            input_text=json.dumps(payload, ensure_ascii=False),
            timeout=115,
        )
        if permission_request:
            # No output is the valid defer contract here: Codex remains the
            # owner of the current conversation's native Allow/Deny prompt.
            if completed.returncode == 0:
                if completed.stdout:
                    sys.stdout.write(completed.stdout)
                if completed.stderr:
                    sys.stderr.write(completed.stderr)
                return 0
            if completed.stderr:
                sys.stderr.write(completed.stderr)
            sys.stderr.write(
                "sulde Codex PermissionRequest adapter degraded_to_native_codex: "
                f"runtime exit {completed.returncode}\n"
            )
            return 0
        empty_success = completed.returncode == 0 and not completed.stdout.strip()
        structured_deny = completed.returncode == 0 and _valid_policy_deny(
            completed.stdout
        )
        exit_two_deny = completed.returncode == 2 and _valid_policy_deny(
            completed.stdout
        )
        if empty_success or structured_deny or exit_two_deny:
            # Empty stdout is the Codex allow/defer contract.  A structured
            # denial is normalized to exit 0 because combining JSON stdout
            # with exit 2 is treated as a failed Hook by Codex.
            if completed.stdout:
                sys.stdout.write(completed.stdout)
            if completed.stderr:
                sys.stderr.write(completed.stderr)
            return 0
        if completed.stderr:
            sys.stderr.write(completed.stderr)
        return _degrade(
            payload,
            f"invalid or empty policy response at exit {completed.returncode}",
        )
    except Exception as error:
        if permission_request:
            sys.stderr.write(
                "sulde Codex PermissionRequest adapter degraded_to_native_codex: "
                f"runtime unavailable: {error}\n"
            )
            return 0
        return _degrade(payload, f"{type(error).__name__}: {error}")


if __name__ == "__main__":
    raise SystemExit(main())
