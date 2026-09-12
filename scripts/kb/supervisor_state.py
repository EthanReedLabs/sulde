#!/usr/bin/env python3
"""Strict append-only state rooted at one retained parent directory."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import threading
from typing import Any, Callable, Iterator


STATE_SCHEMA = "sulde-recovery-supervisor-state-v1"
ROW_SCHEMA = "sulde-recovery-supervisor-state-row-v1"
IDENTITY_SCHEMA = "sulde-recovery-supervisor-identity-v1"
ROW_FIELDS = frozenset({
    "schema", "sequence", "previous_sha256", "event_type",
    "event_identity", "payload", "row_sha256",
})
_LOCAL_LOCKS_GUARD = threading.Lock()
_LOCAL_LOCKS: dict[tuple[int, int, str], threading.Lock] = {}


class SupervisorStateError(RuntimeError):
    """Durable state cannot be trusted or committed."""


class SupervisorStateBusyError(SupervisorStateError):
    """The bounded state lock is already held."""


def require_plain_json(value: Any, *, name: str = "value") -> None:
    kind = type(value)
    if kind in {type(None), str, int, bool}:
        return
    if kind is float:
        if math.isfinite(value):
            return
        raise SupervisorStateError(f"{name} contains a non-finite number")
    if kind is list:
        for index, child in enumerate(value):
            require_plain_json(child, name=f"{name}[{index}]")
        return
    if kind is dict:
        for key, child in value.items():
            if type(key) is not str:
                raise SupervisorStateError(f"{name} contains a non-string key")
            require_plain_json(child, name=f"{name}.{key}")
        return
    raise SupervisorStateError(f"{name} must contain only exact plain JSON types")


def exact_object(
    value: Any, *, name: str, fields: frozenset[str] | None = None,
) -> dict[str, Any]:
    require_plain_json(value, name=name)
    if type(value) is not dict:
        raise SupervisorStateError(f"{name} must be an exact object")
    if fields is not None and frozenset(value) != fields:
        missing = sorted(fields - frozenset(value))
        extra = sorted(frozenset(value) - fields)
        raise SupervisorStateError(
            f"{name} fields invalid: missing={missing}; extra={extra}"
        )
    return value


def exact_text(value: Any, *, name: str) -> str:
    if type(value) is not str or not value.strip():
        raise SupervisorStateError(f"{name} must be an exact non-empty string")
    return value


def canonical_digest(domain: str, value: Any) -> str:
    exact_text(domain, name="digest domain")
    require_plain_json(value, name="digest value")
    envelope = {"schema": IDENTITY_SCHEMA, "domain": domain, "value": value}
    encoded = json.dumps(
        envelope, ensure_ascii=False, allow_nan=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def event_identity(event_type: Any, payload: Any) -> str:
    selected = exact_text(event_type, name="event_type")
    exact_object(payload, name="payload")
    return canonical_digest(f"supervisor-event:{selected}", payload)


def _row_digest(material: dict[str, Any]) -> str:
    return canonical_digest("supervisor-state-row", material)


def _trusted_uid() -> int:
    return os.geteuid() if hasattr(os, "geteuid") else os.getuid()


def _private_regular(value: os.stat_result, label: str) -> None:
    if not stat.S_ISREG(value.st_mode):
        raise SupervisorStateError(f"{label} must be a regular file")
    if value.st_nlink != 1:
        raise SupervisorStateError(f"{label} must have exactly one hard link")
    if value.st_uid != _trusted_uid():
        raise SupervisorStateError(f"{label} owner is not trusted")
    if stat.S_IMODE(value.st_mode) & ~0o600:
        raise SupervisorStateError(f"{label} mode is broader than 0600")


class SupervisorState:
    """Owner-only hash-chain journal with fail-fast serialized access."""

    def __init__(
        self, path: str | os.PathLike[str], *,
        failpoint: Callable[[str], None] | None = None,
    ) -> None:
        raw = os.fspath(path)
        if type(raw) not in {str, bytes} or not os.path.isabs(raw):
            raise SupervisorStateError("state path must be absolute")
        lexical = Path(raw)
        if lexical.name in {"", ".", ".."}:
            raise SupervisorStateError("state journal leaf is invalid")
        try:
            parent = lexical.parent.resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise SupervisorStateError(f"state parent is not canonical: {error}") from error
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            parent_fd = os.open(parent, flags)
        except OSError as error:
            raise SupervisorStateError(f"cannot retain state parent: {error}") from error
        self._parent_path = parent
        self._parent_fd = parent_fd
        self._parent_identity = self._identity(os.fstat(parent_fd))
        self._journal_leaf = lexical.name
        self._lock_leaf = f".{lexical.name}.lock"
        self._leaf_identities: dict[str, tuple[int, int]] = {}
        local_key = (*self._parent_identity, self._lock_leaf)
        with _LOCAL_LOCKS_GUARD:
            self._local_lock = _LOCAL_LOCKS.setdefault(local_key, threading.Lock())
        self.path = parent / self._journal_leaf
        self.lock_path = parent / self._lock_leaf
        self._expected_path = self.path
        self._expected_lock_path = self.lock_path
        self._failpoint = failpoint or (lambda _boundary: None)
        try:
            self._validate_parent()
            for leaf, label in (
                (self._journal_leaf, "state journal"),
                (self._lock_leaf, "state lock"),
            ):
                existing = self._named_stat(leaf, missing_ok=True)
                if existing is not None:
                    _private_regular(existing, label)
                    self._leaf_identities[leaf] = self._identity(existing)
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _identity(value: os.stat_result) -> tuple[int, int]:
        return value.st_dev, value.st_ino

    def close(self) -> None:
        descriptor = getattr(self, "_parent_fd", -1)
        if descriptor >= 0:
            os.close(descriptor)
            self._parent_fd = -1

    def __del__(self) -> None:
        try:
            self.close()
        except OSError:
            pass

    def _validate_parent(self) -> None:
        if (
            self.path != self._expected_path
            or self.lock_path != self._expected_lock_path
            or self._journal_leaf != self._expected_path.name
            or self._lock_leaf != self._expected_lock_path.name
        ):
            raise SupervisorStateError("state path metadata was substituted")
        try:
            opened = os.fstat(self._parent_fd)
            named = os.stat(self._parent_path, follow_symlinks=False)
        except OSError as error:
            raise SupervisorStateError(
                f"state parent identity unavailable: {error}"
            ) from error
        if not stat.S_ISDIR(opened.st_mode) or not stat.S_ISDIR(named.st_mode):
            raise SupervisorStateError("state parent must remain a directory")
        if self._identity(opened) != self._parent_identity:
            raise SupervisorStateError("retained state parent descriptor was substituted")
        if self._identity(named) != self._parent_identity:
            raise SupervisorStateError("state parent pathname identity changed")
        if opened.st_uid != _trusted_uid() or named.st_uid != _trusted_uid():
            raise SupervisorStateError("state parent owner is not trusted")
        mode = stat.S_IMODE(opened.st_mode)
        if mode & 0o022:
            raise SupervisorStateError("state parent mode permits untrusted writes")
        if mode & 0o200 == 0:
            raise SupervisorStateError("state parent is read-only")

    def _named_stat(
        self, leaf: str, *, missing_ok: bool = False,
    ) -> os.stat_result | None:
        self._validate_parent()
        try:
            return os.stat(leaf, dir_fd=self._parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            if missing_ok:
                return None
            raise SupervisorStateError(f"sensitive leaf {leaf} is missing")
        except OSError as error:
            raise SupervisorStateError(f"cannot stat sensitive leaf {leaf}: {error}") from error

    def _check_leaf(self, descriptor: int, leaf: str, label: str) -> None:
        try:
            opened = os.fstat(descriptor)
        except OSError as error:
            raise SupervisorStateError(f"cannot stat open {label}: {error}") from error
        named = self._named_stat(leaf)
        assert named is not None
        _private_regular(opened, label)
        _private_regular(named, label)
        if self._identity(opened) != self._identity(named):
            raise SupervisorStateError(f"{label} pathname identity changed")
        identity = self._identity(opened)
        retained = self._leaf_identities.get(leaf)
        if retained is not None and retained != identity:
            raise SupervisorStateError(f"{label} retained identity changed")
        self._leaf_identities.setdefault(leaf, identity)

    def _open_private(self, leaf: str, flags: int, label: str) -> int:
        self._validate_parent()
        flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        try:
            descriptor = os.open(leaf, flags, 0o600, dir_fd=self._parent_fd)
        except OSError as error:
            raise SupervisorStateError(f"cannot open {label}: {error}") from error
        try:
            self._check_leaf(descriptor, leaf, label)
        except BaseException:
            os.close(descriptor)
            raise
        return descriptor

    @contextmanager
    def _locked(self) -> Iterator[None]:
        if not self._local_lock.acquire(timeout=1.0):
            raise SupervisorStateBusyError(
                "state writer lock is busy; bounded acquisition failed closed"
            )
        descriptor: int | None = None
        locked = False
        try:
            descriptor = self._open_private(
                self._lock_leaf, os.O_RDWR | os.O_CREAT, "state lock"
            )
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except BlockingIOError as error:
                raise SupervisorStateBusyError(
                    "state writer lock is busy; bounded acquisition failed closed"
                ) from error
            self._check_leaf(descriptor, self._lock_leaf, "state lock")
            yield
            self._check_leaf(descriptor, self._lock_leaf, "state lock")
        finally:
            if locked:
                assert descriptor is not None
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            if descriptor is not None:
                os.close(descriptor)
            self._local_lock.release()

    def _read_unlocked(self) -> list[dict[str, Any]]:
        if self._named_stat(self._journal_leaf, missing_ok=True) is None:
            return []
        descriptor = self._open_private(
            self._journal_leaf, os.O_RDONLY, "state journal"
        )
        try:
            chunks: list[bytes] = []
            while True:
                chunk = os.read(descriptor, 65536)
                if not chunk:
                    break
                chunks.append(chunk)
            self._check_leaf(descriptor, self._journal_leaf, "state journal")
        finally:
            os.close(descriptor)
        raw = b"".join(chunks)
        if raw and not raw.endswith(b"\n"):
            raise SupervisorStateError("state journal has a torn final row")
        rows: list[dict[str, Any]] = []
        previous: str | None = None
        identities: set[str] = set()
        for sequence, line in enumerate(raw.splitlines(), start=1):
            try:
                parsed = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise SupervisorStateError(
                    f"state journal row {sequence} is malformed"
                ) from error
            row = exact_object(parsed, name=f"row[{sequence}]", fields=ROW_FIELDS)
            if row["schema"] != ROW_SCHEMA:
                raise SupervisorStateError("state row schema is invalid")
            if type(row["sequence"]) is not int or row["sequence"] != sequence:
                raise SupervisorStateError("state row sequence is invalid")
            if row["previous_sha256"] != previous:
                raise SupervisorStateError("state row predecessor is invalid")
            selected_type = exact_text(row["event_type"], name="row.event_type")
            payload = exact_object(row["payload"], name="row.payload")
            expected_event = event_identity(selected_type, payload)
            if row["event_identity"] != expected_event:
                raise SupervisorStateError("state event identity was tampered")
            material = {field: row[field] for field in ROW_FIELDS - {"row_sha256"}}
            expected_row = _row_digest(material)
            if row["row_sha256"] != expected_row:
                raise SupervisorStateError("state row digest was tampered")
            if expected_event in identities:
                raise SupervisorStateError("state contains duplicate event identities")
            identities.add(expected_event)
            previous = expected_row
            rows.append(deepcopy(row))
        return rows

    @staticmethod
    def _snapshot(rows: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "schema": STATE_SCHEMA,
            "sequence": len(rows),
            "head_sha256": rows[-1]["row_sha256"] if rows else None,
            "events": [{
                "event_type": row["event_type"],
                "event_identity": row["event_identity"],
                "payload": deepcopy(row["payload"]),
                "journal_sequence": row["sequence"],
                "row_sha256": row["row_sha256"],
            } for row in rows],
        }

    def rows(self) -> list[dict[str, Any]]:
        with self._locked():
            return self._read_unlocked()

    def snapshot(self) -> dict[str, Any]:
        with self._locked():
            return self._snapshot(self._read_unlocked())

    def snapshot_read_only(self) -> dict[str, Any]:
        """Validate a stable journal without manufacturing a lock or authority.

        Concurrent appends are inconclusive, never silently accepted as a
        healthy snapshot. Mutating callers must still use the writer lock.
        """
        before = self._named_stat(self._journal_leaf, missing_ok=True)
        rows = self._read_unlocked()
        after = self._named_stat(self._journal_leaf, missing_ok=True)
        def identity(value):
            return None if value is None else (
                value.st_dev, value.st_ino, value.st_size,
                value.st_mtime_ns, value.st_ctime_ns,
            )
        if identity(before) != identity(after):
            raise SupervisorStateBusyError("state changed during read-only observation")
        return self._snapshot(rows)

    @staticmethod
    def _validate_unique(payload: dict[str, Any], fields: tuple[str, ...]) -> None:
        if type(fields) is not tuple or any(
            type(field) is not str or field not in payload for field in fields
        ):
            raise SupervisorStateError("unique_fields must bind existing payload fields")

    def _append_unlocked(
        self, rows: list[dict[str, Any]], event_type: str,
        payload: dict[str, Any], unique_fields: tuple[str, ...],
    ) -> dict[str, Any]:
        selected_identity = event_identity(event_type, payload)
        for row in rows:
            if row["event_identity"] == selected_identity:
                return {"status": "duplicate", "row": deepcopy(row)}
            if unique_fields and row["event_type"] == event_type and all(
                row["payload"].get(field) == payload[field] for field in unique_fields
            ):
                raise SupervisorStateError(
                    f"{event_type} immutable identity has conflicting payloads"
                )
        material = {
            "schema": ROW_SCHEMA, "sequence": len(rows) + 1,
            "previous_sha256": rows[-1]["row_sha256"] if rows else None,
            "event_type": event_type, "event_identity": selected_identity,
            "payload": payload,
        }
        row = {**material, "row_sha256": _row_digest(material)}
        encoded = (json.dumps(
            row, ensure_ascii=False, allow_nan=False, sort_keys=True,
            separators=(",", ":"),
        ) + "\n").encode("utf-8")
        self._failpoint("before_append")
        descriptor = self._open_private(
            self._journal_leaf, os.O_WRONLY | os.O_APPEND | os.O_CREAT,
            "state journal",
        )
        try:
            if stat.S_IMODE(os.fstat(descriptor).st_mode) & 0o200 == 0:
                raise SupervisorStateError("state journal is read-only")
            if os.write(descriptor, encoded) != len(encoded):
                raise SupervisorStateError("state journal append was partial")
            self._failpoint("after_append_before_fsync")
            os.fsync(descriptor)
            self._failpoint("after_fsync")
            self._check_leaf(descriptor, self._journal_leaf, "state journal")
        except OSError as error:
            raise SupervisorStateError(f"cannot append state journal: {error}") from error
        finally:
            os.close(descriptor)
        return {"status": "appended", "row": deepcopy(row)}

    def append(
        self, event_type: Any, payload: Any, *,
        unique_fields: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        selected_type = exact_text(event_type, name="event_type")
        selected_payload = deepcopy(exact_object(payload, name="payload"))
        self._validate_unique(selected_payload, unique_fields)
        with self._locked():
            return self._append_unlocked(
                self._read_unlocked(), selected_type, selected_payload, unique_fields
            )

    def append_derived(
        self, event_type: Any,
        derive: Callable[[dict[str, Any]], dict[str, Any]], *,
        unique_fields: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        """Derive and append under one durable writer critical section."""
        selected_type = exact_text(event_type, name="event_type")
        if not callable(derive):
            raise SupervisorStateError("derive must be callable")
        with self._locked():
            rows = self._read_unlocked()
            payload = deepcopy(exact_object(
                derive(self._snapshot(rows)), name="derived payload"
            ))
            self._validate_unique(payload, unique_fields)
            return self._append_unlocked(
                rows, selected_type, payload, unique_fields
            )
