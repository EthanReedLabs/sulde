"""Ownership-scoped lifecycle for disposable native test hosts, not production."""
import os
import signal
import subprocess
import time


def start_fixture_process(*args, **kwargs):
    """Capture ownership at creation; never discover unrelated processes later."""
    if os.name == "posix":
        if kwargs.get("start_new_session", True) is not True:
            raise ValueError("fixture host requires its own session")
        kwargs["start_new_session"] = True
    process = subprocess.Popen(*args, **kwargs)
    process._sulde_fixture_group = process.pid if os.name == "posix" else None
    process._sulde_fixture_closed = False
    return process


def finish_fixture_process_group(process):
    """Bounded shutdown of a group created here, including an exited leader.

    A successful second call is a no-op, never a signal to a possibly reused
    PID. Escaped sessions are not discovered/killed by global process scanning.
    """
    if not hasattr(process, "_sulde_fixture_group"):
        raise AssertionError("refusing to signal a non-isolated fixture group")
    if process._sulde_fixture_closed:
        return
    group = process._sulde_fixture_group
    if os.name != "posix":
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        process._sulde_fixture_closed = True
        return
    if group != process.pid or group <= 1 or group == os.getpgrp():
        raise AssertionError("refusing to signal a non-isolated fixture group")

    def alive():
        process.poll()
        try:
            os.killpg(group, 0)
        except ProcessLookupError:
            return False
        return True

    for action in (signal.SIGTERM, signal.SIGKILL):
        if not alive():
            break
        try:
            os.killpg(group, action)
        except ProcessLookupError:
            break
        deadline = time.monotonic() + 3
        while alive() and time.monotonic() < deadline:
            time.sleep(0.02)
    if alive():
        raise AssertionError("fixture process group survived bounded shutdown")
    process._sulde_fixture_closed = True
