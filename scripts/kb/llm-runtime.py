#!/usr/bin/env python3
"""Execute one Sulde cognitive prompt through Claude Code or Codex."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

from runtime_provider import ProviderError, cognitive_command, select_provider


WINDOWS_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("auto", "claude", "codex"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        provider, executable = select_provider(args.provider)
        command = cognitive_command(provider, executable)
        environment = os.environ.copy()
        environment["SULDE_ACTIVE_PROVIDER"] = provider
        if os.name == "nt":
            completed = subprocess.run(
                command,
                input=sys.stdin.read(),
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                creationflags=WINDOWS_CREATE_NO_WINDOW,
            )
            return completed.returncode
        os.execvpe(command[0], command, environment)
    except (ProviderError, OSError) as error:
        print(f"SULDE LLM RUNTIME: FAIL: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
