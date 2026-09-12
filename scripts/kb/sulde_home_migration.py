#!/usr/bin/env python3
"""Transactional migration from a host-specific legacy KB into ``SULDE_HOME``.

The caller must quiesce schedulers and Hook writers first and supply an
owner-only receipt.  This module never dual-writes and never removes the
legacy source; retirement is a separate, later operation.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import tempfile
from typing import Iterable
import uuid

from sulde_paths import (
    CONTRACT_IDENTITY_FILE,
    CONTRACT_IDENTITY_SCHEMA,
    SuldeLayout,
    layout,
)


QUIESCENCE_SCHEMA = "sulde-home-migration-quiescence-v1"
POINTER_SCHEMA = "sulde-current-home-v1"
PUBLIC_LAUNCHERS = frozenset(
    {
        "sulde-statusline.py",
        "kb-index",
        "sulde-kb-mcp",
        "mem-sync",
        "model-dispatch",
        "intent-guardian",
        ".sulde-launchers.json",
        ".sulde-command-effects.json",
    }
)


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class FileRecord:
    relative: str
    size: int
    sha256: str
    kind: str
    link_target: str | None
    mode: int | None


_VENV_INTERPRETER_NAME = re.compile(
    r"python(?:\d+(?:\.\d+)*)?(?:\.exe)?",
    re.IGNORECASE,
)


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _assert_safe_directory(path: Path, *, must_exist: bool) -> Path:
    candidate = path.expanduser().absolute()
    if candidate.is_symlink():
        raise MigrationError(f"symbolic-link directory is not allowed: {candidate}")
    if must_exist and not candidate.is_dir():
        raise MigrationError(f"migration source is unavailable: {candidate}")
    if candidate.exists() and not candidate.is_dir():
        raise MigrationError(f"migration directory is not a directory: {candidate}")
    return candidate


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _validated_external_venv_interpreter(
    root: Path,
    link: Path,
    target: Path,
) -> Path:
    try:
        relative = link.relative_to(root)
        source_owner = root.stat(follow_symlinks=False).st_uid
        # Homebrew and framework Python commonly expose ``bin/pythonX.Y`` as
        # a symlink into a sibling ``Frameworks`` directory.  Bind the chain
        # to the concrete interpreter installation prefix, not only its
        # ``bin`` leaf, so a real venv remains portable without accepting an
        # arbitrary filesystem escape.
        external_prefix = target.parent.parent.resolve(strict=True)
    except (OSError, ValueError) as error:
        raise MigrationError(f"external venv interpreter is unavailable: {link}") from error
    if not (
        len(relative.parts) == 3
        and relative.parts[0] == "venv"
        and relative.parts[1] in {"bin", "Scripts"}
        and bool(_VENV_INTERPRETER_NAME.fullmatch(relative.name))
    ):
        raise MigrationError(f"external symbolic link in migration tree: {link}")
    current = target
    seen: set[Path] = set()
    while True:
        if current in seen:
            raise MigrationError(f"external interpreter symlink cycle: {link}")
        seen.add(current)
        try:
            metadata = current.stat(follow_symlinks=False)
        except OSError as error:
            raise MigrationError(f"broken external interpreter link: {link}") from error
        if not stat.S_ISLNK(metadata.st_mode):
            break
        raw_target = os.readlink(current)
        current = Path(
            os.path.abspath(
                raw_target if os.path.isabs(raw_target) else current.parent / raw_target
            )
        )
        try:
            current = current.parent.resolve(strict=True) / current.name
        except OSError as error:
            raise MigrationError(f"broken external interpreter link: {link}") from error
        if not _inside(external_prefix, current):
            raise MigrationError(f"external interpreter escapes its bin prefix: {link}")
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != source_owner
        or metadata.st_mode & 0o022
        or not metadata.st_mode & 0o111
    ):
        raise MigrationError(f"unsafe external venv interpreter: {link}")
    return current


def _validated_symlink_target(
    root: Path,
    link: Path,
    *,
    seen: frozenset[Path] = frozenset(),
) -> Path:
    """Resolve one frozen file-link chain without accepting directory escapes.

    Hugging Face snapshots use relative links to content-addressed blobs and a
    Python venv uses a small interpreter-link chain.  Both are ordinary legacy
    runtime state.  Preserve those exact links, but reject link directories,
    arbitrary external targets, cycles, writable interpreters and non-files.
    """
    if link in seen:
        raise MigrationError(f"symbolic-link cycle in migration tree: {link}")
    try:
        raw_target = os.readlink(link)
    except OSError as error:
        raise MigrationError(f"cannot read migration symbolic link: {link}") from error
    if os.path.isabs(raw_target):
        target = Path(os.path.abspath(raw_target))
        return _validated_external_venv_interpreter(root, link, target)
    else:
        target = Path(os.path.abspath(os.path.join(link.parent, raw_target)))
        if not _inside(root, target):
            raise MigrationError(f"escaping symbolic link in migration tree: {link}")
    try:
        metadata = target.stat(follow_symlinks=False)
    except OSError as error:
        raise MigrationError(f"broken symbolic link in migration tree: {link}") from error
    if stat.S_ISLNK(metadata.st_mode):
        return _validated_symlink_target(
            root,
            target,
            seen=seen | frozenset({link}),
        )
    if not stat.S_ISREG(metadata.st_mode):
        raise MigrationError(f"symbolic link does not resolve to a file: {link}")
    return target


def _records(root: Path) -> tuple[FileRecord, ...]:
    root = _assert_safe_directory(root, must_exist=True)
    rows: list[FileRecord] = [
        FileRecord(
            ".",
            0,
            "",
            "directory",
            None,
            None if os.name == "nt" else stat.S_IMODE(root.stat().st_mode),
        )
    ]
    for directory, names, filenames in os.walk(root, followlinks=False):
        base = Path(directory)
        for name in names:
            candidate = base / name
            if candidate.is_symlink():
                raise MigrationError(
                    f"symbolic-link directory in migration tree: {candidate}"
                )
            metadata = candidate.stat(follow_symlinks=False)
            if not stat.S_ISDIR(metadata.st_mode):
                raise MigrationError(f"non-directory in migration tree: {candidate}")
            rows.append(
                FileRecord(
                    candidate.relative_to(root).as_posix(),
                    0,
                    "",
                    "directory",
                    None,
                    None if os.name == "nt" else stat.S_IMODE(metadata.st_mode),
                )
            )
        for name in filenames:
            candidate = base / name
            metadata = candidate.stat(follow_symlinks=False)
            if stat.S_ISLNK(metadata.st_mode):
                resolved = _validated_symlink_target(root, candidate)
                raw_target = os.readlink(candidate)
                rows.append(
                    FileRecord(
                        candidate.relative_to(root).as_posix(),
                        resolved.stat(follow_symlinks=False).st_size,
                        _file_sha256(resolved),
                        "symlink",
                        raw_target,
                        None,
                    )
                )
                continue
            if not stat.S_ISREG(metadata.st_mode):
                raise MigrationError(f"non-regular file in migration tree: {candidate}")
            rows.append(
                FileRecord(
                    candidate.relative_to(root).as_posix(),
                    metadata.st_size,
                    _file_sha256(candidate),
                    "file",
                    None,
                    None if os.name == "nt" else stat.S_IMODE(metadata.st_mode),
                )
            )
    return tuple(sorted(rows, key=lambda row: row.relative))


def _manifest_digest(records: Iterable[FileRecord]) -> str:
    payload = [row.__dict__ for row in records]
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _sqlite_integrity(root: Path, records: Iterable[FileRecord]) -> list[str]:
    checked: list[str] = []
    for row in records:
        if row.kind not in {"file", "symlink"}:
            continue
        suffixes = Path(row.relative).suffixes
        if not suffixes or suffixes[-1].lower() not in {".db", ".sqlite", ".sqlite3"}:
            continue
        target = root / row.relative
        try:
            connection = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
            result = connection.execute("PRAGMA integrity_check").fetchone()
        except sqlite3.DatabaseError as error:
            raise MigrationError(f"SQLite integrity check failed: {target}: {error}") from error
        finally:
            if "connection" in locals():
                connection.close()
                del connection
        if not result or result[0] != "ok":
            raise MigrationError(f"SQLite integrity check failed: {target}: {result!r}")
        checked.append(row.relative)
    return checked


def _read_quiescence_receipt(path: Path, source: Path) -> dict[str, object]:
    try:
        mode = stat.S_IMODE(path.stat(follow_symlinks=False).st_mode)
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise MigrationError(f"quiescence receipt is unavailable: {error}") from error
    if path.is_symlink() or mode & 0o077:
        raise MigrationError("quiescence receipt must be an owner-only regular file")
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != QUIESCENCE_SCHEMA
        or payload.get("status") != "quiesced"
        or payload.get("source") != str(source)
        or payload.get("active_writers") != 0
        or payload.get("loaded_scheduler_labels") != []
        or not isinstance(payload.get("token"), str)
        or not payload["token"]
    ):
        raise MigrationError("quiescence receipt does not prove a stopped legacy writer set")
    return payload


def plan(source: Path, destination: SuldeLayout) -> dict[str, object]:
    source = _assert_safe_directory(source, must_exist=True)
    root = _assert_safe_directory(destination.root, must_exist=False)
    records = _records(source)
    checked = _sqlite_integrity(source, records)
    conflicts = [
        str(path)
        for path in (
            destination.kb,
            destination.bin,
            destination.control / "current-home.json",
            destination.control / CONTRACT_IDENTITY_FILE,
        )
        if path.exists() or path.is_symlink()
    ]
    return {
        "schema": "sulde-home-migration-plan-v1",
        "source": str(source),
        "destination": str(root),
        "kb_destination": str(destination.kb),
        "file_count": sum(row.kind in {"file", "symlink"} for row in records),
        "directory_count": sum(row.kind == "directory" for row in records),
        "byte_count": sum(row.size for row in records if row.kind == "file"),
        "symlink_count": sum(row.kind == "symlink" for row in records),
        "linked_content_byte_count": sum(
            row.size for row in records if row.kind == "symlink"
        ),
        "manifest_sha256": _manifest_digest(records),
        "sqlite_checked": checked,
        "conflicts": conflicts,
        "ready": not conflicts,
    }


def _copy_tree(
    source: Path,
    destination: Path,
    records: Iterable[FileRecord],
) -> None:
    destination.mkdir(parents=True, mode=0o700)
    rows = tuple(records)
    directories = tuple(
        sorted(
            (row for row in rows if row.kind == "directory"),
            key=lambda row: (len(Path(row.relative).parts), row.relative),
        )
    )
    for row in directories:
        source_directory = source if row.relative == "." else source / row.relative
        target = destination if row.relative == "." else destination / row.relative
        metadata = source_directory.stat(follow_symlinks=False)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or (
                row.mode is not None
                and stat.S_IMODE(metadata.st_mode) != row.mode
            )
        ):
            raise MigrationError(
                f"migration directory changed after planning: {source_directory}"
            )
        target.mkdir(mode=0o700, exist_ok=True)
    for row in rows:
        if row.kind == "directory":
            continue
        source_file = source / row.relative
        target = destination / row.relative
        metadata = source_file.stat(follow_symlinks=False)
        if row.kind == "symlink":
            if (
                not stat.S_ISLNK(metadata.st_mode)
                or os.readlink(source_file) != row.link_target
            ):
                raise MigrationError(
                    f"migration symbolic link changed after planning: {source_file}"
                )
            _validated_symlink_target(source, source_file)
            target.symlink_to(str(row.link_target))
        elif (
            row.kind == "file"
            and stat.S_ISREG(metadata.st_mode)
            and (
                row.mode is None
                or stat.S_IMODE(metadata.st_mode) == row.mode
            )
        ):
            shutil.copy2(source_file, target, follow_symlinks=False)
        else:
            raise MigrationError(f"migration source changed after planning: {source_file}")
    for row in reversed(directories):
        if row.mode is None:
            continue
        target = destination if row.relative == "." else destination / row.relative
        target.chmod(row.mode)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_canonical_json(payload) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, path)
        _fsync_directory(path.parent)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def _contract_identity_payload(
    source: Path,
    destination: SuldeLayout,
    transaction_id: str,
    records: Iterable[FileRecord],
) -> dict[str, object]:
    identities: dict[str, str] = {}
    for row in records:
        relative = Path(row.relative)
        if not (
            row.kind == "file"
            and len(relative.parts) == 3
            and relative.parts[:2] == ("intent", "workspaces")
            and relative.name.endswith(".active.json")
        ):
            continue
        legacy_path = source / relative
        identities[row.relative] = hashlib.sha256(
            str(legacy_path).encode("utf-8", errors="replace")
        ).hexdigest()
    return {
        "schema": CONTRACT_IDENTITY_SCHEMA,
        "transaction_id": transaction_id,
        "source": str(source),
        "kb_home": str(destination.kb),
        "identities": dict(sorted(identities.items())),
    }


def _protected_json_object(path: Path, label: str) -> dict[str, object]:
    try:
        metadata = path.stat(follow_symlinks=False)
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise MigrationError(f"{label} is unavailable: {error}") from error
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or (
            os.name != "nt"
            and (
                metadata.st_uid != os.getuid()
                or stat.S_IMODE(metadata.st_mode) & 0o077
            )
        )
        or not isinstance(payload, dict)
    ):
        raise MigrationError(f"{label} is not an owner-only JSON file")
    return payload


def ensure_contract_identity_map(destination: SuldeLayout) -> dict[str, object] | None:
    """Seal legacy contract identities for an active byte-preserving move.

    Older V1 pointers did not include this map.  They can be upgraded only
    while the identity-bearing intent tree still exactly matches the retained
    source.  Unrelated runtime state is expected to evolve after activation.
    """
    pointer_path = destination.control / "current-home.json"
    if not pointer_path.exists() and not pointer_path.is_symlink():
        return None
    pointer = _protected_json_object(pointer_path, "current home pointer")
    source = _assert_safe_directory(
        Path(str(pointer.get("source") or "")), must_exist=True
    )
    transaction_id = str(pointer.get("transaction_id") or "")
    if (
        pointer.get("schema") != POINTER_SCHEMA
        or pointer.get("status") != "active"
        or pointer.get("sulde_home") != str(destination.root)
        or pointer.get("kb_home") != str(destination.kb)
        or not transaction_id
    ):
        raise MigrationError("current home pointer does not bind this migration")
    identity_path = destination.control / CONTRACT_IDENTITY_FILE
    expected_sha256 = pointer.get("contract_identity_map_sha256")
    if isinstance(expected_sha256, str) and re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        identity = _protected_json_object(identity_path, "contract identity map")
        actual_sha256 = hashlib.sha256(identity_path.read_bytes()).hexdigest()
        if (
            actual_sha256 != expected_sha256
            or identity.get("schema") != CONTRACT_IDENTITY_SCHEMA
            or identity.get("transaction_id") != transaction_id
            or identity.get("source") != str(source)
            or identity.get("kb_home") != str(destination.kb)
        ):
            raise MigrationError("contract identity map differs from active migration")
        return pointer

    source_intent_records = _records(source / "intent")
    migrated_intent_records = _records(destination.kb / "intent")
    if source_intent_records != migrated_intent_records:
        raise MigrationError(
            "cannot upgrade contract identities after identity-bearing state changed"
        )
    source_records = _records(source)
    identity_payload = _contract_identity_payload(
        source, destination, transaction_id, source_records
    )
    _atomic_json(identity_path, identity_payload)
    updated = {
        **pointer,
        "contract_identity_map_sha256": hashlib.sha256(
            identity_path.read_bytes()
        ).hexdigest(),
    }
    _atomic_json(pointer_path, updated)
    if _protected_json_object(pointer_path, "current home pointer") != updated:
        raise MigrationError("upgraded current home pointer did not read back exactly")
    return updated


def apply(source: Path, destination: SuldeLayout, receipt: Path) -> dict[str, object]:
    migration_plan = plan(source, destination)
    if not migration_plan["ready"]:
        raise MigrationError(f"migration destination conflicts: {migration_plan['conflicts']}")
    source = Path(str(migration_plan["source"]))
    quiescence = _read_quiescence_receipt(receipt, source)
    source_records = _records(source)
    if _manifest_digest(source_records) != migration_plan["manifest_sha256"]:
        raise MigrationError("quiesced source changed after migration planning")
    root = destination.root
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    for directory in (
        destination.control,
        destination.state,
        destination.data,
        destination.cache,
        destination.logs,
        destination.venv,
        destination.artifacts,
    ):
        if directory.is_symlink():
            raise MigrationError(f"symbolic-link destination is not allowed: {directory}")
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)

    lock = destination.control / "home-migration.lock"
    try:
        lock.mkdir(mode=0o700)
    except FileExistsError as error:
        raise MigrationError(f"another home migration owns {lock}") from error
    transaction_id = uuid.uuid4().hex
    stage = destination.control / f".home-migration-{transaction_id}"
    kb_activated = False
    bin_activated = False
    pointer = destination.control / "current-home.json"
    identity_path = destination.control / CONTRACT_IDENTITY_FILE
    identity_activated = False
    try:
        stage.mkdir(mode=0o700)
        staged_kb = stage / "kb"
        staged_bin = stage / "bin"
        _copy_tree(source, staged_kb, source_records)
        staged_bin.mkdir(mode=0o700)
        legacy_bin = source / "bin"
        if legacy_bin.is_dir() and not legacy_bin.is_symlink():
            for name in sorted(PUBLIC_LAUNCHERS):
                candidate = legacy_bin / name
                if candidate.is_file() and not candidate.is_symlink():
                    shutil.copy2(candidate, staged_bin / name, follow_symlinks=False)
        staged_records = _records(staged_kb)
        if _manifest_digest(staged_records) != migration_plan["manifest_sha256"]:
            raise MigrationError("staged KB manifest differs from the quiesced source")
        if _manifest_digest(_records(source)) != migration_plan["manifest_sha256"]:
            raise MigrationError("quiesced source changed during migration copying")
        _sqlite_integrity(staged_kb, staged_records)
        _fsync_directory(staged_kb)
        _fsync_directory(staged_bin)

        destination.kb.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staged_kb, destination.kb)
        kb_activated = True
        _fsync_directory(destination.kb.parent)
        os.replace(staged_bin, destination.bin)
        bin_activated = True
        _fsync_directory(destination.bin.parent)
        identity_payload = _contract_identity_payload(
            source, destination, transaction_id, source_records
        )
        _atomic_json(identity_path, identity_payload)
        identity_activated = True
        pointer_payload = {
            "schema": POINTER_SCHEMA,
            "status": "active",
            "transaction_id": transaction_id,
            "source": str(source),
            "sulde_home": str(root),
            "kb_home": str(destination.kb),
            "manifest_sha256": migration_plan["manifest_sha256"],
            "contract_identity_map_sha256": hashlib.sha256(
                identity_path.read_bytes()
            ).hexdigest(),
            "quiescence_token_sha256": hashlib.sha256(
                str(quiescence["token"]).encode("utf-8")
            ).hexdigest(),
        }
        _atomic_json(pointer, pointer_payload)
        if json.loads(pointer.read_text(encoding="utf-8")) != pointer_payload:
            raise MigrationError("activated home pointer did not read back exactly")
        return {**migration_plan, **pointer_payload, "ready": True}
    except Exception:
        # Roll back only directories activated by this exact transaction.
        if bin_activated and destination.bin.is_dir() and not destination.bin.is_symlink():
            os.replace(destination.bin, stage / "bin")
        if kb_activated and destination.kb.is_dir() and not destination.kb.is_symlink():
            os.replace(destination.kb, stage / "kb")
        if pointer.is_file():
            try:
                active = json.loads(pointer.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                active = {}
            if active.get("transaction_id") == transaction_id:
                pointer.unlink()
        if identity_activated and identity_path.is_file():
            try:
                identity = json.loads(identity_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                identity = {}
            if identity.get("transaction_id") == transaction_id:
                identity_path.unlink()
        raise
    finally:
        if stage.is_dir() and not stage.is_symlink():
            shutil.rmtree(stage)
        try:
            lock.rmdir()
        except OSError:
            pass


def rollback(
    activation: dict[str, object],
    destination: SuldeLayout,
    *,
    allow_quiesced_managed_drift: bool = False,
) -> None:
    """Remove only an exact activated migration while the legacy source remains."""
    transaction_id = str(activation.get("transaction_id") or "")
    expected_manifest = str(activation.get("manifest_sha256") or "")
    pointer = destination.control / "current-home.json"
    identity_path = destination.control / CONTRACT_IDENTITY_FILE
    try:
        active = json.loads(pointer.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise MigrationError(f"cannot verify migration rollback pointer: {error}") from error
    if (
        active.get("transaction_id") != transaction_id
        or active.get("manifest_sha256") != expected_manifest
        or active.get("kb_home") != str(destination.kb)
    ):
        raise MigrationError("migration rollback authority differs from active pointer")
    try:
        identity = _protected_json_object(identity_path, "contract identity map")
        identity_sha256 = hashlib.sha256(identity_path.read_bytes()).hexdigest()
    except MigrationError:
        raise
    if (
        identity_sha256 != active.get("contract_identity_map_sha256")
        or identity.get("transaction_id") != transaction_id
    ):
        raise MigrationError("migration rollback contract identity differs from pointer")
    if (
        not allow_quiesced_managed_drift
        and _manifest_digest(_records(destination.kb)) != expected_manifest
    ):
        raise MigrationError("migration rollback refused because activated KB changed")
    pointer.unlink()
    identity_path.unlink()
    if destination.kb.is_dir() and not destination.kb.is_symlink():
        shutil.rmtree(destination.kb)
    if destination.bin.is_dir() and not destination.bin.is_symlink():
        shutil.rmtree(destination.bin)
    _fsync_directory(destination.control)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "apply"))
    parser.add_argument(
        "--source",
        type=Path,
        default=Path.home() / ".claude" / "plugins" / "data" / "sulde-cc" / "kb",
    )
    parser.add_argument("--sulde-home", type=Path)
    parser.add_argument("--quiescence-receipt", type=Path)
    args = parser.parse_args()
    destination = layout(home=args.sulde_home) if args.sulde_home else layout()
    try:
        if args.command == "plan":
            result = plan(args.source, destination)
        else:
            if args.quiescence_receipt is None:
                raise MigrationError("apply requires --quiescence-receipt")
            result = apply(args.source, destination, args.quiescence_receipt)
    except MigrationError as error:
        print(json.dumps({"ready": False, "error": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
