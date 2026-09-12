"""Crash-safe incremental cursors for append-only JSONL audit logs.

The module has no Sulde runtime or environment dependencies.  Callers own the
meaning of a row; this module owns file identity, append boundaries, sequence
and generation continuity, and atomic compare-and-swap persistence.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any


CURSOR_SCHEMA = "sulde-audit-cursor-v2"
EMPTY_CHAIN_SHA256 = hashlib.sha256(b"").hexdigest()
PREFIX_SEGMENT_BYTES = 64 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class AuditCursorError(RuntimeError):
    """The log or cursor cannot be trusted."""


class AuditCursorConflict(AuditCursorError):
    """Another writer won the cursor compare-and-swap."""


class AuditPrefixMismatch(AuditCursorError):
    """A persisted content-addressed prefix segment no longer matches the log."""


@dataclass(frozen=True)
class PrefixSegment:
    start: int
    length: int
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {"start": self.start, "length": self.length, "sha256": self.sha256}

    @classmethod
    def from_dict(cls, value: Any) -> "PrefixSegment":
        if not isinstance(value, dict):
            raise AuditCursorError("cursor prefix segment is invalid")
        start = value.get("start")
        length = value.get("length")
        digest = value.get("sha256")
        if (
            not isinstance(start, int)
            or isinstance(start, bool)
            or start < 0
            or not isinstance(length, int)
            or isinstance(length, bool)
            or length <= 0
            or length > PREFIX_SEGMENT_BYTES
            or not isinstance(digest, str)
            or _SHA256.fullmatch(digest) is None
        ):
            raise AuditCursorError("cursor prefix segment is invalid")
        return cls(start=start, length=length, sha256=digest)


@dataclass(frozen=True)
class AuditCursor:
    log_device: int
    log_inode: int
    offset: int
    last_event_hash: str
    last_sequence: int | None
    runtime_generation: str
    chain_sha256: str = EMPTY_CHAIN_SHA256
    last_line_start: int = 0
    last_line_sha256: str = ""
    prefix_start: int = 0
    prefix_segments: tuple[PrefixSegment, ...] = ()
    recovery_diagnostics: tuple[str, ...] = ()
    revision: int = 0
    projection: dict[str, Any] = field(default_factory=dict)
    schema: str = CURSOR_SCHEMA
    _storage_sha256: str = field(default="", compare=False, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "revision": self.revision,
            "log_identity": {
                "device": self.log_device,
                "inode": self.log_inode,
            },
            "offset": self.offset,
            "last_event_hash": self.last_event_hash,
            "last_sequence": self.last_sequence,
            "runtime_generation": self.runtime_generation,
            "chain_sha256": self.chain_sha256,
            "last_line_start": self.last_line_start,
            "last_line_sha256": self.last_line_sha256,
            "prefix_checkpoint": {
                "start": self.prefix_start,
                "segment_bytes": PREFIX_SEGMENT_BYTES,
                "segments": [item.to_dict() for item in self.prefix_segments],
            },
            "recovery_diagnostics": list(self.recovery_diagnostics),
            "projection": self.projection,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "AuditCursor":
        if not isinstance(value, dict) or value.get("schema") != CURSOR_SCHEMA:
            raise AuditCursorError("cursor schema is invalid")
        identity = value.get("log_identity")
        projection = value.get("projection", {})
        if not isinstance(identity, dict) or not isinstance(projection, dict):
            raise AuditCursorError("cursor identity or projection is invalid")
        prefix = value.get("prefix_checkpoint")
        diagnostics = value.get("recovery_diagnostics", [])
        if (
            not isinstance(prefix, dict)
            or prefix.get("segment_bytes") != PREFIX_SEGMENT_BYTES
            or not isinstance(prefix.get("segments"), list)
            or not isinstance(diagnostics, list)
            or any(not isinstance(item, str) or not item for item in diagnostics)
        ):
            raise AuditCursorError("cursor prefix checkpoint is invalid")
        integers = {
            "revision": value.get("revision"),
            "device": identity.get("device"),
            "inode": identity.get("inode"),
            "offset": value.get("offset"),
            "last_line_start": value.get("last_line_start"),
            "prefix_start": prefix.get("start"),
        }
        if any(
            not isinstance(item, int) or isinstance(item, bool) or item < 0
            for item in integers.values()
        ):
            raise AuditCursorError("cursor integer field is invalid")
        sequence = value.get("last_sequence")
        if sequence is not None and (
            not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0
        ):
            raise AuditCursorError("cursor sequence is invalid")
        hashes = (
            str(value.get("last_event_hash") or ""),
            str(value.get("chain_sha256") or ""),
        )
        if any(_SHA256.fullmatch(item) is None for item in hashes):
            raise AuditCursorError("cursor event or chain hash is invalid")
        last_line_hash = str(value.get("last_line_sha256") or "")
        if last_line_hash and _SHA256.fullmatch(last_line_hash) is None:
            raise AuditCursorError("cursor line hash is invalid")
        generation = value.get("runtime_generation")
        if not isinstance(generation, str) or not generation:
            raise AuditCursorError("cursor runtime generation is invalid")
        if integers["last_line_start"] > integers["offset"]:
            raise AuditCursorError("cursor line boundary exceeds its offset")
        if integers["prefix_start"] > integers["offset"]:
            raise AuditCursorError("cursor prefix start exceeds its offset")
        segments = tuple(PrefixSegment.from_dict(item) for item in prefix["segments"])
        expected_start = integers["prefix_start"]
        for segment in segments:
            if segment.start != expected_start:
                raise AuditCursorError("cursor prefix segments are not contiguous")
            expected_start += segment.length
        if expected_start != integers["offset"]:
            raise AuditCursorError("cursor prefix segments do not cover the checkpoint")
        return cls(
            log_device=integers["device"],
            log_inode=integers["inode"],
            offset=integers["offset"],
            last_event_hash=hashes[0],
            last_sequence=sequence,
            runtime_generation=generation,
            chain_sha256=hashes[1],
            last_line_start=integers["last_line_start"],
            last_line_sha256=last_line_hash,
            prefix_start=integers["prefix_start"],
            prefix_segments=segments,
            recovery_diagnostics=tuple(diagnostics),
            revision=integers["revision"],
            projection=json.loads(json.dumps(projection)),
        )


@dataclass(frozen=True)
class CursorRead:
    cursor: AuditCursor
    rows: tuple[dict[str, Any], ...]
    raw_rows: tuple[bytes, ...]
    bytes_read: int
    integrity_bytes_read: int = 0
    recovered_from_authority: bool = False
    diagnostics: tuple[str, ...] = ()


_DirectoryIdentity = tuple[int, int, int, int]


@dataclass(frozen=True)
class _ParentBinding:
    """No-follow pathname authority for one cursor parent directory."""

    path: Path
    chain: tuple[tuple[str, _DirectoryIdentity], ...]


def cursor_digest(cursor: AuditCursor) -> str:
    return cursor._storage_sha256 or hashlib.sha256(_encoded(cursor)).hexdigest()


def load_cursor(path: Path) -> AuditCursor:
    """Load one canonical cursor through a controlled parent dirfd."""
    parent_descriptor = -1
    try:
        parent_descriptor, parent_binding = _secure_parent(path.parent, create=False)
        cursor, _payload = _load_cursor_at(parent_descriptor, path.name)
        _verify_parent_binding(parent_descriptor, parent_binding)
        return cursor
    except OSError as error:
        raise AuditCursorError(f"cursor cannot be read: {type(error).__name__}") from error
    finally:
        if parent_descriptor >= 0:
            os.close(parent_descriptor)


def scan_increment(
    log_path: Path,
    *,
    runtime_generation: str,
    cursor: AuditCursor | None = None,
    max_bytes: int = 8 * 1024 * 1024,
    enforce_event_generation: bool = True,
) -> CursorRead:
    """Read only complete rows after *cursor* and return the next checkpoint.

    A missing cursor bootstraps from byte zero.  A supplied cursor is an
    authoritative checkpoint: replacement, truncation, boundary rewrite,
    sequence discontinuity, generation drift, or an incomplete tail fails
    closed.  ``max_bytes`` bounds both bootstrap and recovery work.
    """
    if not runtime_generation:
        raise AuditCursorError("runtime generation must be non-empty")
    if max_bytes <= 0:
        raise AuditCursorError("max_bytes must be positive")
    return _scan_increment(
        log_path,
        runtime_generation=runtime_generation,
        cursor=cursor,
        max_bytes=max_bytes,
        enforce_event_generation=enforce_event_generation,
        detach_prefix=False,
        diagnostics=(),
    )


def _scan_increment(
    log_path: Path,
    *,
    runtime_generation: str,
    cursor: AuditCursor | None,
    max_bytes: int,
    enforce_event_generation: bool,
    detach_prefix: bool,
    diagnostics: tuple[str, ...],
) -> CursorRead:
    descriptor = -1
    try:
        descriptor = os.open(
            log_path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            raise AuditCursorError("audit log is not a single-link regular file")
        start = 0
        last_event_hash = EMPTY_CHAIN_SHA256
        last_sequence: int | None = None
        chain_hash = EMPTY_CHAIN_SHA256
        last_line_start = 0
        last_line_hash = ""
        revision = 0
        projection: dict[str, Any] = {}
        prefix_start = 0
        prefix_segments: tuple[PrefixSegment, ...] = ()
        integrity_bytes_read = 0
        if cursor is not None:
            if cursor.runtime_generation != runtime_generation:
                raise AuditCursorError("runtime generation changed")
            if (opened.st_dev, opened.st_ino) != (
                cursor.log_device,
                cursor.log_inode,
            ):
                raise AuditCursorError("audit log identity changed")
            if opened.st_size < cursor.offset:
                raise AuditCursorError("audit log was truncated")
            if detach_prefix:
                prefix_start = cursor.offset
                prefix_segments = ()
            else:
                integrity_bytes_read = _verify_prefix_checkpoint(descriptor, cursor)
                _verify_checkpoint_boundary(descriptor, cursor)
                prefix_start = cursor.prefix_start
                prefix_segments = cursor.prefix_segments
            start = cursor.offset
            last_event_hash = cursor.last_event_hash
            last_sequence = cursor.last_sequence
            chain_hash = cursor.chain_sha256
            last_line_start = cursor.last_line_start
            last_line_hash = cursor.last_line_sha256
            revision = cursor.revision
            projection = json.loads(json.dumps(cursor.projection))
        append_size = opened.st_size - start
        if append_size > max_bytes:
            raise AuditCursorError("audit append exceeds bounded recovery window")
        os.lseek(descriptor, start, os.SEEK_SET)
        payload = _read_exact(descriptor, append_size)
        closed = os.fstat(descriptor)
        if _identity(opened) != _identity(closed):
            raise AuditCursorError("audit log changed while it was read")
        if payload and not payload.endswith(b"\n"):
            raise AuditCursorError("audit log has an incomplete trailing row")
        raw_rows = tuple(payload.splitlines())
        rows: list[dict[str, Any]] = []
        position = start
        for raw in raw_rows:
            try:
                row = json.loads(raw.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError) as error:
                raise AuditCursorError("audit row is not valid JSON") from error
            if not isinstance(row, dict):
                raise AuditCursorError("audit row root is not an object")
            row_hash = hashlib.sha256(raw).hexdigest()
            event_hash = _event_hash(row, row_hash)
            previous_hash = _previous_hash(row)
            if previous_hash is not None and previous_hash != last_event_hash:
                raise AuditCursorError("audit event hash continuity failed")
            sequence = _sequence(row)
            if sequence is not None and last_sequence is not None:
                if sequence != last_sequence + 1:
                    raise AuditCursorError("audit event sequence continuity failed")
            generation = _generation(row)
            if (
                enforce_event_generation
                and generation is not None
                and generation != runtime_generation
            ):
                raise AuditCursorError("audit row runtime generation changed")
            line_start = position
            position += len(raw) + 1
            last_line_start = line_start
            last_line_hash = row_hash
            last_event_hash = event_hash
            if sequence is not None:
                last_sequence = sequence
            chain_hash = hashlib.sha256(
                bytes.fromhex(chain_hash) + bytes.fromhex(row_hash)
            ).hexdigest()
            rows.append(row)
        if cursor is None:
            prefix_segments = _segments_from_bytes(payload, start=0)
        else:
            rebuild_start = start
            retained = list(prefix_segments)
            if retained and retained[-1].length < PREFIX_SEGMENT_BYTES:
                rebuild_start = retained[-1].start
                retained.pop()
            os.lseek(descriptor, rebuild_start, os.SEEK_SET)
            rebuilt_payload = _read_exact(descriptor, opened.st_size - rebuild_start)
            prefix_segments = tuple(retained) + _segments_from_bytes(
                rebuilt_payload,
                start=rebuild_start,
            )
        next_cursor = AuditCursor(
            log_device=opened.st_dev,
            log_inode=opened.st_ino,
            offset=opened.st_size,
            last_event_hash=last_event_hash,
            last_sequence=last_sequence,
            runtime_generation=runtime_generation,
            chain_sha256=chain_hash,
            last_line_start=last_line_start,
            last_line_sha256=last_line_hash,
            prefix_start=prefix_start,
            prefix_segments=prefix_segments,
            recovery_diagnostics=(
                cursor.recovery_diagnostics if cursor is not None else ()
            )
            + diagnostics,
            revision=revision + 1,
            projection=projection,
        )
        return CursorRead(
            next_cursor,
            tuple(rows),
            raw_rows,
            append_size,
            integrity_bytes_read=integrity_bytes_read,
            recovered_from_authority=detach_prefix,
            diagnostics=diagnostics,
        )
    except OSError as error:
        raise AuditCursorError(f"audit log cannot be read: {type(error).__name__}") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def with_projection(cursor: AuditCursor, projection: dict[str, Any]) -> AuditCursor:
    """Return a checkpoint with caller-owned, JSON-safe projection state."""
    try:
        copied = json.loads(json.dumps(projection, ensure_ascii=False))
    except (TypeError, ValueError) as error:
        raise AuditCursorError("cursor projection is not JSON serializable") from error
    if not isinstance(copied, dict):
        raise AuditCursorError("cursor projection root must be an object")
    return replace(cursor, projection=copied)


def save_cursor(
    path: Path,
    cursor: AuditCursor,
    *,
    expected_digest: str | None,
) -> str:
    """Atomically persist *cursor* if the on-disk generation still matches.

    ``expected_digest=None`` means the cursor must not exist.  Callers updating
    an existing cursor pass ``cursor_digest(load_cursor(path))``.  The lock is
    advisory for cooperating writers; the digest comparison is the CAS truth.
    """
    parent_descriptor = -1
    lock_descriptor = -1
    try:
        parent_descriptor, parent_binding = _secure_parent(path.parent, create=True)
        lock_name = f".{path.name}.lock"
        lock_descriptor, lock_created = _open_private_lock(
            parent_descriptor,
            lock_name,
        )
        if lock_created:
            os.fsync(lock_descriptor)
            os.fsync(parent_descriptor)
            _verify_parent_binding(parent_descriptor, parent_binding)
        _lock(lock_descriptor)
        _verify_parent_binding(parent_descriptor, parent_binding)
        exists = _entry_exists(parent_descriptor, path.name)
        if expected_digest is None:
            if exists:
                raise AuditCursorConflict("cursor appeared during create CAS")
        else:
            if not exists:
                raise AuditCursorConflict("cursor disappeared during update CAS")
            current, _current_payload = _load_cursor_at(parent_descriptor, path.name)
            if cursor_digest(current) != expected_digest:
                raise AuditCursorConflict("cursor compare-and-swap lost")
        _verify_parent_binding(parent_descriptor, parent_binding)
        payload = _encoded(cursor)
        temporary = f".{path.name}.{os.getpid()}.{os.urandom(8).hex()}"
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=parent_descriptor,
        )
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.rename(
                temporary,
                path.name,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
            )
            os.fsync(parent_descriptor)
            _verify_parent_binding(parent_descriptor, parent_binding)
        except Exception:
            try:
                os.unlink(temporary, dir_fd=parent_descriptor)
            except OSError:
                pass
            raise
        digest = hashlib.sha256(payload).hexdigest()
        _verify_parent_binding(parent_descriptor, parent_binding)
        return digest
    except OSError as error:
        raise AuditCursorError(
            f"cursor cannot be persisted safely: {type(error).__name__}"
        ) from error
    finally:
        if lock_descriptor >= 0:
            _unlock(lock_descriptor)
            os.close(lock_descriptor)
        if parent_descriptor >= 0:
            os.close(parent_descriptor)


def recover_from_checkpoint(
    log_path: Path,
    checkpoint: AuditCursor,
    *,
    runtime_generation: str,
    max_recovery_bytes: int,
    enforce_event_generation: bool = True,
) -> CursorRead:
    """Bounded recovery from a separately authenticated checkpoint.

    A prefix mismatch is diagnosed once and detached from future projection.
    The persisted projection/hash/sequence remain authoritative, so only bytes
    appended after the checkpoint are parsed.  Replacement, truncation,
    generation drift, and append discontinuity remain hard failures.
    """
    try:
        return scan_increment(
            log_path,
            runtime_generation=runtime_generation,
            cursor=checkpoint,
            max_bytes=max_recovery_bytes,
            enforce_event_generation=enforce_event_generation,
        )
    except AuditPrefixMismatch as error:
        diagnostic = f"authoritative-prefix-detached:{error}"
        return _scan_increment(
            log_path,
            runtime_generation=runtime_generation,
            cursor=checkpoint,
            max_bytes=max_recovery_bytes,
            enforce_event_generation=enforce_event_generation,
            detach_prefix=True,
            diagnostics=(diagnostic,),
        )


def _encoded(cursor: AuditCursor) -> bytes:
    return (
        json.dumps(
            cursor.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _segments_from_bytes(payload: bytes, *, start: int) -> tuple[PrefixSegment, ...]:
    result: list[PrefixSegment] = []
    for index in range(0, len(payload), PREFIX_SEGMENT_BYTES):
        block = payload[index : index + PREFIX_SEGMENT_BYTES]
        result.append(
            PrefixSegment(
                start=start + index,
                length=len(block),
                sha256=hashlib.sha256(block).hexdigest(),
            )
        )
    return tuple(result)


def _verify_prefix_checkpoint(descriptor: int, cursor: AuditCursor) -> int:
    """Re-hash every authoritative segment without replaying its JSON rows."""
    total = 0
    for index, segment in enumerate(cursor.prefix_segments):
        os.lseek(descriptor, segment.start, os.SEEK_SET)
        payload = _read_exact(descriptor, segment.length)
        total += segment.length
        if hashlib.sha256(payload).hexdigest() != segment.sha256:
            raise AuditPrefixMismatch(
                f"segment={index} start={segment.start} length={segment.length}"
            )
    return total


def _validate_private_file(metadata: os.stat_result, *, label: str) -> None:
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise AuditCursorError(f"{label} is not a single-link regular file")
    if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
        raise AuditCursorError(f"{label} owner does not match the runtime user")
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise AuditCursorError(f"{label} mode must be 0600")


def _directory_identity(metadata: os.stat_result) -> _DirectoryIdentity:
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise AuditCursorError("cursor ancestor is not a real directory")
    return (
        metadata.st_dev,
        metadata.st_ino,
        getattr(metadata, "st_uid", -1),
        stat.S_IMODE(metadata.st_mode),
    )


def _open_directory_chain(path: Path) -> tuple[int, _ParentBinding]:
    """Resolve an absolute directory pathname one no-follow component at a time."""
    lexical = Path(os.path.abspath(path.expanduser()))
    if not lexical.is_absolute() or not lexical.anchor:
        raise AuditCursorError("cursor parent pathname is not absolute")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(lexical.anchor, flags)
    current = Path(lexical.anchor)
    chain: list[tuple[str, _DirectoryIdentity]] = []
    try:
        chain.append((str(current), _directory_identity(os.fstat(descriptor))))
        for component in lexical.parts[1:]:
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
            current = current / component
            chain.append((str(current), _directory_identity(os.fstat(descriptor))))
        return descriptor, _ParentBinding(path=lexical, chain=tuple(chain))
    except Exception:
        os.close(descriptor)
        raise


def _secure_parent(path: Path, *, create: bool) -> tuple[int, _ParentBinding]:
    """Open one owned cursor directory and bind its canonical pathname chain."""
    lexical = Path(os.path.abspath(path.expanduser()))
    if os.path.lexists(lexical) and lexical.is_symlink():
        raise AuditCursorError("cursor parent must not be a symlink")
    created_identity: _DirectoryIdentity | None = None
    if not os.path.lexists(lexical):
        if not create:
            raise AuditCursorError("cursor parent does not exist")
        grand_descriptor, grand_binding = _open_directory_chain(lexical.parent)
        try:
            os.mkdir(lexical.name, 0o700, dir_fd=grand_descriptor)
            created = os.stat(
                lexical.name,
                dir_fd=grand_descriptor,
                follow_symlinks=False,
            )
            created_identity = _directory_identity(created)
            os.fsync(grand_descriptor)
            _verify_parent_binding(grand_descriptor, grand_binding)
        finally:
            os.close(grand_descriptor)
    descriptor, binding = _open_directory_chain(lexical)
    opened = os.fstat(descriptor)
    identity = _directory_identity(opened)
    if created_identity is not None and identity != created_identity:
        os.close(descriptor)
        raise AuditCursorError("cursor parent changed after first creation")
    if hasattr(os, "getuid") and opened.st_uid != os.getuid():
        os.close(descriptor)
        raise AuditCursorError("cursor parent owner does not match the runtime user")
    if stat.S_IMODE(opened.st_mode) & 0o022:
        os.close(descriptor)
        raise AuditCursorError("cursor parent is group/other writable")
    if identity != binding.chain[-1][1]:
        os.close(descriptor)
        raise AuditCursorError("cursor parent changed before it was opened")
    _verify_parent_binding(descriptor, binding)
    return descriptor, binding


def _verify_parent_binding(descriptor: int, binding: _ParentBinding) -> None:
    """Prove the opened inode is still reachable through the same pathname."""
    current = _directory_identity(os.fstat(descriptor))
    if current != binding.chain[-1][1]:
        raise AuditCursorError("cursor parent inode changed during the operation")
    rebound_descriptor = -1
    try:
        rebound_descriptor, rebound = _open_directory_chain(binding.path)
        if rebound.path != binding.path or rebound.chain != binding.chain:
            raise AuditCursorError(
                "cursor parent pathname or ancestor chain changed during the operation"
            )
        if _directory_identity(os.fstat(rebound_descriptor)) != current:
            raise AuditCursorError(
                "cursor parent pathname no longer identifies the opened inode"
            )
    except OSError as error:
        raise AuditCursorError(
            "cursor parent pathname cannot be re-resolved without following links"
        ) from error
    finally:
        if rebound_descriptor >= 0:
            os.close(rebound_descriptor)


def _load_cursor_at(parent_descriptor: int, name: str) -> tuple[AuditCursor, bytes]:
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        raise AuditCursorError("cursor name is invalid")
    descriptor = os.open(
        name,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=parent_descriptor,
    )
    try:
        opened = os.fstat(descriptor)
        _validate_private_file(opened, label="cursor")
        payload = _read_exact(descriptor, opened.st_size)
        closed = os.fstat(descriptor)
        if _identity(opened) != _identity(closed):
            raise AuditCursorError("cursor changed while it was read")
        try:
            value = json.loads(payload.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise AuditCursorError("cursor JSON is corrupt") from error
        cursor = AuditCursor.from_dict(value)
        if payload != _encoded(cursor):
            raise AuditCursorError("cursor storage encoding is not canonical")
        digest = hashlib.sha256(payload).hexdigest()
        return replace(cursor, _storage_sha256=digest), payload
    finally:
        os.close(descriptor)


def _entry_exists(parent_descriptor: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False


def _open_private_lock(parent_descriptor: int, name: str) -> tuple[int, bool]:
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(name, flags, 0o600, dir_fd=parent_descriptor)
        created = True
    except FileExistsError:
        descriptor = os.open(
            name,
            os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_descriptor,
        )
        created = False
    try:
        _validate_private_file(os.fstat(descriptor), label="cursor lock")
    except Exception:
        os.close(descriptor)
        raise
    return descriptor, created


def _identity(metadata: os.stat_result) -> tuple[int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
    )


def _read_exact(descriptor: int, size: int) -> bytes:
    payload = bytearray()
    remaining = size
    while remaining:
        chunk = os.read(descriptor, min(1024 * 1024, remaining))
        if not chunk:
            raise AuditCursorError("file became short while reading")
        payload.extend(chunk)
        remaining -= len(chunk)
    return bytes(payload)


def _verify_checkpoint_boundary(descriptor: int, cursor: AuditCursor) -> None:
    if cursor.offset == 0:
        return
    length = cursor.offset - cursor.last_line_start
    if length <= 1 or not cursor.last_line_sha256:
        raise AuditCursorError("cursor has no trustworthy line boundary")
    os.lseek(descriptor, cursor.last_line_start, os.SEEK_SET)
    payload = _read_exact(descriptor, length)
    if not payload.endswith(b"\n"):
        raise AuditCursorError("checkpoint boundary is no longer a complete row")
    if hashlib.sha256(payload[:-1]).hexdigest() != cursor.last_line_sha256:
        raise AuditCursorError("checkpoint row was rewritten")


def _event(row: dict[str, Any]) -> dict[str, Any]:
    nested = row.get("event")
    return nested if isinstance(nested, dict) else row


def _sequence(row: dict[str, Any]) -> int | None:
    value = _event(row).get("sequence")
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise AuditCursorError("audit event sequence is invalid")
    return value


def _generation(row: dict[str, Any]) -> str | None:
    value = _event(row).get("runtime_generation")
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise AuditCursorError("audit runtime generation is invalid")
    return value


def _previous_hash(row: dict[str, Any]) -> str | None:
    event = _event(row)
    for key in ("previous_sha256", "previous_event_sha256"):
        if key in event:
            value = str(event.get(key) or "")
            if _SHA256.fullmatch(value) is None:
                raise AuditCursorError("audit previous hash is invalid")
            return value
    return None


def _event_hash(row: dict[str, Any], row_hash: str) -> str:
    event = _event(row)
    for key in ("event_sha256", "sha256"):
        value = event.get(key)
        if value is not None:
            rendered = str(value)
            if _SHA256.fullmatch(rendered) is None:
                raise AuditCursorError("audit event hash is invalid")
            return rendered
    return row_hash


def _lock(descriptor: int) -> None:
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
    else:
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_EX)


def _unlock(descriptor: int) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_UN)
    except OSError:
        pass
