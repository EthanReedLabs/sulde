"""Generation-switch admission fence (R3 followup 2).

Linearizes lease admission against generation switches: the installer's
fence write + final scope re-check and a run's fence check + lease
publication are mutually exclusive short critical sections on one fence
lock at kb_home.  A run started before a switch can therefore never
publish a superseded-generation lease after the installer's final
re-check — the window is closed by protocol, not by additional checks.
The lock is short (milliseconds per admission); ordinary tasks, old
in-flight runs (which keep their existing leases), and the recovery
channel are never held for the duration of an install.

Fence states: absent (no switch in progress), ``in-switch`` (admission
refused for every generation except the switch target), and removed
(switch committed or rolled back).  The fence file is written and
removed atomically; a damaged fence fails open for admission
(availability of ordinary tasks), while the installer always rewrites
it under the lock.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import time
from typing import Iterator
import uuid

from file_lock import lock_exclusive_nonblocking, unlock


FENCE_NAME = ".generation-switch-fence.json"
FENCE_LOCK_NAME = ".generation-switch-fence.lock"
FENCE_SCHEMA = "sulde-generation-switch-fence-v1"
_GUARD_TIMEOUT_SECONDS = 10.0


class GenerationFenceError(RuntimeError):
    """The admission fence protocol cannot be satisfied."""


def fence_path(kb_home: Path) -> Path:
    return Path(kb_home) / FENCE_NAME


def fence_lock_path(kb_home: Path) -> Path:
    return Path(kb_home) / FENCE_LOCK_NAME


@contextmanager
def fence_lock(kb_home: Path) -> Iterator[None]:
    """Hold the kb_home fence lock (short bounded critical section).

    Installers hold this across [fence write + final scope re-check];
    lease admission holds it across [fence check + lease publication].
    """
    lock = fence_lock_path(kb_home)
    lock.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    handle = lock.open("a+", encoding="utf-8")
    deadline = time.monotonic() + _GUARD_TIMEOUT_SECONDS
    while True:
        try:
            lock_exclusive_nonblocking(handle)
            break
        except BlockingIOError:
            if time.monotonic() >= deadline:
                handle.close()
                raise GenerationFenceError(
                    f"generation-switch fence lock is contended: {lock}"
                )
            time.sleep(0.01)
    try:
        yield
    finally:
        try:
            unlock(handle)
        finally:
            handle.close()


def write_fence(
    kb_home: Path,
    *,
    from_generation: str | None,
    to_generation: str,
    transaction_id: str | None = None,
    transaction_descriptor_sha256: str | None = None,
) -> None:
    """Atomically publish the in-switch fence.  Callers hold fence_lock."""
    fence = {
        "schema": FENCE_SCHEMA,
        "schema_version": 1,
        "state": "in-switch",
        "from_generation": from_generation,
        "to_generation": to_generation,
        "transaction_id": transaction_id,
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "token": uuid.uuid4().hex,
    }
    if transaction_descriptor_sha256 is not None:
        fence["transaction_descriptor_sha256"] = transaction_descriptor_sha256
    target = fence_path(kb_home)
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(fence, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, target)
    directory = os.open(target.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def clear_fence(kb_home: Path) -> bool:
    """Remove the fence (commit, rollback, or recovery).  Idempotent."""
    try:
        fence_path(kb_home).unlink()
        descriptor = os.open(Path(kb_home), os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return True
    except FileNotFoundError:
        return False


def read_fence(kb_home: Path) -> dict | None:
    """Read the fence state; missing/damaged fences read as no fence."""
    path = fence_path(kb_home)
    if not path.is_file() or path.is_symlink():
        return None
    try:
        fence = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(fence, dict) or fence.get("schema") != FENCE_SCHEMA:
        return None
    return fence


def fence_refusal(kb_home: Path, *, run_generation: str) -> str | None:
    """Why this run's admission is refused, or None if it may proceed."""
    fence = read_fence(kb_home)
    if fence is None or fence.get("state") != "in-switch":
        return None
    to_generation = fence.get("to_generation")
    if not isinstance(to_generation, str) or run_generation == to_generation:
        return None
    return (
        "generation switch in progress: this run carries the superseded "
        f"generation {run_generation!r}; resubmit after the switch completes"
    )


@contextmanager
def admission_fence(
    kb_home: Path, *, run_generation: str
) -> Iterator[None]:
    """Run-side admission critical section.

    Holds the fence lock across [fence check + lease publication].  A
    superseded-generation run is refused (GenerationFenceError) instead of
    silently acquiring a lease during an in-flight switch; the target
    generation is admitted and the lock stays held until the caller has
    published its lease.
    """
    with fence_lock(kb_home):
        refusal = fence_refusal(kb_home, run_generation=run_generation)
        if refusal is not None:
            raise GenerationFenceError(refusal)
        yield
