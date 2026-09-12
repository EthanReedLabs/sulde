"""Rebuildable per-session observation projections, never permission authority.

The append-only global log is retained. Readers check a signed cache and scan
only a bounded suffix after its checkpoint. Writers publish under a nonblocking
per-session lock; contention or corruption cannot pause an Agent task. Explicit
rebuild is the only path allowed to scan the entire historical log.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import hmac
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Any, Callable

from file_lock import lock_exclusive_nonblocking, unlock

SCHEMA = "sulde-host-observation-index-v1"
GENERATOR = 1
MAX_INDEX_BYTES = 512 * 1024
MAX_INCREMENT_BYTES = 256 * 1024
BOOTSTRAP_BYTES = 4 * 1024 * 1024
MAX_LINE_BYTES = 64 * 1024
LOG_NAME = "host-capabilities.jsonl"
Validator = Callable[[dict[str, Any]], bool]


def _encoded(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def index_path(home: Path, provider: str, session_id: str) -> Path:
    identity = hashlib.sha256(_encoded([provider, session_id])).hexdigest()
    return home / "host-capability-index" / (identity + ".json")


def _compact(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Keep original event timestamps/identities, not synthetic refreshed facts.
    unique = {hashlib.sha256(_encoded(row)).hexdigest(): row for row in rows}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in unique.values():
        grouped[str(row.get("hook_event") or "")].append(row)
    result: list[dict[str, Any]] = []
    for hook, values in grouped.items():
        ordered = sorted(values, key=lambda row: str(row.get("at") or ""))
        if hook == "SessionStart" and len(ordered) > 16:
            trusted = [row for row in ordered if row.get("source") in {"live_host_hook", "managed_l3"}]
            if trusted:
                result.append(trusted[0])  # untrusted noise cannot age out a live anchor
        result.extend(ordered[-16:])
    return sorted(result, key=lambda row: str(row.get("at") or ""))


def _private_file(path: Path, flags: int) -> int:
    descriptor = os.open(path, flags | getattr(os, "O_NOFOLLOW", 0), 0o600)
    metadata = os.fstat(descriptor)
    if (not stat.S_ISREG(metadata.st_mode) or
            (os.name != "nt" and metadata.st_uid != os.getuid())):
        os.close(descriptor)
        raise ValueError("observation index file identity is invalid")
    return descriptor


def _load(path: Path, key: bytes, provider: str, session_id: str) -> dict[str, Any]:
    with os.fdopen(_private_file(path, os.O_RDONLY), "rb") as handle:
        payload = handle.read(MAX_INDEX_BYTES + 1)
    if len(payload) > MAX_INDEX_BYTES:
        raise ValueError("observation index exceeds its bound")
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError("observation index is not an object")
    signature = value.pop("signature", "")
    if not isinstance(signature, str) or not hmac.compare_digest(
        signature, hmac.new(key, _encoded(value), hashlib.sha256).hexdigest()
    ):
        raise ValueError("observation index signature differs")
    if (value.get("schema") != SCHEMA or value.get("generator_version") != GENERATOR
            or value.get("provider") != provider or value.get("session_id") != session_id
            or not isinstance(value.get("rows"), list)
            or len(value["rows"]) > 129
            or any(not isinstance(row, dict) for row in value["rows"])
            or not isinstance(value.get("checkpoint"), dict)):
        raise ValueError("observation index schema or lane differs")
    return value


def read_index(
    home: Path, provider: str, session_id: str, *, key: bytes, validate: Validator,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read-only catch-up; stale/corrupt indexes fall back without creating files."""
    path = index_path(home, provider, session_id)
    cached: dict[str, Any] | None = None
    index_status = "missing"
    try:
        cached = _load(path, key, provider, session_id)
        index_status = "verified"
    except FileNotFoundError:
        pass
    except (OSError, ValueError, TypeError, UnicodeError):
        index_status = "invalid"
    invalid = 0
    scanned = 0
    rows: list[dict[str, Any]] = []
    checkpoint: dict[str, Any] = {}
    try:
        with os.fdopen(_private_file(home / LOG_NAME, os.O_RDONLY), "rb") as handle:
            metadata = os.fstat(handle.fileno())
            end = metadata.st_size
            start = max(0, end - BOOTSTRAP_BYTES)
            if cached is not None:
                previous = cached.get("checkpoint", {})
                offset = previous.get("offset")
                valid_checkpoint = (
                    isinstance(offset, int) and not isinstance(offset, bool)
                    and 0 <= offset <= end
                    and previous.get("device") == metadata.st_dev
                    and previous.get("inode") == metadata.st_ino
                )
                if valid_checkpoint:
                    handle.seek(max(0, offset - 256))
                    anchor = handle.read(min(offset, 256))
                    valid_checkpoint = hashlib.sha256(anchor).hexdigest() == previous.get("anchor")
                if valid_checkpoint and end - offset <= MAX_INCREMENT_BYTES:
                    start = offset
                    rows = list(cached["rows"])
                else:
                    # Never carry a cached prompt across an unexamined Stop.
                    # Signed lifetime starts remain facts if the log identity
                    # and checkpoint survived; other boundaries need catch-up.
                    if valid_checkpoint:
                        rows = [row for row in cached["rows"] if row.get("hook_event") == "SessionStart"]
                        index_status = "catchup_required"
                    else:
                        index_status = "source_changed"
            handle.seek(start)
            payload = handle.read(end - start)
            scanned = len(payload)
            if start and (cached is None or index_status != "verified"):
                boundary = payload.find(b"\n")
                if boundary < 0 and payload:
                    invalid += 1
                payload = payload[boundary + 1:] if boundary >= 0 else b""
            last_newline = payload.rfind(b"\n")
            complete_end = end - (len(payload) - last_newline - 1)
            if last_newline + 1 != len(payload):
                invalid += 1
            for raw in payload[:last_newline + 1].splitlines():
                if len(raw) > MAX_LINE_BYTES:
                    invalid += 1
                    continue
                try:
                    row = json.loads(raw)
                    if not isinstance(row, dict):
                        raise ValueError("non-object row")
                    if row.get("provider") != provider or (
                        row.get("hook_event") != "MCPInitialize"
                        if session_id == "@provider"
                        else row.get("session_id") != session_id
                    ):
                        continue
                    if not validate(row):
                        raise ValueError("invalid observation")
                    rows.append(row)
                except (ValueError, TypeError, UnicodeError):
                    invalid += 1
            handle.seek(max(0, complete_end - 256))
            checkpoint = {
                "device": metadata.st_dev, "inode": metadata.st_ino,
                "offset": complete_end,
                "anchor": hashlib.sha256(handle.read(min(complete_end, 256))).hexdigest(),
            }
    except FileNotFoundError:
        index_status = "source_missing"
        rows = []
    except (OSError, ValueError, TypeError):
        index_status = "source_unreadable"
        invalid += 1
        rows = []
    return _compact(rows), {
        "status": index_status, "scanned_bytes": scanned, "invalid_rows": invalid,
        "checkpoint": checkpoint, "authority": "telemetry_only_not_permission",
    }


