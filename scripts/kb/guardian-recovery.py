#!/usr/bin/env python3
"""Plan or apply one identity-bound synthetic-artifact cleanup."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Callable


CANDIDATE_SCHEMA = "sulde-guardian-synthetic-artifact-v1"
FINDING_SCHEMA = "sulde-guardian-recovery-finding-v1"
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
MAX_AUDIT_BYTES = 16 * 1024 * 1024


class RecoveryError(RuntimeError):
    """Recovery input or target identity failed closed."""


def _validate_absolute_file_path(path: Path, *, label: str) -> None:
    raw = os.fspath(path)
    if (
        not raw.startswith("/")
        or raw.startswith("//")
        or raw == "/"
        or raw.endswith("/")
        or raw != "/" + "/".join(path.parts[1:])
        or any(part in {"", ".", ".."} for part in path.parts[1:])
    ):
        raise RecoveryError(f"{label} must be one canonical absolute file path")


def _ancestor_chain(path: Path, *, label: str) -> list[tuple[Path, tuple[int, ...]]]:
    """Reject aliases/non-directories and snapshot every pathname ancestor."""
    chain: list[tuple[Path, tuple[int, ...]]] = []
    current = Path("/")
    for component in path.parts[1:-1]:
        current /= component
        try:
            metadata = os.lstat(current)
        except OSError as error:
            raise RecoveryError(f"{label} ancestor cannot be inspected: {error}") from error
        if not stat.S_ISDIR(metadata.st_mode):
            raise RecoveryError(f"{label} has a symlink or non-directory ancestor: {current}")
        chain.append(
            (
                current,
                (
                    metadata.st_dev,
                    metadata.st_ino,
                    metadata.st_mode,
                    metadata.st_uid,
                    metadata.st_nlink,
                    metadata.st_ctime_ns,
                ),
            )
        )
    return chain


def _open_safe_parent_sandbox_fallback(
    path: Path,
    *,
    label: str,
    before: list[tuple[Path, tuple[int, ...]]],
) -> tuple[int, str]:
    """Handle hosts that expose an exact subtree but deny root-fd traversal.

    This still checks every ancestor before and after the exact-parent open and
    pins that parent.  It deliberately does not claim atomicity across a
    concurrent ancestor rename; unsandboxed execution uses the openat walk.
    """
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        parent_fd = os.open(path.parent, flags)
    except OSError as error:
        raise RecoveryError(f"{label} parent cannot be pinned safely: {error}") from error
    try:
        after = _ancestor_chain(path, label=label)
        if before != after:
            raise RecoveryError(f"{label} ancestor identity changed while opening")
        parent_metadata = os.fstat(parent_fd)
        expected_parent = after[-1][1][:2] if after else (
            os.lstat("/").st_dev,
            os.lstat("/").st_ino,
        )
        if (parent_metadata.st_dev, parent_metadata.st_ino) != expected_parent:
            raise RecoveryError(f"{label} opened parent identity is inconsistent")
        return parent_fd, path.name
    except Exception:
        os.close(parent_fd)
        raise


def _open_safe_parent(path: Path, *, label: str) -> tuple[int, str]:
    """Open every ancestor without following aliases, returning the pinned parent."""
    _validate_absolute_file_path(path, label=label)
    ancestor_snapshot = _ancestor_chain(path, label=label)
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    current_fd = -1
    try:
        current_fd = os.open("/", flags)
        for component in path.parts[1:-1]:
            next_fd = os.open(component, flags, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        return current_fd, path.name
    except PermissionError:
        if current_fd >= 0:
            os.close(current_fd)
        return _open_safe_parent_sandbox_fallback(
            path,
            label=label,
            before=ancestor_snapshot,
        )
    except OSError as error:
        if current_fd >= 0:
            os.close(current_fd)
        raise RecoveryError(f"{label} has an unsafe ancestor: {error}") from error


def _safe_lstat(path: Path, *, label: str) -> os.stat_result:
    parent_fd, name = _open_safe_parent(path, label=label)
    try:
        return os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    finally:
        os.close(parent_fd)


def _assert_path_reaches_fd(
    path: Path,
    parent_fd: int,
    name: str,
    fd: int,
    *,
    label: str,
) -> None:
    opened = os.fstat(fd)
    opened_key = (opened.st_dev, opened.st_ino)
    try:
        relative = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        absolute = _safe_lstat(path, label=label)
    except (OSError, RecoveryError) as error:
        raise RecoveryError(f"{label} pathname is no longer safely reachable: {error}") from error
    for reached in (relative, absolute):
        if not stat.S_ISREG(reached.st_mode) or (reached.st_dev, reached.st_ino) != opened_key:
            raise RecoveryError(f"{label} pathname no longer reaches the opened file")


def _owner_only(metadata: os.stat_result) -> bool:
    return metadata.st_uid == os.geteuid() and stat.S_IMODE(metadata.st_mode) & 0o077 == 0


def _sha256_fd(fd: int) -> str:
    digest = hashlib.sha256()
    os.lseek(fd, 0, os.SEEK_SET)
    while True:
        chunk = os.read(fd, 1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
    os.lseek(fd, 0, os.SEEK_SET)
    return digest.hexdigest()


def _read_audit(path: Path) -> tuple[list[dict[str, Any]], tuple[int, int]]:
    _validate_absolute_file_path(path, label="audit")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    parent_fd = -1
    try:
        parent_fd, name = _open_safe_parent(path, label="audit")
        fd = os.open(name, flags, dir_fd=parent_fd)
    except (OSError, RecoveryError) as error:
        if parent_fd >= 0:
            os.close(parent_fd)
        raise RecoveryError(f"audit cannot be opened safely: {error}") from error
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise RecoveryError("audit must be one regular, singly linked file")
        if not _owner_only(before):
            raise RecoveryError("audit must be owner-only and owned by the current user")
        if before.st_size > MAX_AUDIT_BYTES:
            raise RecoveryError("audit exceeds the bounded recovery input size")
        chunks: list[bytes] = []
        remaining = MAX_AUDIT_BYTES + 1
        while remaining > 0:
            chunk = os.read(fd, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        after = os.fstat(fd)
        identity_before = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_uid,
            stat.S_IMODE(before.st_mode),
            before.st_nlink,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        identity_after = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_uid,
            stat.S_IMODE(after.st_mode),
            after.st_nlink,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if identity_before != identity_after or len(payload) != before.st_size:
            raise RecoveryError("audit changed while it was being read")
        _assert_path_reaches_fd(path, parent_fd, name, fd, label="audit")
    finally:
        os.close(fd)
        os.close(parent_fd)
    if payload and not payload.endswith(b"\n"):
        raise RecoveryError("audit has an incomplete append-only tail")
    rows: list[dict[str, Any]] = []
    for line_number, raw in enumerate(payload.splitlines(), start=1):
        try:
            row = json.loads(raw)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise RecoveryError(f"audit line {line_number} is not valid JSON") from error
        if not isinstance(row, dict):
            raise RecoveryError(f"audit line {line_number} is not an object")
        rows.append(row)
    return rows, (before.st_dev, before.st_ino)


def _candidate_payload(row: dict[str, Any]) -> dict[str, Any] | None:
    if row.get("schema") == CANDIDATE_SCHEMA:
        return row
    event = row.get("event")
    if not isinstance(event, dict):
        return None
    artifact = event.get("synthetic_artifact")
    if not isinstance(artifact, dict) or artifact.get("schema") != CANDIDATE_SCHEMA:
        return None
    merged = dict(artifact)
    for key in ("event_id", "session_id"):
        if key in merged and merged[key] != event.get(key):
            raise RecoveryError(f"synthetic artifact {key} conflicts with its audit event")
        merged[key] = event.get(key)
    return merged


def _validate_candidate(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {"schema", "event_id", "session_id", "artifact"}
    if set(payload) != allowed:
        raise RecoveryError("synthetic artifact record has unknown or missing fields")
    event_id = payload.get("event_id")
    session_id = payload.get("session_id")
    artifact = payload.get("artifact")
    if not isinstance(event_id, str) or not event_id or len(event_id) > 200:
        raise RecoveryError("synthetic artifact event_id is invalid")
    if not isinstance(session_id, str) or not session_id or len(session_id) > 200:
        raise RecoveryError("synthetic artifact session_id is invalid")
    if not isinstance(artifact, dict) or set(artifact) != {
        "kind", "synthetic", "target", "identity"
    }:
        raise RecoveryError("synthetic artifact body is invalid")
    if artifact.get("kind") != "single_file" or artifact.get("synthetic") is not True:
        raise RecoveryError("only a declared single-file synthetic artifact is recoverable")
    target = artifact.get("target")
    if not isinstance(target, str) or not target or "\x00" in target:
        raise RecoveryError("synthetic artifact target is invalid")
    if any(character in target for character in "*?["):
        raise RecoveryError("glob-like synthetic artifact targets are forbidden")
    path = Path(target)
    if os.fspath(path) != target:
        raise RecoveryError("synthetic artifact target contains a pathname alias")
    _validate_absolute_file_path(path, label="synthetic artifact target")
    identity = artifact.get("identity")
    expected_keys = {"dev", "inode", "size", "sha256", "uid"}
    if not isinstance(identity, dict) or set(identity) != expected_keys:
        raise RecoveryError("synthetic artifact identity is incomplete")
    for key in ("dev", "inode", "size", "uid"):
        if not isinstance(identity.get(key), int) or identity[key] < 0:
            raise RecoveryError(f"synthetic artifact identity {key} is invalid")
    digest = identity.get("sha256")
    if not isinstance(digest, str) or not SHA256_PATTERN.fullmatch(digest):
        raise RecoveryError("synthetic artifact identity sha256 is invalid")
    if identity["uid"] != os.geteuid():
        raise RecoveryError("synthetic artifact owner is not the current user")
    return payload


def load_candidate(
    audit: Path,
    *,
    event_id: str,
    session_id: str,
) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    rows, audit_key = _read_audit(audit)
    for row in rows:
        candidate = _candidate_payload(row)
        if candidate is None or candidate.get("event_id") != event_id:
            continue
        matches.append(_validate_candidate(candidate))
    if len(matches) != 1:
        raise RecoveryError(
            "recovery requires exactly one known append-only audit event"
        )
    candidate = matches[0]
    if candidate["session_id"] != session_id:
        raise RecoveryError("cross-session synthetic artifact recovery is forbidden")
    target = Path(candidate["artifact"]["target"])
    try:
        target_metadata = _safe_lstat(target, label="synthetic artifact")
    except FileNotFoundError:
        target_metadata = None
    if target_metadata is not None and (target_metadata.st_dev, target_metadata.st_ino) == audit_key:
        raise RecoveryError("audit cannot also be the synthetic artifact target")
    return candidate


def _open_target(path: Path) -> tuple[int, int, str]:
    file_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    parent_fd, name = _open_safe_parent(path, label="synthetic artifact")
    try:
        file_fd = os.open(name, file_flags, dir_fd=parent_fd)
    except FileNotFoundError as error:
        os.close(parent_fd)
        raise RecoveryError("synthetic artifact target is missing") from error
    except Exception:
        os.close(parent_fd)
        raise
    return parent_fd, file_fd, name


def _verify_open_target(
    path: Path,
    parent_fd: int,
    file_fd: int,
    name: str,
    identity: dict[str, Any],
) -> None:
    opened = os.fstat(file_fd)
    if not stat.S_ISREG(opened.st_mode):
        raise RecoveryError("synthetic artifact is not a regular file")
    if opened.st_nlink != 1:
        raise RecoveryError("synthetic artifact must have exactly one hard link")
    actual = {
        "dev": opened.st_dev,
        "inode": opened.st_ino,
        "size": opened.st_size,
        "uid": opened.st_uid,
        "sha256": _sha256_fd(file_fd),
    }
    if actual != identity:
        raise RecoveryError("synthetic artifact identity drifted")
    _assert_path_reaches_fd(
        path,
        parent_fd,
        name,
        file_fd,
        label="synthetic artifact",
    )


def verify_candidate(candidate: dict[str, Any]) -> None:
    artifact = candidate["artifact"]
    path = Path(artifact["target"])
    try:
        parent_fd, file_fd, name = _open_target(path)
    except OSError as error:
        raise RecoveryError(f"synthetic artifact cannot be opened safely: {error}") from error
    try:
        _verify_open_target(path, parent_fd, file_fd, name, artifact["identity"])
    except OSError as error:
        raise RecoveryError(f"synthetic artifact verification failed: {error}") from error
    finally:
        os.close(file_fd)
        os.close(parent_fd)


def finding_path(audit: Path) -> Path:
    return audit.with_name(audit.name + ".recovery-findings.jsonl")


def _verify_finding_sink(path: Path, parent_fd: int, fd: int, name: str) -> os.stat_result:
    metadata = os.fstat(fd)
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise RecoveryError("recovery finding log is not a regular, singly linked file")
    if not _owner_only(metadata):
        raise RecoveryError("recovery finding log must be owner-only and owned by the current user")
    _assert_path_reaches_fd(path, parent_fd, name, fd, label="recovery finding log")
    return metadata


def _open_finding_sink(path: Path) -> tuple[int, int, str]:
    parent_fd, name = _open_safe_parent(path, label="recovery finding log")
    common = os.O_WRONLY | os.O_APPEND | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        try:
            fd = os.open(name, common, dir_fd=parent_fd)
        except FileNotFoundError:
            try:
                fd = os.open(name, common | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parent_fd)
            except FileExistsError as error:
                raise RecoveryError("recovery finding log creation raced with another pathname") from error
        _verify_finding_sink(path, parent_fd, fd, name)
        return parent_fd, fd, name
    except Exception:
        os.close(parent_fd)
        if "fd" in locals():
            os.close(fd)
        raise


def _append_finding_fd(fd: int, payload: dict[str, Any]) -> None:
    line = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n"
    if os.write(fd, line) != len(line):
        raise RecoveryError("recovery finding append was incomplete")
    os.fsync(fd)


def _operation_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    artifact = candidate["artifact"]
    target = artifact["target"]
    identity = artifact["identity"]
    binding = {
        "event_id": candidate["event_id"],
        "session_id": candidate["session_id"],
        "target": target,
        "identity": identity,
    }
    operation_sha256 = hashlib.sha256(
        json.dumps(binding, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "schema": FINDING_SCHEMA,
        "operation_sha256": operation_sha256,
        "event_id": candidate["event_id"],
        "session_id": candidate["session_id"],
        "target_sha256": hashlib.sha256(target.encode("utf-8")).hexdigest(),
        "artifact_sha256": identity["sha256"],
        "target_identity": identity,
    }


def apply_candidate(
    candidate: dict[str, Any],
    *,
    findings: Path,
    checkpoint: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    artifact = candidate["artifact"]
    path = Path(artifact["target"])
    identity = artifact["identity"]
    parent_fd = file_fd = -1
    finding_parent_fd = finding_fd = -1
    finding_name = ""
    prepared = False
    removed = False
    try:
        finding_parent_fd, finding_fd, finding_name = _open_finding_sink(findings)
        sink_metadata = _verify_finding_sink(
            findings, finding_parent_fd, finding_fd, finding_name
        )
        if (sink_metadata.st_dev, sink_metadata.st_ino) == (
            identity["dev"],
            identity["inode"],
        ):
            raise RecoveryError("recovery finding log aliases the synthetic artifact")
        common = _operation_payload(candidate)
        prepared_finding = dict(common, status="prepared", removed=False)
        _append_finding_fd(finding_fd, prepared_finding)
        prepared = True
        if checkpoint is not None:
            checkpoint("after_prepared")
        _verify_finding_sink(findings, finding_parent_fd, finding_fd, finding_name)

        parent_fd, file_fd, name = _open_target(path)
        if checkpoint is not None:
            checkpoint("after_open")
        _verify_open_target(path, parent_fd, file_fd, name, identity)
        if checkpoint is not None:
            checkpoint("before_unlink")
        _verify_open_target(path, parent_fd, file_fd, name, identity)
        _verify_finding_sink(findings, finding_parent_fd, finding_fd, finding_name)
        os.unlink(name, dir_fd=parent_fd)
        removed = True
        if checkpoint is not None:
            checkpoint("after_unlink")
        opened = os.fstat(file_fd)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_dev != identity["dev"]
            or opened.st_ino != identity["inode"]
            or opened.st_size != identity["size"]
            or opened.st_uid != identity["uid"]
            or opened.st_nlink != 0
            or _sha256_fd(file_fd) != identity["sha256"]
        ):
            raise RecoveryError("removed artifact fd identity changed after unlink")
        for lookup in (
            lambda: os.stat(name, dir_fd=parent_fd, follow_symlinks=False),
            lambda: os.stat(path, follow_symlinks=False),
        ):
            try:
                lookup()
            except FileNotFoundError:
                continue
            raise RecoveryError("removed artifact pathname is unexpectedly reachable")
        _verify_finding_sink(findings, finding_parent_fd, finding_fd, finding_name)
        finding = dict(common, status="applied", removed=True)
        _append_finding_fd(finding_fd, finding)
        return finding
    except Exception as error:
        if prepared and finding_fd >= 0:
            try:
                _verify_finding_sink(
                    findings, finding_parent_fd, finding_fd, finding_name
                )
                failure = dict(
                    _operation_payload(candidate),
                    status="failed",
                    reason=str(error),
                    removed=removed,
                )
                _append_finding_fd(finding_fd, failure)
            except Exception as finding_error:
                error = RecoveryError(
                    f"{error}; terminal recovery finding could not be appended safely: {finding_error}"
                )
        if isinstance(error, RecoveryError):
            raise
        raise RecoveryError(str(error)) from error
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        if parent_fd >= 0:
            os.close(parent_fd)
        if finding_fd >= 0:
            os.close(finding_fd)
        if finding_parent_fd >= 0:
            os.close(finding_parent_fd)


def build_plan(
    candidate: dict[str, Any],
    *,
    audit: Path,
) -> dict[str, Any]:
    verify_candidate(candidate)
    return {
        "schema": "sulde-guardian-recovery-plan-v1",
        "status": "ready",
        "event_id": candidate["event_id"],
        "session_id": candidate["session_id"],
        "target": candidate["artifact"]["target"],
        "identity": candidate["artifact"]["identity"],
        "apply_command": [
            sys.executable,
            str(Path(__file__).resolve()),
            "--audit",
            str(audit),
            "--event-id",
            candidate["event_id"],
            "--session-id",
            candidate["session_id"],
            "--apply",
        ],
        "requires_native_permission_request": True,
        "native_permission_request_scope": "new one-time Codex native PermissionRequest",
        "findings": str(finding_path(audit)),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    # Keep the original spelling so lexical aliases cannot be normalized by Path.
    parser.add_argument("--audit", required=True)
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        audit = Path(args.audit)
        if os.fspath(audit) != args.audit:
            raise RecoveryError("audit contains a pathname alias")
        candidate = load_candidate(
            audit,
            event_id=args.event_id,
            session_id=args.session_id,
        )
        if args.apply:
            result = apply_candidate(candidate, findings=finding_path(audit))
        else:
            result = build_plan(candidate, audit=audit)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except RecoveryError as error:
        print(f"guardian recovery refused: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
