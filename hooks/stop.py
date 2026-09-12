#!/usr/bin/env python3
"""Reconcile unfinished guardian events when a host turn stops."""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE / "lib"))
sys.path.insert(0, str(_HERE.parent / "scripts" / "kb"))

from sulde_common import read_json_stdin  # noqa: E402
from host_capabilities import record_hook_observation  # noqa: E402
from intent_guardian import (  # noqa: E402
    IntentGuardianError,
    finalize_host_turn,
)


def main() -> int:
    payload = read_json_stdin()
    record_hook_observation(
        payload,
        provider=str(payload.get("client") or "claude"),
        hook_event="Stop",
    )
    try:
        context = finalize_host_turn(
            payload,
            provider=str(payload.get("client") or "claude"),
        )
        if context:
            print(context)
    except (IntentGuardianError, OSError, UnicodeError) as error:
        sys.stderr.write(f"sulde intent guardian stop observer unavailable: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
