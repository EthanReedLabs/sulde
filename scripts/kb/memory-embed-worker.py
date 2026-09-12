#!/usr/bin/env python3
"""Bounded scheduler entrypoint for the neutral memory embedding backlog."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from sulde_paths import launcher_home


def kb_home() -> Path:
    configured = os.environ.get("SULDE_KB_HOME")
    return (
        Path(configured).expanduser()
        if configured
        else Path.home() / ".sulde" / "data" / "kb"
    )


def main() -> int:
    home = kb_home()
    launcher = launcher_home(home) / "bin" / "kb-index"
    if not launcher.is_file():
        print(f"memory embed worker: stable launcher is unavailable: {launcher}", file=sys.stderr)
        return 2
    environment = os.environ.copy()
    environment["SULDE_KB_HOME"] = str(home)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [
            str(launcher),
            "mem-embed",
            "--limit",
            "250",
        ],
        env=environment,
        timeout=180,
        check=False,
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
