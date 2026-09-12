#!/usr/bin/env python3
"""Pure accepted-byte snapshot revalidation and publication protocol.

This leaf module consumes a closed coordinator authority cut.  It does not
derive authority from worktree state, reports, event tails, or task status
projections.  Successful capture only proves that the bytes matched that cut;
the resulting receipt deliberately grants no execution or composition power.
"""

from __future__ import annotations

from datetime import datetime, timezone
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import tempfile
from typing import Any, BinaryIO, Callable, Iterator
import unicodedata


AUTHORITY_CUT_SCHEMA = "sulde-accepted-snapshot-authority-cut-v1"
CAPTURE_PLAN_SCHEMA = "sulde-accepted-snapshot-capture-plan-v1"
CAPTURE_RECEIPT_SCHEMA = "sulde-accepted-snapshot-capture-receipt-v1"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_OBJECT_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_MAX_ACCEPTED_BLOB_SIZE = 64 * 1024 * 1024
_CHUNK_SIZE = 128 * 1024

_AUTHORITY_KEYS = {
    "schema",
    "authority_cut_id",
    "recorded_at",
    "program",
    "repository",
    "selected_tasks",
}
_PROGRAM_KEYS = {
    "program_id",
    "as_of_sequence",
    "last_event_sha256",
    "accepted_event_id",
    "accepted_event_sha256",
    "accepted_event_sequence",
}
_REPOSITORY_KEYS = {"root_identity", "base_commit"}
_TASK_KEYS = {
    "task_id",
    "generation",
    "generation_state",
    "superseded_by_generation",
    "open_successor_generation",
    "accepted_event",
    "accepted_verification",
    "task_definition_sha256",
    "active_evidence",
    "selected_predecessor",
    "supersession",
    "dependency_closure",
    "sources",
}
_EVENT_KEYS = {"event_id", "event_sha256", "sequence", "recorded_at"}
_VERIFICATION_KEYS = {
    "run_id",
    "epoch",
    "verified_at",
    "accepted_event_id",
    "task_definition_sha256",
    "evidence_set_sha256",
}
_EVIDENCE_KEYS = {"evidence_id", "sha256", "status", "observed_at"}
_PREDECESSOR_KEYS = {
    "task_id",
    "generation",
    "accepted_event_id",
    "accepted_event_sha256",
}
_SUPERSESSION_KEYS = {"selected_generation", "supersedes_generation"}
_DEPENDENCY_KEYS = {
    "task_id",
    "generation",
    "accepted_event_id",
    "accepted_event_sha256",
    "state",
}
_SOURCE_KEYS = {
    "operation",
    "path",
    "mode",
    "expected_before_sha256",
    "expected_after_sha256",
    "size",
    "source_kind",
    "git_object",
}
_PLAN_KEYS = {
    "schema",
    "plan_id",
    "authority_cut_sha256",
    "authority_cut",
    "planned_at",
    "sources",
    "execution_authorized",
    "composition_ready",
}
_PLAN_SOURCE_KEYS = {
    "task_id",
    "generation",
    "accepted_verification_run_id",
    "accepted_verification_epoch",
    "task_definition_sha256",
    "active_evidence_set_sha256",
    "operation",
    "path",
    "mode",
    "expected_before_sha256",
    "expected_after_sha256",
    "size",
    "source_kind",
    "git_object",
    "final_relative_path",
    "final_sha256",
    "final_size",
}
_RECEIPT_KEYS = {
    "schema",
    "receipt_id",
    "plan_id",
    "authority_cut_sha256",
    "historical_authority_recorded_at",
    "captured_at",
    "blobs",
    "execution_authorized",
    "composition_ready",
    "later_coordinator_authority_required",
}
_BLOB_RECEIPT_KEYS = {
    "task_id",
    "generation",
    "operation",
    "path",
    "source_kind",
    "observed_at",
    "relative_path",
    "sha256",
    "size",
    "receipt_identity",
}


class AcceptedSnapshotError(RuntimeError):
    """A safe denial with a stable disposition and machine-readable code."""

    def __init__(self, disposition: str, code: str, message: str):
        if disposition not in {"INSUFFICIENT", "BLOCKED"}:
            raise ValueError("invalid snapshot denial disposition")
        super().__init__(message)
        self.disposition = disposition
        self.code = code

    def as_dict(self) -> dict[str, str]:
        return {
            "disposition": self.disposition,
            "code": self.code,
            "message": str(self),
        }


Boundary = Callable[[str, dict[str, object]], None]


def _deny(disposition: str, code: str, message: str) -> None:
    raise AcceptedSnapshotError(disposition, code, message)


def _boundary(
    callback: Boundary | None, label: str, **details: object
) -> None:
    if callback is not None:
        callback(label, details)


