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
REVERSE_SCHEMA = "sulde-first-migration-reversal-v1"
REVERSE_ACTIVE_SCHEMA = "sulde-install-active-reversal-v1"
REVERSE_JOURNAL_SCHEMA = "sulde-first-migration-reversal-stage-v1"
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
    "hook_trust_write_started",
    "hook_trust_written",
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


def content_identity(path: Path) -> str:
    """Path-independent identity using the existing snapshot byte/mode schema."""
    raw, _ = _capture_snapshot(Path(), (path,))
    target = json.loads(raw)["targets"][0]
    target.pop("path")
    return _sha256(_canonical(target))


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
    journal_schema = JOURNAL_SCHEMA
    stage_rank = _STAGE_RANK
    terminal_stages = _TERMINAL_STAGES

    def __init__(
        self,
        recovery_root: Path,
        descriptor: dict[str, Any],
        snapshot: dict[str, Any],
        failpoint: Failpoint | None = None,
    ) -> None:
        self.recovery_root = recovery_root
        self.descriptor = descriptor
        self.descriptor_sha256 = _sha256(_canonical(descriptor))
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
            rank = self.stage_rank.get(stage) if isinstance(stage, str) else None
            if (
                record.get("schema") != self.journal_schema
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
        current_rank = self.stage_rank.get(records[-1]["stage"], -1) if records else -1
        requested_rank = self.stage_rank.get(stage)
        if requested_rank is None or requested_rank <= current_rank:
            raise JournalError("transaction stages must be strictly monotonic")
        if self.failpoint is not None:
            self.failpoint(f"journal.before.{stage}")
        record: dict[str, Any] = {
            "schema": self.journal_schema,
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

    def _retained_output_matches(self, path: Path) -> bool:
        """Only sealed atomic-profile retirement outputs may remain after rollback.

        This does not change the original snapshot or exempt other missing paths.
        Published directories may have readers holding their resolved path or fd.
        """
        expected = self.descriptor["expected_postconditions"]
        outputs = expected.get("retained_outputs", {})
        if not outputs or str(path) not in outputs:
            return False
        if "registry_remove_started" not in {row["stage"] for row in self.read_records()}:
            # Targets prepared before this durable boundary have not been
            # published as cache aliases. Partial copies remain rollback-owned.
            return False
        rows = expected.get("retirements", [])
        allowed = {str(row[key]) for row in rows for key in ("target", "record")}
        if (expected.get("cache_handoff") != "atomic-v1"
                or not isinstance(outputs, dict) or not set(outputs).issubset(allowed)
                or path.parent.resolve() != path.parent):
            raise JournalError("retained output scope differs from sealed retirement authority")
        digest = outputs[str(path)]
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise JournalError("retained output identity is invalid")
        if content_identity(path) != digest:
            raise JournalError("retained output content differs from sealed identity")
        return True

    def restore_snapshot(self, *, atomic_directories=(), staging_parent=None) -> None:
        snapshot = _validate_snapshot(
            self.snapshot_root, expected_digest=self.snapshot_sha256
        )
        self._verify_published_retained_targets()
        blobs = self.snapshot_root / "blobs"
        atomic_paths = {str(path) for path in atomic_directories}
        for target in snapshot["targets"]:
            path = Path(target["path"])
            state = target["state"]
            if state == "missing" and (path.exists() or path.is_symlink()):
                if self._retained_output_matches(path):
                    continue
            published_path = None
            staging = None
            if state == "directory" and str(path) in atomic_paths:
                parent = Path(staging_parent)
                if parent.resolve() != parent or not parent.is_dir():
                    raise JournalError("atomic restore staging parent is unsafe")
                if not (path.exists() or path.is_symlink()):
                    raise JournalError("atomic restore cannot hide a missing live path")
                if path.lstat().st_dev != parent.stat().st_dev:
                    raise JournalError("atomic restore crosses filesystems")
                staging = Path(tempfile.mkdtemp(prefix=".sulde-restore-", dir=parent))
                published_path, path = path, staging / "tree"
            elif not (atomic_paths and state == "file" and path.is_file() and not path.is_symlink()):
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
            if published_path is not None:
                from atomic_cache_handoff import exchange
                exchange(path, published_path)
                # Preserve displaced bytes for crash forensics. They are not
                # authoritative; the sealed snapshot remains the recovery source.
        if not self.verify_restored_snapshot():
            raise JournalError("rollback snapshot restore did not verify")

    def _verify_published_retained_targets(self) -> None:
        expected = self.descriptor["expected_postconditions"]
        if expected.get("cache_handoff") != "atomic-v1":
            return
        if "registry_remove_started" not in {row["stage"] for row in self.read_records()}:
            return
        # All targets exist before this boundary, even if a crash precedes an
        # alias's record write. A missing target must not inherit the original
        # snapshot's "missing" success rule: existing readers may hold it.
        for row in expected.get("retirements", []):
            if not self._retained_output_matches(Path(row["target"])):
                raise JournalError("published retirement target lacks sealed identity")

    def verify_restored_snapshot(self) -> bool:
        snapshot = _validate_snapshot(
            self.snapshot_root, expected_digest=self.snapshot_sha256
        )
        self._verify_published_retained_targets()
        blobs = self.snapshot_root / "blobs"
        for target in snapshot["targets"]:
            path = Path(target["path"])
            if target["state"] == "missing":
                if path.exists() or path.is_symlink():
                    if not self._retained_output_matches(path):
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
        if not records or records[-1]["stage"] not in self.terminal_stages:
            raise JournalError("active recovery authority cannot be cleared before terminal readback")
        active = _read_active(self.recovery_root)
        if (active.get("transaction_id") != self.transaction_id
                or active.get("descriptor_sha256") != self.descriptor_sha256):
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
        payload.get("schema") not in {ACTIVE_SCHEMA, REVERSE_ACTIVE_SCHEMA}
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
    transaction = load_transaction(
        root, active["transaction_id"],
        expected_descriptor_sha256=active["descriptor_sha256"], failpoint=failpoint,
    )
    expected = REVERSE_ACTIVE_SCHEMA if isinstance(transaction, ReverseTransaction) else ACTIVE_SCHEMA
    if active["schema"] != expected:
        raise JournalError("active authority type differs from its descriptor")
    return transaction


def load_transaction(
    recovery_root: Path,
    transaction_id: str,
    *,
    expected_descriptor_sha256: str,
    failpoint: Failpoint | None = None,
) -> Transaction:
    """Read an exactly bound journal, including after active cleanup.

    This is observation only: it never recreates an active pointer or grants
    recovery authority from an unbound directory or a self-computed digest.
    """
    if not isinstance(transaction_id, str) or not _TRANSACTION_ID.fullmatch(transaction_id):
        raise JournalError("transaction lookup ID is invalid")
    if not isinstance(expected_descriptor_sha256, str) or not _SHA256.fullmatch(expected_descriptor_sha256):
        raise JournalError("transaction lookup requires a bound descriptor digest")
    root = Path(recovery_root).expanduser()
    _validate_metadata(root, directory=True)
    _validate_metadata(root / "transactions", directory=True)
    _validate_metadata(root / "snapshots", directory=True)
    transaction_root = root / "transactions" / transaction_id
    _validate_metadata(transaction_root, directory=True)
    descriptor_path = transaction_root / "descriptor.json"
    descriptor_raw = _read_secure(descriptor_path)
    if _sha256(descriptor_raw) != expected_descriptor_sha256:
        raise JournalError("transaction descriptor digest mismatch")
    descriptor = _json_object(descriptor_raw, label="transaction descriptor")
    if descriptor_raw != _canonical(descriptor):
        raise JournalError("transaction descriptor raw bytes are not canonical")
    reverse = descriptor.get("schema") == REVERSE_SCHEMA
    if reverse:
        _validate_reverse_descriptor(descriptor)
    else:
        _validate_descriptor(descriptor)
    if descriptor["transaction_id"] != transaction_id:
        raise JournalError("transaction ID does not match its descriptor")
    _validate_metadata(transaction_root / "journal.jsonl", directory=False)
    snapshot = _validate_snapshot(
        root / "snapshots" / descriptor["snapshot_sha256"],
        expected_digest=descriptor["snapshot_sha256"],
    )
    cls = ReverseTransaction if reverse else Transaction
    return cls(root, descriptor, snapshot, failpoint)


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
        if isinstance(existing, ReverseTransaction):
            raise TransactionCollision("a reversal owns the stable recovery location")
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
    if failpoint is not None:
        failpoint("transaction.before_journal")
    _atomic_write(transaction_root / "journal.jsonl", b"")
    if failpoint is not None:
        failpoint("transaction.after_journal")
    active = {
        "schema": ACTIVE_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "transaction_id": transaction_id,
        "descriptor_sha256": _sha256(descriptor_raw),
    }
    if failpoint is not None:
        failpoint("transaction.before_active")
    _atomic_write(root / "active.json", _canonical(active))
    if failpoint is not None:
        failpoint("transaction.after_active")
    loaded = load_active_transaction(root, failpoint=failpoint)
    if loaded is None:
        raise JournalError("new transaction authority vanished during readback")
    return loaded


_REVERSE_FIELDS = {"schema", "schema_version", "transaction_id", "old_generation",
                   "new_generation", "snapshot_sha256", "origin", "authority_json"}
_REVERSE_STAGES = ("prepared", "fenced", "restore_started", "restored", "committed")


def _validate_reverse_descriptor(value: dict[str, Any]) -> None:
    if (set(value) != _REVERSE_FIELDS or value.get("schema") != REVERSE_SCHEMA
            or type(value.get("schema_version")) is not int or value["schema_version"] != 1
            or not isinstance(value.get("transaction_id"), str)
            or not _TRANSACTION_ID.fullmatch(value["transaction_id"])):
        raise JournalError("reversal descriptor schema or identity is invalid")
    origin = value.get("origin")
    if (not isinstance(origin, dict) or set(origin) != {"transaction_id", "descriptor_sha256"}
            or not isinstance(origin["transaction_id"], str)
            or not _TRANSACTION_ID.fullmatch(origin["transaction_id"])
            or origin["transaction_id"] == value["transaction_id"]
            or not isinstance(origin["descriptor_sha256"], str)
            or not _SHA256.fullmatch(origin["descriptor_sha256"])
            or not isinstance(value.get("snapshot_sha256"), str)
            or not _SHA256.fullmatch(value["snapshot_sha256"])):
        raise JournalError("reversal origin binding is invalid")
    for field in ("old_generation", "new_generation"):
        if not isinstance(value.get(field), str) or not value[field]:
            raise JournalError("reversal generation is unproven")
    raw = value.get("authority_json")
    if not isinstance(raw, str):
        raise JournalError("reversal authority is missing")
    plan = _json_object(raw.encode(), label="reversal authority")
    if _canonical(plan).decode() != raw:
        raise JournalError("reversal authority is not canonical")
    _validate_no_secrets(value)


class ReverseTransaction(Transaction):
    """Exact inverse; snapshot ALWAYS means the original old destination.

    No new-state snapshot is captured. The old committed journal is read-only;
    its own rollback stages must never be appended by the inverse controller.
    Caller holds the deployment lock, just as for forward transactions.
    """
    journal_schema = REVERSE_JOURNAL_SCHEMA
    stage_rank = {stage: index for index, stage in enumerate(_REVERSE_STAGES)}
    terminal_stages = frozenset({"committed"})

    def origin_transaction(self) -> Transaction:
        binding = self.descriptor["origin"]
        origin = load_transaction(self.recovery_root, binding["transaction_id"],
                                  expected_descriptor_sha256=binding["descriptor_sha256"])
        if (isinstance(origin, ReverseTransaction) or origin.stage != "committed"
                or origin.snapshot_sha256 != self.snapshot_sha256
                or origin.descriptor["new_generation"] != self.descriptor["old_generation"]
                or origin.descriptor["old_generation"] != self.descriptor["new_generation"]):
            raise JournalError("reversal is not the exact inverse of a committed installation")
        return origin


def begin_reversal(recovery_root: Path, *, operation_id: str, origin: Transaction,
                   authority_json: str, failpoint: Failpoint | None = None) -> ReverseTransaction:
    """Durably acquire the SAME active slot. This is not an approval interface.

    Only the approved maintenance controller calls this after lineage, expiry,
    process, lease and CAS checks. Persisted start is the mechanical recovery
    boundary; orphan descriptors before active publication confer no authority.
    """
    root = Path(recovery_root).expanduser()
    if root.resolve() != origin.recovery_root.resolve():
        raise JournalError("reversal origin belongs to a different recovery root")
    sealed = {"schema": REVERSE_SCHEMA, "schema_version": 1,
              "transaction_id": operation_id,
              "old_generation": origin.descriptor["new_generation"],
              "new_generation": origin.descriptor["old_generation"],
              "snapshot_sha256": origin.snapshot_sha256,
              "origin": {"transaction_id": origin.transaction_id,
                         "descriptor_sha256": origin.descriptor_sha256},
              "authority_json": authority_json}
    _validate_reverse_descriptor(sealed)
    if isinstance(origin, ReverseTransaction) or origin.stage != "committed":
        raise JournalError("reversal requires a committed forward origin")
    origin.verify_snapshot()
    existing = load_active_transaction(root)
    if existing is not None:
        if isinstance(existing, ReverseTransaction) and existing.descriptor == sealed:
            return existing
        raise TransactionCollision("another transaction owns the reversal slot")
    directory = root / "transactions" / operation_id
    if directory.exists() or directory.is_symlink():
        raise TransactionCollision("reversal identity already used; exact recovery required")
    directory.mkdir(mode=0o700)
    _fsync_directory(directory.parent)
    raw = _canonical(sealed)
    _atomic_write(directory / "descriptor.json", raw)
    _atomic_write(directory / "journal.jsonl", b"")
    if failpoint:
        failpoint("reversal.before_active")
    _atomic_write(root / "active.json", _canonical({"schema": REVERSE_ACTIVE_SCHEMA,
        "schema_version": 1, "transaction_id": operation_id, "descriptor_sha256": _sha256(raw)}))
    if failpoint:
        failpoint("reversal.after_active")
    loaded = load_active_transaction(root, failpoint=failpoint)
    if not isinstance(loaded, ReverseTransaction) or loaded.descriptor != sealed:
        raise JournalError("reversal authority failed independent readback")
    loaded.origin_transaction()
    return loaded
