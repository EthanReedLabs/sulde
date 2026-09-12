#!/usr/bin/env python3
"""Adapt Codex PostToolUse payloads to Sulde's shared audit hook."""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import json
import os
import subprocess
from typing import Any

from _adapter_common import (
    configure_utf8_stdio,
    normalize_codex_session,
    run_runtime,
    runtime_root,
)


configure_utf8_stdio()
SULDE_HOOK = runtime_root() / "hooks" / "post_tool_use.py"


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
    if "tool_response" not in value and value.get("toolResponse") is not None:
        value["tool_response"] = value["toolResponse"]
    value["client"] = "codex"
    return value


def _record_failure(
    payload: dict[str, Any],
    *,
    error_kind: str,
    exit_code: int | None = None,
    diagnostic_stderr: str = "",
    execution_identity: tuple[str, str] = ("unknown", "unknown"),
) -> None:
    """Best-effort audit telemetry that never changes effect or permission truth."""
    # Record the actual runtime outcome before the adapter's nonblocking exit.
    # This channel deliberately has no Guardian contract or effect-ledger lock.
    try:
        from _hook_observer import classify, facts, identity, record
        module_before, artifact_before = execution_identity
        module_changed = identity(SULDE_HOOK) != module_before
        artifact_changed = identity(SULDE_HOOK.parent.parent.parent / ".codex-plugin/generation.json") != artifact_before
        kind = {"TimeoutExpired": "timeout", "FileNotFoundError": "script_missing",
                "OSError": "interpreter_or_executable_unavailable"}.get(error_kind, error_kind)
        if error_kind == "nonzero_exit" and diagnostic_stderr:
            kind, _ = classify(exit_code, diagnostic_stderr.encode("utf-8", "replace")[-8192:], b"")
        row = facts(hook="sulde:post-tool-use", stage="runtime", payload=payload,
                    code=exit_code, kind=kind, module="unknown" if module_changed else module_before,
                    artifact="unknown" if artifact_changed else artifact_before)
        row["module_identity_status"] = "changed_during_execution" if module_changed else "stable_path_snapshot"
        if artifact_changed:
            row["artifact_identity_status"] = "changed_during_execution"
        record(row)
    except Exception:
        sys.stderr.write("sulde: hook_observer_delivery_unavailable; action_not_retried\n")
    runtime_kb = runtime_root() / "scripts" / "kb"
    try:
        sys.path.insert(0, str(runtime_kb))
        from host_capabilities import record_hook_failure

        record_hook_failure(
            provider="codex",
            hook_event="PostToolUse",
            stage="runtime",
            error_kind=error_kind,
            session_id=str(payload.get("session_id") or payload.get("sessionId") or ""),
            workspace=(
                payload.get("sulde_workspace_root")
                or payload.get("cwd")
                or ""
            ),
            call_id=str(
                payload.get("call_id")
                or payload.get("toolUseId")
                or payload.get("tool_use_id")
                or payload.get("callId")
                or ""
            ),
            exit_code=exit_code,
            loaded_module_generation=os.environ.get(
                "SULDE_LOADED_MODULE_GENERATION", ""
            ),
            artifact_generation=os.environ.get("SULDE_ARTIFACT_GENERATION", ""),
        )
    except (ImportError, OSError, UnicodeError, ValueError, RuntimeError):
        pass
    finally:
        try:
            sys.path.remove(str(runtime_kb))
        except ValueError:
            pass


def main() -> int:
    context = ""
    payload = _payload()
    sys.path.insert(0, str(runtime_root() / "scripts" / "kb"))
    try:
        from production_recovery_control import route_native_recovery
        recovery = route_native_recovery(payload, runtime=runtime_root(), event="PostToolUse")
    except (ImportError, OSError, RuntimeError, ValueError):
        recovery = None
    if recovery is not None:
        # The recovery journal owns these effects. An ordinary PostTool-only
        # observation must not invent a second task debt for the same repair.
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PostToolUse", "additionalContext": recovery["reason"],
        }}, ensure_ascii=False))
        return 0
    execution_identity = ("unknown", "unknown")
    try:
        from _hook_observer import identity
        execution_identity = (identity(SULDE_HOOK), identity(SULDE_HOOK.parent.parent.parent / ".codex-plugin/generation.json"))
    except (ImportError, OSError):
        pass
    try:
        completed = run_runtime(
            SULDE_HOOK,
            input_text=json.dumps(payload, ensure_ascii=False),
            timeout=115,
        )
        if completed.returncode == 0:
            context = completed.stdout.strip()
        else:
            _record_failure(
                payload,
                error_kind="nonzero_exit",
                exit_code=completed.returncode,
                diagnostic_stderr=completed.stderr,
                execution_identity=execution_identity,
            )
            sys.stderr.write(
                "sulde: PostToolUse audit runtime failed; effect outcome remains "
                "inconclusive and the host task continues\n"
            )
        if completed.stderr:
            sys.stderr.write(completed.stderr)
    except (OSError, subprocess.TimeoutExpired) as error:
        _record_failure(payload, error_kind=type(error).__name__, execution_identity=execution_identity)
        sys.stderr.write(f"sulde Codex post-tool adapter unavailable: {error}\n")
    if context:
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PostToolUse",
                        "additionalContext": context,
                    }
                },
                ensure_ascii=False,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
