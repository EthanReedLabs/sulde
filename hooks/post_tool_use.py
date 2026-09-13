#!/usr/bin/env python3
"""sulde PostToolUse entrypoint for silent KB adoption feedback."""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE / "lib"))
sys.path.insert(0, str(_HERE.parent / "scripts" / "kb"))

from sulde_common import read_json_stdin, silent_exit_if_no_config  # noqa: E402

import kb_feedback  # noqa: E402
from host_capabilities import record_hook_observation  # noqa: E402
from intent_guardian import (  # noqa: E402
    IntentGuardianError,
    process_hook,
)

try:
    import yaml  # noqa: F401
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False


def main() -> int:
    payload = read_json_stdin()
    provider = str(payload.get("client") or "claude")
    native_event = str(
        payload.get("hook_event_name") or payload.get("hookEventName") or "PostToolUse"
    )
    observation_event = (
        "PostToolUseFailure"
        if provider == "claude" and native_event == "PostToolUseFailure"
        else "PostToolUse"
    )
    live_observed = record_hook_observation(
        payload,
        provider=provider,
        hook_event=observation_event,
    )
    payload["_sulde_live_hook_observed"] = live_observed
    if (
        native_event == "PostToolUseFailure"
        or payload.get("error") is not None
    ):
        payload["success"] = False
    try:
        process_hook(
            payload,
            phase="completed",
            provider=provider,
        )
    except (IntentGuardianError, OSError, UnicodeError) as error:
        sys.stderr.write(f"sulde intent guardian post-event unavailable: {error}\n")
    kb_feedback.run(payload)
    if not _HAS_YAML:
        return 0
    silent_exit_if_no_config()
    return 0


if __name__ == "__main__":
    sys.exit(main())
