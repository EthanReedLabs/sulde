#!/usr/bin/env python3
"""POSIX parent-death watchdog for one managed provider process group.

The wrapper and provider share a fresh process group.  A private pipe is held
open only by the Sulde parent.  If that parent is hard-killed, EOF on the pipe
causes this wrapper to terminate the whole group, including itself.  Normal
provider stdout/stderr/stdin remain directly connected to the parent runtime.
"""

from __future__ import annotations

import argparse
import os
import select
import signal
import subprocess
import sys
import time


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--parent-fd", type=int, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command[:1] == ["--"]:
        args.command = args.command[1:]
    if not args.command:
        parser.error("provider command is required")
    return args


def main() -> int:
    args = parse_args()
    terminate_requested = False

    def request_termination(_signum: int, _frame: object) -> None:
        nonlocal terminate_requested
        terminate_requested = True

    signal.signal(signal.SIGTERM, request_termination)
    signal.signal(signal.SIGINT, request_termination)
    provider = subprocess.Popen(args.command)
    parent_fd = args.parent_fd
    parent_alive = True
    try:
        while provider.poll() is None:
            readable, _, _ = select.select([parent_fd], [], [], 0.1)
            if readable:
                try:
                    parent_alive = bool(os.read(parent_fd, 1))
                except OSError:
                    parent_alive = False
                if not parent_alive:
                    terminate_requested = True
            if not terminate_requested:
                continue
            try:
                os.killpg(os.getpgrp(), signal.SIGTERM)
            except ProcessLookupError:
                pass
            deadline = time.monotonic() + 0.5
            while provider.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            if provider.poll() is None or not parent_alive:
                # SIGKILL also ends this wrapper.  That is intentional: after
                # parent death there must be no watchdog or provider survivor.
                os.killpg(os.getpgrp(), signal.SIGKILL)
            break
        returncode = provider.wait()
        return int(returncode)
    finally:
        try:
            os.close(parent_fd)
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
