#!/usr/bin/env python3
"""Merge a legacy host-specific memory DB into the neutral Sulde home once.

The caller must first quiesce managed writers.  This module takes an immediate
SQLite lock on the legacy database, creates integrity-checked backups of both
inputs, merges by durable memory identities, and retires only the legacy
``memory.db`` as read-only.  It never deletes either source or backup.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import tempfile
from typing import Any
import uuid


SCHEMA = "sulde-memory-home-reconcile-v1"
RETIREMENT_SCHEMA = "sulde-legacy-memory-retirement-v1"
RETIREMENT_FILE = ".sulde-memory-retired.json"


class MemoryReconcileError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_database(path: Path, *, label: str) -> Path:
    candidate = path.expanduser().absolute()
    try:
        metadata = candidate.stat(follow_symlinks=False)
    except OSError as error:
        raise MemoryReconcileError(f"{label} is unavailable: {candidate}") from error
    owner = os.geteuid() if hasattr(os, "geteuid") else os.getuid()
    if (
        candidate.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != owner
        or metadata.st_nlink != 1
    ):
        raise MemoryReconcileError(f"{label} is not one owner-controlled regular file")
    return candidate


def _connect(path: Path, *, timeout: float = 10.0) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=timeout)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _integrity(connection: sqlite3.Connection, *, label: str) -> None:
    result = connection.execute("PRAGMA integrity_check").fetchone()
    if result is None or str(result[0]).lower() != "ok":
        raise MemoryReconcileError(f"{label} integrity check failed: {result!r}")
    required = {"mem_entries", "mem_vectors", "mem_fts", "mem_edges", "mem_entities"}
    tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
        )
    }
    missing = sorted(required - tables)
    if missing:
        raise MemoryReconcileError(f"{label} schema is incomplete: {','.join(missing)}")


def _stats(connection: sqlite3.Connection) -> dict[str, int]:
    return {
        "entries": int(connection.execute("SELECT COUNT(*) FROM mem_entries").fetchone()[0]),
        "pending": int(
            connection.execute("SELECT COUNT(*) FROM mem_entries WHERE embedded=0").fetchone()[0]
        ),
        "vectors": int(connection.execute("SELECT COUNT(*) FROM mem_vectors").fetchone()[0]),
        "edges": int(connection.execute("SELECT COUNT(*) FROM mem_edges").fetchone()[0]),
        "entities": int(connection.execute("SELECT COUNT(*) FROM mem_entities").fetchone()[0]),
    }


def plan(source: Path, destination: Path) -> dict[str, Any]:
    source = _safe_database(source, label="legacy memory database")
    destination = _safe_database(destination, label="neutral memory database")
    if source.resolve() == destination.resolve():
        raise MemoryReconcileError("legacy and neutral memory databases are identical")
    legacy = _connect(source)
    neutral = _connect(destination)
    try:
        _integrity(legacy, label="legacy memory database")
        _integrity(neutral, label="neutral memory database")
        # Compute the cross-database identity delta without attaching either
        # writable database or mutating either input.
        destination_keys = {
            (str(row[0]), str(row[1]))
            for row in neutral.execute(
                "SELECT session_id, content_hash FROM mem_entries"
            )
        }
        source_keys = [
            (str(row[0]), str(row[1]))
            for row in legacy.execute(
                "SELECT session_id, content_hash FROM mem_entries"
            )
        ]
        missing_entries = sum(key not in destination_keys for key in source_keys)
        return {
            "schema": SCHEMA,
            "ready": True,
            "source": str(source),
            "destination": str(destination),
            "source_stats": _stats(legacy),
            "destination_stats": _stats(neutral),
            "missing_entries": missing_entries,
            "reconcile_required": bool(missing_entries or stat.S_IMODE(source.stat().st_mode) & 0o222),
        }
    finally:
        neutral.close()
        legacy.close()


def _snapshot_database(connection: sqlite3.Connection, target: Path) -> None:
    """Write the committed snapshot protected by the caller's write lock."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        target.parent.chmod(0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", dir=target.parent
    )
    temporary = Path(temporary_name)
    os.close(descriptor)
    try:
        database_row = connection.execute("PRAGMA database_list").fetchone()
        if database_row is None or not str(database_row[2] or ""):
            raise MemoryReconcileError("SQLite connection has no main database path")
        database = Path(str(database_row[2])).absolute()
        reader = sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)
        snapshot = sqlite3.connect(temporary)
        try:
            reader.backup(snapshot)
            snapshot.commit()
        finally:
            snapshot.close()
            reader.close()
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except (OSError, sqlite3.Error) as error:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise MemoryReconcileError(
            f"cannot snapshot SQLite database for {target.name}: {error}"
        ) from error
    if os.name != "nt":
        target.chmod(0o600)
    backup = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
    try:
        _integrity(backup, label=f"backup {target.name}")
    finally:
        backup.close()


