#!/usr/bin/env python3
"""sulde-cc UserPromptSubmit entrypoint.

Ordinary reminder failures degrade visibly without blocking. Legacy
control-shaped text is never authority; factual attestations and pause requests
still fail closed unless their state transition is persisted.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE / "lib"))
sys.path.insert(0, str(_HERE.parent / "scripts" / "kb"))

from sulde_common import read_json_stdin, silent_exit_if_no_config  # noqa: E402

import kb_recall  # noqa: E402
import mem_capture  # noqa: E402
import mem_recall  # noqa: E402
from human_control import parse_human_control  # noqa: E402
from host_capabilities import record_hook_observation  # noqa: E402
from intent_guardian import IntentGuardianError, observe_user_prompt  # noqa: E402

try:
    import yaml  # noqa: F401
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

import skill_trigger  # noqa: E402
import perf_gate  # noqa: E402


def main() -> int:
    payload = read_json_stdin()
    payload["sulde_observation_source"] = str(
        payload.get("sulde_observation_source")
        or os.environ.get("SULDE_HOOK_OBSERVATION_SOURCE")
        or "unclassified"
    )
    record_hook_observation(
        payload,
        provider=str(payload.get("client") or "claude"),
        hook_event="UserPromptSubmit",
    )
    control = parse_human_control(str(payload.get("prompt") or ""))
    try:
        guardian_context = observe_user_prompt(
            payload,
            provider=str(payload.get("client") or "claude"),
        )
        if guardian_context:
            print(guardian_context)
    except (IntentGuardianError, OSError, UnicodeError) as error:
        status = (
            f"[sulde intent] CONTROL_NOT_RECORDED action={control.action} "
            f"target={control.target} reason={error}"
            if control
            else f"[sulde intent] UNAVAILABLE reason={error}"
        )
        print(status)
        sys.stderr.write(status + "\n")
        if control:
            return 2
    if control:
        # Exact control-plane messages are receipts, not task content.  Do not
        # capture, recall, trigger Skills, or feed performance advice from them.
        return 0
    mem_capture.run(payload)
    kb_recall.run(payload)
    mem_recall.run(payload)
    if not _HAS_YAML:
        sys.stderr.write(
            "sulde: pyyaml not installed — skill triggers / perf gate disabled. "
            "Run `pip install pyyaml>=6.0` to enable.\n"
        )
        return 0
    config = silent_exit_if_no_config()
    skill_trigger.run(config, payload)
    perf_gate.run(config, payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
