#!/usr/bin/env python3
"""sulde-cc UserPromptSubmit entrypoint.

Runs the soft-severity reminders (skill_trigger + perf_gate). Never blocks
the prompt; only writes additional context to stdout for Claude to read.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE / "lib"))

try:
    import yaml  # noqa: F401
except ImportError:
    sys.stderr.write(
        "sulde: pyyaml not installed — skill triggers / perf gate disabled. "
        "Install PyYAML 6.0+ from the plugin's hooks/requirements.txt to enable.\n"
    )
    sys.exit(0)

from sulde_common import read_json_stdin, silent_exit_if_no_config  # noqa: E402

import skill_trigger  # noqa: E402
import perf_gate  # noqa: E402
import community_extensions  # noqa: E402


def main() -> int:
    payload = read_json_stdin()
    config = silent_exit_if_no_config()
    skill_trigger.run(config, payload)
    perf_gate.run(config, payload)
    community_extensions.run("UserPromptSubmit", config, payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