def _atomic_json(path: Path, payload: dict[str, Any], *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_canonical(payload) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        if os.name != "nt":
            temporary.chmod(mode)
        os.replace(temporary, path)
    except Exception:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def _merge(legacy: sqlite3.Connection, neutral: sqlite3.Connection) -> dict[str, int]:
    inserted_entries = 0
    restored_vectors = 0
    restored_fts = 0
    id_map: dict[int, int] = {}
    entry_columns = (
        "project", "session_id", "source_host", "role", "content",
        "content_hash", "ts", "embedded",
    )
    for row in legacy.execute(
        "SELECT id, project, session_id, source_host, role, content, content_hash, ts, embedded "
        "FROM mem_entries ORDER BY id"
    ):
        existing = neutral.execute(
            "SELECT id, embedded FROM mem_entries WHERE session_id=? AND content_hash=?",
            (row["session_id"], row["content_hash"]),
        ).fetchone()
        if existing is None:
            values = tuple(row[column] for column in entry_columns)
            cursor = neutral.execute(
                "INSERT INTO mem_entries(project,session_id,source_host,role,content,content_hash,ts,embedded) "
                "VALUES (?,?,?,?,?,?,?,?)",
                values,
            )
            destination_id = int(cursor.lastrowid)
            inserted_entries += 1
        else:
            destination_id = int(existing["id"])
        id_map[int(row["id"])] = destination_id

        vector = legacy.execute(
            "SELECT dim, vector FROM mem_vectors WHERE id=?", (row["id"],)
        ).fetchone()
        destination_vector = neutral.execute(
            "SELECT 1 FROM mem_vectors WHERE id=?", (destination_id,)
        ).fetchone()
        if vector is not None and destination_vector is None:
            neutral.execute(
                "INSERT INTO mem_vectors(id,dim,vector) VALUES (?,?,?)",
                (destination_id, vector["dim"], vector["vector"]),
            )
            neutral.execute(
                "UPDATE mem_entries SET embedded=1 WHERE id=?", (destination_id,)
            )
            restored_vectors += 1

        fts = legacy.execute(
            "SELECT seg_text FROM mem_fts WHERE rowid=?", (row["id"],)
        ).fetchone()
        destination_fts = neutral.execute(
            "SELECT 1 FROM mem_fts WHERE rowid=?", (destination_id,)
        ).fetchone()
        if fts is not None and destination_fts is None:
            neutral.execute(
                "INSERT INTO mem_fts(rowid,seg_text) VALUES (?,?)",
                (destination_id, fts["seg_text"]),
            )
            restored_fts += 1

    if "mem_capture_state" in {
        str(row[0])
        for row in legacy.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }:
        for row in legacy.execute(
            "SELECT transcript_path, byte_offset FROM mem_capture_state"
        ):
            neutral.execute(
                """
                INSERT INTO mem_capture_state(transcript_path,byte_offset) VALUES (?,?)
                ON CONFLICT(transcript_path) DO UPDATE SET
                  byte_offset=MAX(mem_capture_state.byte_offset, excluded.byte_offset)
                """,
                (row["transcript_path"], row["byte_offset"]),
            )

    inserted_entities = 0
    for row in legacy.execute("SELECT name,type,first_seen FROM mem_entities"):
        cursor = neutral.execute(
            "INSERT OR IGNORE INTO mem_entities(name,type,first_seen) VALUES (?,?,?)",
            (row["name"], row["type"], row["first_seen"]),
        )
        inserted_entities += max(cursor.rowcount, 0)

    inserted_edges = 0
    for row in legacy.execute(
        "SELECT src,rel,dst,entry_id,extracted_by,confidence,ts FROM mem_edges ORDER BY id"
    ):
        mapped_entry = id_map.get(int(row["entry_id"])) if row["entry_id"] is not None else None
        cursor = neutral.execute(
            """
            INSERT OR IGNORE INTO mem_edges(src,rel,dst,entry_id,extracted_by,confidence,ts)
            VALUES (?,?,?,?,?,?,?)
            """,
            (
                row["src"], row["rel"], row["dst"], mapped_entry,
                row["extracted_by"], row["confidence"], row["ts"],
            ),
        )
        inserted_edges += max(cursor.rowcount, 0)
        if mapped_entry is not None:
            neutral.execute(
                "UPDATE mem_edges SET entry_id=? WHERE src=? AND rel=? AND dst=? AND entry_id IS NULL",
                (mapped_entry, row["src"], row["rel"], row["dst"]),
            )

    return {
        "inserted_entries": inserted_entries,
        "restored_vectors": restored_vectors,
        "restored_fts": restored_fts,
        "inserted_edges": inserted_edges,
        "inserted_entities": inserted_entities,
    }


def reconcile(
    source: Path,
    destination: Path,
    *,
    archive_root: Path,
) -> dict[str, Any]:
    source = _safe_database(source, label="legacy memory database")
    destination = _safe_database(destination, label="neutral memory database")
    if source.resolve() == destination.resolve():
        raise MemoryReconcileError("legacy and neutral memory databases are identical")

    transaction_id = uuid.uuid4().hex
    transaction_root = archive_root.expanduser().absolute() / transaction_id
    transaction_root.mkdir(parents=True, exist_ok=False)
    if os.name != "nt":
        transaction_root.chmod(0o700)
    source_mode = stat.S_IMODE(source.stat(follow_symlinks=False).st_mode)
    legacy = _connect(source)
    neutral = _connect(destination)
    committed = False
    try:
        _integrity(legacy, label="legacy memory database")
        _integrity(neutral, label="neutral memory database")
        legacy.execute("PRAGMA wal_checkpoint(FULL)")
        neutral.execute("PRAGMA wal_checkpoint(FULL)")
        legacy.execute("BEGIN IMMEDIATE")
        neutral.execute("BEGIN IMMEDIATE")
        _snapshot_database(legacy, transaction_root / "legacy-memory.db")
        _snapshot_database(neutral, transaction_root / "neutral-before.db")
        before = _stats(neutral)
        merged = _merge(legacy, neutral)
        neutral.commit()
        committed = True
        _integrity(neutral, label="reconciled neutral memory database")
        after = _stats(neutral)
        if after["entries"] < before["entries"]:
            raise MemoryReconcileError("reconciliation reduced neutral memory entries")

        retired_files: list[str] = []
        if os.name != "nt":
            for candidate in (source, source.with_name(source.name + "-wal"), source.with_name(source.name + "-shm")):
                if candidate.is_file() and not candidate.is_symlink():
                    candidate.chmod(0o444)
                    retired_files.append(str(candidate))
        legacy.rollback()
        legacy.close()
        legacy = None  # type: ignore[assignment]

        payload = {
            "schema": SCHEMA,
            "ready": True,
            "transaction_id": transaction_id,
            "source": str(source),
            "destination": str(destination),
            "source_mode_before": source_mode,
            "source_sha256": _sha256(source),
            "destination_sha256": _sha256(destination),
            "archive_root": str(transaction_root),
            "legacy_backup_sha256": _sha256(transaction_root / "legacy-memory.db"),
            "neutral_backup_sha256": _sha256(transaction_root / "neutral-before.db"),
            "before": before,
            "after": after,
            "merge": merged,
            "retired_files": retired_files,
            "at": datetime.now(timezone.utc).isoformat(),
        }
        payload["receipt_sha256"] = hashlib.sha256(_canonical(payload)).hexdigest()
        _atomic_json(transaction_root / "receipt.json", payload)
        retirement = {
            "schema": RETIREMENT_SCHEMA,
            "status": "read_only_archive",
            "transaction_id": transaction_id,
            "neutral_memory_db": str(destination),
            "receipt": str(transaction_root / "receipt.json"),
            "receipt_sha256": payload["receipt_sha256"],
        }
        _atomic_json(source.parent / RETIREMENT_FILE, retirement, mode=0o444)
        return payload
    except Exception:
        if not committed:
            try:
                neutral.rollback()
            except sqlite3.Error:
                pass
        if legacy is not None:
            try:
                legacy.rollback()
            except sqlite3.Error:
                pass
        raise
    finally:
        neutral.close()
        if legacy is not None:
            legacy.close()


def restore_legacy_write_mode(receipt: dict[str, Any]) -> None:
    """Undo only this transaction's retirement bit for home-migration rollback."""
    if receipt.get("schema") != SCHEMA or receipt.get("ready") is not True:
        raise MemoryReconcileError("memory reconciliation receipt is invalid")
    source = _safe_database(
        Path(str(receipt.get("source") or "")),
        label="retired legacy memory database",
    )
    transaction_id = str(receipt.get("transaction_id") or "")
    marker = source.parent / RETIREMENT_FILE
    try:
        retirement = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise MemoryReconcileError("legacy memory retirement marker is invalid") from error
    if (
        retirement.get("schema") != RETIREMENT_SCHEMA
        or retirement.get("transaction_id") != transaction_id
    ):
        raise MemoryReconcileError("legacy memory retirement belongs to another transaction")
    mode = receipt.get("source_mode_before")
    if type(mode) is not int or mode < 0 or mode > 0o777:
        raise MemoryReconcileError("legacy memory prior mode is invalid")
    if os.name != "nt":
        source.chmod(mode)
    marker.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "apply"))
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "plan":
            result = plan(args.source, args.destination)
        else:
            if args.archive_root is None:
                raise MemoryReconcileError("apply requires --archive-root")
            result = reconcile(
                args.source,
                args.destination,
                archive_root=args.archive_root,
            )
    except (MemoryReconcileError, OSError, sqlite3.Error, ValueError) as error:
        print(json.dumps({"ready": False, "error": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
