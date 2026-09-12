#!/usr/bin/env python3
"""Portable non-blocking exclusive file locking for KB scripts."""

from __future__ import annotations

import errno
import os
from typing import IO


if os.name == "nt":
    import msvcrt
else:
    import fcntl


_LOCK_CONTENTION_ERRNOS = {errno.EACCES, errno.EAGAIN, errno.EDEADLK}


def lock_exclusive_nonblocking(handle: IO[str]) -> None:
    """Exclusively lock *handle*, raising BlockingIOError without waiting."""
    if os.name == "nt":
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            if error.errno in _LOCK_CONTENTION_ERRNOS:
                raise BlockingIOError(error.errno, error.strerror) from error
            raise
        return

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def unlock(handle: IO[str]) -> None:
    """Release a lock previously acquired by lock_exclusive_nonblocking."""
    if os.name == "nt":
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
