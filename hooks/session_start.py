#!/usr/bin/env python3
"""sulde-cc SessionStart entrypoint.

Injects CLAUDE.md head + optional baseline / health output as
`additionalContext` so the session starts with current project state.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE / "lib"))

try:
    import yaml  # noqa: F401
except ImportError:
    # Without pyyaml we can't parse config → can't know what to inject.
    # Stay silent so the session starts unimpeded.
    sys.exit(0)

from sulde_common import read_json_stdin, silent_exit_if_no_config  # noqa: E402

import claude_md_inject  # noqa: E402
import community_extensions  # noqa: E402


def main() -> int:
    payload = read_json_stdin()
    config = silent_exit_if_no_config()
    claude_md_inject.run(config, payload)
    community_extensions.run("SessionStart", config, payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
