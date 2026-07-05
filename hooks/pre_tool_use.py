#!/usr/bin/env python3
"""sulde-cc PreToolUse entrypoint.

Dispatches Bash + Write/Edit tool calls to the relevant check_*.py module.
Stays silent (exit 0) when:
  - pyyaml is not installed (graceful degradation — #22 fix)
  - the cwd is not under a `.sulde-config.yaml` project
  - the config has `enabled: false`
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow `from sulde_common import ...` regardless of where Claude Code invokes us.
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE / "lib"))

try:
    import yaml  # noqa: F401  pyyaml runtime probe
except ImportError:
    sys.stderr.write(
        "sulde: pyyaml not installed — hook enforcement disabled. "
        "Run `pip install pyyaml>=6.0` to enable. (See V0.2.0-DESIGN-v2.md §3.1.1.)\n"
    )
    sys.exit(0)

from sulde_common import read_json_stdin, silent_exit_if_no_config  # noqa: E402

import check_task_md_baseline  # noqa: E402
import check_handoff_verify  # noqa: E402
import check_subdir_cd  # noqa: E402
import check_git_commit_alias  # noqa: E402


def main() -> int:
    payload = read_json_stdin()
    config = silent_exit_if_no_config()

    tool_name = payload.get("tool_name", "")

    if tool_name == "Bash":
        check_subdir_cd.run(config, payload)
        check_git_commit_alias.run(config, payload)
    elif tool_name in ("Write", "Edit", "MultiEdit"):
        check_task_md_baseline.run(config, payload)
        check_handoff_verify.run(config, payload)

    # No check tripped → allow by default (no JSON output).
    return 0


if __name__ == "__main__":
    sys.exit(main())
