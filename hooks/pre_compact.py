#!/usr/bin/env python3
"""sulde-cc PreCompact entrypoint."""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE / "lib"))

from sulde_common import read_json_stdin, silent_exit_if_no_config  # noqa: E402

import kb_compact  # noqa: E402

try:
    import yaml  # noqa: F401
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False


def main() -> int:
    payload = read_json_stdin()
    kb_compact.run(payload)
    if not _HAS_YAML:
        return 0
    silent_exit_if_no_config()
    return 0


if __name__ == "__main__":
    sys.exit(main())
