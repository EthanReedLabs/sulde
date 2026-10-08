"""Low-level persistence and inhibitory relocation fences, independent of policy.

Ledger writers can import these primitives without loading approval or execution
controllers. Fence absence never grants authority; original bounds are retained.
"""
from __future__ import annotations
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import time
from typing import Any, Iterator
from file_lock import lock_exclusive_nonblocking, unlock
from .decision_types import IntentGuardianError

MAX_WORKTREES = 128
MAX_STORE_BYTES = 256 * 1024**2
STORE_READ_BYTES = 1024**2
FENCE_SCHEMA = "sulde-repository-relocation-write-fence-v1"

def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


@contextmanager
def _exclusive_path_lock(lock_path: Path, *, timeout: float = 3.0) -> Iterator[None]:
    """Serialize one short state transition across Claude/Codex processes."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    with lock_path.open("a+", encoding="utf-8") as lock_handle:
        while True:
            try:
                lock_exclusive_nonblocking(lock_handle)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise IntentGuardianError(f"guardian state lock busy: {lock_path}")
                time.sleep(0.01)
        try:
            yield
        finally:
            unlock(lock_handle)


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode()).hexdigest()


def _canonical(path: Path) -> Path:
    """Do not erase evidence of a supplied symlink by resolving it first."""
    expanded = path.expanduser()
    if not expanded.is_absolute() or expanded != expanded.resolve():
        raise IntentGuardianError("relocation requires canonical absolute non-symlink paths")
    return expanded


def _git(root: Path, *args: str) -> bytes:
    # Never inherit a caller's alternate index/object/worktree/config lane, and
    # do not invoke a configured fsmonitor or refresh an index during a read.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_OPTIONAL_LOCKS="0")
    try:
        result = subprocess.run(
            ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", str(root), *args],
            env=env, capture_output=True, check=False, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise IntentGuardianError("relocation Git observation unavailable") from error
    if result.returncode:
        # Do not echo arbitrary Git diagnostics, local URLs, or file contents.
        raise IntentGuardianError("relocation Git observation failed")
    if len(result.stdout) > 8 * 1024**2:
        raise IntentGuardianError("relocation Git observation exceeds evidence bound")
    return result.stdout


def _read_plan_file(path: Path) -> dict[str, Any]:
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 8 * 1024**2):
        raise IntentGuardianError("relocation plan/decision is not a bounded owner-only file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as error:
        raise IntentGuardianError("relocation plan/decision is invalid") from error
    if not isinstance(value, dict):
        raise IntentGuardianError("relocation plan/decision must be an object")
    return value


def _store_home(path: Path) -> Path | None:
    """Do not consult ambient home, or apply a registry to arbitrary files."""
    # Normal stores may arrive through macOS /var or /tmp aliases. Resolve
    # their established location; strict source-root identity is a separate
    # relocation preflight check, not a new restriction on ordinary writers.
    path = path.expanduser().resolve()
    if path.name == "auto-sediment-source.json":
        return path.parent
    if path.parent.name in {"sessions", "workspaces"} and path.parent.parent.name == "intent":
        return path.parents[2]
    return None


def _fence_directory(home: Path) -> Path:
    return _canonical(home) / "intent" / "repository-relocations" / "write-fences"


def _read_write_fences(home: Path) -> list[dict[str, Any]]:
    root = _fence_directory(home)
    if not root.exists() and not root.is_symlink():
        return []
    _canonical(root)
    if not root.is_dir():
        raise IntentGuardianError("relocation fence registry is not a directory")
    paths = []
    for item in root.iterdir():
        paths.append(item)
        if len(paths) > MAX_WORKTREES:
            raise IntentGuardianError("relocation fence registry exceeds bound")
    values = []
    for path in sorted(paths):
        value = _read_plan_file(path)
        material = {key: val for key, val in value.items() if key != "sha256"}
        if (set(value) != {"schema", "source", "destination", "stores", "preflight_sha256", "sha256"}
                or value["schema"] != FENCE_SCHEMA or value["sha256"] != _digest(material)
                or path.name != value["sha256"] + ".json"
                or not isinstance(value["stores"], list) or not value["stores"]
                or len(value["stores"]) > MAX_WORKTREES * 32
                or not re.fullmatch(r"[0-9a-f]{64}", str(value["preflight_sha256"]))):
            raise IntentGuardianError("relocation fence record is invalid")
        for key in ("source", "destination"):
            if not isinstance(value[key], str):
                raise IntentGuardianError("relocation fence root is invalid")
            _canonical(Path(value[key]))
        for store in value["stores"]:
            if not isinstance(store, str) or _store_home(_canonical(Path(store))) != home:
                raise IntentGuardianError("relocation fence store is outside its registry")
        values.append(value)
    return values


def require_relocation_write_allowed(path: Path, *, workspace: Path | None = None) -> None:
    """Inhibitory check only, under the writer's own existing lock.

    A fence never authorizes any operation. Absence means this extra restriction
    does not apply, not that the normal policy/approval checks have passed. Pure
    ledger replay and other reads must not call this function.
    """
    home = _store_home(path)
    if home is None:
        return
    for value in _read_write_fences(home):
        affected = str(path.expanduser().resolve()) in value["stores"]
        if workspace is not None:
            root = workspace.expanduser().resolve()
            affected = affected or any(root.is_relative_to(Path(value[key])) for key in ("source", "destination"))
        if affected:
            raise IntentGuardianError("repository relocation pending: write fenced; use controlled relocation recovery")


@contextmanager
def relocation_registration_write(path: Path, *, workspace: Path):
    """Serialize only registry publication, never the whole migration window.

    Callers already hold their contract/mapping lock. The relocation publisher
    takes those locks first and this short registration lock last. Thus a new
    session/contract cannot appear between inventory revalidation and fence
    publication. Unrelated readers never acquire this lock.
    """
    home = _store_home(path)
    if home is None:
        yield
        return
    with _exclusive_path_lock(home / "intent" / ".repository-relocation-registry.lock"):
        require_relocation_write_allowed(path, workspace=workspace)
        yield


def _store_snapshot(path: Path, *, remaining_bytes: int | None = None,
                    allow_archive_link: bool = False,
                    max_bytes: int = MAX_STORE_BYTES,
                    read_bytes: int = STORE_READ_BYTES) -> dict[str, Any]:
    """Stream one stable owner-held store; never return its contents.

    The two-link exception is private to already-proven interrupted archival
    pairs. Initial snapshots and ordinary ledgers always require one link.
    """
    path = _canonical(path)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return {"sha256": "", "mode": None, "size": 0}
    except OSError as error:
        raise IntentGuardianError("relocation store cannot be opened without following links") from error
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise IntentGuardianError("relocation store is not a regular file")
        if before.st_uid != os.getuid():
            raise IntentGuardianError("relocation store belongs to another owner")
        if before.st_nlink not in ((1, 2) if allow_archive_link else (1,)):
            raise IntentGuardianError("relocation store link count differs")
        if before.st_size > max_bytes:
            raise IntentGuardianError("relocation store exceeds per-file byte bound")
        if remaining_bytes is not None and before.st_size > remaining_bytes:
            raise IntentGuardianError("relocation stores exceed total byte bound")
        digest, size = hashlib.sha256(), 0
        while True:
            chunk = os.read(fd, read_bytes)
            if not chunk:
                break
            size += len(chunk)
            if size > before.st_size:
                raise IntentGuardianError("relocation store grew during observation")
            digest.update(chunk)
        after, current = os.fstat(fd), path.lstat()
        def identity(info):
            return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink,
                    info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        if size != before.st_size or identity(after) != identity(before) or identity(current) != identity(before):
            raise IntentGuardianError("relocation store changed during observation")
        return {"sha256": digest.hexdigest(), "mode": stat.S_IMODE(before.st_mode), "size": size}
    except OSError as error:
        raise IntentGuardianError("relocation store changed or became unreadable during observation") from error
    finally:
        os.close(fd)
