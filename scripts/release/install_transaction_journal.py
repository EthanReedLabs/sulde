#!/usr/bin/env python3
"""Pure durable authority for Codex installer crash recovery.

This leaf owns no registry, launcher, or deployment behavior.  It only seals
caller-supplied identities, snapshots local paths, appends monotonic stages,
and restores the sealed snapshot after a verified restart.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
from typing import Any, Callable, Iterable


SCHEMA = "sulde-install-transaction-v1"
SNAPSHOT_SCHEMA = "sulde-install-rollback-snapshot-v1"
ACTIVE_SCHEMA = "sulde-install-active-transaction-v1"
JOURNAL_SCHEMA = "sulde-install-transaction-stage-v1"
SCHEMA_VERSION = 1

STAGES = (
    "prepared",
    "registry_remove_started",
    "registry_removed",
    "registry_add_started",
    "registry_added",
    "launcher_publish_started",
    "launcher_published",
    "deployment_publish_started",
    "deployment_published",
    "scheduler_reconcile_started",
    "scheduler_reconciled",
    "postconditions_verified",
    "committed",
    "rollback_started",
    "rolled_back",
    "cleanup_complete",
)
_STAGE_RANK = {name: index for index, name in enumerate(STAGES)}
_TERMINAL_STAGES = frozenset({"committed", "rolled_back", "cleanup_complete"})
_SHA256 = re.compile(r"[0-9a-f]{64}")
_TRANSACTION_ID = re.compile(r"[0-9a-f]{32,64}")
_FORBIDDEN_KEYS = re.compile(r"(?:secret|password|credential|environment|token)", re.I)
_DESCRIPTOR_INPUT_FIELDS = {
    "transaction_id",
    "old_generation",
    "new_generation",
    "artifact",
    "runtime",
    "registry",
    "launcher",
    "deployment",
    "installed_tree",
    "expected_postconditions",
}
_DESCRIPTOR_FIELDS = _DESCRIPTOR_INPUT_FIELDS | {
    "schema",
    "schema_version",
    "snapshot_sha256",
}


class JournalError(RuntimeError):
    """Recovery authority is missing, unsafe, ambiguous, or inconsistent."""


class TransactionCollision(JournalError):
    """A different transaction already owns the stable recovery location."""


Failpoint = Callable[[str], None]


def _current_uid() -> int | None:
    getter = getattr(os, "getuid", None)
    return getter() if callable(getter) else None


def _canonical(payload: object) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _ensure_directory(path: Path) -> None:
    existed = path.exists() or path.is_symlink()
    if not existed:
        path.mkdir(parents=True, mode=0o700)
        if os.name != "nt":
            path.chmod(0o700)
    _validate_metadata(path, directory=True)


def _validate_metadata(path: Path, *, directory: bool) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise JournalError(f"recovery path is missing or unreadable: {path}") from error
    expected_kind = stat.S_ISDIR if directory else stat.S_ISREG
    if stat.S_ISLNK(metadata.st_mode) or not expected_kind(metadata.st_mode):
        raise JournalError(f"recovery path is linked or has the wrong kind: {path}")
    uid = _current_uid()
    if uid is not None and metadata.st_uid != uid:
        raise JournalError(f"recovery path owner drifted: {path}")
    if not directory and metadata.st_nlink != 1:
        raise JournalError(f"recovery file link count drifted: {path}")
    if os.name != "nt":
        expected_mode = 0o700 if directory else 0o600
        actual_mode = stat.S_IMODE(metadata.st_mode)
        if actual_mode != expected_mode:
            raise JournalError(
                f"recovery path mode drifted: {path}: {actual_mode:o} != {expected_mode:o}"
            )
    return metadata


def _read_secure(path: Path) -> bytes:
    before = _validate_metadata(path, directory=False)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        current = os.fstat(descriptor)
        if (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino):
            raise JournalError(f"recovery file changed during open: {path}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _atomic_write(path: Path, content: bytes) -> None:
    _ensure_directory(path.parent)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        if os.name != "nt":
            os.fchmod(descriptor, 0o600)
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise JournalError(f"short write while persisting recovery file: {path}")
            view = view[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, path)
        _fsync_directory(path.parent)
        if _read_secure(path) != content:
            raise JournalError(f"recovery file readback differs: {path}")
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except OSError:
            pass


def _json_object(raw: bytes, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise JournalError(f"{label} is invalid JSON") from error
    if not isinstance(payload, dict):
        raise JournalError(f"{label} is not an object")
    return payload


def _validate_no_secrets(value: object, *, path: str = "descriptor") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str) or _FORBIDDEN_KEYS.search(key):
                raise JournalError(f"{path} contains a forbidden or non-string field")
            _validate_no_secrets(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _validate_no_secrets(child, path=f"{path}[{index}]")
    elif value is not None and not isinstance(value, (str, int, bool)):
        raise JournalError(f"{path} contains a non-JSON value")


def _validate_descriptor(payload: dict[str, Any]) -> None:
    if set(payload) != _DESCRIPTOR_FIELDS:
        raise JournalError("transaction descriptor fields do not match the sealed schema")
    if payload.get("schema") != SCHEMA or type(payload.get("schema_version")) is not int:
        raise JournalError("transaction descriptor schema is unsupported")
    if payload["schema_version"] != SCHEMA_VERSION:
        raise JournalError("transaction descriptor schema is unsupported")
    transaction_id = payload.get("transaction_id")
    if not isinstance(transaction_id, str) or not _TRANSACTION_ID.fullmatch(transaction_id):
        raise JournalError("transaction descriptor ID is invalid")
    if not isinstance(payload.get("snapshot_sha256"), str) or not _SHA256.fullmatch(
        payload["snapshot_sha256"]
    ):
        raise JournalError("transaction descriptor snapshot digest is invalid")
    for field in (
        "artifact",
        "runtime",
        "registry",
        "launcher",
        "deployment",
        "installed_tree",
        "expected_postconditions",
    ):
        if not isinstance(payload.get(field), dict) or not payload[field]:
            raise JournalError(f"transaction descriptor {field} identity is invalid")
    _validate_no_secrets(payload)
    if _canonical(payload) != _canonical(json.loads(_canonical(payload))):
        raise JournalError("transaction descriptor is not canonical")


def _source_file(path: Path) -> tuple[bytes, int]:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise JournalError(f"snapshot source is not a regular file: {path}")
    if metadata.st_nlink != 1:
        raise JournalError(f"snapshot source has ambiguous hard links: {path}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        current = os.fstat(descriptor)
        if (metadata.st_dev, metadata.st_ino) != (current.st_dev, current.st_ino):
            raise JournalError(f"snapshot source changed during open: {path}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks), stat.S_IMODE(metadata.st_mode)
    finally:
        os.close(descriptor)


def _capture_snapshot(staging: Path, paths: Iterable[Path]) -> tuple[bytes, dict[str, bytes]]:
    targets: list[dict[str, Any]] = []
    blobs: dict[str, bytes] = {}
    seen: set[str] = set()
    for raw_path in paths:
        path = Path(os.path.abspath(str(Path(raw_path).expanduser())))
        key = str(path)
        if key in seen:
            raise JournalError(f"duplicate snapshot target: {path}")
        seen.add(key)
        if path.is_symlink():
            raise JournalError(f"snapshot target is a symbolic link: {path}")
        if not path.exists():
            targets.append({"path": key, "state": "missing"})
            continue
        if path.is_file():
            content, mode = _source_file(path)
            digest = _sha256(content)
            blobs.setdefault(digest, content)
            targets.append(
                {"path": key, "state": "file", "mode": mode, "sha256": digest}
            )
            continue
        if not path.is_dir():
            raise JournalError(f"snapshot target has unsupported kind: {path}")
        entries: list[dict[str, Any]] = [
            {"relative": ".", "kind": "directory", "mode": stat.S_IMODE(path.stat().st_mode)}
        ]
        for child in sorted(path.rglob("*")):
            if child.is_symlink():
                raise JournalError(f"snapshot tree contains a symbolic link: {child}")
            relative = child.relative_to(path).as_posix()
            if child.is_dir():
                entries.append(
                    {
                        "relative": relative,
                        "kind": "directory",
                        "mode": stat.S_IMODE(child.stat().st_mode),
                    }
                )
            elif child.is_file():
                content, mode = _source_file(child)
                digest = _sha256(content)
                blobs.setdefault(digest, content)
                entries.append(
                    {
                        "relative": relative,
                        "kind": "file",
                        "mode": mode,
                        "sha256": digest,
                    }
                )
            else:
                raise JournalError(f"snapshot tree contains an unsupported entry: {child}")
        targets.append({"path": key, "state": "directory", "entries": entries})
    manifest = {
        "schema": SNAPSHOT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "targets": targets,
    }
    return _canonical(manifest), blobs


def _persist_snapshot(recovery_root: Path, transaction_id: str, paths: Iterable[Path]) -> str:
    staging_parent = recovery_root / "snapshot-staging"
    _ensure_directory(staging_parent)
    staging = staging_parent / transaction_id
    if staging.exists() or staging.is_symlink():
        raise TransactionCollision(f"snapshot staging collides with transaction {transaction_id}")
    staging.mkdir(mode=0o700)
    _fsync_directory(staging_parent)
    try:
        manifest_raw, blobs = _capture_snapshot(staging, paths)
        digest = _sha256(manifest_raw)
        blobs_root = staging / "blobs"
        _ensure_directory(blobs_root)
        for blob_digest, content in sorted(blobs.items()):
            _atomic_write(blobs_root / blob_digest, content)
        _atomic_write(staging / "manifest.json", manifest_raw)
        _fsync_directory(staging)
        snapshots = recovery_root / "snapshots"
        _ensure_directory(snapshots)
        destination = snapshots / digest
        if destination.exists() or destination.is_symlink():
            existing = _validate_snapshot(destination, expected_digest=digest)
            if existing != _json_object(manifest_raw, label="snapshot manifest"):
                raise JournalError("content-addressed snapshot collision")
            shutil.rmtree(staging)
            _fsync_directory(staging_parent)
        else:
            os.replace(staging, destination)
            _fsync_directory(snapshots)
        return digest
    except Exception:
        if staging.is_dir() and not staging.is_symlink():
            shutil.rmtree(staging, ignore_errors=True)
        raise


def _validate_snapshot(root: Path, *, expected_digest: str) -> dict[str, Any]:
    _validate_metadata(root, directory=True)
    if root.name != expected_digest or not _SHA256.fullmatch(expected_digest):
        raise JournalError("snapshot content-address does not match its descriptor")
    manifest_path = root / "manifest.json"
    raw = _read_secure(manifest_path)
    if _sha256(raw) != expected_digest:
        raise JournalError("snapshot manifest digest mismatch")
    payload = _json_object(raw, label="snapshot manifest")
    if raw != _canonical(payload):
        raise JournalError("snapshot manifest raw bytes are not canonical")
    if set(payload) != {"schema", "schema_version", "targets"}:
        raise JournalError("snapshot manifest fields are invalid")
    if (
        payload.get("schema") != SNAPSHOT_SCHEMA
        or type(payload.get("schema_version")) is not int
        or payload["schema_version"] != SCHEMA_VERSION
        or not isinstance(payload.get("targets"), list)
    ):
        raise JournalError("snapshot manifest schema is unsupported")
    blobs_root = root / "blobs"
    _validate_metadata(blobs_root, directory=True)
    expected_blobs: set[str] = set()
    for target in payload["targets"]:
        if not isinstance(target, dict) or not isinstance(target.get("path"), str):
            raise JournalError("snapshot target record is invalid")
        if not Path(target["path"]).is_absolute():
            raise JournalError("snapshot target path is not absolute")
        state = target.get("state")
        if state == "missing":
            if set(target) != {"path", "state"}:
                raise JournalError("missing snapshot target has unknown fields")
        elif state == "file":
            if set(target) != {"path", "state", "mode", "sha256"}:
                raise JournalError("file snapshot target has unknown fields")
            expected_blobs.add(str(target.get("sha256")))
        elif state == "directory":
            if set(target) != {"path", "state", "entries"} or not isinstance(
                target.get("entries"), list
            ):
                raise JournalError("directory snapshot target is invalid")
            relatives: set[str] = set()
            for entry in target["entries"]:
                if not isinstance(entry, dict) or entry.get("kind") not in {
                    "file",
                    "directory",
                }:
                    raise JournalError("snapshot tree entry is invalid")
                relative = entry.get("relative")
                if not isinstance(relative, str) or relative in relatives:
                    raise JournalError("snapshot tree relative path is invalid")
                relatives.add(relative)
                candidate = Path(relative)
                if relative != "." and (candidate.is_absolute() or ".." in candidate.parts):
                    raise JournalError("snapshot tree relative path escapes its target")
                expected_fields = {"relative", "kind", "mode"}
                if entry["kind"] == "file":
                    expected_fields.add("sha256")
                    expected_blobs.add(str(entry.get("sha256")))
                if set(entry) != expected_fields:
                    raise JournalError("snapshot tree entry has unknown fields")
        else:
            raise JournalError("snapshot target state is unsupported")
    actual_blobs = {path.name for path in blobs_root.iterdir()}
    if actual_blobs != expected_blobs:
        raise JournalError("snapshot blob inventory mismatch")
    for digest in expected_blobs:
        if not _SHA256.fullmatch(digest):
            raise JournalError("snapshot blob name is not a digest")
        content = _read_secure(blobs_root / digest)
        if _sha256(content) != digest:
            raise JournalError("snapshot blob digest mismatch")
    return payload


def _remove_current(path: Path) -> None:
    if path.is_symlink():
        raise JournalError(f"refusing to replace ambiguous symbolic link during recovery: {path}")
    if not path.exists():
        return
    if path.is_file():
        path.unlink()
        return
    if not path.is_dir():
        raise JournalError(f"refusing to replace unsupported recovery target: {path}")
    for child in path.rglob("*"):
        if child.is_symlink():
            raise JournalError(f"refusing to delete linked recovery target: {child}")
    shutil.rmtree(path)


def _write_restored_file(path: Path, content: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.restore.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if os.name != "nt":
            temporary.chmod(mode)
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        try:
            temporary.unlink()
        except OSError:
            pass


class Transaction:
    def __init__(
        self,
        recovery_root: Path,
        descriptor: dict[str, Any],
        snapshot: dict[str, Any],
        failpoint: Failpoint | None = None,
    ) -> None:
        self.recovery_root = recovery_root
        self.descriptor = descriptor
        self.transaction_id = str(descriptor["transaction_id"])
        self.snapshot_sha256 = str(descriptor["snapshot_sha256"])
        self.snapshot = snapshot
        self.transaction_root = recovery_root / "transactions" / self.transaction_id
        self.descriptor_path = self.transaction_root / "descriptor.json"
        self.journal_path = self.transaction_root / "journal.jsonl"
        self.snapshot_root = recovery_root / "snapshots" / self.snapshot_sha256
        self.active_path = recovery_root / "active.json"
        self.failpoint = failpoint
        records = self.read_records()
        self.stage = str(records[-1]["stage"]) if records else None

    def read_records(self) -> list[dict[str, Any]]:
        raw = _read_secure(self.journal_path)
        if raw and not raw.endswith(b"\n"):
            raise JournalError("transaction journal has a truncated tail")
        records: list[dict[str, Any]] = []
        previous = ""
        previous_rank = -1
        for index, line in enumerate(raw.splitlines(), start=1):
            try:
                record = json.loads(line.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError) as error:
                raise JournalError("transaction journal contains invalid raw bytes") from error
            if not isinstance(record, dict) or set(record) != {
                "schema",
                "schema_version",
                "transaction_id",
                "sequence",
                "stage",
                "previous_sha256",
                "record_sha256",
            }:
                raise JournalError("transaction journal record fields are invalid")
            digest = record.pop("record_sha256")
            expected = _sha256(_canonical(record))
            record["record_sha256"] = digest
            stage = record.get("stage")
            rank = _STAGE_RANK.get(stage) if isinstance(stage, str) else None
            if (
                record.get("schema") != JOURNAL_SCHEMA
                or type(record.get("schema_version")) is not int
                or record["schema_version"] != SCHEMA_VERSION
                or record.get("transaction_id") != self.transaction_id
                or type(record.get("sequence")) is not int
                or record["sequence"] != index
                or record.get("previous_sha256") != previous
                or not isinstance(digest, str)
                or digest != expected
                or rank is None
                or rank <= previous_rank
            ):
                raise JournalError("transaction journal sequence, hash chain, or stage is invalid")
            previous = digest
            previous_rank = rank
            records.append(record)
        return records

    def append(self, stage: str) -> dict[str, Any]:
        records = self.read_records()
        current_rank = _STAGE_RANK.get(records[-1]["stage"], -1) if records else -1
        requested_rank = _STAGE_RANK.get(stage)
        if requested_rank is None or requested_rank <= current_rank:
            raise JournalError("transaction stages must be strictly monotonic")
        if self.failpoint is not None:
            self.failpoint(f"journal.before.{stage}")
        record: dict[str, Any] = {
            "schema": JOURNAL_SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "transaction_id": self.transaction_id,
            "sequence": len(records) + 1,
            "stage": stage,
            "previous_sha256": records[-1]["record_sha256"] if records else "",
        }
        record["record_sha256"] = _sha256(_canonical(record))
        encoded = _canonical(record)
        _validate_metadata(self.journal_path, directory=False)
        descriptor = os.open(
            self.journal_path,
            os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            metadata = os.fstat(descriptor)
            if metadata.st_nlink != 1:
                raise JournalError("transaction journal link count drifted")
            view = memoryview(encoded)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise JournalError("transaction journal append was short")
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        _fsync_directory(self.transaction_root)
        readback = self.read_records()
        if readback[-1] != record:
            raise JournalError("transaction journal append readback differs")
        self.stage = stage
        if self.failpoint is not None:
            self.failpoint(f"journal.after.{stage}")
        return record

    def verify_snapshot(self) -> bool:
        _validate_snapshot(self.snapshot_root, expected_digest=self.snapshot_sha256)
        return True

    def restore_snapshot(self) -> None:
        snapshot = _validate_snapshot(
            self.snapshot_root, expected_digest=self.snapshot_sha256
        )
        blobs = self.snapshot_root / "blobs"
        for target in snapshot["targets"]:
            path = Path(target["path"])
            state = target["state"]
            _remove_current(path)
            if state == "missing":
                continue
            if state == "file":
                _write_restored_file(
                    path,
                    _read_secure(blobs / target["sha256"]),
                    int(target["mode"]),
                )
                continue
            entries = target["entries"]
            directory_entries = sorted(
                (row for row in entries if row["kind"] == "directory"),
                key=lambda row: (len(Path(row["relative"]).parts), row["relative"]),
            )
            for entry in directory_entries:
                destination = path if entry["relative"] == "." else path / entry["relative"]
                destination.mkdir(parents=True, exist_ok=True)
            for entry in entries:
                if entry["kind"] != "file":
                    continue
                _write_restored_file(
                    path / entry["relative"],
                    _read_secure(blobs / entry["sha256"]),
                    int(entry["mode"]),
                )
            if os.name != "nt":
                for entry in reversed(directory_entries):
                    destination = (
                        path
                        if entry["relative"] == "."
                        else path / entry["relative"]
                    )
                    destination.chmod(int(entry["mode"]))
        if not self.verify_restored_snapshot():
            raise JournalError("rollback snapshot restore did not verify")

    def verify_restored_snapshot(self) -> bool:
        snapshot = _validate_snapshot(
            self.snapshot_root, expected_digest=self.snapshot_sha256
        )
        blobs = self.snapshot_root / "blobs"
        for target in snapshot["targets"]:
            path = Path(target["path"])
            if target["state"] == "missing":
                if path.exists() or path.is_symlink():
                    return False
                continue
            if target["state"] == "file":
                if path.is_symlink() or not path.is_file():
                    return False
                if path.read_bytes() != _read_secure(blobs / target["sha256"]):
                    return False
                if os.name != "nt" and stat.S_IMODE(path.stat().st_mode) != target["mode"]:
                    return False
                continue
            if path.is_symlink() or not path.is_dir():
                return False
            expected = {row["relative"]: row for row in target["entries"]}
            actual = {"."}
            actual.update(child.relative_to(path).as_posix() for child in path.rglob("*"))
            if actual != set(expected):
                return False
            for relative, entry in expected.items():
                child = path if relative == "." else path / relative
                if child.is_symlink():
                    return False
                if entry["kind"] == "directory" and not child.is_dir():
                    return False
                if entry["kind"] == "file":
                    if not child.is_file() or child.read_bytes() != _read_secure(
                        blobs / entry["sha256"]
                    ):
                        return False
                if os.name != "nt" and stat.S_IMODE(child.stat().st_mode) != entry["mode"]:
                    return False
        return True

    def clear_active(self) -> None:
        records = self.read_records()
        if not records or records[-1]["stage"] not in _TERMINAL_STAGES:
            raise JournalError("active recovery authority cannot be cleared before terminal readback")
        active = _read_active(self.recovery_root)
        if active.get("transaction_id") != self.transaction_id:
            raise JournalError("active recovery authority belongs to another transaction")
        self.active_path.unlink()
        _fsync_directory(self.recovery_root)


def _read_active(recovery_root: Path) -> dict[str, Any]:
    raw = _read_secure(recovery_root / "active.json")
    payload = _json_object(raw, label="active transaction authority")
    if raw != _canonical(payload) or set(payload) != {
        "schema",
        "schema_version",
        "transaction_id",
        "descriptor_sha256",
    }:
        raise JournalError("active transaction authority raw bytes or fields are invalid")
    if (
        payload.get("schema") != ACTIVE_SCHEMA
        or type(payload.get("schema_version")) is not int
        or payload["schema_version"] != SCHEMA_VERSION
        or not isinstance(payload.get("transaction_id"), str)
        or not _TRANSACTION_ID.fullmatch(payload["transaction_id"])
        or not isinstance(payload.get("descriptor_sha256"), str)
        or not _SHA256.fullmatch(payload["descriptor_sha256"])
    ):
        raise JournalError("active transaction authority schema is unsupported")
    return payload


def load_active_transaction(
    recovery_root: Path, *, failpoint: Failpoint | None = None
) -> Transaction | None:
    root = Path(recovery_root).expanduser()
    active_path = root / "active.json"
    if not active_path.exists() and not active_path.is_symlink():
        return None
    _validate_metadata(root, directory=True)
    active = _read_active(root)
    transaction_root = root / "transactions" / active["transaction_id"]
    _validate_metadata(transaction_root, directory=True)
    descriptor_path = transaction_root / "descriptor.json"
    descriptor_raw = _read_secure(descriptor_path)
    if _sha256(descriptor_raw) != active["descriptor_sha256"]:
        raise JournalError("active transaction descriptor digest mismatch")
    descriptor = _json_object(descriptor_raw, label="transaction descriptor")
    if descriptor_raw != _canonical(descriptor):
        raise JournalError("transaction descriptor raw bytes are not canonical")
    _validate_descriptor(descriptor)
    if descriptor["transaction_id"] != active["transaction_id"]:
        raise JournalError("active transaction ID does not match its descriptor")
    _validate_metadata(transaction_root / "journal.jsonl", directory=False)
    snapshot = _validate_snapshot(
        root / "snapshots" / descriptor["snapshot_sha256"],
        expected_digest=descriptor["snapshot_sha256"],
    )
    return Transaction(root, descriptor, snapshot, failpoint)


def begin_transaction(
    recovery_root: Path,
    descriptor: dict[str, Any],
    *,
    snapshot_paths: Iterable[Path],
    failpoint: Failpoint | None = None,
) -> Transaction:
    root = Path(recovery_root).expanduser()
    _ensure_directory(root)
    existing = load_active_transaction(root, failpoint=failpoint)
    if existing is not None:
        supplied = dict(descriptor)
        stored = {key: existing.descriptor[key] for key in _DESCRIPTOR_INPUT_FIELDS}
        if supplied == stored:
            return existing
        raise TransactionCollision(
            "a different transaction already owns the stable recovery location"
        )
    if set(descriptor) != _DESCRIPTOR_INPUT_FIELDS:
        raise JournalError("caller transaction descriptor fields are incomplete or unknown")
    transaction_id = descriptor.get("transaction_id")
    if not isinstance(transaction_id, str) or not _TRANSACTION_ID.fullmatch(transaction_id):
        raise JournalError("caller transaction ID is invalid")
    _validate_no_secrets(descriptor)
    snapshot_sha256 = _persist_snapshot(root, transaction_id, tuple(snapshot_paths))
    sealed = {
        **descriptor,
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "snapshot_sha256": snapshot_sha256,
    }
    _validate_descriptor(sealed)
    transactions = root / "transactions"
    _ensure_directory(transactions)
    transaction_root = transactions / transaction_id
    if transaction_root.exists() or transaction_root.is_symlink():
        raise TransactionCollision(f"transaction evidence already exists: {transaction_id}")
    transaction_root.mkdir(mode=0o700)
    _fsync_directory(transactions)
    descriptor_raw = _canonical(sealed)
    _atomic_write(transaction_root / "descriptor.json", descriptor_raw)
    _atomic_write(transaction_root / "journal.jsonl", b"")
    active = {
        "schema": ACTIVE_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "transaction_id": transaction_id,
        "descriptor_sha256": _sha256(descriptor_raw),
    }
    _atomic_write(root / "active.json", _canonical(active))
    loaded = load_active_transaction(root, failpoint=failpoint)
    if loaded is None:
        raise JournalError("new transaction authority vanished during readback")
    return loaded
