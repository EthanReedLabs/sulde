#!/usr/bin/env python3
"""sulde PreToolUse entrypoint.

Dispatches Bash + Write/Edit tool calls to the relevant check_*.py module.
Stays silent (exit 0) when:
  - pyyaml is not installed (graceful degradation — #22 fix)
  - the cwd is not under a `.sulde-config.yaml` project
  - the config has `enabled: false`
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Allow `from sulde_common import ...` regardless of where Claude Code invokes us.
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE / "lib"))
sys.path.insert(0, str(_HERE.parent / "scripts" / "kb"))

from sulde_common import load_config, read_json_stdin  # noqa: E402

import kb_guard  # noqa: E402
from host_capabilities import record_hook_observation  # noqa: E402
from intent_guardian import (  # noqa: E402
    IntentGuardianError,
    kb_home,
    normalize_hook_event,
    observe_native_permission_request,
    process_hook,
)
from codex_recovery_defer import payload_requires_fail_closed  # noqa: E402
from sulde_paths import launcher_home  # noqa: E402

try:
    import yaml  # noqa: F401  pyyaml runtime probe
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

import check_task_md_baseline  # noqa: E402
import check_handoff_verify  # noqa: E402
import check_subdir_cd  # noqa: E402
import check_git_commit_alias  # noqa: E402
import check_postmortem_reminder  # noqa: E402


def _emit_guardian_denial(reason: str) -> None:
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


def _requires_material_guardian(payload: dict, *, provider: str) -> bool:
    """Conservatively identify calls that cannot run without supervision."""
    if provider.strip().lower() == "codex":
        # Keep the independent fallback surface identical to the static Codex
        # adapter: read, Git and exact recovery remain under native authority
        # even when contract/session resolution itself is unavailable.
        return payload_requires_fail_closed(
            payload,
            runtime_root=_HERE.parent,
            launcher_home=launcher_home(kb_home()),
        )
    try:
        event = normalize_hook_event(payload, phase="started", provider=provider)
    except (OSError, UnicodeError, ValueError, TypeError):
        read_only = {
            "read", "glob", "grep", "find", "view_image", "search",
            "webrun", "web.run", "web__run",
        }
        return str(payload.get("tool_name") or "").strip().lower() not in read_only
    if (
        event.get("supervision_domain") == "execution_passthrough"
        and event.get("execution_domain") == "git"
    ):
        return False
    effect = str(event.get("effect") or "unknown")
    return effect in {"local_write", "external_write", "destructive", "unknown"} or (
        event.get("kind") == "mcp" and effect != "read"
    )


def main() -> int:
    payload = read_json_stdin()
    requested_event = str(
        payload.get("hook_event_name")
        or payload.get("hookEventName")
        or os.environ.get("SULDE_CODEX_HOOK_EVENT")
        or "PreToolUse"
    )
    if requested_event.lower().replace("_", "") == "permissionrequest":
        record_hook_observation(
            payload,
            provider="codex",
            hook_event="PermissionRequest",
        )
        result = observe_native_permission_request(payload, provider="codex")
        if result["action"] == "deny":
            print(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "PermissionRequest",
                            "decision": {
                                "behavior": "deny",
                                "message": (
                                    "Sulde refused this approval request: "
                                    + str(result["reason"])
                                ),
                            },
                        }
                    },
                    ensure_ascii=False,
                )
            )
        # ``defer`` and ``ignore`` intentionally emit no decision. Codex keeps
        # ownership of the current conversation's native Allow/Deny prompt.
        return 0

    live_observed = record_hook_observation(
        payload,
        provider=str(payload.get("client") or "claude"),
        hook_event="PreToolUse",
    )
    payload["_sulde_live_hook_observed"] = live_observed
    # Run established deterministic gates first. If one blocks, the guardian
    # must not leave a phantom open event for a tool that never executed.
    config = load_config()
    kb_guard.run(config, payload)
    if not _HAS_YAML:
        sys.stderr.write(
            "sulde: pyyaml not installed — legacy project hook enforcement disabled. "
            "Run `pip install pyyaml>=6.0` to enable. (See V0.2.0-DESIGN-v2.md §3.1.1.)\n"
        )
    elif config is not None and config.enabled:
        tool_name = payload.get("tool_name", "")
        if tool_name == "Bash":
            check_subdir_cd.run(config, payload)
            check_postmortem_reminder.run(config, payload)
            check_git_commit_alias.run(config, payload)
        elif tool_name in ("Write", "Edit", "MultiEdit"):
            check_task_md_baseline.run(config, payload)
            check_handoff_verify.run(config, payload)

    provider = str(payload.get("client") or "claude")
    try:
        decision, _contract_path = process_hook(
            payload,
            phase="started",
            provider=provider,
        )
    except (IntentGuardianError, OSError, UnicodeError) as error:
        sys.stderr.write(f"sulde intent guardian unavailable: {error}\n")
        if _requires_material_guardian(payload, provider=provider):
            _emit_guardian_denial(
                "Sulde intent guardian is busy or unavailable; this material/unknown "
                "action was not dispatched. Read-only diagnosis, Git execution and "
                "independent recovery remain available."
            )
            return 0
        decision, _contract_path = None, None
    if decision is not None and decision.action == "deny":
        _emit_guardian_denial(
            f"Sulde intent guardian blocked this action: {decision.reason}."
        )
        return 0

    # A successful Codex PreToolUse hook stays silent when it does not rewrite
    # the tool input.  Codex accepts ``permissionDecision: allow`` only with an
    # ``updatedInput`` payload; a bare allow is reported as a failed Hook and
    # then fails open.  Structured output is therefore reserved for denials.
    return 0


if __name__ == "__main__":
    sys.exit(main())