def _is_plain_json(value: object) -> bool:
    if value is None or type(value) in {str, int, float, bool}:
        return True
    if type(value) is list:
        return all(_is_plain_json(item) for item in value)
    if type(value) is dict:
        return all(
            type(key) is str and _is_plain_json(item)
            for key, item in value.items()  # type: ignore[union-attr]
        )
    return False


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _exact_keys(value: object, expected: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict:
        _deny("BLOCKED", "AUTHORITY_SCHEMA", f"{label} must be an object")
    selected = value  # type: ignore[assignment]
    if set(selected) != expected:
        missing = sorted(expected - set(selected))
        extra = sorted(set(selected) - expected)
        _deny(
            "BLOCKED",
            "AUTHORITY_SCHEMA",
            f"{label} is not closed (missing={missing}, extra={extra})",
        )
    return selected


def _exact_plan_keys(value: object, expected: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != expected:  # type: ignore[arg-type]
        _deny("BLOCKED", "PLAN_SCHEMA", f"{label} does not match the closed schema")
    return value  # type: ignore[return-value]


def _require_string(value: object, label: str, *, identifier: bool = False) -> str:
    if type(value) is not str or not value:
        _deny("BLOCKED", "AUTHORITY_SCHEMA", f"{label} must be a non-empty string")
    if identifier and not _SAFE_ID_RE.fullmatch(value):
        _deny("BLOCKED", "AUTHORITY_SCHEMA", f"{label} has an invalid identifier")
    return value


def _require_int(value: object, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        _deny("BLOCKED", "AUTHORITY_SCHEMA", f"{label} must be an integer >= {minimum}")
    return value


def _require_sha256(value: object, label: str) -> str:
    if type(value) is not str or not _SHA256_RE.fullmatch(value):
        _deny("BLOCKED", "AUTHORITY_SCHEMA", f"{label} must be a lowercase SHA-256")
    return value


def _parse_time(value: object, label: str, *, code: str = "AUTHORITY_SCHEMA") -> datetime:
    if type(value) is not str or not value:
        _deny("BLOCKED", code, f"{label} must be a timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _deny("BLOCKED", code, f"{label} must be an ISO-8601 timestamp")
    if parsed.tzinfo is None:
        _deny("BLOCKED", code, f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _file_identity(info: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        stat.S_IFMT(info.st_mode),
        stat.S_IMODE(info.st_mode),
        info.st_uid,
        info.st_nlink,
    )


def repository_root_identity(repository_root: Path | str) -> str:
    """Return the physical root identity bound by an authority cut."""

    root = Path(repository_root)
    try:
        before = os.lstat(root)
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
            _deny("BLOCKED", "REPOSITORY_ROOT", "repository root is not a real directory")
        resolved = root.resolve(strict=True)
        after = os.stat(resolved, follow_symlinks=False)
    except FileNotFoundError:
        _deny("BLOCKED", "REPOSITORY_ROOT", "repository root is missing")
    if _file_identity(before) != _file_identity(after):
        _deny("BLOCKED", "REPOSITORY_ROOT", "repository root identity changed")
    return canonical_sha256(
        {
            "resolved_path": os.fsdecode(os.fsencode(str(resolved))),
            "device": after.st_dev,
            "inode": after.st_ino,
        }
    )


def accepted_blob_relative_path(sha256: str) -> str:
    if not _SHA256_RE.fullmatch(sha256):
        _deny("BLOCKED", "AUTHORITY_SCHEMA", "accepted blob digest is invalid")
    return f"accepted-blobs/{sha256[:2]}/{sha256}"


def _safe_relative_path(value: object) -> str:
    if type(value) is not str or not value or "\x00" in value:
        _deny("BLOCKED", "UNSAFE_PATH", "source path must be a non-empty native string")
    if os.path.isabs(value) or value.startswith(("/", "\\")):
        _deny("BLOCKED", "UNSAFE_PATH", f"absolute source path rejected: {value!r}")
    if os.altsep and os.altsep in value:
        _deny("BLOCKED", "UNSAFE_PATH", f"alternate path separator rejected: {value!r}")
    parts = value.split(os.sep)
    if any(part in {"", ".", ".."} for part in parts):
        _deny("BLOCKED", "UNSAFE_PATH", f"non-canonical source path rejected: {value!r}")
    if os.path.normpath(value) != value or unicodedata.normalize("NFC", value) != value:
        _deny("BLOCKED", "UNSAFE_PATH", f"non-canonical source path rejected: {value!r}")
    if os.fsdecode(os.fsencode(value)) != value:
        _deny("BLOCKED", "UNSAFE_PATH", f"source path is not a native round-trip string: {value!r}")
    return value


def _collision_key(path: str) -> str:
    return unicodedata.normalize("NFKC", path).casefold()


def _safe_regular_mode(mode: object) -> int:
    if type(mode) is not int or mode < 0 or mode > 0o777:
        _deny("BLOCKED", "AUTHORITY_SCHEMA", "source mode must be a permission integer")
    if not mode & stat.S_IRUSR or mode & 0o022:
        _deny("BLOCKED", "AUTHORITY_SCHEMA", f"unsafe regular-file mode: {mode:#o}")
    return mode


def _validate_source(source: object, label: str) -> dict[str, Any]:
    row = _exact_keys(source, _SOURCE_KEYS, label)
    operation = row["operation"]
    source_kind = row["source_kind"]
    if operation not in {"add", "modify", "unchanged"}:
        _deny("BLOCKED", "AUTHORITY_SCHEMA", f"unsupported operation: {operation!r}")
    if source_kind not in {"current", "git_object"}:
        _deny("BLOCKED", "AUTHORITY_SCHEMA", f"unsupported source kind: {source_kind!r}")
    _safe_relative_path(row["path"])
    _safe_regular_mode(row["mode"])
    before = row["expected_before_sha256"]
    if before is not None:
        _require_sha256(before, f"{label}.expected_before_sha256")
    after = _require_sha256(row["expected_after_sha256"], f"{label}.expected_after_sha256")
    size = _require_int(row["size"], f"{label}.size")
    if size > _MAX_ACCEPTED_BLOB_SIZE:
        _deny("BLOCKED", "AUTHORITY_SCHEMA", "accepted source exceeds the bounded size limit")
    git_object = row["git_object"]
    if source_kind == "git_object":
        if operation != "unchanged" or before != after:
            _deny("BLOCKED", "AUTHORITY_SCHEMA", "Git-object source must be unchanged")
        if type(git_object) is not str or not _GIT_OBJECT_RE.fullmatch(git_object):
            _deny("BLOCKED", "AUTHORITY_SCHEMA", "Git object identity is invalid")
    else:
        if operation not in {"add", "modify"} or git_object is not None:
            _deny("BLOCKED", "AUTHORITY_SCHEMA", "current source descriptor is inconsistent")
        if (operation == "add") != (before is None):
            _deny("BLOCKED", "AUTHORITY_SCHEMA", "before digest does not match operation")
    return row


def validate_authority_cut(authority_cut: object) -> dict[str, Any]:
    """Validate a closed, exact, plain-JSON coordinator authority cut."""

    if not _is_plain_json(authority_cut):
        _deny("BLOCKED", "AUTHORITY_NOT_PLAIN_JSON", "authority cut is not plain JSON data")
    authority = _exact_keys(authority_cut, _AUTHORITY_KEYS, "authority cut")
    if authority["schema"] != AUTHORITY_CUT_SCHEMA:
        _deny("BLOCKED", "AUTHORITY_SCHEMA", "unsupported authority cut schema")
    _require_string(authority["authority_cut_id"], "authority_cut_id", identifier=True)
    cut_time = _parse_time(authority["recorded_at"], "recorded_at")

    program = _exact_keys(authority["program"], _PROGRAM_KEYS, "program")
    _require_string(program["program_id"], "program_id", identifier=True)
    as_of = _require_int(program["as_of_sequence"], "as_of_sequence", minimum=1)
    _require_sha256(program["last_event_sha256"], "last_event_sha256")
    accepted_program_id = _require_string(
        program["accepted_event_id"], "accepted_event_id", identifier=True
    )
    accepted_program_sha = _require_sha256(
        program["accepted_event_sha256"], "accepted_event_sha256"
    )
    accepted_program_sequence = _require_int(
        program["accepted_event_sequence"], "accepted_event_sequence", minimum=1
    )
    if accepted_program_sequence > as_of:
        _deny("BLOCKED", "ACCEPTED_EVENT_MISMATCH", "accepted event is beyond authority cut")

    repository = _exact_keys(authority["repository"], _REPOSITORY_KEYS, "repository")
    _require_sha256(repository["root_identity"], "repository.root_identity")
    if type(repository["base_commit"]) is not str or not _GIT_OBJECT_RE.fullmatch(
        repository["base_commit"]
    ):
        _deny("BLOCKED", "AUTHORITY_SCHEMA", "repository base commit is invalid")

    tasks = authority["selected_tasks"]
    if type(tasks) is not list or not tasks:
        _deny("INSUFFICIENT", "NO_ACCEPTED_TASKS", "authority cut selects no tasks")
    task_keys: set[tuple[str, int]] = set()
    path_keys: dict[str, str] = {}
    accepted_program_matches = 0
    for index, item in enumerate(tasks):
        task = _exact_keys(item, _TASK_KEYS, f"selected_tasks[{index}]")
        task_id = _require_string(task["task_id"], f"task[{index}].task_id", identifier=True)
        generation = _require_int(task["generation"], f"task[{index}].generation", minimum=1)
        if (task_id, generation) in task_keys:
            _deny("BLOCKED", "AUTHORITY_SCHEMA", "duplicate selected task generation")
        task_keys.add((task_id, generation))
        if task["generation_state"] != "accepted":
            _deny("INSUFFICIENT", "GENERATION_NOT_ACCEPTED", f"{task_id} generation is not accepted")
        superseded = task["superseded_by_generation"]
        if superseded is not None:
            _require_int(superseded, "superseded_by_generation", minimum=1)
            _deny("INSUFFICIENT", "GENERATION_SUPERSEDED", f"{task_id} generation is superseded")
        successor = task["open_successor_generation"]
        if successor is not None:
            _require_int(successor, "open_successor_generation", minimum=1)
            _deny("INSUFFICIENT", "OPEN_SUCCESSOR", f"{task_id} has an open successor")

        event = _exact_keys(task["accepted_event"], _EVENT_KEYS, f"{task_id}.accepted_event")
        event_id = _require_string(event["event_id"], "accepted event id", identifier=True)
        event_sha = _require_sha256(event["event_sha256"], "accepted event sha256")
        event_sequence = _require_int(event["sequence"], "accepted event sequence", minimum=1)
        event_time = _parse_time(event["recorded_at"], "accepted event recorded_at")
        if event_sequence > as_of or event_time > cut_time:
            _deny("BLOCKED", "ACCEPTED_EVENT_MISMATCH", "task acceptance lies beyond authority cut")
        if (
            event_id == accepted_program_id
            and event_sha == accepted_program_sha
            and event_sequence == accepted_program_sequence
        ):
            accepted_program_matches += 1

        task_definition_sha = _require_sha256(
            task["task_definition_sha256"], "task_definition_sha256"
        )
        evidence = task["active_evidence"]
        if type(evidence) is not list or not evidence:
            _deny("INSUFFICIENT", "ACTIVE_EVIDENCE_MISSING", f"{task_id} has no active evidence")
        evidence_ids: set[str] = set()
        evidence_times: list[datetime] = []
        for evidence_index, evidence_item in enumerate(evidence):
            record = _exact_keys(
                evidence_item, _EVIDENCE_KEYS, f"{task_id}.active_evidence[{evidence_index}]"
            )
            evidence_id = _require_string(record["evidence_id"], "evidence_id", identifier=True)
            if evidence_id in evidence_ids:
                _deny("BLOCKED", "AUTHORITY_SCHEMA", "duplicate active evidence identity")
            evidence_ids.add(evidence_id)
            _require_sha256(record["sha256"], "active evidence sha256")
            evidence_time = _parse_time(record["observed_at"], "active evidence observed_at")
            evidence_times.append(evidence_time)
            if evidence_time > cut_time:
                _deny("BLOCKED", "EVIDENCE_SET_MISMATCH", "evidence is newer than authority cut")
            if record["status"] != "ok":
                _deny("INSUFFICIENT", "ACTIVE_EVIDENCE_ERROR", f"{evidence_id} is not successful")

        verification = _exact_keys(
            task["accepted_verification"], _VERIFICATION_KEYS, f"{task_id}.accepted_verification"
        )
        _require_string(verification["run_id"], "verification run_id", identifier=True)
        _require_int(verification["epoch"], "verification epoch", minimum=1)
        verified_time = _parse_time(verification["verified_at"], "verified_at")
        if verified_time > event_time or verified_time > cut_time:
            _deny("BLOCKED", "STALE_VERIFICATION", "verification timestamp is not historical")
        if any(evidence_time > verified_time for evidence_time in evidence_times):
            _deny("BLOCKED", "STALE_VERIFICATION", "verification predates active evidence")
        if (
            verification["accepted_event_id"] != event_id
            or verification["task_definition_sha256"] != task_definition_sha
        ):
            _deny("BLOCKED", "STALE_VERIFICATION", "verification does not bind accepted task generation")
        _require_sha256(verification["evidence_set_sha256"], "evidence_set_sha256")
        if verification["evidence_set_sha256"] != canonical_sha256(evidence):
            _deny("BLOCKED", "EVIDENCE_SET_MISMATCH", "active evidence differs from accepted verification")

        predecessor = task["selected_predecessor"]
        if predecessor is not None:
            predecessor = _exact_keys(predecessor, _PREDECESSOR_KEYS, "selected_predecessor")
            _require_string(predecessor["task_id"], "predecessor task_id", identifier=True)
            _require_int(predecessor["generation"], "predecessor generation", minimum=1)
            _require_string(predecessor["accepted_event_id"], "predecessor event id", identifier=True)
            _require_sha256(predecessor["accepted_event_sha256"], "predecessor event sha256")

        supersession = _exact_keys(task["supersession"], _SUPERSESSION_KEYS, "supersession")
        if supersession["selected_generation"] != generation:
            _deny("BLOCKED", "AUTHORITY_SCHEMA", "supersession selection differs from task generation")
        previous = supersession["supersedes_generation"]
        if previous is not None:
            _require_int(previous, "supersedes_generation", minimum=1)
            if previous >= generation:
                _deny("BLOCKED", "AUTHORITY_SCHEMA", "superseded generation is not older")

        closure = task["dependency_closure"]
        if type(closure) is not list:
            _deny("BLOCKED", "AUTHORITY_SCHEMA", "dependency closure must be an array")
        closure_identities: set[tuple[str, int, str, str]] = set()
        for dependency_item in closure:
            dependency = _exact_keys(dependency_item, _DEPENDENCY_KEYS, "dependency")
            dependency_id = _require_string(dependency["task_id"], "dependency task_id", identifier=True)
            dependency_generation = _require_int(
                dependency["generation"], "dependency generation", minimum=1
            )
            dependency_event_id = _require_string(
                dependency["accepted_event_id"], "dependency event id", identifier=True
            )
            dependency_event_sha = _require_sha256(
                dependency["accepted_event_sha256"], "dependency event sha256"
            )
            if dependency["state"] != "accepted":
                _deny("INSUFFICIENT", "DEPENDENCY_NOT_ACCEPTED", f"{dependency_id} is not accepted")
            identity = (
                dependency_id,
                dependency_generation,
                dependency_event_id,
                dependency_event_sha,
            )
            if identity in closure_identities:
                _deny("BLOCKED", "AUTHORITY_SCHEMA", "duplicate dependency closure identity")
            closure_identities.add(identity)
        if predecessor is not None:
            predecessor_identity = (
                predecessor["task_id"],
                predecessor["generation"],
                predecessor["accepted_event_id"],
                predecessor["accepted_event_sha256"],
            )
            if predecessor_identity not in closure_identities:
                _deny(
                    "BLOCKED",
                    "PREDECESSOR_CLOSURE_MISMATCH",
                    "selected predecessor is absent from dependency closure",
                )

        sources = task["sources"]
        if type(sources) is not list or not sources:
            _deny("INSUFFICIENT", "SOURCE_MISSING", f"{task_id} has no accepted source descriptors")
        for source_index, source_item in enumerate(sources):
            source = _validate_source(source_item, f"{task_id}.sources[{source_index}]")
            key = _collision_key(source["path"])
            if key in path_keys:
                _deny(
                    "BLOCKED",
                    "PATH_COLLISION",
                    f"source paths collide under NFKC casefold: {path_keys[key]!r}, {source['path']!r}",
                )
            path_keys[key] = source["path"]

    if accepted_program_matches != 1:
        _deny(
            "BLOCKED",
            "ACCEPTED_EVENT_MISMATCH",
            "program accepted event does not select exactly one accepted task event",
        )
    return authority


def _plan_sources(authority: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for task in authority["selected_tasks"]:
        verification = task["accepted_verification"]
        for source in task["sources"]:
            sha256 = source["expected_after_sha256"]
            rows.append(
                {
                    "task_id": task["task_id"],
                    "generation": task["generation"],
                    "accepted_verification_run_id": verification["run_id"],
                    "accepted_verification_epoch": verification["epoch"],
                    "task_definition_sha256": task["task_definition_sha256"],
                    "active_evidence_set_sha256": verification["evidence_set_sha256"],
                    "operation": source["operation"],
                    "path": source["path"],
                    "mode": source["mode"],
                    "expected_before_sha256": source["expected_before_sha256"],
                    "expected_after_sha256": sha256,
                    "size": source["size"],
                    "source_kind": source["source_kind"],
                    "git_object": source["git_object"],
                    "final_relative_path": accepted_blob_relative_path(sha256),
                    "final_sha256": sha256,
                    "final_size": source["size"],
                }
            )
    return rows


def make_capture_plan(
    authority_cut: object,
    *,
    repository_root: Path | str,
    planned_at: str,
) -> dict[str, Any]:
    authority = validate_authority_cut(authority_cut)
    if repository_root_identity(repository_root) != authority["repository"]["root_identity"]:
        _deny("BLOCKED", "REPOSITORY_ROOT_MISMATCH", "injected repository root differs from authority")
    planned_time = _parse_time(planned_at, "planned_at", code="PLAN_SCHEMA")
    if planned_time < _parse_time(authority["recorded_at"], "recorded_at"):
        _deny("BLOCKED", "PLAN_SCHEMA", "plan predates historical authority")
    body = {
        "schema": CAPTURE_PLAN_SCHEMA,
        "authority_cut_sha256": canonical_sha256(authority),
        "authority_cut": json.loads(_canonical_bytes(authority)),
        "planned_at": planned_at,
        "sources": _plan_sources(authority),
        "execution_authorized": False,
        "composition_ready": False,
    }
    return {**body, "plan_id": canonical_sha256(body)}


def _validate_plan(plan: object, repository_root: Path | str) -> dict[str, Any]:
    if not _is_plain_json(plan):
        _deny("BLOCKED", "PLAN_SCHEMA", "capture plan is not plain JSON")
    row = _exact_plan_keys(plan, _PLAN_KEYS, "capture plan")
    if row["schema"] != CAPTURE_PLAN_SCHEMA:
        _deny("BLOCKED", "PLAN_SCHEMA", "unsupported capture plan schema")
    if row["execution_authorized"] is not False or row["composition_ready"] is not False:
        _deny("BLOCKED", "PLAN_SCHEMA", "capture plan cannot authorize execution or composition")
    plan_id = row["plan_id"]
    if type(plan_id) is not str or not _SHA256_RE.fullmatch(plan_id):
        _deny("BLOCKED", "PLAN_SCHEMA", "capture plan identity is invalid")
    body = {key: value for key, value in row.items() if key != "plan_id"}
    if canonical_sha256(body) != plan_id:
        _deny("BLOCKED", "PLAN_IDENTITY_MISMATCH", "capture plan identity does not match its bytes")
    if type(row["authority_cut_sha256"]) is not str or not _SHA256_RE.fullmatch(
        row["authority_cut_sha256"]
    ):
        _deny("BLOCKED", "PLAN_SCHEMA", "authority cut digest is invalid")
    authority = validate_authority_cut(row["authority_cut"])
    if canonical_sha256(authority) != row["authority_cut_sha256"]:
        _deny("BLOCKED", "PLAN_IDENTITY_MISMATCH", "authority cut digest mismatch")
    expected = make_capture_plan(
        authority, repository_root=repository_root, planned_at=row["planned_at"]
    )
    if expected != row:
        _deny("BLOCKED", "PLAN_IDENTITY_MISMATCH", "plan is not the canonical authority projection")
    for source in row["sources"]:
        _exact_plan_keys(source, _PLAN_SOURCE_KEYS, "capture plan source")
    return row


def _known_t01_critic_pollution(stream: BinaryIO) -> bool:
    stream.seek(0)
    raw = stream.read()
    stream.seek(0)
    if b"t01" not in raw.lower() or b"critic" not in raw.lower():
        return False
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return (
        type(value) is dict
        and str(value.get("task_id", "")).casefold() == "t01"
        and "critic" in str(value.get("schema", "")).casefold()
    )


def _spool_and_verify(
    chunks: Iterator[bytes], source: dict[str, Any], *, boundary: Boundary | None
) -> BinaryIO:
    spool = tempfile.SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b")
    hasher = hashlib.sha256()
    total = 0
    try:
        for chunk in chunks:
            if not chunk:
                continue
            total += len(chunk)
            if total > source["size"] or total > _MAX_ACCEPTED_BLOB_SIZE:
                _deny("BLOCKED", "SOURCE_DRIFT", f"source grew beyond accepted size: {source['path']}")
            hasher.update(chunk)
            spool.write(chunk)
            _boundary(boundary, "source.after_chunk", path=source["path"], size=total)
        actual_sha = hasher.hexdigest()
        if total != source["size"] or actual_sha != source["expected_after_sha256"]:
            _deny(
                "BLOCKED",
                "SOURCE_DRIFT",
                f"current bytes differ from accepted authority descriptor: {source['path']}",
            )
        spool.seek(0)
        if _known_t01_critic_pollution(spool):
            _deny(
                "BLOCKED",
                "KNOWN_T01_CRITIC_POLLUTION",
                "known polluted T01 critic artifact is never accepted source material",
            )
        spool.seek(0)
        return spool
    except BaseException:
        close = getattr(chunks, "close", None)
        if close is not None:
            close()
        spool.close()
        raise


def _same_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return _file_identity(left) == _file_identity(right)


def _same_directory_identity(left: os.stat_result, right: os.stat_result) -> bool:
    """Compare a directory without treating child-count changes as replacement."""

    return (
        left.st_dev,
        left.st_ino,
        stat.S_IFMT(left.st_mode),
        stat.S_IMODE(left.st_mode),
        left.st_uid,
    ) == (
        right.st_dev,
        right.st_ino,
        stat.S_IFMT(right.st_mode),
        stat.S_IMODE(right.st_mode),
        right.st_uid,
    )


def _check_owner(info: os.stat_result, code: str, label: str) -> None:
    if info.st_uid != os.geteuid():
        _deny("BLOCKED", code, f"{label} is not owned by the effective uid")


def _current_chunks(
    repository_root: Path | str,
    source: dict[str, Any],
    *,
    boundary: Boundary | None,
) -> Iterator[bytes]:
    root = Path(repository_root)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    cloexec = getattr(os, "O_CLOEXEC", 0)
    nonblock = getattr(os, "O_NONBLOCK", 0)
    opened_dirs: list[int] = []
    links: list[tuple[int, str, int, os.stat_result]] = []
    leaf_fd: int | None = None
    try:
        root_before = os.stat(root, follow_symlinks=False)
        if not stat.S_ISDIR(root_before.st_mode):
            _deny("BLOCKED", "REPOSITORY_ROOT", "source root is not a directory")
        _check_owner(root_before, "SOURCE_OWNER", "source root")
        root_fd = os.open(root, os.O_RDONLY | directory | nofollow | cloexec)
        opened_dirs.append(root_fd)
        if not _same_identity(root_before, os.fstat(root_fd)):
            _deny("BLOCKED", "SOURCE_PARENT_DRIFT", "source root changed while opening")
        parent_fd = root_fd
        parts = source["path"].split(os.sep)
        for component in parts[:-1]:
            try:
                before = os.stat(component, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                _deny("INSUFFICIENT", "SOURCE_MISSING", f"source parent is missing: {source['path']}")
            if stat.S_ISLNK(before.st_mode):
                _deny("BLOCKED", "SOURCE_SYMLINK", f"source parent is a symlink: {component}")
            if not stat.S_ISDIR(before.st_mode):
                _deny("BLOCKED", "SOURCE_PARENT_DRIFT", f"source parent is not a directory: {component}")
            _check_owner(before, "SOURCE_OWNER", f"source parent {component}")
            if stat.S_IMODE(before.st_mode) & 0o022:
                _deny("BLOCKED", "SOURCE_MODE", f"source parent is group/world writable: {component}")
            child_fd = os.open(
                component, os.O_RDONLY | directory | nofollow | cloexec, dir_fd=parent_fd
            )
            opened_dirs.append(child_fd)
            opened = os.fstat(child_fd)
            if not _same_identity(before, opened):
                _deny("BLOCKED", "SOURCE_PARENT_DRIFT", f"source parent changed: {component}")
            links.append((parent_fd, component, child_fd, opened))
            parent_fd = child_fd

        leaf = parts[-1]
        try:
            leaf_before = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            _deny("INSUFFICIENT", "SOURCE_MISSING", f"accepted source is missing: {source['path']}")
        if stat.S_ISLNK(leaf_before.st_mode):
            _deny("BLOCKED", "SOURCE_SYMLINK", f"accepted source is a symlink: {source['path']}")
        if not stat.S_ISREG(leaf_before.st_mode):
            _deny("BLOCKED", "SOURCE_TYPE", f"accepted source is not a regular file: {source['path']}")
        if leaf_before.st_nlink != 1:
            _deny("BLOCKED", "SOURCE_HARDLINK", f"accepted source has multiple links: {source['path']}")
        _check_owner(leaf_before, "SOURCE_OWNER", f"accepted source {source['path']}")
        if stat.S_IMODE(leaf_before.st_mode) != source["mode"]:
            _deny("BLOCKED", "SOURCE_MODE", f"accepted source mode drift: {source['path']}")
        leaf_fd = os.open(
            leaf, os.O_RDONLY | nofollow | cloexec | nonblock, dir_fd=parent_fd
        )
        leaf_opened = os.fstat(leaf_fd)
        if not _same_identity(leaf_before, leaf_opened):
            _deny("BLOCKED", "SOURCE_IDENTITY_DRIFT", f"accepted source changed while opening: {source['path']}")
        _boundary(boundary, "source.after_open", path=source["path"])
        while True:
            chunk = os.read(leaf_fd, _CHUNK_SIZE)
            if not chunk:
                break
            yield chunk
        leaf_after = os.fstat(leaf_fd)
        try:
            leaf_entry_after = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            _deny("BLOCKED", "SOURCE_IDENTITY_DRIFT", f"source entry disappeared: {source['path']}")
        if not _same_identity(leaf_opened, leaf_after) or not _same_identity(
            leaf_opened, leaf_entry_after
        ):
            _deny("BLOCKED", "SOURCE_IDENTITY_DRIFT", f"source identity changed after read: {source['path']}")
        for ancestor_fd, name, child_fd, opened in reversed(links):
            try:
                entry_after = os.stat(name, dir_fd=ancestor_fd, follow_symlinks=False)
            except FileNotFoundError:
                _deny("BLOCKED", "SOURCE_PARENT_DRIFT", f"source parent disappeared: {name}")
            if not _same_identity(opened, os.fstat(child_fd)) or not _same_identity(
                opened, entry_after
            ):
                _deny("BLOCKED", "SOURCE_PARENT_DRIFT", f"source parent changed after read: {name}")
        root_after = os.stat(root, follow_symlinks=False)
        if not _same_identity(root_before, root_after) or not _same_identity(
            root_before, os.fstat(root_fd)
        ):
            _deny("BLOCKED", "SOURCE_PARENT_DRIFT", "source root changed after read")
        _boundary(boundary, "source.after_revalidation", path=source["path"])
    except AcceptedSnapshotError:
        raise
    except OSError as error:
        if error.errno in {errno.ELOOP}:
            _deny("BLOCKED", "SOURCE_SYMLINK", f"symlink rejected: {source['path']}")
        if error.errno in {errno.ENOENT, errno.ENOTDIR}:
            _deny("INSUFFICIENT", "SOURCE_MISSING", f"source missing: {source['path']}")
        _deny("BLOCKED", "SOURCE_IO", f"safe source read failed: {error}")
    finally:
        if leaf_fd is not None:
            os.close(leaf_fd)
        for fd in reversed(opened_dirs):
            os.close(fd)


def _git_output(repository_root: Path | str, args: list[str]) -> bytes:
    try:
        completed = subprocess.run(
            ["git", "-C", os.fspath(repository_root), *args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env={
                **os.environ,
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_NO_REPLACE_OBJECTS": "1",
            },
        )
    except OSError as error:
        _deny("BLOCKED", "GIT_OBJECT_UNAVAILABLE", f"cannot invoke Git: {error}")
    if completed.returncode != 0:
        _deny(
            "INSUFFICIENT",
            "GIT_OBJECT_UNAVAILABLE",
            f"pinned Git object is unavailable (exit {completed.returncode})",
        )
    return completed.stdout


def _git_chunks(
    repository_root: Path | str,
    base_commit: str,
    source: dict[str, Any],
    *,
    boundary: Boundary | None,
) -> Iterator[bytes]:
    if _git_output(repository_root, ["cat-file", "-t", base_commit]) != b"commit\n":
        _deny("BLOCKED", "GIT_OBJECT_MISMATCH", "pinned base identity is not a commit")
    listing = _git_output(
        repository_root, ["ls-tree", "-z", base_commit, "--", source["path"]]
    )
    records = [record for record in listing.split(b"\0") if record]
    if len(records) != 1 or b"\t" not in records[0]:
        _deny("INSUFFICIENT", "GIT_OBJECT_UNAVAILABLE", "pinned base path is absent or ambiguous")
    metadata, raw_path = records[0].split(b"\t", 1)
    try:
        mode_text, object_type, object_id = metadata.decode("ascii").split(" ")
        tree_path = raw_path.decode("utf-8")
    except (UnicodeDecodeError, ValueError):
        _deny("BLOCKED", "GIT_OBJECT_MISMATCH", "invalid pinned Git tree record")
    if tree_path != source["path"] or object_type != "blob":
        _deny("BLOCKED", "GIT_OBJECT_MISMATCH", "pinned tree path is not the accepted blob")
    if object_id != source["git_object"]:
        _deny("BLOCKED", "GIT_OBJECT_MISMATCH", "pinned Git object differs from authority")
    git_mode = 0o755 if mode_text == "100755" else 0o644 if mode_text == "100644" else None
    if git_mode != source["mode"]:
        _deny("BLOCKED", "GIT_OBJECT_MISMATCH", "pinned Git mode differs from authority")

    try:
        process = subprocess.Popen(
            ["git", "-C", os.fspath(repository_root), "cat-file", "blob", object_id],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={
                **os.environ,
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_NO_REPLACE_OBJECTS": "1",
            },
        )
    except OSError as error:
        _deny("BLOCKED", "GIT_OBJECT_UNAVAILABLE", f"cannot read pinned Git object: {error}")
    assert process.stdout is not None
    try:
        _boundary(boundary, "git.before_read", path=source["path"], git_object=object_id)
        while True:
            chunk = process.stdout.read(_CHUNK_SIZE)
            if not chunk:
                break
            yield chunk
        process.stdout.close()
        returncode = process.wait()
        if returncode != 0:
            _deny("INSUFFICIENT", "GIT_OBJECT_UNAVAILABLE", f"Git cat-file failed with exit {returncode}")
        _boundary(boundary, "git.after_read", path=source["path"], git_object=object_id)
    except BaseException:
        if process.poll() is None:
            process.kill()
            process.wait()
        raise
    finally:
        if process.stdout and not process.stdout.closed:
            process.stdout.close()
        if process.stderr:
            process.stderr.close()


def _capture_source(
    repository_root: Path | str,
    base_commit: str,
    source: dict[str, Any],
    *,
    boundary: Boundary | None,
) -> BinaryIO:
    if source["source_kind"] == "git_object":
        chunks = _git_chunks(
            repository_root, base_commit, source, boundary=boundary
        )
    else:
        chunks = _current_chunks(repository_root, source, boundary=boundary)
    return _spool_and_verify(chunks, source, boundary=boundary)


def _validate_authority_root(authority_root: Path | str) -> Path:
    root = Path(authority_root)
    if not root.is_absolute():
        _deny("BLOCKED", "AUTHORITY_ROOT", "authority root must be explicitly injected and absolute")
    try:
        raw = os.lstat(root)
        resolved = root.resolve(strict=True)
        selected = os.stat(resolved, follow_symlinks=False)
    except FileNotFoundError:
        _deny("BLOCKED", "AUTHORITY_ROOT", "injected authority root is missing")
    if stat.S_ISLNK(raw.st_mode) or not stat.S_ISDIR(raw.st_mode) or not _same_identity(raw, selected):
        _deny("BLOCKED", "AUTHORITY_ROOT", "authority root must be a real stable directory")
    _check_owner(selected, "AUTHORITY_ROOT", "authority root")
    if stat.S_IMODE(selected.st_mode) != 0o700:
        _deny("BLOCKED", "AUTHORITY_ROOT", "authority root mode must be 0700")
    temporary = Path(tempfile.gettempdir()).resolve(strict=True)
    try:
        common = Path(os.path.commonpath([str(resolved), str(temporary)]))
    except ValueError:
        _deny("BLOCKED", "AUTHORITY_ROOT", "authority root is outside the temporary authority area")
    if common != temporary or resolved == temporary:
        _deny("BLOCKED", "AUTHORITY_ROOT", "synthetic publication is restricted below the temp root")
    return resolved


def _open_owner_directory(parent_fd: int, name: str, *, boundary: Boundary | None) -> int:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    cloexec = getattr(os, "O_CLOEXEC", 0)
    created = False
    try:
        before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        try:
            os.mkdir(name, 0o700, dir_fd=parent_fd)
            created = True
        except FileExistsError:
            pass
        before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
        _deny("BLOCKED", "PUBLICATION_PATH", f"publication ancestor is unsafe: {name}")
    _check_owner(before, "PUBLICATION_PATH", f"publication ancestor {name}")
    if stat.S_IMODE(before.st_mode) != 0o700:
        _deny("BLOCKED", "PUBLICATION_PATH", f"publication ancestor mode is not 0700: {name}")
    fd = os.open(name, os.O_RDONLY | directory | nofollow | cloexec, dir_fd=parent_fd)
    if not _same_directory_identity(before, os.fstat(fd)):
        os.close(fd)
        _deny("BLOCKED", "PUBLICATION_PATH", f"publication ancestor changed: {name}")
    if created:
        try:
            os.fsync(parent_fd)
            _boundary(boundary, "publish.after_directory_fsync", directory=name)
        except BaseException:
            os.close(fd)
            raise
    return fd


def _lock_fd(fd: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX)


def _unlock_fd(fd: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)


def _open_lock(shard_fd: int, sha256: str, *, boundary: Boundary | None) -> int:
    name = f".lock-{sha256}"
    flags = os.O_RDWR | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    created = False
    try:
        fd = os.open(name, flags | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=shard_fd)
        created = True
    except FileExistsError:
        fd = os.open(name, flags, dir_fd=shard_fd)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1:
        os.close(fd)
        _deny("BLOCKED", "PUBLICATION_PATH", "publication lock is unsafe")
    _check_owner(info, "PUBLICATION_PATH", "publication lock")
    try:
        entry = os.stat(name, dir_fd=shard_fd, follow_symlinks=False)
    except FileNotFoundError:
        os.close(fd)
        _deny("BLOCKED", "PUBLICATION_PATH", "publication lock entry disappeared")
    if not _same_identity(info, entry):
        os.close(fd)
        _deny("BLOCKED", "PUBLICATION_PATH", "publication lock entry changed")
    if created:
        try:
            os.fsync(shard_fd)
            _boundary(boundary, "publish.after_lock_entry_fsync", sha256=sha256)
        except BaseException:
            os.close(fd)
            raise
    _lock_fd(fd)
    try:
        locked_entry = os.stat(name, dir_fd=shard_fd, follow_symlinks=False)
    except FileNotFoundError:
        _unlock_fd(fd)
        os.close(fd)
        _deny("BLOCKED", "PUBLICATION_PATH", "publication lock changed before locking")
    if not _same_identity(info, os.fstat(fd)) or not _same_identity(info, locked_entry):
        _unlock_fd(fd)
        os.close(fd)
        _deny("BLOCKED", "PUBLICATION_PATH", "publication lock identity drift")
    return fd


def _read_fd_digest(fd: int, maximum: int) -> tuple[str, int]:
    os.lseek(fd, 0, os.SEEK_SET)
    hasher = hashlib.sha256()
    total = 0
    while True:
        chunk = os.read(fd, _CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > maximum or total > _MAX_ACCEPTED_BLOB_SIZE:
            return "", total
        hasher.update(chunk)
    return hasher.hexdigest(), total


def _validate_final_blob(shard_fd: int, sha256: str, size: int) -> bool:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    cloexec = getattr(os, "O_CLOEXEC", 0)
    try:
        before = os.stat(sha256, dir_fd=shard_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_IMODE(before.st_mode) != 0o600
        or before.st_nlink != 1
    ):
        _deny("BLOCKED", "PUBLICATION_CONFLICT", "existing accepted blob is unsafe")
    _check_owner(before, "PUBLICATION_CONFLICT", "existing accepted blob")
    fd = os.open(sha256, os.O_RDONLY | nofollow | cloexec, dir_fd=shard_fd)
    try:
        if not _same_identity(before, os.fstat(fd)):
            _deny("BLOCKED", "PUBLICATION_CONFLICT", "accepted blob changed while opening")
        actual_sha, actual_size = _read_fd_digest(fd, size)
        if actual_sha != sha256 or actual_size != size:
            _deny("BLOCKED", "PUBLICATION_CONFLICT", "existing blob content does not match its address")
        if not _same_identity(before, os.fstat(fd)):
            _deny("BLOCKED", "PUBLICATION_CONFLICT", "accepted blob changed while reading")
    finally:
        os.close(fd)
    return True


def _recover_staging(
    shard_fd: int,
    sha256: str,
    size: int,
    *,
    boundary: Boundary | None,
) -> None:
    prefix = f".stage-{sha256}-"
    final_present = False
    try:
        os.stat(sha256, dir_fd=shard_fd, follow_symlinks=False)
        final_present = True
    except FileNotFoundError:
        pass
    for name in sorted(os.listdir(shard_fd)):
        if not name.startswith(prefix):
            continue
        info = os.stat(name, dir_fd=shard_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != os.geteuid()
            or info.st_nlink not in {1, 2}
        ):
            _deny("BLOCKED", "PUBLICATION_CONFLICT", "controlled staging entry is unsafe")
        stage_fd = os.open(
            name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
            dir_fd=shard_fd,
        )
        try:
            actual_sha, actual_size = _read_fd_digest(stage_fd, size)
            complete = actual_sha == sha256 and actual_size == size
            if complete and not final_present:
                os.fsync(stage_fd)
        finally:
            os.close(stage_fd)
        if complete and not final_present:
            try:
                os.link(
                    name,
                    sha256,
                    src_dir_fd=shard_fd,
                    dst_dir_fd=shard_fd,
                    follow_symlinks=False,
                )
                final_present = True
                os.fsync(shard_fd)
                _boundary(boundary, "publish.after_recovery_link", sha256=sha256)
            except FileExistsError:
                final_present = True
        os.unlink(name, dir_fd=shard_fd)
        os.fsync(shard_fd)
        _boundary(
            boundary,
            "publish.after_recovery_cleanup",
            sha256=sha256,
            complete=complete,
        )


def _validate_publication_chain(
    authority_root: Path,
    root_fd: int,
    root_opened: os.stat_result,
    store_fd: int,
    shard_fd: int,
    shard_name: str,
) -> None:
    try:
        root_entry = os.stat(authority_root, follow_symlinks=False)
        store_entry = os.stat("accepted-blobs", dir_fd=root_fd, follow_symlinks=False)
        shard_entry = os.stat(shard_name, dir_fd=store_fd, follow_symlinks=False)
    except FileNotFoundError:
        _deny("BLOCKED", "PUBLICATION_PATH", "publication ancestor disappeared")
    if not _same_directory_identity(root_opened, os.fstat(root_fd)) or not _same_directory_identity(
        root_opened, root_entry
    ):
        _deny("BLOCKED", "PUBLICATION_PATH", "authority root identity drift")
    if not _same_directory_identity(os.fstat(store_fd), store_entry):
        _deny("BLOCKED", "PUBLICATION_PATH", "accepted-blobs ancestor identity drift")
    if not _same_directory_identity(os.fstat(shard_fd), shard_entry):
        _deny("BLOCKED", "PUBLICATION_PATH", "accepted blob shard identity drift")


def _publish_spool(
    spool: BinaryIO,
    *,
    authority_root: Path,
    sha256: str,
    size: int,
    plan_id: str,
    boundary: Boundary | None,
) -> str:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    cloexec = getattr(os, "O_CLOEXEC", 0)
    root_opened = os.stat(authority_root, follow_symlinks=False)
    root_fd = os.open(authority_root, os.O_RDONLY | directory | nofollow | cloexec)
    if not _same_directory_identity(root_opened, os.fstat(root_fd)):
        os.close(root_fd)
        _deny("BLOCKED", "PUBLICATION_PATH", "authority root changed while opening")
    store_fd: int | None = None
    shard_fd: int | None = None
    lock_fd: int | None = None
    stage_fd: int | None = None
    stage_name: str | None = None
    linked = False
    try:
        store_fd = _open_owner_directory(root_fd, "accepted-blobs", boundary=boundary)
        shard_fd = _open_owner_directory(store_fd, sha256[:2], boundary=boundary)
        lock_fd = _open_lock(shard_fd, sha256, boundary=boundary)
        _recover_staging(shard_fd, sha256, size, boundary=boundary)
        if _validate_final_blob(shard_fd, sha256, size):
            _validate_publication_chain(
                authority_root,
                root_fd,
                root_opened,
                store_fd,
                shard_fd,
                sha256[:2],
            )
            return accepted_blob_relative_path(sha256)

        stage_name = f".stage-{sha256}-{plan_id[:16]}-{secrets.token_hex(8)}"
        stage_fd = os.open(
            stage_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | cloexec | nofollow,
            0o600,
            dir_fd=shard_fd,
        )
        stage_info = os.fstat(stage_fd)
        if (
            not stat.S_ISREG(stage_info.st_mode)
            or stat.S_IMODE(stage_info.st_mode) != 0o600
            or stage_info.st_nlink != 1
            or stage_info.st_uid != os.geteuid()
        ):
            _deny("BLOCKED", "PUBLICATION_PATH", "new staging file is unsafe")
        os.fsync(shard_fd)
        _boundary(boundary, "publish.after_stage_entry_fsync", sha256=sha256)
        spool.seek(0)
        written = 0
        while True:
            chunk = spool.read(_CHUNK_SIZE)
            if not chunk:
                break
            view = memoryview(chunk)
            while view:
                count = os.write(stage_fd, view)
                if count <= 0:
                    raise OSError(errno.EIO, "short staging write")
                written += count
                view = view[count:]
            _boundary(boundary, "publish.after_write", sha256=sha256, size=written)
        if written != size:
            raise OSError(errno.EIO, "staging size mismatch")
        os.fsync(stage_fd)
        _boundary(boundary, "publish.after_file_fsync", sha256=sha256)
        os.close(stage_fd)
        stage_fd = None

        try:
            os.link(
                stage_name,
                sha256,
                src_dir_fd=shard_fd,
                dst_dir_fd=shard_fd,
                follow_symlinks=False,
            )
            linked = True
        except FileExistsError:
            if not _validate_final_blob(shard_fd, sha256, size):
                _deny("BLOCKED", "PUBLICATION_CONFLICT", "no-replace publication conflict")
        _boundary(boundary, "publish.after_link", sha256=sha256, linked=linked)
        os.fsync(shard_fd)
        _boundary(boundary, "publish.after_final_dir_fsync", sha256=sha256)
        os.unlink(stage_name, dir_fd=shard_fd)
        stage_name = None
        os.fsync(shard_fd)
        _boundary(boundary, "publish.after_stage_unlink", sha256=sha256)
        if not _validate_final_blob(shard_fd, sha256, size):
            _deny("BLOCKED", "PUBLICATION_CONFLICT", "published blob disappeared")
        _validate_publication_chain(
            authority_root,
            root_fd,
            root_opened,
            store_fd,
            shard_fd,
            sha256[:2],
        )
        return accepted_blob_relative_path(sha256)
    except AcceptedSnapshotError:
        if stage_fd is not None:
            os.close(stage_fd)
            stage_fd = None
        if stage_name is not None and shard_fd is not None:
            try:
                os.unlink(stage_name, dir_fd=shard_fd)
                os.fsync(shard_fd)
            except FileNotFoundError:
                pass
        raise
    except Exception as error:
        if stage_fd is not None:
            os.close(stage_fd)
            stage_fd = None
        if stage_name is not None and shard_fd is not None:
            try:
                os.unlink(stage_name, dir_fd=shard_fd)
                os.fsync(shard_fd)
            except FileNotFoundError:
                pass
        _deny("BLOCKED", "PUBLICATION_IO", f"accepted blob publication failed: {error}")
    finally:
        if stage_fd is not None:
            os.close(stage_fd)
        if lock_fd is not None:
            _unlock_fd(lock_fd)
            os.close(lock_fd)
        if shard_fd is not None:
            os.close(shard_fd)
        if store_fd is not None:
            os.close(store_fd)
        os.close(root_fd)


def capture_plan(
    plan: object,
    *,
    repository_root: Path | str,
    authority_root: Path | str,
    captured_at: str,
    boundary: Boundary | None = None,
) -> dict[str, Any]:
    """Revalidate all selected bytes and publish content-addressed snapshots."""

    selected = _validate_plan(plan, repository_root)
    capture_time = _parse_time(captured_at, "captured_at", code="RECEIPT_SCHEMA")
    planned_time = _parse_time(selected["planned_at"], "planned_at", code="PLAN_SCHEMA")
    if capture_time < planned_time:
        _deny("BLOCKED", "RECEIPT_SCHEMA", "capture timestamp predates plan")
    root = _validate_authority_root(authority_root)
    authority = selected["authority_cut"]
    base_commit = authority["repository"]["base_commit"]
    blobs: list[dict[str, Any]] = []
    for source in selected["sources"]:
        spool = _capture_source(
            repository_root, base_commit, source, boundary=boundary
        )
        try:
            relative_path = _publish_spool(
                spool,
                authority_root=root,
                sha256=source["final_sha256"],
                size=source["final_size"],
                plan_id=selected["plan_id"],
                boundary=boundary,
            )
        finally:
            spool.close()
        blob_body = {
            "task_id": source["task_id"],
            "generation": source["generation"],
            "operation": source["operation"],
            "path": source["path"],
            "source_kind": source["source_kind"],
            "observed_at": captured_at,
            "relative_path": relative_path,
            "sha256": source["final_sha256"],
            "size": source["final_size"],
        }
        blobs.append({**blob_body, "receipt_identity": canonical_sha256(blob_body)})
    body = {
        "schema": CAPTURE_RECEIPT_SCHEMA,
        "plan_id": selected["plan_id"],
        "authority_cut_sha256": selected["authority_cut_sha256"],
        "historical_authority_recorded_at": authority["recorded_at"],
        "captured_at": captured_at,
        "blobs": blobs,
        "execution_authorized": False,
        "composition_ready": False,
        "later_coordinator_authority_required": True,
    }
    receipt = {**body, "receipt_id": canonical_sha256(body)}
    validate_capture_receipt(receipt)
    return receipt


def validate_capture_receipt(receipt: object) -> dict[str, Any]:
    """Validate the closed public, data-only capture receipt."""

    if not _is_plain_json(receipt) or type(receipt) is not dict or set(receipt) != _RECEIPT_KEYS:
        _deny("BLOCKED", "RECEIPT_SCHEMA", "capture receipt does not match the closed schema")
    selected = receipt
    if (
        selected["schema"] != CAPTURE_RECEIPT_SCHEMA
        or selected["execution_authorized"] is not False
        or selected["composition_ready"] is not False
        or selected["later_coordinator_authority_required"] is not True
    ):
        _deny("BLOCKED", "RECEIPT_SCHEMA", "receipt authority flags are invalid")
    for label in ("receipt_id", "plan_id", "authority_cut_sha256"):
        if type(selected[label]) is not str or not _SHA256_RE.fullmatch(selected[label]):
            _deny("BLOCKED", "RECEIPT_SCHEMA", f"invalid receipt field: {label}")
    historical = _parse_time(
        selected["historical_authority_recorded_at"],
        "historical_authority_recorded_at",
        code="RECEIPT_SCHEMA",
    )
    current = _parse_time(selected["captured_at"], "captured_at", code="RECEIPT_SCHEMA")
    if current < historical:
        _deny("BLOCKED", "RECEIPT_SCHEMA", "current observation predates historical authority")
    if type(selected["blobs"]) is not list or not selected["blobs"]:
        _deny("BLOCKED", "RECEIPT_SCHEMA", "receipt has no accepted blobs")
    seen_sources: set[tuple[str, int, str]] = set()
    for blob in selected["blobs"]:
        if type(blob) is not dict or set(blob) != _BLOB_RECEIPT_KEYS:
            _deny("BLOCKED", "RECEIPT_SCHEMA", "blob receipt does not match the closed schema")
        if (
            type(blob["task_id"]) is not str
            or not _SAFE_ID_RE.fullmatch(blob["task_id"])
            or type(blob["generation"]) is not int
            or blob["generation"] < 1
            or blob["operation"] not in {"add", "modify", "unchanged"}
            or blob["source_kind"] not in {"current", "git_object"}
        ):
            _deny("BLOCKED", "RECEIPT_SCHEMA", "blob authority fields are invalid")
        try:
            safe_path = _safe_relative_path(blob["path"])
        except AcceptedSnapshotError as error:
            raise AcceptedSnapshotError(
                "BLOCKED", "RECEIPT_SCHEMA", f"blob path is invalid: {error}"
            ) from error
        source_identity = (blob["task_id"], blob["generation"], safe_path)
        if source_identity in seen_sources:
            _deny("BLOCKED", "RECEIPT_SCHEMA", "receipt contains a duplicate source identity")
        seen_sources.add(source_identity)
        if blob["observed_at"] != selected["captured_at"]:
            _deny("BLOCKED", "RECEIPT_SCHEMA", "blob current timestamp mismatch")
        if (
            type(blob["sha256"]) is not str
            or not _SHA256_RE.fullmatch(blob["sha256"])
            or blob["relative_path"] != accepted_blob_relative_path(blob["sha256"])
            or type(blob["size"]) is not int
            or blob["size"] < 0
            or blob["size"] > _MAX_ACCEPTED_BLOB_SIZE
            or type(blob["receipt_identity"]) is not str
            or not _SHA256_RE.fullmatch(blob["receipt_identity"])
        ):
            _deny("BLOCKED", "RECEIPT_SCHEMA", "blob address fields are invalid")
        blob_body = {key: value for key, value in blob.items() if key != "receipt_identity"}
        if blob["receipt_identity"] != canonical_sha256(blob_body):
            _deny("BLOCKED", "RECEIPT_SCHEMA", "blob receipt identity mismatch")
    body = {key: value for key, value in selected.items() if key != "receipt_id"}
    if selected["receipt_id"] != canonical_sha256(body):
        _deny("BLOCKED", "RECEIPT_SCHEMA", "capture receipt identity mismatch")
    return selected


__all__ = [
    "AUTHORITY_CUT_SCHEMA",
    "CAPTURE_PLAN_SCHEMA",
    "CAPTURE_RECEIPT_SCHEMA",
    "AcceptedSnapshotError",
    "accepted_blob_relative_path",
    "canonical_sha256",
    "capture_plan",
    "make_capture_plan",
    "repository_root_identity",
    "validate_authority_cut",
    "validate_capture_receipt",
]
