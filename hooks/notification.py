#!/usr/bin/env python3
"""sulde-cc Notification entrypoint."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE / "lib"))

from sulde_common import configure_utf8_stdio  # noqa: E402

import kb_notify  # noqa: E402

configure_utf8_stdio()


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    kb_notify.run(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
