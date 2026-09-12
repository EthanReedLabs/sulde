#!/usr/bin/env python3
"""Run the repository test suite without inheriting production Sulde state.

This is the supported entrypoint for local and CI test execution.  It gives the
child interpreter a disposable user/config/KB environment, rejects child writes
to the real per-user KB, and separately verifies signed concurrent host appends.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from typing import Iterable

# This entrypoint imports sibling runtime modules before it creates the child
# environment.  Disable bytecode in the current interpreter first so invoking
# the official test runner can never make the source tree fail its own release
# inventory gate.
sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

_KB_MODULE_DIRECTORY = str(Path(__file__).resolve().parent)
if _KB_MODULE_DIRECTORY not in sys.path:
    sys.path.insert(0, _KB_MODULE_DIRECTORY)

from audit_cursor import (
    AuditCursor,
    AuditCursorError,
    cursor_digest,
    load_cursor,
    save_cursor,
    scan_increment,
    with_projection,
)
from sulde_paths import kb_home as neutral_kb_home


ROOT = Path(__file__).resolve().parents[2]

_HOST_IDENTITY_VARIABLES = {
    "CLAUDECODE",
    "CLAUDE_CODE_ENTRYPOINT",
    "CLAUDE_SESSION_ID",
    "CODEX_CI",
    "CODEX_THREAD_ID",
}
_SECRET_NAME_PARTS = ("API_KEY", "PASSWORD", "SECRET", "TOKEN")
_OBSERVATION_LOG_NAME = "host-capabilities.jsonl"
_PROCESS_GUARD_MODULE = "sitecustomize.py"
_PROCESS_GUARD_LOG = "production-write-attempts.jsonl"
_MAX_CONCURRENT_OBSERVATION_APPEND_BYTES = 1024 * 1024
_OBSERVATION_BASELINE_TAIL_BYTES = 4 * 1024 * 1024
_AUDIT_CURSOR_BOOTSTRAP_BYTES = 64 * 1024 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_HEX_32_RE = re.compile(r"^[0-9a-f]{32}$")

_PROCESS_GUARD_SOURCE = r'''"""Injected by run-isolated-tests.py; not an authority boundary."""
import json
import os
import sys

_ROOT_VALUE = os.environ.get("SULDE_ISOLATED_TEST_PRODUCTION_ROOT", "")
_LOG = os.environ.get("SULDE_ISOLATED_TEST_VIOLATION_LOG", "")
_RUN_ID = os.environ.get("SULDE_ISOLATED_TEST_RUN_ID", "")
_ENABLED = bool(_ROOT_VALUE and _LOG and _RUN_ID)
_ROOT = os.path.normcase(os.path.realpath(_ROOT_VALUE)) if _ENABLED else ""
_RECORDING = False


def _resolved(value):
    if not isinstance(value, (str, bytes, os.PathLike)):
        return ""
    try:
        return os.path.normcase(os.path.realpath(os.path.abspath(os.fsdecode(value))))
    except (OSError, TypeError, ValueError):
        return ""


def _inside_production(value):
    candidate = _resolved(value)
    if not candidate:
        return False
    try:
        return os.path.commonpath((_ROOT, candidate)) == _ROOT
    except (OSError, ValueError):
        return False


def _deny(event, value):
    global _RECORDING
    if _RECORDING:
        raise PermissionError("isolated test production write denied")
    _RECORDING = True
    try:
        row = {
            "event": event,
            "path": _resolved(value),
            "pid": os.getpid(),
            "run_id": _RUN_ID,
        }
        flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        descriptor = os.open(_LOG, flags, 0o600)
        try:
            os.write(
                descriptor,
                (json.dumps(row, sort_keys=True) + "\n").encode("utf-8"),
            )
        finally:
            os.close(descriptor)
    finally:
        _RECORDING = False
    raise PermissionError("isolated test production write denied")


def _audit(event, arguments):
    targets = ()
    if event == "open" and arguments:
        mode = arguments[1] if len(arguments) > 1 else None
        flags = arguments[2] if len(arguments) > 2 else 0
        writes = (
            isinstance(mode, str) and any(marker in mode for marker in "wax+")
        ) or (
            isinstance(flags, int)
            and bool(
                flags
                & (
                    os.O_WRONLY
                    | os.O_RDWR
                    | os.O_APPEND
                    | os.O_CREAT
                    | os.O_TRUNC
                )
            )
        )
        if writes:
            targets = (arguments[0],)
    elif event in {
        "os.remove",
        "os.rmdir",
        "os.mkdir",
        "os.chmod",
        "os.chown",
        "os.utime",
        "os.truncate",
        "os.setxattr",
        "os.removexattr",
        "sqlite3.connect",
    } and arguments:
        targets = (arguments[0],)
    elif event in {"os.rename", "os.link"} and len(arguments) >= 2:
        targets = (arguments[0], arguments[1])
    elif event == "os.symlink" and len(arguments) >= 2:
        targets = (arguments[1],)
    for target in targets:
        if _inside_production(target):
            _deny(event, target)


if _ENABLED:
    sys.addaudithook(_audit)
'''


def _is_sensitive_environment_name(name: str) -> bool:
    upper = name.upper()
    return any(part in upper for part in _SECRET_NAME_PARTS) or upper.endswith("_KEY")


def filesystem_snapshot(root: Path) -> tuple[tuple[object, ...], ...]:
    """Return a cheap mutation sentinel without reading secret-bearing content."""
    if not root.exists():
        return ()
    rows: list[tuple[object, ...]] = []
    pending = [root]
    while pending:
        current = pending.pop()
        try:
            entries = sorted(current.iterdir(), key=lambda item: item.name)
        except OSError as error:
            rows.append((str(current.relative_to(root)), "unreadable", type(error).__name__))
            continue
        for entry in entries:
            try:
                metadata = entry.lstat()
            except OSError as error:
                rows.append((str(entry.relative_to(root)), "unreadable", type(error).__name__))
                continue
            relative = str(entry.relative_to(root))
            if entry.is_symlink():
                try:
                    target = os.readlink(entry)
                except OSError:
                    target = "<unreadable>"
                rows.append((relative, "symlink", target, metadata.st_mtime_ns))
            elif entry.is_dir():
                rows.append((relative, "directory", metadata.st_mode, metadata.st_mtime_ns))
                pending.append(entry)
            else:
                rows.append(
                    (
                        relative,
                        "file",
                        metadata.st_mode,
                        metadata.st_size,
                        metadata.st_mtime_ns,
                        metadata.st_ino,
                    )
                )
    return tuple(sorted(rows))


def isolated_environment(
    temporary_root: Path,
    *,
    production_kb: Path,
    inherited: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build the narrow environment shared by every supported test invocation."""
    environment = {
        name: value
        for name, value in dict(inherited or os.environ).items()
        if not name.startswith("SULDE_")
        and name not in _HOST_IDENTITY_VARIABLES
        and not _is_sensitive_environment_name(name)
    }
    fake_home = temporary_root / "home"
    codex_home = temporary_root / "codex-home"
    claude_home = temporary_root / "claude-home"
    kb_home = temporary_root / "kb-home"
    temporary_files = temporary_root / "tmp"
    xdg_config = temporary_root / "xdg-config"
    xdg_cache = temporary_root / "xdg-cache"
    xdg_data = temporary_root / "xdg-data"
    process_guard = temporary_root / "process-guard"
    pycache = temporary_root / "pycache"
    for path in (
        fake_home,
        codex_home,
        claude_home,
        kb_home,
        temporary_files,
        xdg_config,
        xdg_cache,
        xdg_data,
        process_guard,
        pycache,
    ):
        path.mkdir(parents=True, exist_ok=True)
    guard_module = process_guard / _PROCESS_GUARD_MODULE
    guard_module.write_text(_PROCESS_GUARD_SOURCE, encoding="utf-8")
    guard_log = process_guard / _PROCESS_GUARD_LOG
    guard_log.touch(mode=0o600)
    inherited_python_path = environment.get("PYTHONPATH", "")
    guarded_python_path = str(process_guard)
    if inherited_python_path:
        guarded_python_path += os.pathsep + inherited_python_path
    environment.update(
        {
            "HOME": str(fake_home),
            "USERPROFILE": str(fake_home),
            "CODEX_HOME": str(codex_home),
            "CLAUDE_CONFIG_DIR": str(claude_home),
            "XDG_CONFIG_HOME": str(xdg_config),
            "XDG_CACHE_HOME": str(xdg_cache),
            "XDG_DATA_HOME": str(xdg_data),
            "TMPDIR": str(temporary_files),
            "TMP": str(temporary_files),
            "TEMP": str(temporary_files),
            "SULDE_KB_HOME": str(kb_home),
            "SULDE_HOME": str(temporary_root / "sulde-home"),
            "SULDE_PRODUCTION_KB_HOME": str(production_kb),
            "SULDE_TEST_MODE": "1",
            "SULDE_HOOK_OBSERVATION_SOURCE": "synthetic_smoke",
            "SULDE_ISOLATED_TEST_PRODUCTION_ROOT": str(production_kb),
            "SULDE_ISOLATED_TEST_RUN_ID": secrets.token_hex(16),
            "SULDE_ISOLATED_TEST_VIOLATION_LOG": str(guard_log),
            "SULDE_NOTIFY": "off",
            "PYTHONPATH": guarded_python_path,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPYCACHEPREFIX": str(pycache),
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        }
    )
    return environment


