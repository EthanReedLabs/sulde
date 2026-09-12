#!/usr/bin/env python3
"""Bounded Sulde statusline reader for interactive host startup paths."""

from __future__ import annotations

import os
import sys

sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

from pathlib import Path

from sulde_status_snapshot import read_snapshot


def kb_home() -> Path:
    configured = os.environ.get("SULDE_KB_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".sulde" / "data" / "kb"


def configure_utf8_stdio() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="strict")
            except (LookupError, OSError, ValueError):
                pass


def main() -> int:
    configure_utf8_stdio()
    # ``--statusline`` is accepted because stable launchers append it.  No
    # other mode is intentionally exposed from this startup-only entrypoint.
    if sys.argv[1:] not in ([], ["--statusline"]):
        print("usage: sulde-statusline.py [--statusline]", file=sys.stderr)
        return 2
    snapshot = read_snapshot(kb_home())
    print(snapshot["line"])
    return 0 if snapshot["healthy"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
