#!/usr/bin/env python3
"""Adapt Codex Stop payloads to Sulde's shared turn reconciler."""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import json
import subprocess
from typing import Any

from _adapter_common import (
    configure_utf8_stdio,
    normalize_codex_session,
    run_runtime,
    runtime_root,
)


configure_utf8_stdio()
SULDE_HOOK = runtime_root() / "hooks" / "stop.py"


def _payload() -> dict[str, Any]:
    try:
        value = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(value, dict):
        return {}
    normalize_codex_session(value)
    value["client"] = "codex"
    return value


def main() -> int:
    context = ""
    try:
        completed = run_runtime(
            SULDE_HOOK,
            input_text=json.dumps(_payload(), ensure_ascii=False),
            timeout=115,
        )
        context = completed.stdout.strip()
        if completed.stderr:
            sys.stderr.write(completed.stderr)
    except (OSError, subprocess.TimeoutExpired) as error:
        sys.stderr.write(f"sulde Codex stop adapter unavailable: {error}\n")
    if context:
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "Stop",
                        "additionalContext": context,
                    }
                },
                ensure_ascii=False,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