def process_guard_violations(environment: dict[str, str]) -> list[dict[str, object]]:
    """Read child-attributed write attempts without trusting child exit status."""
    path = Path(environment["SULDE_ISOLATED_TEST_VIOLATION_LOG"])
    try:
        payload = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        return [{"event": "guard-log-unreadable", "error": type(error).__name__}]
    violations: list[dict[str, object]] = []
    for line in payload.splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            row = {"event": "guard-log-invalid"}
        if not isinstance(row, dict):
            row = {"event": "guard-log-invalid"}
        violations.append(row)
    return violations


def _empty_log_projection() -> dict[str, object]:
    return {
        "event_ids": [],
        "nonces": [],
        "legacy_identities": [],
        "guardian_lanes": [],
        "guardian_row_hashes": [],
        "guardian_last_sequence": None,
        "guardian_inflight": [],
    }


def _project_log_rows(
    projection: dict[str, object],
    raw_rows: Iterable[bytes],
) -> dict[str, object]:
    """Update the bounded attribution projection stored in an audit cursor."""
    event_ids = set(str(item) for item in projection.get("event_ids", []))
    nonces = set(str(item) for item in projection.get("nonces", []))
    legacy_identities = {
        tuple(str(part) for part in item)
        for item in projection.get("legacy_identities", [])
        if isinstance(item, list) and len(item) == 5
    }
    guardian_lanes = {
        tuple(str(part) for part in item.get("key", [])): str(item.get("at") or "")
        for item in projection.get("guardian_lanes", [])
        if isinstance(item, dict) and len(item.get("key", [])) == 3
    }
    guardian_row_hashes = set(
        str(item) for item in projection.get("guardian_row_hashes", [])
    )
    guardian_last_sequence = projection.get("guardian_last_sequence")
    guardian_inflight = {
        tuple(str(part) for part in item.get("key", [])): dict(item.get("event", {}))
        for item in projection.get("guardian_inflight", [])
        if isinstance(item, dict)
        and len(item.get("key", [])) == 3
        and isinstance(item.get("event"), dict)
    }
    for raw_line in raw_rows:
        try:
            row = json.loads(raw_line.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(row, dict):
            continue
        event_id = row.get("event_id")
        if isinstance(event_id, str):
            event_ids.add(event_id)
        proof = row.get("provenance")
        nonce = proof.get("nonce") if isinstance(proof, dict) else None
        if isinstance(nonce, str):
            nonces.add(nonce)
        unsigned_row = dict(row)
        stored_event_id = str(unsigned_row.pop("event_id", ""))
        expected_event_id = hashlib.sha256(
            json.dumps(
                unsigned_row,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if (
            row.get("schema") == "sulde-host-capability-observation-v1"
            and row.get("provider") in {"claude", "codex"}
            and row.get("source") == "live_host_hook"
            and row.get("outcome") == "observed"
            and _SHA256_RE.fullmatch(str(row.get("runtime_sha256") or ""))
            is not None
            and stored_event_id == expected_event_id
            and not isinstance(proof, dict)
        ):
            legacy_identities.add(
                (
                    str(row.get("provider") or ""),
                    str(row.get("runtime_sha256") or ""),
                    str(row.get("session_id") or ""),
                    str(row.get("workspace_id") or ""),
                    str(row.get("source") or ""),
                )
            )
        event = row.get("event")
        if row.get("schema") == "sulde-guardian-event-v1" and isinstance(event, dict):
            guardian_row_hashes.add(hashlib.sha256(raw_line).hexdigest())
            observed_at = _parse_utc(event.get("at"))
            lane = (
                str(event.get("provider") or ""),
                str(event.get("session_id") or ""),
                str(event.get("runtime_generation") or ""),
            )
            if observed_at is not None and all(lane):
                rendered = observed_at.isoformat()
                previous = _parse_utc(guardian_lanes.get(lane))
                if previous is None or observed_at > previous:
                    guardian_lanes[lane] = rendered
            sequence = event.get("sequence")
            if isinstance(sequence, int) and not isinstance(sequence, bool):
                guardian_last_sequence = sequence
            call_id = str(event.get("call_id") or "")
            call_key = (lane[0], lane[1], call_id)
            if call_id and event.get("phase") == "started":
                guardian_inflight[call_key] = dict(event)
            elif call_id and event.get("phase") == "completed":
                guardian_inflight.pop(call_key, None)
    # The current-run time window already prevents replay of unbounded ancient
    # rows.  Keep a bounded tail so cursor size remains independent of log age.
    return {
        "event_ids": sorted(event_ids)[-4096:],
        "nonces": sorted(nonces)[-4096:],
        "legacy_identities": [list(item) for item in sorted(legacy_identities)[-512:]],
        "guardian_lanes": [
            {"key": list(key), "at": value}
            for key, value in sorted(guardian_lanes.items())[-512:]
        ],
        "guardian_row_hashes": sorted(guardian_row_hashes)[-4096:],
        "guardian_last_sequence": guardian_last_sequence,
        "guardian_inflight": [
            {"key": list(key), "event": value}
            for key, value in sorted(guardian_inflight.items())[-512:]
        ],
    }


def _cursor_baseline_fields(cursor: AuditCursor) -> dict[str, object]:
    projection = cursor.projection
    return {
        "inode": cursor.log_inode,
        "size": cursor.offset,
        "digest": cursor.chain_sha256,
        "ends_newline": True,
        "event_ids": frozenset(projection.get("event_ids", [])),
        "nonces": frozenset(projection.get("nonces", [])),
        "legacy_identities": frozenset(
            tuple(item) for item in projection.get("legacy_identities", [])
        ),
        "guardian_lanes": {
            tuple(item["key"]): _parse_utc(item["at"])
            for item in projection.get("guardian_lanes", [])
            if isinstance(item, dict)
        },
        "guardian_row_hashes": frozenset(
            projection.get("guardian_row_hashes", [])
        ),
        "guardian_last_sequence": projection.get("guardian_last_sequence"),
        "guardian_inflight": {
            tuple(item["key"]): dict(item["event"])
            for item in projection.get("guardian_inflight", [])
            if isinstance(item, dict)
        },
    }


def _append_log_baseline(
    path: Path,
    *,
    cursor_path: Path | None = None,
    runtime_generation: str = "isolated-test-audit-v1",
) -> dict[str, object]:
    """Capture an append baseline, using a persistent warm cursor when supplied."""
    if not path.exists():
        if cursor_path is not None and os.path.lexists(cursor_path):
            return {"exists": False, "valid": False, "reason": "log missing with live cursor"}
        return {
            "exists": False,
            "valid": not os.path.lexists(path),
            "event_ids": frozenset(),
            "nonces": frozenset(),
            "guardian_lanes": {},
            "guardian_row_hashes": frozenset(),
            "guardian_last_sequence": None,
            "guardian_inflight": {},
        }
    if cursor_path is not None:
        try:
            prior = load_cursor(cursor_path) if os.path.lexists(cursor_path) else None
            expected_digest = cursor_digest(prior) if prior is not None else None
            read = scan_increment(
                path,
                runtime_generation=runtime_generation,
                cursor=prior,
                max_bytes=_AUDIT_CURSOR_BOOTSTRAP_BYTES,
                enforce_event_generation=False,
            )
            projection = _project_log_rows(
                prior.projection if prior is not None else _empty_log_projection(),
                read.raw_rows,
            )
            checkpoint = with_projection(read.cursor, projection)
            saved_digest = save_cursor(
                cursor_path,
                checkpoint,
                expected_digest=expected_digest,
            )
            metadata = path.stat()
            return {
                "exists": True,
                "valid": True,
                "mode": stat.S_IMODE(metadata.st_mode),
                "uid": getattr(metadata, "st_uid", None),
                "mtime_ns": metadata.st_mtime_ns,
                "cursor": checkpoint,
                "cursor_path": cursor_path,
                "cursor_digest": saved_digest,
                "runtime_generation": runtime_generation,
                "catchup_bytes": read.bytes_read,
                **_cursor_baseline_fields(checkpoint),
            }
        except (AuditCursorError, OSError) as error:
            return {
                "exists": True,
                "valid": False,
                "reason": f"cursor:{type(error).__name__}:{error}",
            }
    for _attempt in range(4):
        descriptor = -1
        try:
            metadata = path.lstat()
            if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
                return {"exists": True, "valid": False, "reason": "not a regular file"}
            flags = os.O_RDONLY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(path, flags)
            opened = os.fstat(descriptor)
            digest = hashlib.sha256()
            tail = bytearray()
            last_byte = b""
            remaining = opened.st_size
            while remaining:
                chunk = os.read(descriptor, min(1024 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                digest.update(chunk)
                last_byte = chunk[-1:]
                tail.extend(chunk)
                if len(tail) > _OBSERVATION_BASELINE_TAIL_BYTES:
                    del tail[: len(tail) - _OBSERVATION_BASELINE_TAIL_BYTES]
            closed = os.fstat(descriptor)
            if (
                remaining
                or opened.st_ino != closed.st_ino
                or opened.st_size != closed.st_size
                or opened.st_mtime_ns != closed.st_mtime_ns
            ):
                time.sleep(0.005)
                continue
            tail_payload = bytes(tail)
            if opened.st_size > len(tail_payload):
                separator = tail_payload.find(b"\n")
                tail_payload = tail_payload[separator + 1 :] if separator >= 0 else b""
            event_ids: set[str] = set()
            nonces: set[str] = set()
            legacy_identities: set[tuple[str, str, str, str, str]] = set()
            guardian_lanes: dict[tuple[str, str, str], datetime] = {}
            guardian_row_hashes: set[str] = set()
            guardian_last_sequence: int | None = None
            guardian_inflight: dict[tuple[str, str, str], dict[str, object]] = {}
            for raw_line in tail_payload.splitlines():
                try:
                    row = json.loads(raw_line.decode("utf-8"))
                except (UnicodeError, json.JSONDecodeError):
                    continue
                if not isinstance(row, dict):
                    continue
                event_id = row.get("event_id")
                if isinstance(event_id, str):
                    event_ids.add(event_id)
                proof = row.get("provenance")
                nonce = proof.get("nonce") if isinstance(proof, dict) else None
                if isinstance(nonce, str):
                    nonces.add(nonce)
                unsigned_row = dict(row)
                stored_event_id = str(unsigned_row.pop("event_id", ""))
                expected_event_id = hashlib.sha256(
                    json.dumps(
                        unsigned_row,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
                if (
                    row.get("schema") == "sulde-host-capability-observation-v1"
                    and row.get("provider") in {"claude", "codex"}
                    and row.get("source") == "live_host_hook"
                    and row.get("outcome") == "observed"
                    and _SHA256_RE.fullmatch(str(row.get("runtime_sha256") or ""))
                    is not None
                    and stored_event_id == expected_event_id
                    and not isinstance(proof, dict)
                ):
                    legacy_identities.add(
                        (
                            str(row.get("provider") or ""),
                            str(row.get("runtime_sha256") or ""),
                            str(row.get("session_id") or ""),
                            str(row.get("workspace_id") or ""),
                            str(row.get("source") or ""),
                        )
                    )
                event = row.get("event")
                if (
                    row.get("schema") == "sulde-guardian-event-v1"
                    and isinstance(event, dict)
                ):
                    guardian_row_hashes.add(hashlib.sha256(raw_line).hexdigest())
                    observed_at = _parse_utc(event.get("at"))
                    lane = (
                        str(event.get("provider") or ""),
                        str(event.get("session_id") or ""),
                        str(event.get("runtime_generation") or ""),
                    )
                    if observed_at is not None and all(lane):
                        previous = guardian_lanes.get(lane)
                        if previous is None or observed_at > previous:
                            guardian_lanes[lane] = observed_at
                    sequence = event.get("sequence")
                    if isinstance(sequence, int) and not isinstance(sequence, bool):
                        guardian_last_sequence = sequence
                    call_id = str(event.get("call_id") or "")
                    call_key = (lane[0], lane[1], call_id)
                    if call_id and event.get("phase") == "started":
                        guardian_inflight[call_key] = dict(event)
                    elif call_id and event.get("phase") == "completed":
                        guardian_inflight.pop(call_key, None)
            return {
                "exists": True,
                "valid": True,
                "inode": opened.st_ino,
                "mode": stat.S_IMODE(opened.st_mode),
                "uid": getattr(opened, "st_uid", None),
                "size": opened.st_size,
                "mtime_ns": opened.st_mtime_ns,
                "digest": digest.hexdigest(),
                "ends_newline": opened.st_size == 0 or last_byte == b"\n",
                "event_ids": frozenset(event_ids),
                "nonces": frozenset(nonces),
                "legacy_identities": frozenset(legacy_identities),
                "guardian_lanes": guardian_lanes,
                "guardian_row_hashes": frozenset(guardian_row_hashes),
                "guardian_last_sequence": guardian_last_sequence,
                "guardian_inflight": guardian_inflight,
            }
        except OSError as error:
            return {
                "exists": True,
                "valid": False,
                "reason": type(error).__name__,
            }
        finally:
            if descriptor >= 0:
                os.close(descriptor)
    return {"exists": True, "valid": False, "reason": "unstable during snapshot"}


def _audit_cursor_path(cursor_home: Path, log_path: Path) -> Path:
    identity = hashlib.sha256(str(log_path).encode("utf-8")).hexdigest()
    return cursor_home / f"{identity}.cursor.json"


def _observation_baseline(
    root: Path,
    *,
    cursor_home: Path | None = None,
) -> dict[str, object]:
    log = root / _OBSERVATION_LOG_NAME
    return _append_log_baseline(
        log,
        cursor_path=_audit_cursor_path(cursor_home, log) if cursor_home else None,
        runtime_generation="host-capability-observation-v1",
    )


def _read_appended_log(
    path: Path,
    baseline: dict[str, object],
    *,
    label: str,
    max_append_bytes: int = _MAX_CONCURRENT_OBSERVATION_APPEND_BYTES,
) -> tuple[bytes | None, str]:
    if not baseline.get("valid"):
        return None, f"{label} baseline was not trustworthy"
    checkpoint = baseline.get("cursor")
    if isinstance(checkpoint, AuditCursor):
        try:
            read = scan_increment(
                path,
                runtime_generation=str(baseline.get("runtime_generation") or ""),
                cursor=checkpoint,
                max_bytes=max_append_bytes,
                enforce_event_generation=False,
            )
            projection = _project_log_rows(checkpoint.projection, read.raw_rows)
            baseline["candidate_cursor"] = with_projection(read.cursor, projection)
            if not read.raw_rows:
                return b"", ""
            return b"\n".join(read.raw_rows) + b"\n", ""
        except AuditCursorError as error:
            return None, f"{label} cursor validation failed: {error}"
    if not path.exists() or path.is_symlink():
        if baseline.get("exists"):
            return None, f"{label} was removed or replaced"
        if os.path.lexists(path):
            return None, f"new {label} is not a regular file"
        return b"", ""
    for _attempt in range(4):
        descriptor = -1
        try:
            flags = os.O_RDONLY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(path, flags)
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode):
                return None, f"{label} is not a regular file"
            old_size = int(baseline.get("size") or 0)
            if baseline.get("exists"):
                if opened.st_ino != baseline.get("inode"):
                    return None, f"{label} inode changed"
                if stat.S_IMODE(opened.st_mode) != baseline.get("mode"):
                    return None, f"{label} mode changed"
                if getattr(opened, "st_uid", None) != baseline.get("uid"):
                    return None, f"{label} owner changed"
            elif stat.S_IMODE(opened.st_mode) & 0o077:
                return None, f"new {label} is not private"
            if opened.st_size < old_size:
                return None, f"{label} was truncated"
            digest = hashlib.sha256()
            remaining = old_size
            while remaining:
                chunk = os.read(descriptor, min(1024 * 1024, remaining))
                if not chunk:
                    return None, f"{label} prefix became unreadable"
                remaining -= len(chunk)
                digest.update(chunk)
            if old_size and digest.hexdigest() != baseline.get("digest"):
                return None, f"{label} prefix was rewritten"
            append_size = opened.st_size - old_size
            if append_size > max_append_bytes:
                return None, f"{label} append exceeded the bounded review window"
            appended = bytearray()
            remaining = append_size
            while remaining:
                chunk = os.read(descriptor, remaining)
                if not chunk:
                    return None, f"{label} append became unreadable"
                remaining -= len(chunk)
                appended.extend(chunk)
            closed = os.fstat(descriptor)
            if (
                opened.st_ino != closed.st_ino
                or opened.st_size != closed.st_size
                or opened.st_mtime_ns != closed.st_mtime_ns
            ):
                time.sleep(0.005)
                continue
            if not appended and baseline.get("exists"):
                if opened.st_mtime_ns != baseline.get("mtime_ns"):
                    return None, f"{label} metadata changed without an append"
                return b"", ""
            if old_size and not baseline.get("ends_newline"):
                return None, f"{label} append continued an incomplete baseline row"
            if appended and not appended.endswith(b"\n"):
                return None, f"{label} append ended with an incomplete row"
            return bytes(appended), ""
        except OSError as error:
            return None, f"{label} read failed: {type(error).__name__}"
        finally:
            if descriptor >= 0:
                os.close(descriptor)
    return None, f"{label} remained unstable during attribution"


def _commit_baseline_cursor(baseline: dict[str, object]) -> None:
    candidate = baseline.get("candidate_cursor")
    path = baseline.get("cursor_path")
    expected = baseline.get("cursor_digest")
    if not isinstance(candidate, AuditCursor) or not isinstance(path, Path):
        return
    if not isinstance(expected, str):
        raise AuditCursorError("baseline cursor lost its CAS digest")
    baseline["cursor_digest"] = save_cursor(
        path,
        candidate,
        expected_digest=expected,
    )
    baseline["cursor"] = candidate


def _read_appended_observations(
    root: Path,
    baseline: dict[str, object],
) -> tuple[bytes | None, str]:
    return _read_appended_log(
        root / _OBSERVATION_LOG_NAME,
        baseline,
        label="host capability log",
    )


_HOST_CAPABILITIES_MODULE = None
_INTENT_GUARDIAN_MODULE = None


def _host_capabilities_module():
    global _HOST_CAPABILITIES_MODULE
    if _HOST_CAPABILITIES_MODULE is not None:
        return _HOST_CAPABILITIES_MODULE
    path = Path(__file__).resolve().with_name("host_capabilities.py")
    name = "_sulde_isolated_runner_host_capabilities"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load host capability verifier")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    _HOST_CAPABILITIES_MODULE = module
    return module


def _intent_guardian_module():
    global _INTENT_GUARDIAN_MODULE
    if _INTENT_GUARDIAN_MODULE is not None:
        return _INTENT_GUARDIAN_MODULE
    directory = str(Path(__file__).resolve().parent)
    inserted = directory not in sys.path
    if inserted:
        sys.path.insert(0, directory)
    try:
        path = Path(directory) / "intent_guardian.py"
        name = "_sulde_isolated_runner_intent_guardian"
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise RuntimeError("cannot load intent guardian verifier")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    finally:
        if inserted:
            sys.path.remove(directory)
    _INTENT_GUARDIAN_MODULE = module
    return module


def _parse_utc(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _stable_json_file(path: Path, *, max_bytes: int = 8 * 1024 * 1024) -> dict[str, object]:
    if not path.exists():
        return {"exists": False, "valid": not os.path.lexists(path)}
    for _attempt in range(4):
        descriptor = -1
        try:
            metadata = path.lstat()
            if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
                return {"exists": True, "valid": False, "reason": "not a regular file"}
            flags = os.O_RDONLY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(path, flags)
            opened = os.fstat(descriptor)
            if opened.st_size > max_bytes:
                return {"exists": True, "valid": False, "reason": "file exceeds limit"}
            chunks: list[bytes] = []
            remaining = opened.st_size
            while remaining:
                chunk = os.read(descriptor, remaining)
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            closed = os.fstat(descriptor)
            current = path.lstat()
            if (
                remaining
                or opened.st_ino != closed.st_ino
                or opened.st_size != closed.st_size
                or opened.st_mtime_ns != closed.st_mtime_ns
                or current.st_ino != opened.st_ino
                or current.st_mtime_ns != opened.st_mtime_ns
            ):
                time.sleep(0.005)
                continue
            payload = b"".join(chunks)
            value = json.loads(payload.decode("utf-8"))
            if not isinstance(value, dict):
                return {"exists": True, "valid": False, "reason": "JSON root is not an object"}
            return {
                "exists": True,
                "valid": True,
                "inode": opened.st_ino,
                "mode": stat.S_IMODE(opened.st_mode),
                "uid": getattr(opened, "st_uid", None),
                "mtime_ns": opened.st_mtime_ns,
                "digest": hashlib.sha256(payload).hexdigest(),
                "value": value,
            }
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            return {"exists": True, "valid": False, "reason": type(error).__name__}
        finally:
            if descriptor >= 0:
                os.close(descriptor)
    return {"exists": True, "valid": False, "reason": "unstable during snapshot"}


def _guardian_relative_paths(workspace: Path | str) -> dict[str, str]:
    resolved = Path(workspace).expanduser().resolve()
    key = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:24]
    directory = Path("intent") / "workspaces"
    contract = directory / f"{key}.active.json"
    return {
        "directory": directory.as_posix(),
        "contract": contract.as_posix(),
        "audit": contract.with_name(f"{key}.active.events.jsonl").as_posix(),
    }


def _guardian_baseline(
    root: Path,
    workspace: Path | str,
    *,
    cursor_home: Path | None = None,
) -> dict[str, object]:
    relative = _guardian_relative_paths(workspace)
    contract_path = root / relative["contract"]
    audit_path = root / relative["audit"]
    contract = _stable_json_file(contract_path)
    audit = _append_log_baseline(
        audit_path,
        cursor_path=(
            _audit_cursor_path(cursor_home, audit_path) if cursor_home else None
        ),
        runtime_generation="guardian-audit-projection-v1",
    )
    valid = bool(contract.get("valid") and audit.get("valid"))
    if contract.get("exists"):
        value = contract.get("value")
        if not isinstance(value, dict):
            valid = False
        else:
            try:
                bound_workspace = Path(str(value.get("workspace_root") or "")).resolve()
            except (OSError, RuntimeError, ValueError):
                valid = False
            else:
                valid = valid and bound_workspace == Path(workspace).expanduser().resolve()
    elif audit.get("exists"):
        valid = False
    return {
        "valid": valid,
        "relative": relative,
        "contract": contract,
        "audit": audit,
    }


def _guardian_event_id(event: dict[str, object]) -> str:
    source = "\0".join(
        str(event.get(key) or "")
        for key in ("kind", "server", "action", "target", "arguments_digest")
    )
    identity = event.get("event_identity_schema")
    if identity == "sulde-host-call-event-v2" and event.get("call_id"):
        source += "\0" + "\0".join(str(event.get(key) or "") for key in ("provider", "session_id", "call_id"))
    elif identity is not None:
        return "invalid-event-identity-schema"
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:24]


def _guardian_event_fingerprint(event: dict[str, object]) -> str:
    source = "\0".join(
        str(event.get(key) or "")
        for key in ("provider", "session_id", "capability", "target", "arguments_digest")
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _validate_guardian_read_projection(
    root: Path,
    *,
    baseline: dict[str, object],
    started_at: datetime,
    ended_at: datetime,
    parent_host_sessions: dict[str, str] | None,
    relevant_filesystem_changed: bool,
) -> tuple[bool, int, str]:
    if not baseline.get("valid"):
        return False, 0, "guardian baseline was not trustworthy"
    relative = baseline.get("relative")
    contract_before = baseline.get("contract")
    audit_before = baseline.get("audit")
    if not isinstance(relative, dict) or not isinstance(contract_before, dict):
        return False, 0, "guardian baseline shape is invalid"
    if not isinstance(audit_before, dict):
        return False, 0, "guardian audit baseline shape is invalid"
    contract_path = root / str(relative["contract"])
    audit_path = root / str(relative["audit"])
    appended, reason = _read_appended_log(
        audit_path,
        audit_before,
        label="guardian audit log",
    )
    if appended is None:
        return False, 0, reason
    contract_after = _stable_json_file(contract_path)
    if not contract_before.get("exists"):
        if appended or contract_after.get("exists") or relevant_filesystem_changed:
            return False, 0, "guardian state appeared during the isolated test run"
        return True, 0, ""
    if not contract_after.get("valid") or not contract_after.get("exists"):
        return False, 0, "guardian active contract was removed or became invalid"
    if (
        contract_after.get("mode") != contract_before.get("mode")
        or contract_after.get("uid") != contract_before.get("uid")
    ):
        return False, 0, "guardian active contract mode or owner changed"
    before_value = contract_before.get("value")
    after_value = contract_after.get("value")
    if not isinstance(before_value, dict) or not isinstance(after_value, dict):
        return False, 0, "guardian active contract JSON is invalid"
    if not appended:
        if (
            contract_after.get("digest") != contract_before.get("digest")
            or relevant_filesystem_changed
        ):
            return False, 0, "guardian active contract changed without an audit append"
        return True, 0, ""

    runtime = before_value.get("runtime")
    if not isinstance(runtime, dict):
        return False, 0, "guardian active contract has no runtime projection"
    expected = json.loads(json.dumps(before_value, ensure_ascii=False))
    expected_runtime = expected["runtime"]
    expected_sequence = int(expected_runtime.get("sequence", 0))
    baseline_sequence = audit_before.get("guardian_last_sequence")
    if baseline_sequence is not None and int(baseline_sequence) != expected_sequence:
        return False, 0, "guardian contract and audit sequence were not aligned at baseline"
    lanes = dict(audit_before.get("guardian_lanes") or {})
    inflight = dict(audit_before.get("guardian_inflight") or {})
    prior_hashes = set(audit_before.get("guardian_row_hashes") or ())
    parent_sessions = dict(parent_host_sessions or {})
    lower = started_at - timedelta(seconds=10)
    upper = ended_at + timedelta(seconds=10)
    freshness_cutoff = started_at - timedelta(minutes=30)
    chain = bytes.fromhex(str(audit_before.get("digest") or hashlib.sha256(b"").hexdigest()))
    accepted = 0
    last_event_at: datetime | None = None
    for line_number, raw_line in enumerate(appended.splitlines(), start=1):
        row_hash = hashlib.sha256(raw_line).hexdigest()
        if row_hash in prior_hashes:
            return False, accepted, f"guardian row {line_number} replayed prior audit bytes"
        chain = hashlib.sha256(chain + bytes.fromhex(row_hash)).digest()
        try:
            row = json.loads(raw_line.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            return False, accepted, f"guardian row {line_number} is invalid JSON"
        if not isinstance(row, dict) or set(row) != {"schema", "event", "decision", "contract"}:
            return False, accepted, f"guardian row {line_number} has an unexpected envelope"
        event = row.get("event")
        decision = row.get("decision")
        contract_summary = row.get("contract")
        if (
            row.get("schema") != "sulde-guardian-event-v1"
            or not isinstance(event, dict)
            or not isinstance(decision, dict)
            or not isinstance(contract_summary, dict)
        ):
            return False, accepted, f"guardian row {line_number} has an invalid schema"
        provider = str(event.get("provider") or "")
        session_id = str(event.get("session_id") or "")
        generation = str(event.get("runtime_generation") or "")
        lane = (provider, session_id, generation)
        call_key = (provider, session_id, str(event.get("call_id") or ""))
        started_event = inflight.get(call_key)
        completion_binding_fields = (
            "provider",
            "session_id",
            "runtime_generation",
            "event_id",
            "kind",
            "server",
            "action",
            "capability",
            "target",
            "arguments_digest",
            "effect",
            "call_id",
            "verification_kind",
            "verification_sha256",
        )
        anchored_unknown_completion = bool(
            isinstance(started_event, dict)
            and started_event.get("phase") == "started"
            and event.get("phase") == "completed"
            and event.get("effect") == "unknown"
            and all(
                started_event.get(field) == event.get(field)
                for field in completion_binding_fields
            )
        )
        lane_time = lanes.get(lane)
        parent_match = bool(session_id and parent_sessions.get(provider) == session_id)
        fresh_lane = isinstance(lane_time, datetime) and lane_time >= freshness_cutoff
        observed_at = _parse_utc(event.get("at"))
        expected_sequence += 1
        fingerprint = _guardian_event_fingerprint(event)
        if (
            provider not in {"claude", "codex"}
            or not session_id
            or not generation
            or not (parent_match or fresh_lane)
            or observed_at is None
            or observed_at < lower
            or observed_at > upper
            or event.get("schema") != "sulde-guardian-event-v1"
            or (
                event.get("effect") != "read"
                and not anchored_unknown_completion
            )
            or event.get("phase") not in {"started", "completed"}
            or event.get("event_id") != _guardian_event_id(event)
            or event.get("fingerprint") != fingerprint
            or event.get("sequence") != expected_sequence
            or event.get("intent_id") != before_value.get("intent_id")
            or event.get("intent_revision") != before_value.get("revision")
            or event.get("task_epoch") != before_value.get("task_epoch")
            or decision.get("action") != "allow"
            or decision.get("would_action") != "allow"
            or decision.get("fingerprint") != fingerprint
            or decision.get("verification_required") is not False
            or decision.get("awaiting_human") is not False
            or any(
                key in event
                for key in (
                    "continuation_authority",
                    "effect_attempt_id",
                    "retry_intervention_id",
                    "semantic_retry_intervention_id",
                    "blocked_by_attempt_id",
                    "independent_verification",
                )
            )
        ):
            return False, accepted, f"guardian row {line_number} is not an attributable read event"
        expected_contract_summary = {
            "intent_id": before_value.get("intent_id"),
            "revision": before_value.get("revision"),
            "mode": before_value.get("mode"),
            "status": before_value.get("status"),
        }
        if contract_summary != expected_contract_summary:
            return False, accepted, f"guardian row {line_number} contract binding changed"
        frames = expected_runtime.get("active_skill_frames")
        if isinstance(frames, list):
            expected_parents = [
                str(frame.get("name") or "")
                for frame in frames
                if isinstance(frame, dict)
                and frame.get("provider") == provider
                and frame.get("session_id") == session_id
            ]
            if event.get("parent_skills") != expected_parents:
                return False, accepted, f"guardian row {line_number} skill lane binding changed"
        expected_runtime["sequence"] = expected_sequence
        if anchored_unknown_completion:
            expected_runtime["material_sequence"] = int(
                expected_runtime.get("material_sequence", 0)
            ) + 1
            inflight.pop(call_key, None)
        metrics = expected_runtime.get("supervision_metrics")
        if not isinstance(metrics, dict):
            return False, accepted, "guardian supervision metrics are invalid"
        metrics["allowed"] = int(metrics.get("allowed", 0)) + 1
        # A paired opaque execution callback is attributable but no longer
        # means effect uncertainty. Only the runtime's explicit degraded mode
        # advances this projection.
        if event.get("supervision_mode") == "degraded_observe":
            metrics["degraded_observe"] = int(metrics.get("degraded_observe", 0)) + 1
        prior_hashes.add(row_hash)
        lanes[lane] = observed_at
        last_event_at = observed_at
        accepted += 1
    updated_at = _parse_utc(after_value.get("updated_at"))
    if (
        updated_at is None
        or updated_at < lower
        or updated_at > upper
        or (last_event_at is not None and updated_at < last_event_at - timedelta(seconds=10))
    ):
        return False, accepted, "guardian active contract timestamp is outside the append window"
    expected["updated_at"] = after_value.get("updated_at")
    if json.dumps(expected, ensure_ascii=False, sort_keys=True) != json.dumps(
        after_value,
        ensure_ascii=False,
        sort_keys=True,
    ):
        return False, accepted, "guardian active contract is not the projection of appended reads"
    return True, accepted, ""


def _validate_external_observation_rows(
    payload: bytes,
    *,
    root: Path,
    baseline: dict[str, object],
    started_at: datetime,
    ended_at: datetime,
    parent_host_sessions: dict[str, str] | None = None,
    expected_workspace: Path | str = ROOT,
) -> tuple[bool, int, str]:
    if not payload:
        return True, 0, ""
    host = _host_capabilities_module()
    lower = started_at - timedelta(seconds=host.PROVENANCE_CLOCK_SKEW_SECONDS)
    upper = ended_at + timedelta(seconds=host.PROVENANCE_CLOCK_SKEW_SECONDS)
    seen_event_ids = set(baseline.get("event_ids") or ())
    seen_nonces = set(baseline.get("nonces") or ())
    legacy_identities = set(baseline.get("legacy_identities") or ())
    parent_sessions = dict(parent_host_sessions or {})
    expected_workspace_id = host.workspace_identifier(expected_workspace)
    accepted = 0
    for line_number, raw_line in enumerate(payload.splitlines(), start=1):
        try:
            row = json.loads(raw_line.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            return False, accepted, f"appended observation row {line_number} is not valid JSON"
        if not isinstance(row, dict):
            return False, accepted, f"appended observation row {line_number} is not an object"
        if (
            row.get("schema") != host.OBSERVATION_SCHEMA
            or row.get("provider") not in host.PROVIDERS
            or row.get("source") not in {"live_host_hook", "managed_l3"}
            or row.get("outcome") != "observed"
            or _SHA256_RE.fullmatch(str(row.get("runtime_sha256") or "")) is None
        ):
            return (
                False,
                accepted,
                f"appended observation row {line_number} is not trusted live evidence",
            )
        try:
            specification = next(
                item
                for item in host.capability_specs(str(row["provider"]))
                if row.get("hook_event") in item.hook_events
            )
        except (StopIteration, ValueError, host.HostCapabilityError):
            return False, accepted, f"appended observation row {line_number} has an unknown hook"
        if row.get("capability_id") != specification.capability_id:
            return (
                False,
                accepted,
                f"appended observation row {line_number} has a capability mismatch",
            )
        event_id = str(row.get("event_id") or "")
        unsigned_row = dict(row)
        unsigned_row.pop("event_id", None)
        expected_event_id = hashlib.sha256(
            json.dumps(
                unsigned_row,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        proof = row.get("provenance")
        nonce = str(proof.get("nonce") or "") if isinstance(proof, dict) else ""
        if (
            _SHA256_RE.fullmatch(event_id) is None
            or event_id != expected_event_id
            or event_id in seen_event_ids
        ):
            return (
                False,
                accepted,
                f"appended observation row {line_number} is replayed or malformed",
            )
        observed = _parse_utc(row.get("at"))
        if (
            observed is None
            or observed < lower
            or observed > upper
        ):
            return (
                False,
                accepted,
                f"appended observation row {line_number} is outside this run window",
            )
        if isinstance(proof, dict):
            issued = _parse_utc(proof.get("issued_at"))
            if (
                issued is None
                or issued < lower
                or issued > upper
                or _HEX_32_RE.fullmatch(nonce) is None
                or nonce in seen_nonces
                or not host._stored_provenance_valid(row, root)
            ):
                return (
                    False,
                    accepted,
                    f"appended observation row {line_number} has invalid provenance",
                )
            seen_nonces.add(nonce)
        else:
            provider = str(row.get("provider") or "")
            session_id = str(row.get("session_id") or "")
            legacy_identity = (
                provider,
                str(row.get("runtime_sha256") or ""),
                session_id,
                str(row.get("workspace_id") or ""),
                str(row.get("source") or ""),
            )
            if (
                not session_id
                or parent_sessions.get(provider) != session_id
                or row.get("workspace_id") != expected_workspace_id
                or legacy_identity not in legacy_identities
            ):
                return (
                    False,
                    accepted,
                    f"appended observation row {line_number} lacks attributable provenance",
                )
        seen_event_ids.add(event_id)
        accepted += 1
    return True, accepted, ""


def production_mutation_verdict(
    root: Path,
    *,
    before_filesystem: tuple[tuple[object, ...], ...],
    before_observation: dict[str, object],
    after_filesystem: tuple[tuple[object, ...], ...],
    started_at: datetime,
    ended_at: datetime,
    parent_host_sessions: dict[str, str] | None = None,
    expected_workspace: Path | str = ROOT,
    before_guardian: dict[str, object] | None = None,
) -> tuple[bool, int, str]:
    """Accept only attributable host telemetry and narrow guardian read projections."""
    appended, reason = _read_appended_observations(root, before_observation)
    if appended is None:
        return False, 0, reason
    host_safe, host_count, reason = _validate_external_observation_rows(
        appended, root=root, baseline=before_observation, started_at=started_at,
        ended_at=ended_at, parent_host_sessions=parent_host_sessions,
        expected_workspace=expected_workspace,
    )
    if not host_safe:
        return False, host_count, reason
    from host_observation_index import attributable_index_paths
    host = _host_capabilities_module()
    try:
        index_names = attributable_index_paths(
            root, [json.loads(raw) for raw in appended.splitlines()], key=host._read_provenance_key(root),
            validate=lambda row: host._valid_observation(row, root),
        )
    except (OSError, ValueError, host.HostProvenanceError):
        index_names = set()
    guardian_names: set[str] = set()
    if isinstance(before_guardian, dict):
        relative = before_guardian.get("relative")
        if isinstance(relative, dict):
            guardian_names = {str(value) for value in relative.values()}
    attributed_names = {_OBSERVATION_LOG_NAME, *guardian_names, *index_names}
    without_attributed = lambda rows: tuple(
        row for row in rows if row and str(row[0]) not in attributed_names
    )
    before_other = without_attributed(before_filesystem)
    after_other = without_attributed(after_filesystem)
    if before_other != after_other:
        before_rows = {str(row[0]): row for row in before_other}
        after_rows = {str(row[0]): row for row in after_other}
        changed = sorted(
            name
            for name in before_rows.keys() | after_rows.keys()
            if before_rows.get(name) != after_rows.get(name)
        )
        detail = ", ".join(changed[:3]) or "metadata outside attributable host state"
        return False, 0, f"production KB changed outside attributable host state: {detail}"
    guardian_count = 0
    if isinstance(before_guardian, dict):
        guardian_before_rows = tuple(
            row for row in before_filesystem if row and str(row[0]) in guardian_names
        )
        guardian_after_rows = tuple(
            row for row in after_filesystem if row and str(row[0]) in guardian_names
        )
        guardian_safe, guardian_count, reason = _validate_guardian_read_projection(
            root,
            baseline=before_guardian,
            started_at=started_at,
            ended_at=ended_at,
            parent_host_sessions=parent_host_sessions,
            relevant_filesystem_changed=guardian_before_rows != guardian_after_rows,
        )
        if not guardian_safe:
            return False, host_count + guardian_count, reason
        audit_before = before_guardian.get("audit")
        if isinstance(audit_before, dict):
            try:
                _commit_baseline_cursor(audit_before)
            except AuditCursorError as error:
                return False, host_count + guardian_count, f"guardian cursor CAS failed: {error}"
    try:
        _commit_baseline_cursor(before_observation)
    except AuditCursorError as error:
        return False, host_count + guardian_count, f"observation cursor CAS failed: {error}"
    return True, host_count + guardian_count, ""


def unittest_command(names: Iterable[str], *, start: str, pattern: str) -> list[str]:
    selected = [name for name in names if name]
    if selected:
        return [sys.executable, "-m", "unittest", "-v", *selected]
    return [
        sys.executable,
        "-m",
        "unittest",
        "discover",
        "-s",
        start,
        "-p",
        pattern,
        "-v",
    ]


def os_isolated_test_command(command: list[str], production_kb: Path) -> list[str]:
    """Apply an OS-enforced read-only boundary to the production KB."""
    if sys.platform == "darwin":
        executable = shutil.which("sandbox-exec")
        if executable is None:
            raise RuntimeError("sandbox-exec is unavailable")
        escaped = str(production_kb).replace("\\", "\\\\").replace('"', '\\"')
        profile = (
            '(version 1) (allow default) '
            f'(deny file-write* (subpath "{escaped}"))'
        )
        return [executable, "-p", profile, *command]
    if sys.platform.startswith("linux"):
        executable = shutil.which("bwrap")
        if executable is None:
            raise RuntimeError("bubblewrap is unavailable")
        return [
            executable,
            "--die-with-parent",
            "--bind",
            "/",
            "/",
            "--ro-bind",
            str(production_kb),
            str(production_kb),
            "--",
            *command,
        ]
    raise RuntimeError("no supported OS test isolation backend")


def preflight_os_test_isolation(production_kb: Path, environment: dict[str, str]) -> None:
    """Prove the native wrapper denies writes before reading host baselines."""
    run_id = environment.get("SULDE_ISOLATED_TEST_RUN_ID", "")
    if _HEX_32_RE.fullmatch(run_id) is None:
        raise RuntimeError("OS test isolation proof lacks a valid run id")
    probe = production_kb / f".sulde-isolation-probe-{run_id}"
    if os.path.lexists(probe):
        raise RuntimeError("OS test isolation proof target already exists")
    proof_source = (
        "import sys\n"
        "from pathlib import Path\n"
        "try:\n"
        "    Path(sys.argv[1]).write_bytes(b\"isolation-probe\")\n"
        "except PermissionError:\n"
        "    print(\"sulde-native-write-denied-v1\")\n"
        "else:\n"
        "    raise SystemExit(9)\n"
    )
    command = os_isolated_test_command(
        [sys.executable, "-S", "-c", proof_source, str(probe)],
        production_kb,
    )
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if os.path.lexists(probe):
        try:
            probe.unlink()
        except OSError as error:
            raise RuntimeError(
                "OS test isolation backend allowed a production write and "
                f"the proof artifact could not be removed: {error}"
            ) from error
        raise RuntimeError("OS test isolation backend allowed a production write")
    if (
        completed.returncode != 0
        or completed.stdout.strip() != "sulde-native-write-denied-v1"
    ):
        detail = (completed.stderr or completed.stdout).strip().splitlines()[:1]
        raise RuntimeError(
            "OS test isolation backend did not prove write denial"
            + (f": {detail[0]}" if detail else "")
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tests", nargs="*", help="optional unittest module/class/test names")
    parser.add_argument("--start", default="tests", help="unittest discovery directory")
    parser.add_argument("--pattern", default="test_*.py", help="unittest discovery pattern")
    parser.add_argument(
        "--production-diagnostics",
        action="store_true",
        help=(
            "collect the bounded production-state attribution snapshot; normal code "
            "evidence relies on the OS write-denial boundary instead"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    real_home = Path.home().expanduser().resolve()
    production_kb = Path(
        os.environ.get(
            "SULDE_PRODUCTION_KB_HOME",
            neutral_kb_home(),
        )
    ).expanduser().resolve()
    cursor_home = Path(
        os.environ.get(
            "SULDE_AUDIT_CURSOR_HOME",
            ROOT / ".codex-agent" / "test-audit-cursors",
        )
    ).expanduser().resolve()
    try:
        if os.path.commonpath((str(production_kb), str(cursor_home))) == str(production_kb):
            print(
                "isolated test gate failed: audit cursors must not live in production KB",
                file=sys.stderr,
            )
            return 3
    except ValueError:
        pass
    cursor_home.mkdir(parents=True, exist_ok=True)
    parent_host_sessions = {
        "codex": os.environ.get("CODEX_THREAD_ID", ""),
        "claude": os.environ.get("CLAUDE_SESSION_ID", ""),
    }
    with tempfile.TemporaryDirectory(prefix="sulde-tests-") as temporary_name:
        temporary_root = Path(temporary_name)
        environment = isolated_environment(
            temporary_root,
            production_kb=production_kb,
        )
        try:
            preflight_os_test_isolation(production_kb, environment)
        except RuntimeError as error:
            print(f"isolated test gate failed: {error}", file=sys.stderr)
            return 3
        started_at = datetime.now(timezone.utc)
        before: tuple[tuple[object, ...], ...] = ()
        before_observation: dict[str, object] = {"valid": True}
        before_guardian: dict[str, object] = {"valid": True}
        if args.production_diagnostics:
            before = filesystem_snapshot(production_kb)
            before_observation = _observation_baseline(
                production_kb,
                cursor_home=cursor_home,
            )
            before_guardian = _guardian_baseline(
                production_kb,
                ROOT,
                cursor_home=cursor_home,
            )
            if not before_observation.get("valid") or not before_guardian.get("valid"):
                print(
                    "isolated test gate failed: production host-state baseline "
                    "could not be verified",
                    file=sys.stderr,
                )
                return 3
        try:
            child_command = os_isolated_test_command(
                unittest_command(args.tests, start=args.start, pattern=args.pattern),
                production_kb,
            )
        except RuntimeError as error:
            print(f"isolated test gate failed: {error}", file=sys.stderr)
            return 3
        completed = subprocess.run(
            child_command,
            cwd=ROOT,
            env=environment,
            check=False,
        )
        ended_at = datetime.now(timezone.utc)
        after = filesystem_snapshot(production_kb) if args.production_diagnostics else ()
        violations = process_guard_violations(environment)
        safe, accepted, reason = True, 0, ""
        if args.production_diagnostics:
            safe, accepted, reason = production_mutation_verdict(
                production_kb,
                before_filesystem=before,
                before_observation=before_observation,
                after_filesystem=after,
                started_at=started_at,
                ended_at=ended_at,
                parent_host_sessions=parent_host_sessions,
                expected_workspace=ROOT,
                before_guardian=before_guardian,
            )
    if violations:
        print(
            "isolated test gate failed: test subprocess attempted "
            f"{len(violations)} production KB write(s)",
            file=sys.stderr,
        )
        return 3
    if args.production_diagnostics and not safe and not violations:
        print(
            "isolated test gate: concurrent external production state was "
            f"observed behind the verified read-only boundary: {reason}",
            file=sys.stderr,
        )
    elif args.production_diagnostics and accepted:
        print(
            "isolated test gate: attributed "
            f"{accepted} concurrent host-state event(s)",
            file=sys.stderr,
        )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
