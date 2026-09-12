#!/usr/bin/env python3
"""Cross-platform integration tests for the KB scripts' file lock."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_exclusive_nonblocking_lock_can_be_reacquired_after_release(tmp_path: Path) -> None:
    from scripts.kb.file_lock import lock_exclusive_nonblocking, unlock

    lock_path = tmp_path / "portable.lock"
    lock_path.touch()
    holder_code = """
import sys
from pathlib import Path
from scripts.kb.file_lock import lock_exclusive_nonblocking, unlock

handle = Path(sys.argv[1]).open("a+")
lock_exclusive_nonblocking(handle)
print("locked", flush=True)
sys.stdin.readline()
unlock(handle)
handle.close()
"""
    holder = subprocess.Popen(
        [sys.executable, "-c", holder_code, str(lock_path)],
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    try:
        assert holder.stdout is not None
        assert holder.stdout.readline() == "locked\n"
        with lock_path.open("a+") as contender:
            started = time.monotonic()
            try:
                lock_exclusive_nonblocking(contender)
            except BlockingIOError:
                pass
            else:
                unlock(contender)
                raise AssertionError("a second process acquired an already-held lock")
            assert time.monotonic() - started < 1.0

        assert holder.stdin is not None
        holder.stdin.write("release\n")
        holder.stdin.flush()
        assert holder.wait(timeout=5) == 0

        with lock_path.open("a+") as reacquired:
            lock_exclusive_nonblocking(reacquired)
            unlock(reacquired)
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.wait(timeout=5)
