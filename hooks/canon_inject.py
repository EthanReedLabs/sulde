#!/usr/bin/env python3
"""SessionStart canon injection: unconditional, before any project-config gate.

CANON.md ships at plugin root; every session in every project gets it as
additionalContext. Kept standalone so failure or absence degrades silently.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE / "lib"))

from sulde_common import configure_utf8_stdio  # noqa: E402

configure_utf8_stdio()

MAX_CHARS = 4000


def main() -> int:
    try:
        text = (Path(__file__).resolve().parents[1] / "CANON.md").read_text(
            encoding="utf-8"
        ).strip()[:MAX_CHARS]
    except OSError:
        return 0
    if not text:
        return 0
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": f"[sulde-canon]\n{text}",
                }
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