def publish_index(
    home: Path, provider: str, session_id: str, *, key: bytes, validate: Validator,
) -> bool:
    """Best effort, nonblocking; append-before-publish crashes replay next time."""
    path = index_path(home, provider, session_id)
    temporary: str | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path.parent.is_symlink():
            return False
        with os.fdopen(_private_file(path.with_suffix(".lock"), os.O_RDWR | os.O_CREAT), "r+") as lock:
            lock_exclusive_nonblocking(lock)
            try:
                # Read after taking the lock: concurrent publishers cannot
                # overwrite a newer checkpoint with their stale snapshot.
                rows, projection = read_index(home, provider, session_id, key=key, validate=validate)
                if not projection["checkpoint"] or projection["invalid_rows"]:
                    return False
                value = {
                    "schema": SCHEMA, "source_version": "sulde-host-capability-observation-v1",
                    "generator_version": GENERATOR, "provider": provider,
                    "session_id": session_id, "rows": rows,
                    "checkpoint": projection["checkpoint"],
                }
                value["signature"] = hmac.new(key, _encoded(value), hashlib.sha256).hexdigest()
                encoded = _encoded(value)
                if len(encoded) > MAX_INDEX_BYTES:
                    return False
                descriptor, temporary = tempfile.mkstemp(prefix=".publish-", dir=path.parent)
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(encoded)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, path)
                temporary = None
                return True
            finally:
                unlock(lock)
    except (OSError, ValueError, TypeError):
        return False
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def attributable_index_paths(home: Path, rows: list[dict], *, key: bytes, validate: Validator) -> set[str]:
    """Audit-only: exact signed projections accompanying validated host appends.

    No directory-wide exclusion, unfinished rebuild, deleted cache, or arbitrary
    lock contents are accepted. The caller independently validates source rows.
    """
    accepted: set[str] = set()
    parent = home / "host-capability-index"
    if parent.is_symlink() or not parent.is_dir():
        return accepted
    lanes = {(row.get("provider"), "@provider" if row.get("hook_event") == "MCPInitialize"
              else row.get("session_id")) for row in rows}
    for provider, session in lanes:
        if not isinstance(provider, str) or not isinstance(session, str):
            continue
        path = index_path(home, provider, session)
        try:
            cached = _load(path, key, provider, session)
            if not all(validate(row) for row in cached["rows"]):
                continue
            _retained, status = read_index(home, provider, session, key=key, validate=validate)
            if status["status"] != "verified" or status["invalid_rows"]:
                continue
            lock = path.with_suffix(".lock")
            with os.fdopen(_private_file(lock, os.O_RDONLY), "rb") as handle:
                if handle.read(1):
                    continue
            accepted.update((parent.name, str(path.relative_to(home)), str(lock.relative_to(home))))
        except (OSError, ValueError, TypeError, UnicodeError):
            continue
    return accepted


