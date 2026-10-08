"""Bounded concurrency quota for managed runs.

Parallel managed runs are capped by lease files under the workspace state
directory.  A lease is one exclusively-locked file held for the lifetime of
one run; a lease whose lock can be re-acquired belongs to a dead process.

Atomicity (R1-02): every lease mutation — pruning, counting, creating,
locking, rechecking, releasing — happens under one exclusive *guard lock*
(``.guard.lock``) in the leases directory.  A lease therefore can never be
observed in its created-but-unlocked window, which previously let a scanner
delete a just-created lease and over-commit the quota.  Crash semantics:
locks die with their process; the managed-run parent-death watchdog bounds
the provider child tree, so a prunable lease implies its creator (and by the
watchdog contract its execution tree) is gone.

Scope (R1-02): the quota and the active-generation projection are scoped to
one leases directory (one workspace state directory).  Nothing here claims
global cross-worktree coverage; consumers must aggregate every scope they
care about.  Read-only observers never mutate: pruning happens only on the
acquisition path.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from typing import Any, IO, Iterator

from file_lock import lock_exclusive_nonblocking, unlock


RUN_LEASE_SCHEMA = "sulde-run-lease-v1"
DEFAULT_MAX_CONCURRENT_RUNS = 4
GUARD_LOCK_FILENAME = ".guard.lock"
_LEASE_POLL_SECONDS = 0.1
_GUARD_TIMEOUT_SECONDS = 5.0


class RunConcurrencyError(RuntimeError):
    """A concurrency slot cannot be acquired or released safely."""


class RunConcurrencyLimitError(RunConcurrencyError):
    """Every bounded slot is held by a live process."""


class RunConcurrencyBusyError(RunConcurrencyError):
    """The lease-directory guard lock is contended beyond its bound."""


def max_concurrent_runs(environment: dict[str, str] | None = None) -> int:
    current = os.environ if environment is None else environment
    raw = str(current.get("SULDE_MAX_CONCURRENT_RUNS") or "").strip()
    if not raw:
        return DEFAULT_MAX_CONCURRENT_RUNS
    try:
        value = int(raw)
    except ValueError as error:
        raise RunConcurrencyError(
            f"SULDE_MAX_CONCURRENT_RUNS is not an integer: {raw!r}"
        ) from error
    if value < 1:
        raise RunConcurrencyError(
            f"SULDE_MAX_CONCURRENT_RUNS must be >= 1, got {value}"
        )
    return value


def _lease_is_stale(path: Path) -> bool:
    """A lease is stale exactly when its exclusive lock can be re-acquired.

    Only meaningful under the guard lock: outside it the created-but-unlocked
    window would make a live lease look stale.
    """
    try:
        handle = path.open("r+", encoding="utf-8")
    except FileNotFoundError:
        return False
    except OSError as error:
        raise RunConcurrencyError(
            f"run lease cannot be inspected: {path}: {error}"
        ) from error
    try:
        lock_exclusive_nonblocking(handle)
    except BlockingIOError:
        return False
    finally:
        handle.close()
    return True


def _prune_stale_leases(leases_dir: Path) -> int:
    """Prune dead-process leases.  Callers must hold the guard lock."""
    pruned = 0
    for candidate in sorted(leases_dir.glob("*.lease")):
        if _lease_is_stale(candidate):
            try:
                candidate.unlink()
                pruned += 1
            except FileNotFoundError:
                pass
            except OSError as error:
                raise RunConcurrencyError(
                    f"stale run lease cannot be pruned: {candidate}: {error}"
                ) from error
    return pruned


def _live_lease_count(leases_dir: Path) -> int:
    return sum(1 for candidate in leases_dir.glob("*.lease") if candidate.is_file())


@contextmanager
def lease_guard(leases_dir: Path) -> Iterator[None]:
    """Hold the lease-directory guard lock (bounded wait, fail closed).

    This is the coordination point required by R1-01: generation-aware
    reclamation holds the same guard across its reference-check-and-delete
    window, so a managed run cannot acquire a lease for a generation between
    the check and the deletion.
    """
    try:
        leases_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError as error:
        raise RunConcurrencyError(
            f"run lease directory cannot be created: {error}"
        ) from error
    guard_path = leases_dir / GUARD_LOCK_FILENAME
    try:
        handle = guard_path.open("a+", encoding="utf-8")
    except OSError as error:
        raise RunConcurrencyError(
            f"run lease guard lock cannot be opened: {error}"
        ) from error
    deadline = time.monotonic() + _GUARD_TIMEOUT_SECONDS
    while True:
        try:
            lock_exclusive_nonblocking(handle)
            break
        except BlockingIOError:
            if time.monotonic() >= deadline:
                handle.close()
                raise RunConcurrencyBusyError(
                    f"run lease guard lock is contended: {guard_path}"
                )
            time.sleep(0.01)
    try:
        yield
    finally:
        try:
            unlock(handle)
        finally:
            handle.close()


class RunLease:
    """One held concurrency slot; release is idempotent and guard-serialized."""

    def __init__(self, path: Path, handle: IO[str], leases_dir: Path) -> None:
        self.path = path
        self._handle: IO[str] | None = handle
        self._leases_dir = leases_dir

    @property
    def held(self) -> bool:
        return self._handle is not None

    def release(self) -> None:
        handle, self._handle = self._handle, None
        if handle is None:
            return
        # Guard-serialized so a concurrent reclamation cannot observe this
        # lease half-released (unlocked file still present, or vice versa).
        with lease_guard(self._leases_dir):
            try:
                unlock(handle)
            finally:
                handle.close()
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass


def active_run_leases(leases_dir: Path) -> list[dict[str, Any]]:
    """Read-only projection of lease files with their labels and generations.

    Never mutates the directory (no pruning — pruning is an acquisition-path
    responsibility).  A lease whose creating process crashed after creation
    but before its next acquisition-path prune stays listed: a stale entry
    counts as an active reference for generation safety, which is the
    conservative direction.
    """
    projection: list[dict[str, Any]] = []
    for candidate in sorted(leases_dir.glob("*.lease")):
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            payload = {}
        if payload.get("schema") != RUN_LEASE_SCHEMA:
            payload = {"schema": RUN_LEASE_SCHEMA}
        projection.append(
            {
                "path": str(candidate),
                "pid": payload.get("pid"),
                "label": payload.get("label"),
                "runtime_generation": payload.get("runtime_generation"),
                "acquired_at": payload.get("acquired_at"),
            }
        )
    return projection


def acquire_run_slot(
    state_dir: Path,
    *,
    max_concurrent: int | None = None,
    timeout_seconds: float = 30.0,
    label: str = "managed-run",
    runtime_generation: str | None = None,
) -> RunLease:
    """Acquire one bounded slot or raise RunConcurrencyLimitError.

    The lease evidence records the runtime generation the run started with
    (C3): the installer/generation guard can then see which generations have
    in-flight executions before switching or reclaiming anything.  All quota
    bookkeeping is serialized by the directory guard lock.
    """
    if max_concurrent is None:
        max_concurrent = max_concurrent_runs()
    if max_concurrent < 1:
        raise RunConcurrencyError("max_concurrent must be >= 1")
    leases_dir = state_dir / "run-leases"
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while True:
        with lease_guard(leases_dir):
            _prune_stale_leases(leases_dir)
            if _live_lease_count(leases_dir) < max_concurrent:
                lease_path = leases_dir / f"{os.getpid()}-{time.monotonic_ns()}.lease"
                try:
                    handle = lease_path.open("x", encoding="utf-8")
                except FileExistsError:
                    continue
                except OSError as error:
                    raise RunConcurrencyError(
                        f"run lease cannot be created: {error}"
                    ) from error
                evidence = {
                    "schema": RUN_LEASE_SCHEMA,
                    "label": label[:128],
                    "pid": os.getpid(),
                    "runtime_generation": (
                        str(runtime_generation)[:256] if runtime_generation else None
                    ),
                    "acquired_at": datetime.now(timezone.utc).isoformat(),
                }
                try:
                    handle.write(json.dumps(evidence, sort_keys=True))
                    handle.flush()
                    lock_exclusive_nonblocking(handle)
                except OSError as error:
                    handle.close()
                    try:
                        lease_path.unlink()
                    except FileNotFoundError:
                        pass
                    raise RunConcurrencyError(
                        f"run lease cannot be locked: {error}"
                    ) from error
                # Count includes our own just-created lease; still under the
                # guard, so no other process can have slipped in.
                if _live_lease_count(leases_dir) <= max_concurrent:
                    return RunLease(lease_path, handle, leases_dir)
                unlock(handle)
                handle.close()
                try:
                    lease_path.unlink()
                except FileNotFoundError:
                    pass
        if time.monotonic() >= deadline:
            raise RunConcurrencyLimitError(
                "bounded run concurrency exhausted: "
                f"{max_concurrent} slot(s) held for {label}"
            )
        time.sleep(_LEASE_POLL_SECONDS)