def _atomic_signed(path: Path, value: dict[str, Any], key: bytes) -> None:
    sealed = dict(value)
    sealed["signature"] = hmac.new(key, _encoded(value), hashlib.sha256).hexdigest()
    descriptor, temporary = tempfile.mkstemp(prefix=".rebuild-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_encoded(sealed))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def rebuild_step(
    home: Path, provider: str, session_id: str, *, key: bytes,
    validate: Validator, max_bytes: int = 8 * 1024 * 1024,
) -> dict[str, Any]:
    """Explicit resumable maintenance. Never called by a Hook or doctor.

    Each checkpoint signs both retained original rows and segment hashes.
    Resuming verifies every consumed source segment; ordinary readers do not
    pay that historical verification cost. Corruption cannot publish a cache.
    """
    if not 1 <= max_bytes <= 64 * 1024 * 1024:
        raise ValueError("rebuild step budget is invalid")
    path = index_path(home, provider, session_id)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.parent.is_symlink():
        raise ValueError("index directory is a symlink")
    progress_path = path.with_suffix(".rebuild.json")
    with os.fdopen(_private_file(path.with_suffix(".lock"), os.O_RDWR | os.O_CREAT), "r+") as lock:
        lock_exclusive_nonblocking(lock)
        try:
            try:
                progress = _load(progress_path, key, provider, session_id)
            except FileNotFoundError:
                progress = {"rows": [], "segments": [], "invalid_rows": 0}
            rows = list(progress["rows"])
            segments = list(progress.get("segments", []))
            invalid = int(progress.get("invalid_rows", 0))
            with os.fdopen(_private_file(home / LOG_NAME, os.O_RDONLY), "rb") as source:
                metadata = os.fstat(source.fileno())
                old = progress.get("checkpoint")
                if old and (old["device"], old["inode"]) != (metadata.st_dev, metadata.st_ino):
                    raise ValueError("rebuild source identity changed")
                offset = 0
                for segment in segments:
                    if segment["start"] != offset:
                        raise ValueError("rebuild segments are not contiguous")
                    payload = source.read(segment["length"])
                    if hashlib.sha256(payload).hexdigest() != segment["sha256"]:
                        raise ValueError("rebuild source prefix changed")
                    offset += len(payload)
                if old and offset != old["offset"]:
                    raise ValueError("rebuild checkpoint differs")
                consumed = 0
                digest = hashlib.sha256()
                while consumed < max_bytes:
                    raw = source.readline(MAX_LINE_BYTES + 1)
                    if not raw:
                        break
                    if not raw.endswith(b"\n") or len(raw) > MAX_LINE_BYTES:
                        raise ValueError("rebuild source has a torn or oversized row")
                    consumed += len(raw)
                    digest.update(raw)
                    try:
                        row = json.loads(raw)
                        if not isinstance(row, dict):
                            raise ValueError("non-object observation")
                        if row.get("provider") != provider or (
                            row.get("hook_event") != "MCPInitialize" if session_id == "@provider"
                            else row.get("session_id") != session_id
                        ):
                            continue
                        if not validate(row):
                            raise ValueError("unverified observation")
                        rows.append(row)
                        if len(rows) > 256:
                            rows = _compact(rows)
                    except (ValueError, TypeError, UnicodeError):
                        invalid += 1
                end = source.tell()
                finished = end == os.fstat(source.fileno()).st_size
                if consumed:
                    segments.append({"start": offset, "length": consumed, "sha256": digest.hexdigest()})
                source.seek(max(0, end - 256))
                checkpoint = {
                    "device": metadata.st_dev, "inode": metadata.st_ino, "offset": end,
                    "anchor": hashlib.sha256(source.read(min(end, 256))).hexdigest(),
                }
            value = {
                "schema": SCHEMA, "generator_version": GENERATOR,
                "source_version": "sulde-host-capability-observation-v1",
                "provider": provider, "session_id": session_id,
                "rows": _compact(rows), "checkpoint": checkpoint,
            }
            _atomic_signed(progress_path, {**value, "segments": segments, "invalid_rows": invalid}, key)
            status = "inconclusive" if invalid else "complete" if finished else "in_progress"
            if finished and not invalid:
                _atomic_signed(path, value, key)
            return {
                "status": status, "offset": end, "scanned_bytes": consumed,
                "retained_rows": len(value["rows"]), "invalid_rows": invalid,
                "source_modified": False, "authority_transferred": False,
            }
        finally:
            unlock(lock)
