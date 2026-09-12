#!/usr/bin/env python3
"""Append-only control plane for the Intent Guardian remediation program.

Workers may report implementation evidence, but only the configured coordinator
can promote work beyond ``implemented`` or close the program.  The event log is
the authority; JSON status output is a projection rebuilt from that log.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
from typing import Any, Iterator
import unicodedata

from file_lock import lock_exclusive_nonblocking, unlock


MANIFEST_SCHEMA = "sulde-guardian-program-manifest-v1"
TASK_SCHEMA = "sulde-guardian-program-task-v1"
EVENT_SCHEMA = "sulde-guardian-program-event-v1"
STATUS_SCHEMA = "sulde-guardian-program-status-v1"
EVIDENCE_SCHEMA = "sulde-guardian-program-evidence-v1"
COMPLETION_SNAPSHOT_SCHEMA = "sulde-guardian-program-completion-snapshot-v1"
PREPARED_COMPLETION_SCHEMA = "sulde-guardian-program-prepared-completion-v1"
AUTHORITY_ENV = "SULDE_GUARDIAN_PROGRAM_AUTHORITY"
AUTHORITY_FILE = ".coordinator-authority"
AUTHORITY_RECOVERY_DOMAIN = "sulde-guardian-program-authority-recovery-v1"
COMPLETION_DIRECTORY = "completion-evidence"

TASK_STATES = (
    "planned",
    "ready",
    "running",
    "implemented",
    "task_verified",
    "integrated",
    "system_verified",
    "accepted",
    "blocked",
    "superseded",
)

TRANSITIONS = {
    "planned": {"ready", "blocked", "superseded"},
    "ready": {"running", "blocked", "superseded"},
    "running": {"implemented", "blocked"},
    "implemented": {"running", "task_verified", "blocked"},
    "task_verified": {"running", "integrated", "blocked"},
    "integrated": {"running", "system_verified", "blocked"},
    "system_verified": {"running", "accepted", "blocked"},
    "accepted": set(),
    "blocked": {"ready", "running", "superseded"},
    "superseded": set(),
}

CAPABILITY_TIERS = {"deep", "balanced", "light"}
FINDING_DISPOSITIONS = {
    "fixed_current",
    "transferred",
    "new_task",
    "deferred_human",
    "rejected_with_evidence",
}
FINDING_EVIDENCE_STATUSES = {"verified", "inconclusive", "constructed"}
EVIDENCE_VERDICTS = {"pass", "fail", "inconclusive"}
EVIDENCE_GATE_ORDER = (
    "implemented",
    "task_verified",
    "integrated",
    "system_verified",
    "accepted",
)


class GuardianProgramError(RuntimeError):
    """The program control plane is unavailable or internally inconsistent."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise GuardianProgramError(f"value is not lossless JSON: {error}") from error


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _file_digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _require_identifier(value: Any, *, label: str) -> str:
    text = str(value or "")
    if not text or len(text) > 100:
        raise GuardianProgramError(f"{label} must be 1..100 characters")
    if not all(character.isalnum() or character in "-_." for character in text):
        raise GuardianProgramError(f"{label} contains unsupported characters")
    return text


def _require_text(value: Any, *, label: str, limit: int = 4000) -> str:
    text = str(value or "").strip()
    if not text or len(text) > limit:
        raise GuardianProgramError(f"{label} must be 1..{limit} characters")
    return text


def _require_string_list(value: Any, *, label: str) -> list[str]:
    if not isinstance(value, list):
        raise GuardianProgramError(f"{label} must be a list")
    result: list[str] = []
    for index, item in enumerate(value):
        result.append(_require_text(item, label=f"{label}[{index}]", limit=1000))
    if len(result) != len(set(result)):
        raise GuardianProgramError(f"{label} must not contain duplicates")
    return result


def _require_sha256(value: Any, *, label: str) -> str:
    text = str(value or "")
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise GuardianProgramError(f"{label} must be a lowercase SHA-256 digest")
    return text


def _validate_finding_resolution_channels(
    disposition: str,
    *,
    linked_task: str,
    evidence_id: str,
    human_evidence: str,
) -> None:
    populated = {
        "linked_task": bool(linked_task),
        "evidence_id": bool(evidence_id),
        "human_evidence": bool(human_evidence),
    }
    expected = {
        "fixed_current": set(),
        "transferred": {"linked_task"},
        "new_task": {"linked_task"},
        "deferred_human": {"human_evidence"},
        "rejected_with_evidence": {"evidence_id"},
    }[disposition]
    observed = {name for name, present in populated.items() if present}
    if observed != expected:
        raise GuardianProgramError(
            "finding resolution channels do not match the selected disposition"
        )


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise GuardianProgramError(f"cannot read JSON object: {path.name}: {error}") from error
    if not isinstance(value, dict):
        raise GuardianProgramError(f"JSON root must be an object: {path.name}")
    return value


def _load_json_bytes(payload: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GuardianProgramError(f"cannot read JSON object: {label}: {error}") from error
    if not isinstance(value, dict):
        raise GuardianProgramError(f"JSON root must be an object: {label}")
    return value


def _validate_manifest(value: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "schema",
        "program_id",
        "objective",
        "coordinator",
        "requirements",
        "program_evidence_required",
        "allow_human_deferred",
    }
    if set(value) != allowed:
        raise GuardianProgramError("manifest fields do not match the v1 schema")
    if value.get("schema") != MANIFEST_SCHEMA:
        raise GuardianProgramError("manifest schema is unsupported")
    requirements = value.get("requirements")
    if not isinstance(requirements, list) or not requirements:
        raise GuardianProgramError("manifest requirements must be a non-empty list")
    normalized_requirements: list[dict[str, Any]] = []
    requirement_ids: set[str] = set()
    for index, row in enumerate(requirements):
        if not isinstance(row, dict) or set(row) != {"id", "title", "acceptance"}:
            raise GuardianProgramError(f"requirements[{index}] does not match the schema")
        requirement_id = _require_identifier(row["id"], label="requirement id")
        if requirement_id in requirement_ids:
            raise GuardianProgramError("requirement ids must be unique")
        requirement_ids.add(requirement_id)
        acceptance = _require_string_list(
            row["acceptance"], label="requirement acceptance"
        )
        if not acceptance:
            raise GuardianProgramError("requirement acceptance must be non-empty")
        normalized_requirements.append(
            {
                "id": requirement_id,
                "title": _require_text(row["title"], label="requirement title"),
                "acceptance": acceptance,
            }
        )
    allow_human_deferred = value["allow_human_deferred"]
    if not isinstance(allow_human_deferred, bool):
        raise GuardianProgramError("allow_human_deferred must be a JSON boolean")
    return {
        "schema": MANIFEST_SCHEMA,
        "program_id": _require_identifier(value["program_id"], label="program_id"),
        "objective": _require_text(value["objective"], label="objective"),
        "coordinator": _require_identifier(value["coordinator"], label="coordinator"),
        "requirements": normalized_requirements,
        "program_evidence_required": _require_string_list(
            value["program_evidence_required"], label="program_evidence_required"
        ),
        "allow_human_deferred": allow_human_deferred,
    }


def _validate_task(value: dict[str, Any]) -> dict[str, Any]:
    required_fields = {
        "schema",
        "task_id",
        "title",
        "owner",
        "capability_tier",
        "base_commit",
        "depends_on",
        "owned_paths",
        "requirements",
        "acceptance",
        "evidence_gates",
    }
    fields = set(value)
    if fields != required_fields and fields != required_fields | {"supersedes"}:
        raise GuardianProgramError("task fields do not match the v1 schema")
    if value.get("schema") != TASK_SCHEMA:
        raise GuardianProgramError("task fields do not match the v1 schema")
    tier = str(value.get("capability_tier") or "")
    if tier not in CAPABILITY_TIERS:
        raise GuardianProgramError("task capability_tier is invalid")
    gates = value.get("evidence_gates")
    if not isinstance(gates, dict) or any(state not in TASK_STATES for state in gates):
        raise GuardianProgramError("task evidence_gates is invalid")
    normalized_gates: dict[str, list[str]] = {}
    for state, kinds in gates.items():
        normalized_gates[state] = _require_string_list(
            kinds, label=f"evidence_gates.{state}"
        )
    required_gate_states = {"implemented", "task_verified", "integrated", "system_verified"}
    if set(normalized_gates) != required_gate_states or any(
        not normalized_gates[state] for state in required_gate_states
    ):
        raise GuardianProgramError(
            "task evidence_gates must define non-empty implemented, task_verified, "
            "integrated and system_verified gates"
        )
    owned_paths = _require_string_list(value["owned_paths"], label="owned_paths")
    for path in owned_paths:
        parts = path.split("/")
        recursive_subtree = path.endswith("/**")
        literal_scope = path[:-3] if recursive_subtree else path
        if (
            path.startswith("/")
            or "\\" in path
            or any(part in {"", ".", ".."} for part in parts)
            or "/".join(parts) != path
            or any(token in literal_scope for token in ("*", "?", "[", "]"))
            or (not recursive_subtree and any(token in path for token in ("*", "?", "[", "]")))
        ):
            raise GuardianProgramError(
                "owned_paths must use canonical relative POSIX exact paths or a terminal /** subtree"
            )
    acceptance = _require_string_list(value["acceptance"], label="acceptance")
    if not owned_paths or not acceptance:
        raise GuardianProgramError("task owned_paths and acceptance must be non-empty")
    normalized_task = {
        "schema": TASK_SCHEMA,
        "task_id": _require_identifier(value["task_id"], label="task_id"),
        "title": _require_text(value["title"], label="task title"),
        "owner": _require_identifier(value["owner"], label="task owner"),
        "capability_tier": tier,
        "base_commit": _require_text(value["base_commit"], label="base_commit", limit=200),
        "depends_on": _require_string_list(value["depends_on"], label="depends_on"),
        "supersedes": _require_string_list(value.get("supersedes", []), label="supersedes"),
        "owned_paths": owned_paths,
        "requirements": _require_string_list(value["requirements"], label="requirements"),
        "acceptance": acceptance,
        "evidence_gates": normalized_gates,
    }
    if set(normalized_task["depends_on"]) & set(normalized_task["supersedes"]):
        raise GuardianProgramError("a task cannot depend on a task it supersedes")
    return normalized_task


def _ownership_key(pattern: str) -> str:
    """Return a conservative cross-filesystem key for ownership comparisons."""

    return unicodedata.normalize("NFKC", pattern).casefold()


def _ownership_scope(pattern: str) -> tuple[str, bool]:
    recursive_subtree = pattern.endswith("/**")
    literal_scope = pattern[:-3] if recursive_subtree else pattern
    return _ownership_key(literal_scope), recursive_subtree


def _ownership_paths_overlap(left: str, right: str) -> bool:
    left_scope, left_recursive = _ownership_scope(left)
    right_scope, right_recursive = _ownership_scope(right)
    if left_scope == right_scope:
        return True
    if left_recursive and right_scope.startswith(f"{left_scope}/"):
        return True
    if right_recursive and left_scope.startswith(f"{right_scope}/"):
        return True
    return False


def _ownership_conflicts(
    task: dict[str, Any], tasks: dict[str, dict[str, Any]]
) -> list[dict[str, str]]:
    conflicts: list[dict[str, str]] = []
    serialized_after = set(task["depends_on"]) | set(task.get("supersedes", []))
    for existing in tasks.values():
        if existing["task_id"] in serialized_after or existing["state"] == "superseded":
            continue
        for new_path in task["owned_paths"]:
            for existing_path in existing["owned_paths"]:
                if _ownership_paths_overlap(new_path, existing_path):
                    conflicts.append(
                        {
                            "task_id": existing["task_id"],
                            "new_path": new_path,
                            "existing_path": existing_path,
                        }
                    )
    return conflicts


def _supersession_claimants(
    tasks: dict[str, dict[str, Any]], task_id: str
) -> list[str]:
    return [
        task["task_id"]
        for task in tasks.values()
        if task_id in task.get("supersedes", []) and task["state"] != "superseded"
    ]


def _terminal_successor(
    tasks: dict[str, dict[str, Any]], task: dict[str, Any]
) -> dict[str, Any] | None:
    current = task
    seen: set[str] = set()
    while current["state"] == "superseded":
        task_id = current["task_id"]
        if task_id in seen:
            raise GuardianProgramError("task supersession graph contains a cycle")
        seen.add(task_id)
        current = tasks.get(current["superseded_by"])
        if current is None:
            return None
    return current


def _dependency_is_accepted(
    tasks: dict[str, dict[str, Any]], dependency_id: str
) -> bool:
    dependency = tasks[dependency_id]
    terminal = _terminal_successor(tasks, dependency)
    return terminal is not None and terminal["state"] == "accepted"


def _terminal_evidence(
    evidence_rows: dict[str, dict[str, Any]], evidence: dict[str, Any]
) -> dict[str, Any] | None:
    current = evidence
    seen: set[str] = set()
    while current["superseded_by"]:
        evidence_id = current["evidence_id"]
        if evidence_id in seen:
            raise GuardianProgramError("evidence supersession graph contains a cycle")
        seen.add(evidence_id)
        current = evidence_rows.get(current["superseded_by"])
        if current is None:
            return None
    return current


def _replacement_preserves_semantics(
    evidence: dict[str, Any], replacement: dict[str, Any]
) -> bool:
    if evidence["kind"] == "finding_resolution":
        return set(evidence["findings"]).issubset(replacement["findings"])
    return True


def _validate_evidence_document(
    value: dict[str, Any],
    *,
    scope: str,
    task_id: str,
    kind: str,
) -> dict[str, Any]:
    allowed = {
        "schema",
        "scope",
        "task_id",
        "kind",
        "baseline",
        "run_id",
        "verdict",
        "summary",
        "facts",
        "requirements",
        "findings",
        "acceptance",
        "commands",
        "artifacts",
    }
    if set(value) != allowed or value.get("schema") != EVIDENCE_SCHEMA:
        raise GuardianProgramError("evidence document fields do not match the v1 schema")
    if value.get("scope") != scope or str(value.get("task_id") or "") != task_id:
        raise GuardianProgramError("evidence document scope or task binding does not match")
    if value.get("kind") != kind:
        raise GuardianProgramError("evidence document kind does not match")
    baseline = _require_text(value.get("baseline"), label="evidence baseline", limit=500)
    run_id = _require_identifier(value.get("run_id"), label="evidence run_id")
    verdict = str(value.get("verdict") or "")
    if verdict not in EVIDENCE_VERDICTS:
        raise GuardianProgramError("evidence document verdict is invalid")
    facts = _require_string_list(value.get("facts"), label="evidence facts")
    if not facts:
        raise GuardianProgramError("evidence document must contain at least one fact")
    requirements = _require_string_list(
        value.get("requirements"), label="evidence requirements"
    )
    if scope == "program" and requirements:
        raise GuardianProgramError("program evidence must not claim task requirements")
    findings = _require_string_list(value.get("findings"), label="evidence findings")
    for finding_id in findings:
        _require_identifier(finding_id, label="evidence finding id")
    if scope == "program" and findings:
        raise GuardianProgramError("program evidence must not claim task findings")
    raw_acceptance = value.get("acceptance")
    if not isinstance(raw_acceptance, list):
        raise GuardianProgramError("evidence acceptance must be a list")
    acceptance: list[dict[str, str]] = []
    acceptance_keys: set[tuple[str, str]] = set()
    for index, row in enumerate(raw_acceptance):
        if not isinstance(row, dict) or set(row) != {
            "requirement_id",
            "clause",
            "fact",
        }:
            raise GuardianProgramError(
                f"evidence acceptance[{index}] does not match the schema"
            )
        normalized_row = {
            "requirement_id": _require_identifier(
                row["requirement_id"], label="acceptance requirement_id"
            ),
            "clause": _require_text(row["clause"], label="acceptance clause"),
            "fact": _require_text(row["fact"], label="acceptance fact"),
        }
        key = (normalized_row["requirement_id"], normalized_row["clause"])
        if key in acceptance_keys:
            raise GuardianProgramError(
                "evidence acceptance must map each requirement clause exactly once"
            )
        acceptance_keys.add(key)
        acceptance.append(normalized_row)
    if scope == "program" and acceptance:
        raise GuardianProgramError("program evidence must not claim task acceptance clauses")
    raw_commands = value.get("commands")
    if not isinstance(raw_commands, list):
        raise GuardianProgramError("evidence commands must be a list")
    commands: list[dict[str, Any]] = []
    for index, row in enumerate(raw_commands):
        if not isinstance(row, dict) or set(row) != {"argv", "exit_code", "result"}:
            raise GuardianProgramError(f"evidence commands[{index}] does not match the schema")
        argv = _require_string_list(row["argv"], label=f"evidence commands[{index}].argv")
        if not argv:
            raise GuardianProgramError("evidence command argv must not be empty")
        exit_code = row["exit_code"]
        if exit_code is not None and (not isinstance(exit_code, int) or isinstance(exit_code, bool)):
            raise GuardianProgramError("evidence command exit_code must be an integer or null")
        result = str(row.get("result") or "")
        if result not in EVIDENCE_VERDICTS:
            raise GuardianProgramError("evidence command result is invalid")
        commands.append({"argv": argv, "exit_code": exit_code, "result": result})
    raw_artifacts = value.get("artifacts")
    if not isinstance(raw_artifacts, list):
        raise GuardianProgramError("evidence artifacts must be a list")
    artifacts: list[dict[str, str]] = []
    for index, row in enumerate(raw_artifacts):
        if not isinstance(row, dict) or set(row) != {"path", "sha256"}:
            raise GuardianProgramError(f"evidence artifacts[{index}] does not match the schema")
        raw_path = _require_text(
            row["path"], label=f"evidence artifacts[{index}].path", limit=1000
        )
        path = Path(raw_path)
        if path.is_absolute() or ".." in path.parts:
            raise GuardianProgramError("evidence artifact paths must stay relative to the program root")
        artifacts.append(
            {
                "path": path.as_posix(),
                "sha256": _require_sha256(
                    row["sha256"], label=f"evidence artifacts[{index}].sha256"
                ),
            }
        )
    if not commands and not artifacts:
        raise GuardianProgramError("evidence must bind at least one command or artifact")
    if verdict == "pass" and any(
        command["result"] != "pass" or command["exit_code"] != 0
        for command in commands
    ):
        raise GuardianProgramError(
            "passing evidence requires successful commands with zero exit codes"
        )
    return {
        "schema": EVIDENCE_SCHEMA,
        "scope": scope,
        "task_id": task_id,
        "kind": kind,
        "baseline": baseline,
        "run_id": run_id,
        "verdict": verdict,
        "summary": _require_text(value.get("summary"), label="evidence summary"),
        "facts": facts,
        "requirements": requirements,
        "findings": findings,
        "acceptance": acceptance,
        "commands": commands,
        "artifacts": artifacts,
    }


def _evidence_artifact_errors(
    root: Path, document: dict[str, Any]
) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    resolved_root = root.resolve(strict=True)
    for artifact in document["artifacts"]:
        raw_candidate = root / artifact["path"]
        if raw_candidate.is_symlink():
            errors.append({"path": artifact["path"], "reason": "symlink"})
            continue
        candidate = raw_candidate.resolve(strict=False)
        try:
            candidate.relative_to(resolved_root)
        except ValueError:
            errors.append({"path": artifact["path"], "reason": "outside_root"})
            continue
        if not candidate.is_file() or candidate.is_symlink():
            errors.append({"path": artifact["path"], "reason": "missing_or_symlink"})
            continue
        if candidate.stat().st_nlink != 1:
            errors.append({"path": artifact["path"], "reason": "hardlink_alias"})
            continue
        if _file_digest(candidate) != artifact["sha256"]:
            errors.append({"path": artifact["path"], "reason": "digest_mismatch"})
    return errors


def _evidence_binding_reason(
    status: dict[str, Any], evidence: dict[str, Any], document: dict[str, Any]
) -> str:
    expected_baseline = (
        status["tasks"][evidence["task_id"]]["base_commit"]
        if evidence["scope"] == "task"
        else f"program:{status['program_id']}"
    )
    if evidence["baseline"] != expected_baseline:
        return "baseline_binding_mismatch"
    if evidence["scope"] == "task":
        task = status["tasks"][evidence["task_id"]]
        if (
            evidence["recorded_sequence"] <= task["evidence_floor_sequence"]
            or evidence["run_id"] != task["verification_run_id"]
        ):
            return "verification_run_binding_mismatch"
    if (
        document["verdict"] != evidence["verdict"]
        or document["summary"] != evidence["summary"]
        or document["requirements"] != evidence["requirements"]
        or document["findings"] != evidence["findings"]
        or document["acceptance"] != evidence["acceptance"]
        or document["baseline"] != evidence["baseline"]
        or document["run_id"] != evidence["run_id"]
    ):
        return "binding_mismatch"
    if evidence["kind"] == "requirement_traceability":
        if evidence["scope"] != "task" or set(document["requirements"]) != set(
            status["tasks"][evidence["task_id"]]["requirements"]
        ):
            return "requirement_binding_mismatch"
        expected_clauses = {
            (requirement_id, clause)
            for requirement_id in status["tasks"][evidence["task_id"]]["requirements"]
            for clause in status["requirements"][requirement_id]["acceptance"]
        }
        observed_clauses = {
            (item["requirement_id"], item["clause"])
            for item in document["acceptance"]
        }
        if observed_clauses != expected_clauses:
            return "acceptance_binding_mismatch"
    if evidence["kind"] == "finding_resolution":
        if evidence["scope"] != "task" or not document["findings"]:
            return "finding_binding_mismatch"
        task = status["tasks"][evidence["task_id"]]
        for finding_id in document["findings"]:
            finding = status["findings"].get(finding_id)
            if not finding or (
                finding["task_id"] != evidence["task_id"]
                and finding_id not in task["finding_obligations"]
            ):
                return "finding_binding_mismatch"
    return ""


def _secure_root(root: Path, *, create: bool) -> Path:
    root = root.expanduser().absolute()
    if create:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        info = root.lstat()
    except OSError as error:
        raise GuardianProgramError(f"program root is unavailable: {error}") from error
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise GuardianProgramError("program root must be a real directory")
    if hasattr(os, "geteuid") and info.st_uid != os.geteuid():
        raise GuardianProgramError("program root owner does not match the current user")
    if stat.S_IMODE(info.st_mode) & 0o022:
        raise GuardianProgramError("program root must not be group/other writable")
    return root


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_once(path: Path, value: dict[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise GuardianProgramError(f"refusing to replace existing {path.name}")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(6)}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(temporary, flags, 0o600)
    try:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        _fsync_directory(path.parent)
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def _write_initial_event(path: Path, row: dict[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        info = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_size != 0:
            raise GuardianProgramError("initial event target is not absent or an empty regular file")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(6)}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(_canonical(row).decode("utf-8") + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        _fsync_directory(path.parent)
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def _read_authority_file(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise GuardianProgramError("coordinator authority must be a regular file")
    info = path.stat()
    if hasattr(os, "geteuid") and info.st_uid != os.geteuid():
        raise GuardianProgramError("coordinator authority owner is invalid")
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise GuardianProgramError("coordinator authority must be owner-only")
    token = path.read_text(encoding="utf-8").strip()
    if len(token) < 32:
        raise GuardianProgramError("coordinator authority is malformed")
    return token


def _provision_authority_file(root: Path) -> str:
    path = root / AUTHORITY_FILE
    if path.exists() or path.is_symlink():
        return _read_authority_file(path)
    token = secrets.token_urlsafe(48)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(6)}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(token + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
        os.chmod(path, 0o600)
        _fsync_directory(root)
    except FileExistsError:
        return _provision_authority_file(root)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return token


def _secure_directory(path: Path) -> Path:
    created = False
    try:
        path.mkdir(mode=0o700)
        created = True
    except FileExistsError:
        pass
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise GuardianProgramError("completion evidence directory must be real")
    if hasattr(os, "geteuid") and info.st_uid != os.geteuid():
        raise GuardianProgramError("completion evidence directory owner is invalid")
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise GuardianProgramError("completion evidence directory must be owner-only")
    if created:
        _fsync_directory(path.parent)
    return path


def materialize_completion_permissions(root: Path) -> dict[str, Any]:
    """Harden Git-portable completion evidence after validating every byte.

    Git can only reproduce the executable bit, so an owner-read-only evidence
    file committed from a valid program is checked out as ``0644``.  Treating
    that transport mode as immutable is unsafe, while requiring a manual
    ``chmod`` makes every fresh clone fail before it can verify itself.  This
    two-phase materializer accepts only the exact portable/current modes,
    proves the content-addressed or authority-addressed binding for every
    entry, and only then narrows files to ``0400`` and directories to ``0700``.
    """
    if os.name == "nt":
        raise GuardianProgramError(
            "completion permission materialization requires POSIX modes"
        )
    lexical_root = root.expanduser().absolute()
    if lexical_root.is_symlink():
        raise GuardianProgramError("program root must not be a symlink")
    try:
        program_root = lexical_root.resolve(strict=True)
    except OSError as error:
        raise GuardianProgramError("program root is unavailable") from error
    base = program_root / COMPLETION_DIRECTORY
    if not base.exists() and not base.is_symlink():
        return {
            "schema": "sulde-completion-permission-materialization-v1",
            "root": str(program_root),
            "directories_verified": 0,
            "directories_hardened": 0,
            "files_verified": 0,
            "files_hardened": 0,
        }

    expected_directories = {
        "": base,
        "blobs": base / "blobs",
        "snapshots": base / "snapshots",
        "prepared": base / "prepared",
    }
    opened_directories: list[tuple[int, Path, int]] = []
    opened_files: list[tuple[int, Path, int]] = []
    hardened_directories = 0
    hardened_files = 0
    try:
        for label, directory in expected_directories.items():
            try:
                metadata = directory.lstat()
            except OSError as error:
                raise GuardianProgramError(
                    f"completion evidence directory is unavailable: {label or '.'}"
                ) from error
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise GuardianProgramError(
                    f"completion evidence directory must be real: {label or '.'}"
                )
            if hasattr(os, "geteuid") and metadata.st_uid != os.geteuid():
                raise GuardianProgramError(
                    f"completion evidence directory owner is invalid: {label or '.'}"
                )
            mode = stat.S_IMODE(metadata.st_mode)
            if mode not in {0o700, 0o755}:
                raise GuardianProgramError(
                    f"completion evidence directory mode is not portable: {label or '.'}"
                )
            flags = os.O_RDONLY
            if hasattr(os, "O_DIRECTORY"):
                flags |= os.O_DIRECTORY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(directory, flags)
            opened_directories.append((descriptor, directory, mode))

        unexpected = sorted(
            entry.name
            for entry in base.iterdir()
            if entry.name not in {"blobs", "snapshots", "prepared"}
        )
        if unexpected:
            raise GuardianProgramError(
                "completion evidence contains unexpected entries: "
                + ", ".join(unexpected)
            )

        directory_contracts = {
            "blobs": ".blob",
            "snapshots": ".json",
            "prepared": ".json",
        }
        for label, suffix in directory_contracts.items():
            directory = expected_directories[label]
            for candidate in sorted(directory.iterdir(), key=lambda path: path.name):
                match = re.fullmatch(rf"([0-9a-f]{{64}}){re.escape(suffix)}", candidate.name)
                if match is None:
                    raise GuardianProgramError(
                        f"completion evidence name is invalid: {candidate.name}"
                    )
                if candidate.is_symlink():
                    raise GuardianProgramError(
                        f"completion evidence must not be a symlink: {candidate.name}"
                    )
                flags = os.O_RDONLY
                if hasattr(os, "O_NOFOLLOW"):
                    flags |= os.O_NOFOLLOW
                try:
                    descriptor = os.open(candidate, flags)
                except OSError as error:
                    raise GuardianProgramError(
                        f"completion evidence cannot be opened safely: {candidate.name}"
                    ) from error
                opened_files.append((descriptor, candidate, 0))
                metadata = os.fstat(descriptor)
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                    raise GuardianProgramError(
                        f"completion evidence must be an unaliased regular file: {candidate.name}"
                    )
                if hasattr(os, "geteuid") and metadata.st_uid != os.geteuid():
                    raise GuardianProgramError(
                        f"completion evidence owner is invalid: {candidate.name}"
                    )
                mode = stat.S_IMODE(metadata.st_mode)
                if mode not in {0o400, 0o644}:
                    raise GuardianProgramError(
                        f"completion evidence mode is not portable: {candidate.name}"
                    )
                opened_files[-1] = (descriptor, candidate, mode)
                chunks: list[bytes] = []
                while True:
                    chunk = os.read(descriptor, 1024 * 1024)
                    if not chunk:
                        break
                    chunks.append(chunk)
                payload = b"".join(chunks)
                stem = match.group(1)
                if label in {"blobs", "snapshots"}:
                    if hashlib.sha256(payload).hexdigest() != stem:
                        raise GuardianProgramError(
                            f"completion evidence content digest mismatch: {candidate.name}"
                        )
                else:
                    prepared = _load_json_bytes(
                        payload, label="prepared completion materialization"
                    )
                    required = {
                        "schema",
                        "program_id",
                        "authority_event_sha256",
                        "final_gate_sha256",
                        "evidence_snapshot_path",
                        "evidence_snapshot_sha256",
                    }
                    if (
                        set(prepared) != required
                        or prepared.get("schema") != PREPARED_COMPLETION_SCHEMA
                        or prepared.get("authority_event_sha256") != stem
                    ):
                        raise GuardianProgramError(
                            f"prepared completion binding mismatch: {candidate.name}"
                        )
                    _require_identifier(
                        prepared.get("program_id"), label="prepared program_id"
                    )
                    _require_sha256(
                        prepared.get("final_gate_sha256"),
                        label="prepared final_gate_sha256",
                    )
                    snapshot_sha256 = _require_sha256(
                        prepared.get("evidence_snapshot_sha256"),
                        label="prepared evidence_snapshot_sha256",
                    )
                    if prepared.get("evidence_snapshot_path") != (
                        f"{COMPLETION_DIRECTORY}/snapshots/{snapshot_sha256}.json"
                    ):
                        raise GuardianProgramError(
                            f"prepared completion snapshot binding mismatch: {candidate.name}"
                        )

        # No mutation occurs before every directory, file and binding passes.
        for descriptor, _candidate, mode in opened_files:
            if mode == 0o644:
                os.fchmod(descriptor, 0o400)
                os.fsync(descriptor)
                hardened_files += 1
            if stat.S_IMODE(os.fstat(descriptor).st_mode) != 0o400:
                raise GuardianProgramError(
                    "completion evidence did not materialize as owner-read-only"
                )
        for descriptor, _directory, mode in reversed(opened_directories):
            if mode == 0o755:
                os.fchmod(descriptor, 0o700)
                os.fsync(descriptor)
                hardened_directories += 1
            if stat.S_IMODE(os.fstat(descriptor).st_mode) != 0o700:
                raise GuardianProgramError(
                    "completion evidence directory did not materialize as owner-only"
                )
    finally:
        for descriptor, _candidate, _mode in opened_files:
            os.close(descriptor)
        for descriptor, _directory, _mode in opened_directories:
            os.close(descriptor)

    return {
        "schema": "sulde-completion-permission-materialization-v1",
        "root": str(program_root),
        "directories_verified": len(opened_directories),
        "directories_hardened": hardened_directories,
        "files_verified": len(opened_files),
        "files_hardened": hardened_files,
    }


def _read_bound_bytes(
    root: Path,
    relative_path: str,
    expected_sha256: str | None,
    *,
    immutable: bool = False,
) -> bytes:
    relative = Path(_require_text(relative_path, label="bound file path", limit=1000))
    if relative.is_absolute() or ".." in relative.parts:
        raise GuardianProgramError("bound file path must stay inside the program root")
    raw = root / relative
    if raw.is_symlink():
        raise GuardianProgramError("bound file must not be a symlink")
    try:
        candidate = raw.resolve(strict=True)
        candidate.relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as error:
        raise GuardianProgramError("bound file is unavailable or outside the program root") from error
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(candidate, flags)
    except OSError as error:
        raise GuardianProgramError("bound file cannot be opened safely") from error
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise GuardianProgramError("bound file must be a regular file")
        if info.st_nlink != 1:
            raise GuardianProgramError("bound file must not have hardlink aliases")
        if immutable:
            if hasattr(os, "geteuid") and info.st_uid != os.geteuid():
                raise GuardianProgramError("immutable completion evidence owner is invalid")
            if stat.S_IMODE(info.st_mode) != 0o400:
                raise GuardianProgramError(
                    "immutable completion evidence must be owner-read-only"
                )
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        payload = b"".join(chunks)
    finally:
        os.close(descriptor)
    if expected_sha256 is not None:
        if hashlib.sha256(payload).hexdigest() != _require_sha256(
            expected_sha256, label="bound file sha256"
        ):
            raise GuardianProgramError("bound file digest does not match its evidence")
    return payload


def _store_content_addressed(root: Path, directory: str, suffix: str, payload: bytes) -> Path:
    base = _secure_directory(root / COMPLETION_DIRECTORY)
    target_directory = _secure_directory(base / directory)
    digest = hashlib.sha256(payload).hexdigest()
    target = target_directory / f"{digest}{suffix}"
    if target.exists() or target.is_symlink():
        existing = _read_bound_bytes(
            root,
            target.relative_to(root).as_posix(),
            digest,
            immutable=True,
        )
        if existing != payload:
            raise GuardianProgramError("content-addressed completion evidence collided")
        return target
    temporary = target.with_name(f".{target.name}.{os.getpid()}.{secrets.token_hex(6)}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
            os.fchmod(handle.fileno(), 0o400)
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        _fsync_directory(target_directory)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return target


def _prepared_completion_path(root: Path, authority_event_sha256: str) -> Path:
    _require_sha256(authority_event_sha256, label="completion authority sha256")
    base = _secure_directory(root / COMPLETION_DIRECTORY)
    prepared = _secure_directory(base / "prepared")
    return prepared / f"{authority_event_sha256}.json"


def _prepared_completion_payload(prepared: dict[str, Any]) -> dict[str, str]:
    return {
        "final_gate_sha256": prepared["final_gate_sha256"],
        "evidence_snapshot_path": prepared["evidence_snapshot_path"],
        "evidence_snapshot_sha256": prepared["evidence_snapshot_sha256"],
    }


def _validate_prepared_completion(
    value: dict[str, Any],
    *,
    program_id: str,
    authority_event_sha256: str,
    final_gate_sha256: str,
) -> dict[str, str]:
    if set(value) != {
        "schema",
        "program_id",
        "authority_event_sha256",
        "final_gate_sha256",
        "evidence_snapshot_path",
        "evidence_snapshot_sha256",
    } or value.get("schema") != PREPARED_COMPLETION_SCHEMA:
        raise GuardianProgramError("prepared completion schema is invalid")
    normalized_program_id = _require_identifier(
        value.get("program_id"), label="prepared program_id"
    )
    if (
        normalized_program_id != program_id
        or value.get("authority_event_sha256") != authority_event_sha256
        or value.get("final_gate_sha256") != final_gate_sha256
    ):
        raise GuardianProgramError("prepared completion authority binding is invalid")
    _require_sha256(value["final_gate_sha256"], label="prepared final_gate_sha256")
    _require_sha256(
        value["evidence_snapshot_sha256"],
        label="prepared evidence_snapshot_sha256",
    )
    return {
        key: str(value[key])
        for key in (
            "schema",
            "program_id",
            "authority_event_sha256",
            "final_gate_sha256",
            "evidence_snapshot_path",
            "evidence_snapshot_sha256",
        )
    }


def _load_prepared_completion(
    root: Path,
    *,
    program_id: str,
    authority_event_sha256: str,
    final_gate_sha256: str,
) -> dict[str, str] | None:
    path = _prepared_completion_path(root, authority_event_sha256)
    if not path.exists() and not path.is_symlink():
        return None
    payload = _read_bound_bytes(
        root,
        path.relative_to(root).as_posix(),
        None,
        immutable=True,
    )
    return _validate_prepared_completion(
        _load_json_bytes(payload, label="prepared completion"),
        program_id=program_id,
        authority_event_sha256=authority_event_sha256,
        final_gate_sha256=final_gate_sha256,
    )


def _store_prepared_completion(
    root: Path,
    prepared: dict[str, Any],
) -> dict[str, str]:
    normalized = _validate_prepared_completion(
        prepared,
        program_id=str(prepared.get("program_id") or ""),
        authority_event_sha256=str(prepared.get("authority_event_sha256") or ""),
        final_gate_sha256=str(prepared.get("final_gate_sha256") or ""),
    )
    path = _prepared_completion_path(root, normalized["authority_event_sha256"])
    payload = _canonical(normalized) + b"\n"
    if path.exists() or path.is_symlink():
        existing = _read_bound_bytes(
            root,
            path.relative_to(root).as_posix(),
            None,
            immutable=True,
        )
        if existing != payload:
            raise GuardianProgramError("prepared completion conflicts with prior authority")
        return normalized
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{secrets.token_hex(6)}.tmp"
    )
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
            os.fchmod(handle.fileno(), 0o400)
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return normalized


def _require_authority(status: dict[str, Any]) -> None:
    expected = str(status.get("coordinator_authority_sha256") or "")
    supplied = os.environ.get(AUTHORITY_ENV, "")
    if not expected or not supplied or hashlib.sha256(supplied.encode("utf-8")).hexdigest() != expected:
        raise GuardianProgramError(
            "coordinator authority is required from the controlled execution context"
        )


def authority_recovery_confirmation(program_id: str, event_head_sha256: str) -> str:
    """Bind an explicit break-glass confirmation to one exact program head."""
    native_program = _require_identifier(program_id, label="program_id")
    native_head = _require_sha256(event_head_sha256, label="event head")
    return hashlib.sha256(
        f"{AUTHORITY_RECOVERY_DOMAIN}\0{native_program}\0{native_head}".encode("utf-8")
    ).hexdigest()


@contextmanager
def _control_lock(root: Path) -> Iterator[None]:
    lock_path = root / ".control.lock"
    handle = lock_path.open("a+", encoding="utf-8")
    os.chmod(lock_path, 0o600)
    try:
        try:
            lock_exclusive_nonblocking(handle)
        except BlockingIOError as error:
            raise GuardianProgramError("guardian program control lock is busy") from error
        yield
    finally:
        try:
            unlock(handle)
        finally:
            handle.close()


def _read_events(root: Path) -> list[dict[str, Any]]:
    path = root / "events.jsonl"
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise GuardianProgramError(f"cannot read event log: {error}") from error
    if text and not text.endswith("\n"):
        raise GuardianProgramError("event log has an incomplete tail")
    events: list[dict[str, Any]] = []
    previous = ""
    for number, line in enumerate(text.splitlines(), start=1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise GuardianProgramError(f"event log line {number} is invalid JSON") from error
        if not isinstance(row, dict) or row.get("schema") != EVENT_SCHEMA:
            raise GuardianProgramError(f"event log line {number} has an invalid schema")
        expected_keys = {
            "schema",
            "sequence",
            "event_id",
            "at",
            "actor",
            "type",
            "payload",
            "previous_sha256",
            "event_sha256",
        }
        if set(row) != expected_keys or row.get("sequence") != number:
            raise GuardianProgramError(f"event log line {number} is not contiguous")
        if row.get("previous_sha256") != previous:
            raise GuardianProgramError(f"event log line {number} breaks the hash chain")
        unsigned = {key: value for key, value in row.items() if key != "event_sha256"}
        if row.get("event_sha256") != _digest(unsigned):
            raise GuardianProgramError(f"event log line {number} digest mismatch")
        previous = row["event_sha256"]
        events.append(row)
    return events


def _write_event_row(root: Path, row: dict[str, Any]) -> None:
    path = root / "events.jsonl"
    current = _read_events(root)
    previous_sha256 = current[-1]["event_sha256"] if current else ""
    if (
        row.get("sequence") != len(current) + 1
        or row.get("previous_sha256") != previous_sha256
    ):
        raise GuardianProgramError("event row no longer extends the authoritative head")
    existing = path.read_bytes() if path.exists() else b""
    if existing and not existing.endswith(b"\n"):
        raise GuardianProgramError("event log has an incomplete tail")
    payload = existing + _canonical(row) + b"\n"
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{secrets.token_hex(6)}.tmp"
    )
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        _fsync_directory(root)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _append_event(
    root: Path,
    *,
    actor: str,
    kind: str,
    payload: dict[str, Any],
    expected_last_sha256: str | None = None,
) -> dict[str, Any]:
    actor = _require_identifier(actor, label="actor")
    with _control_lock(root):
        events = _read_events(root)
        current_last = events[-1]["event_sha256"] if events else ""
        if expected_last_sha256 is not None and current_last != expected_last_sha256:
            raise GuardianProgramError("program state changed before append; reload and retry")
        if any(row["type"] == "program_completed" for row in events):
            raise GuardianProgramError("program is already completed and immutable")
        if kind == "program_completed":
            raise GuardianProgramError("program completion must use the completion gate")
        row: dict[str, Any] = {
            "schema": EVENT_SCHEMA,
            "sequence": len(events) + 1,
            "event_id": f"gpe-{secrets.token_hex(12)}",
            "at": _now(),
            "actor": actor,
            "type": kind,
            "payload": payload,
            "previous_sha256": current_last,
        }
        row["event_sha256"] = _digest(row)
        project(
            root,
            _events=[*events, row],
            _manifest_value=_manifest(root),
        )
        _write_event_row(root, row)
        return row


def _manifest(root: Path) -> dict[str, Any]:
    return _validate_manifest(_load_json(root / "manifest.json"))


def initialize(root: Path, manifest_path: Path, *, actor: str) -> dict[str, Any]:
    root = _secure_root(root, create=True)
    manifest = _validate_manifest(_load_json(manifest_path))
    if actor != manifest["coordinator"]:
        raise GuardianProgramError("only the configured coordinator may initialize")
    actor = _require_identifier(actor, label="actor")
    with _control_lock(root):
        event_path = root / "events.jsonl"
        target = root / "manifest.json"
        if target.exists():
            if _validate_manifest(_load_json(target)) != manifest:
                raise GuardianProgramError("orphan manifest does not match initialization input")
        else:
            _write_once(target, manifest)
        if event_path.exists() and event_path.stat().st_size:
            events = _read_events(root)
            if len(events) != 1 or events[0]["type"] != "program_initialized":
                raise GuardianProgramError("program root is already initialized")
            status = project(root, _events=events, _manifest_value=manifest)
            if status["coordinator"] != actor:
                raise GuardianProgramError("program root is already initialized")
            authority_path = root / AUTHORITY_FILE
            if not authority_path.exists() and not authority_path.is_symlink():
                raise GuardianProgramError("initialized program lost coordinator authority")
            authority_token = _read_authority_file(authority_path)
            if hashlib.sha256(authority_token.encode("utf-8")).hexdigest() != status[
                "coordinator_authority_sha256"
            ]:
                raise GuardianProgramError("initialized program authority does not match")
            return events[0]
        authority_token = _provision_authority_file(root)
        authority_sha256 = hashlib.sha256(authority_token.encode("utf-8")).hexdigest()
        row: dict[str, Any] = {
            "schema": EVENT_SCHEMA,
            "sequence": 1,
            "event_id": f"gpe-{secrets.token_hex(12)}",
            "at": _now(),
            "actor": actor,
            "type": "program_initialized",
            "payload": {
                "manifest_sha256": _digest(manifest),
                "coordinator_authority_sha256": authority_sha256,
            },
            "previous_sha256": "",
        }
        row["event_sha256"] = _digest(row)
        _write_initial_event(event_path, row)
        return row


def provision_authority(root: Path) -> dict[str, Any]:
    """One-time migration for a v1 program created before authority capabilities."""
    root = _secure_root(root, create=False)
    status = project(root)
    if status["coordinator_authority_sha256"]:
        raise GuardianProgramError("coordinator authority is already provisioned")
    token = _provision_authority_file(root)
    return _append_event(
        root,
        actor=status["coordinator"],
        kind="coordinator_authority_provisioned",
        payload={
            "coordinator_authority_sha256": hashlib.sha256(
                token.encode("utf-8")
            ).hexdigest()
        },
        expected_last_sha256=status["last_event_sha256"],
    )


def rotate_lost_authority(
    root: Path,
    *,
    actor: str,
    expected_last_sha256: str,
    confirmation: str,
    approval_id: str,
    reason: str,
) -> dict[str, Any]:
    """Recover a lost coordinator capability without rewriting program history.

    This is deliberately not a normal rotation API. It works only when the
    authority file is absent or no longer matches the authoritative event
    projection, and requires an exact-head confirmation that is suitable for a
    human-visible break-glass card. The replacement becomes authoritative only
    through an append-only event.
    """
    root = _secure_root(root, create=False)
    actor = _require_identifier(actor, label="actor")
    expected_head = _require_sha256(
        expected_last_sha256, label="expected_last_sha256"
    )
    native_confirmation = _require_sha256(
        confirmation, label="authority recovery confirmation"
    )
    native_approval_id = _require_identifier(approval_id, label="approval_id")
    native_reason = _require_text(reason, label="authority recovery reason")
    with _control_lock(root):
        events = _read_events(root)
        status = project(root, _events=events, _manifest_value=_manifest(root))
        if actor != status["coordinator"]:
            raise GuardianProgramError(
                "only the configured coordinator may recover lost authority"
            )
        if status["completion_event_seen"]:
            raise GuardianProgramError("completed program authority is immutable")
        if status["last_event_sha256"] != expected_head:
            raise GuardianProgramError(
                "program state changed before authority recovery; reload and reconfirm"
            )
        expected_confirmation = authority_recovery_confirmation(
            status["program_id"], expected_head
        )
        if not secrets.compare_digest(native_confirmation, expected_confirmation):
            raise GuardianProgramError(
                "authority recovery confirmation does not bind the current program head"
            )

        authority_path = root / AUTHORITY_FILE
        if authority_path.exists() or authority_path.is_symlink():
            replacement_token = _read_authority_file(authority_path)
            replacement_sha256 = hashlib.sha256(
                replacement_token.encode("utf-8")
            ).hexdigest()
            if secrets.compare_digest(
                replacement_sha256, status["coordinator_authority_sha256"]
            ):
                raise GuardianProgramError(
                    "coordinator authority is still available; break-glass recovery is forbidden"
                )
        else:
            replacement_token = _provision_authority_file(root)
            replacement_sha256 = hashlib.sha256(
                replacement_token.encode("utf-8")
            ).hexdigest()
        if secrets.compare_digest(
            replacement_sha256, status["coordinator_authority_sha256"]
        ):
            raise GuardianProgramError("authority recovery did not rotate the capability")

        payload = {
            "approval_id": native_approval_id,
            "confirmation_sha256": native_confirmation,
            "coordinator_authority_sha256": replacement_sha256,
            "previous_authority_sha256": status["coordinator_authority_sha256"],
            "reason": native_reason,
        }
        row: dict[str, Any] = {
            "schema": EVENT_SCHEMA,
            "sequence": len(events) + 1,
            "event_id": f"gpe-{secrets.token_hex(12)}",
            "at": _now(),
            "actor": actor,
            "type": "coordinator_authority_rotated",
            "payload": payload,
            "previous_sha256": expected_head,
        }
        row["event_sha256"] = _digest(row)
        project(
            root,
            _events=[*events, row],
            _manifest_value=_manifest(root),
        )
        _write_event_row(root, row)
        return row


def _task_evidence_kinds(status: dict[str, Any], task_id: str) -> set[str]:
    task = status["tasks"][task_id]
    return {
        row["kind"]
        for row in status["evidence"].values()
        if row["scope"] == "task"
        and row["task_id"] == task_id
        and row["verdict"] == "pass"
        and not row["superseded_by"]
        and row["recorded_sequence"] > task["evidence_floor_sequence"]
        and row["run_id"] == task["verification_run_id"]
    }


def _evidence_identity_errors(status: dict[str, Any]) -> list[dict[str, str]]:
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for evidence in status["evidence"].values():
        if evidence["superseded_by"]:
            continue
        identity = (
            evidence["scope"],
            evidence["task_id"],
            evidence["kind"],
            evidence["baseline"],
        )
        groups.setdefault(identity, []).append(evidence)
    return [
        {
            "evidence_id": evidence["evidence_id"],
            "reason": "active_identity_conflict",
        }
        for rows in groups.values()
        if len(rows) > 1
        for evidence in rows
    ]


def _finding_resolution_coverage(status: dict[str, Any], task_id: str) -> set[str]:
    invalid_ids = {row["evidence_id"] for row in status["evidence_errors"]}
    task = status["tasks"][task_id]
    return {
        finding_id
        for evidence in status["evidence"].values()
        if evidence["scope"] == "task"
        and evidence["task_id"] == task_id
        and evidence["kind"] == "finding_resolution"
        and evidence["verdict"] == "pass"
        and not evidence["superseded_by"]
        and evidence["evidence_id"] not in invalid_ids
        and evidence["recorded_sequence"] > task["evidence_floor_sequence"]
        and evidence["run_id"] == task["verification_run_id"]
        for finding_id in evidence["findings"]
    }


def _required_evidence_through(task: dict[str, Any], destination: str) -> set[str]:
    required: set[str] = set()
    for state in EVIDENCE_GATE_ORDER:
        required.update(task["evidence_gates"].get(state, []))
        if state == destination:
            break
    return required


def _open_findings(status: dict[str, Any], task_id: str | None = None) -> list[dict[str, Any]]:
    rows = [row for row in status["findings"].values() if not row.get("resolved_at")]
    if task_id is not None:
        rows = [row for row in rows if row["task_id"] == task_id]
    return rows


def project(
    root: Path,
    *,
    verify_evidence: bool = False,
    _events: list[dict[str, Any]] | None = None,
    _manifest_value: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = _secure_root(root, create=False)
    manifest = _manifest_value if _manifest_value is not None else _manifest(root)
    events = list(_events) if _events is not None else _read_events(root)
    if not events or events[0]["type"] != "program_initialized":
        raise GuardianProgramError("program initialization event is missing")
    initialization_payload = events[0]["payload"]
    if not isinstance(initialization_payload, dict) or initialization_payload.get(
        "manifest_sha256"
    ) != _digest(manifest):
        raise GuardianProgramError("manifest does not match initialization authority")
    if set(initialization_payload) not in (
        {"manifest_sha256"},
        {"manifest_sha256", "coordinator_authority_sha256"},
    ):
        raise GuardianProgramError("program initialization payload is invalid")
    initialization_authority = str(
        initialization_payload.get("coordinator_authority_sha256") or ""
    )
    if initialization_authority:
        _require_sha256(
            initialization_authority, label="coordinator_authority_sha256"
        )
    status: dict[str, Any] = {
        "schema": STATUS_SCHEMA,
        "program_id": manifest["program_id"],
        "objective": manifest["objective"],
        "coordinator": manifest["coordinator"],
        "coordinator_authority_sha256": initialization_authority,
        "requirements": {row["id"]: row for row in manifest["requirements"]},
        "tasks": {},
        "findings": {},
        "evidence": {},
        "program_completed": False,
        "completion_event_seen": False,
        "completion": None,
        "event_count": len(events),
        "last_event_sha256": events[-1]["event_sha256"],
        "evidence_errors": [],
    }
    for row in events[1:]:
        if status["completion_event_seen"]:
            raise GuardianProgramError("program event exists after immutable completion")
        payload = row["payload"]
        kind = row["type"]
        actor = row["actor"]
        if kind == "task_registered":
            task = _validate_task(payload)
            task_id = task["task_id"]
            if actor != manifest["coordinator"] or task_id in status["tasks"]:
                raise GuardianProgramError("task registration authority or uniqueness failed")
            missing_requirements = set(task["requirements"]) - set(status["requirements"])
            missing_dependencies = set(task["depends_on"]) - set(status["tasks"])
            missing_superseded = set(task["supersedes"]) - set(status["tasks"])
            if missing_requirements or missing_dependencies or missing_superseded:
                raise GuardianProgramError(
                    "task references unknown requirements, dependencies or superseded tasks"
                )
            for superseded_id in task["supersedes"]:
                superseded = status["tasks"][superseded_id]
                if (
                    _supersession_claimants(status["tasks"], superseded_id)
                    or
                    superseded["state"]
                    not in {"planned", "ready", "implemented", "blocked"}
                    or not set(superseded["requirements"]).issubset(task["requirements"])
                ):
                    raise GuardianProgramError("task supersession target or coverage is invalid")
            if _ownership_conflicts(task, status["tasks"]):
                raise GuardianProgramError("task path ownership overlaps an unserialized task")
            inherited_obligations = sorted(
                {
                    finding_id
                    for superseded_id in task["supersedes"]
                    for finding_id in status["tasks"][superseded_id][
                        "finding_obligations"
                    ]
                }
            )
            status["tasks"][task_id] = {
                **task,
                "state": "planned",
                "registered_at": row["at"],
                "updated_at": row["at"],
                "superseded_by": "",
                "finding_obligations": inherited_obligations,
                "verification_epoch": 0,
                "verification_run_id": "",
                "evidence_floor_sequence": row["sequence"],
                "history": [],
            }
        elif kind == "coordinator_authority_provisioned":
            if actor != manifest["coordinator"] or status["coordinator_authority_sha256"]:
                raise GuardianProgramError("coordinator authority provisioning is invalid")
            authority_sha256 = _require_sha256(
                payload.get("coordinator_authority_sha256"),
                label="coordinator_authority_sha256",
            )
            status["coordinator_authority_sha256"] = authority_sha256
        elif kind == "coordinator_authority_rotated":
            if actor != manifest["coordinator"] or set(payload) != {
                "approval_id",
                "confirmation_sha256",
                "coordinator_authority_sha256",
                "previous_authority_sha256",
                "reason",
            }:
                raise GuardianProgramError("coordinator authority rotation is invalid")
            previous_authority = _require_sha256(
                payload.get("previous_authority_sha256"),
                label="previous_authority_sha256",
            )
            replacement_authority = _require_sha256(
                payload.get("coordinator_authority_sha256"),
                label="coordinator_authority_sha256",
            )
            confirmation_sha256 = _require_sha256(
                payload.get("confirmation_sha256"),
                label="authority recovery confirmation",
            )
            _require_identifier(payload.get("approval_id"), label="approval_id")
            _require_text(payload.get("reason"), label="authority recovery reason")
            if (
                previous_authority != status["coordinator_authority_sha256"]
                or replacement_authority == previous_authority
                or confirmation_sha256
                != authority_recovery_confirmation(
                    status["program_id"], row["previous_sha256"]
                )
            ):
                raise GuardianProgramError("coordinator authority rotation binding failed")
            status["coordinator_authority_sha256"] = replacement_authority
        elif kind == "evidence_recorded":
            evidence_id = _require_identifier(payload.get("evidence_id"), label="evidence_id")
            if evidence_id in status["evidence"]:
                raise GuardianProgramError("evidence_id was replayed")
            scope = payload.get("scope")
            task_id = str(payload.get("task_id") or "")
            if scope not in {"program", "task"}:
                raise GuardianProgramError("evidence scope is invalid")
            if scope == "task":
                if task_id not in status["tasks"]:
                    raise GuardianProgramError("task evidence references an unknown task")
                if actor not in {manifest["coordinator"], status["tasks"][task_id]["owner"]}:
                    raise GuardianProgramError("task evidence actor is unauthorized")
            elif actor != manifest["coordinator"] or task_id:
                raise GuardianProgramError("program evidence actor is unauthorized")
            evidence = {
                "evidence_id": evidence_id,
                "scope": scope,
                "task_id": task_id,
                "kind": _require_identifier(payload.get("kind"), label="evidence kind"),
                "baseline": _require_text(
                    payload.get("baseline"), label="evidence baseline", limit=500
                ),
                "run_id": _require_identifier(
                    payload.get("run_id"), label="evidence run_id"
                ),
                "path": _require_text(payload.get("path"), label="evidence path", limit=1000),
                "sha256": _require_sha256(payload.get("sha256"), label="evidence sha256"),
                "verdict": str(payload.get("verdict") or ""),
                "requirements": _require_string_list(
                    payload.get("requirements", []), label="evidence requirements"
                ),
                "findings": _require_string_list(
                    payload.get("findings", []), label="evidence findings"
                ),
                "acceptance": payload.get("acceptance", []),
                "summary": _require_text(payload.get("summary"), label="evidence summary"),
                "recorded_at": row["at"],
                "recorded_sequence": row["sequence"],
                "actor": actor,
                "superseded_by": "",
            }
            if evidence["verdict"] not in EVIDENCE_VERDICTS:
                raise GuardianProgramError("recorded evidence verdict is invalid")
            status["evidence"][evidence_id] = evidence
        elif kind == "evidence_superseded":
            evidence_id = _require_identifier(payload.get("evidence_id"), label="evidence_id")
            replacement_id = _require_identifier(
                payload.get("replacement_id"), label="replacement_id"
            )
            evidence = status["evidence"].get(evidence_id)
            replacement = status["evidence"].get(replacement_id)
            if (
                actor != manifest["coordinator"]
                or not evidence
                or evidence["superseded_by"]
                or not replacement
                or replacement["superseded_by"]
                or evidence_id == replacement_id
                or any(
                    evidence[field] != replacement[field]
                    for field in ("scope", "task_id", "kind", "baseline")
                )
                or replacement["verdict"] != "pass"
                or replacement["recorded_sequence"] <= evidence["recorded_sequence"]
                or not _replacement_preserves_semantics(evidence, replacement)
            ):
                raise GuardianProgramError("evidence supersession authority or binding failed")
            evidence["superseded_by"] = replacement_id
        elif kind == "finding_recorded":
            finding_id = _require_identifier(payload.get("finding_id"), label="finding_id")
            task_id = _require_identifier(payload.get("task_id"), label="finding task_id")
            if finding_id in status["findings"] or task_id not in status["tasks"]:
                raise GuardianProgramError("finding uniqueness or task reference failed")
            if actor not in {manifest["coordinator"], status["tasks"][task_id]["owner"]}:
                raise GuardianProgramError("finding actor is unauthorized")
            evidence_status = _require_identifier(
                payload.get("evidence_status"), label="finding evidence_status"
            )
            if evidence_status not in FINDING_EVIDENCE_STATUSES:
                raise GuardianProgramError("finding evidence_status is invalid")
            status["findings"][finding_id] = {
                "finding_id": finding_id,
                "task_id": task_id,
                "symptom": _require_text(payload.get("symptom"), label="finding symptom"),
                "evidence": _require_text(payload.get("evidence"), label="finding evidence"),
                "evidence_status": evidence_status,
                "recorded_at": row["at"],
                "recorded_sequence": row["sequence"],
                "recorded_by": actor,
                "resolved_at": "",
                "disposition": "",
                "root_cause": "",
                "resolution": "",
                "linked_task": "",
                "resolution_evidence_id": "",
                "human_evidence": "",
            }
        elif kind == "finding_resolved":
            finding_id = _require_identifier(payload.get("finding_id"), label="finding_id")
            finding = status["findings"].get(finding_id)
            if actor != manifest["coordinator"] or not finding or finding["resolved_at"]:
                raise GuardianProgramError("finding resolution authority or state failed")
            disposition = str(payload.get("disposition") or "")
            if disposition not in FINDING_DISPOSITIONS:
                raise GuardianProgramError("finding disposition is invalid")
            linked_task = str(payload.get("linked_task") or "")
            human_evidence = str(payload.get("human_evidence") or "")
            resolution_evidence_id = str(payload.get("evidence_id") or "")
            _validate_finding_resolution_channels(
                disposition,
                linked_task=linked_task,
                evidence_id=resolution_evidence_id,
                human_evidence=human_evidence,
            )
            if disposition in {"transferred", "new_task"}:
                target = status["tasks"].get(linked_task)
                if (
                    not target
                    or linked_task == finding["task_id"]
                    or target["state"] in {"accepted", "superseded"}
                    or _supersession_claimants(status["tasks"], linked_task)
                ):
                    raise GuardianProgramError(
                        "finding transfer must reference a different non-terminal registered task"
                    )
                target["finding_obligations"].append(finding_id)
            if disposition == "deferred_human" and (
                not manifest["allow_human_deferred"] or not human_evidence
            ):
                raise GuardianProgramError("human deferral lacks manifest authority or evidence")
            if disposition == "rejected_with_evidence":
                resolution_evidence = status["evidence"].get(resolution_evidence_id)
                if (
                    not resolution_evidence
                    or resolution_evidence["scope"] != "task"
                    or resolution_evidence["task_id"] != finding["task_id"]
                    or resolution_evidence["kind"] != "finding_resolution"
                    or finding_id not in resolution_evidence["findings"]
                    or resolution_evidence["verdict"] != "pass"
                    or resolution_evidence["superseded_by"]
                    or resolution_evidence["recorded_sequence"]
                    <= finding["recorded_sequence"]
                ):
                    raise GuardianProgramError(
                        "rejected finding must reference passing evidence for the same task"
                    )
            finding.update(
                {
                    "resolved_at": row["at"],
                    "disposition": disposition,
                    "root_cause": _require_text(
                        payload.get("root_cause"), label="finding root_cause"
                    ),
                    "resolution": _require_text(
                        payload.get("resolution"), label="finding resolution"
                    ),
                    "linked_task": linked_task,
                    "resolution_evidence_id": resolution_evidence_id,
                    "human_evidence": human_evidence,
                }
            )
        elif kind == "task_transitioned":
            task_id = _require_identifier(payload.get("task_id"), label="task_id")
            task = status["tasks"].get(task_id)
            destination = str(payload.get("to") or "")
            if not task or destination not in TASK_STATES:
                raise GuardianProgramError("task transition target is invalid")
            source = task["state"]
            if payload.get("from") != source or destination not in TRANSITIONS[source]:
                raise GuardianProgramError("task transition is not valid from current state")
            if destination in {"task_verified", "integrated", "system_verified", "accepted"}:
                if actor != manifest["coordinator"]:
                    raise GuardianProgramError("only the coordinator may verify or accept work")
            elif actor not in {manifest["coordinator"], task["owner"]}:
                raise GuardianProgramError("task transition actor is unauthorized")
            if destination == "superseded":
                superseded_by = str(payload.get("superseded_by") or "")
                successor = status["tasks"].get(superseded_by)
                if (
                    actor != manifest["coordinator"]
                    or not successor
                    or task_id not in successor["supersedes"]
                ):
                    raise GuardianProgramError("task supersession authority or successor is invalid")
            else:
                superseded_by = ""
            if source == "blocked" and actor != manifest["coordinator"]:
                raise GuardianProgramError("only the coordinator may replay an unblock")
            if source in EVIDENCE_GATE_ORDER and destination == "running" and actor != manifest["coordinator"]:
                raise GuardianProgramError("only the coordinator may reopen verified work")
            if destination in {"ready", "running", "implemented", "task_verified", "integrated", "system_verified", "accepted"}:
                if _supersession_claimants(status["tasks"], task_id):
                    raise GuardianProgramError(
                        "a registered successor prevents the predecessor from becoming active"
                    )
                if any(
                    status["tasks"][superseded_id]["state"] != "superseded"
                    or status["tasks"][superseded_id]["superseded_by"] != task_id
                    for superseded_id in task["supersedes"]
                ):
                    raise GuardianProgramError(
                        "successor cannot become active before every predecessor is superseded"
                    )
                unmet = [
                    dependency
                    for dependency in task["depends_on"]
                    if not _dependency_is_accepted(status["tasks"], dependency)
                ]
                if unmet:
                    raise GuardianProgramError("task dependencies are not accepted")
            required = (
                _required_evidence_through(task, destination)
                if destination in EVIDENCE_GATE_ORDER
                else set(task["evidence_gates"].get(destination, []))
            )
            missing = required - _task_evidence_kinds(status, task_id)
            if missing:
                raise GuardianProgramError(
                    f"task transition lacks evidence: {','.join(sorted(missing))}"
                )
            if destination in {"task_verified", "integrated", "system_verified", "accepted"}:
                if _open_findings(status, task_id):
                    raise GuardianProgramError("task has unresolved findings")
                unresolved_obligations = set(task["finding_obligations"]) - (
                    _finding_resolution_coverage(status, task_id)
                )
                if unresolved_obligations:
                    raise GuardianProgramError(
                        "task has transferred finding obligations without resolution evidence"
                    )
            if destination == "running":
                task["verification_epoch"] += 1
                task["verification_run_id"] = f"run-{row['event_id']}"
                task["evidence_floor_sequence"] = row["sequence"]
            task["state"] = destination
            task["superseded_by"] = superseded_by
            task["updated_at"] = row["at"]
            task["history"].append(
                {
                    "from": source,
                    "to": destination,
                    "at": row["at"],
                    "actor": actor,
                    "note": _require_text(payload.get("note"), label="transition note"),
                }
            )
        elif kind == "program_completed":
            if actor != manifest["coordinator"] or status["completion_event_seen"]:
                raise GuardianProgramError("program completion authority or uniqueness failed")
            normalized_completion = _validate_completion_payload(payload)
            gate = _final_gate_projection(
                status,
                manifest,
                authority_event_sha256=row["previous_sha256"],
                evidence_errors=_evidence_identity_errors(status),
            )
            if (
                not gate["ready"]
                or normalized_completion["final_gate_sha256"] != _digest(gate)
            ):
                raise GuardianProgramError("program completion does not match its prior gate")
            completion_integrity = "verified"
            completion_integrity_error = ""
            try:
                _validate_completion_snapshot(
                    root,
                    status,
                    normalized_completion,
                    authority_event_sha256=row["previous_sha256"],
                )
            except GuardianProgramError as error:
                completion_integrity = "failed"
                completion_integrity_error = str(error)
                status["evidence_errors"].append(
                    {
                        "evidence_id": "completion-snapshot",
                        "reason": "completion_integrity_failed",
                    }
                )
            status["completion_event_seen"] = True
            status["program_completed"] = completion_integrity == "verified"
            status["completion"] = {
                **normalized_completion,
                "authority_event_sha256": row["previous_sha256"],
                "event_sha256": row["event_sha256"],
                "completed_at": row["at"],
                "integrity": completion_integrity,
                "integrity_error": completion_integrity_error,
            }
        else:
            raise GuardianProgramError(f"unsupported program event type: {kind}")
    status["evidence_errors"].extend(_evidence_identity_errors(status))
    if verify_evidence and not status["completion_event_seen"]:
        for evidence in status["evidence"].values():
            if evidence["superseded_by"]:
                continue
            raw_candidate = root / evidence["path"]
            if raw_candidate.is_symlink():
                status["evidence_errors"].append(
                    {"evidence_id": evidence["evidence_id"], "reason": "symlink"}
                )
                continue
            candidate = raw_candidate.resolve(strict=False)
            try:
                candidate.relative_to(root.resolve(strict=True))
            except ValueError:
                status["evidence_errors"].append(
                    {"evidence_id": evidence["evidence_id"], "reason": "outside_root"}
                )
                continue
            if not candidate.is_file() or candidate.is_symlink():
                status["evidence_errors"].append(
                    {"evidence_id": evidence["evidence_id"], "reason": "missing_or_symlink"}
                )
                continue
            if candidate.stat().st_nlink != 1:
                status["evidence_errors"].append(
                    {
                        "evidence_id": evidence["evidence_id"],
                        "reason": "hardlink_alias",
                    }
                )
                continue
            if _file_digest(candidate) != evidence["sha256"]:
                status["evidence_errors"].append(
                    {"evidence_id": evidence["evidence_id"], "reason": "digest_mismatch"}
                )
                continue
            try:
                document = _validate_evidence_document(
                    _load_json(candidate),
                    scope=evidence["scope"],
                    task_id=evidence["task_id"],
                    kind=evidence["kind"],
                )
            except GuardianProgramError:
                status["evidence_errors"].append(
                    {"evidence_id": evidence["evidence_id"], "reason": "invalid_content"}
                )
                continue
            binding_reason = _evidence_binding_reason(status, evidence, document)
            if binding_reason:
                status["evidence_errors"].append(
                    {"evidence_id": evidence["evidence_id"], "reason": binding_reason}
                )
                continue
            artifact_errors = _evidence_artifact_errors(root, document)
            if artifact_errors:
                status["evidence_errors"].append(
                    {
                        "evidence_id": evidence["evidence_id"],
                        "reason": "artifact_invalid",
                        "artifacts": artifact_errors,
                    }
                )
    return status


def register_task(root: Path, task_path: Path, *, actor: str) -> dict[str, Any]:
    root = _secure_root(root, create=False)
    status = project(root)
    _require_authority(status)
    if actor != status["coordinator"]:
        raise GuardianProgramError("only the coordinator may register tasks")
    task = _validate_task(_load_json(task_path))
    if task["task_id"] in status["tasks"]:
        raise GuardianProgramError("task is already registered")
    if set(task["depends_on"]) - set(status["tasks"]):
        raise GuardianProgramError("register dependency tasks first")
    if set(task["supersedes"]) - set(status["tasks"]):
        raise GuardianProgramError("register superseded tasks first")
    if set(task["requirements"]) - set(status["requirements"]):
        raise GuardianProgramError("task references an unknown requirement")
    for superseded_id in task["supersedes"]:
        superseded = status["tasks"][superseded_id]
        if (
            _supersession_claimants(status["tasks"], superseded_id)
            or
            superseded["state"]
            not in {"planned", "ready", "implemented", "blocked"}
            or not set(superseded["requirements"]).issubset(task["requirements"])
        ):
            raise GuardianProgramError("task supersession target or coverage is invalid")
    if _ownership_conflicts(task, status["tasks"]):
        raise GuardianProgramError("task path ownership overlaps an unserialized task")
    return _append_event(
        root,
        actor=actor,
        kind="task_registered",
        payload=task,
        expected_last_sha256=status["last_event_sha256"],
    )


def record_evidence(
    root: Path,
    *,
    actor: str,
    scope: str,
    task_id: str,
    kind: str,
    path: Path,
    summary: str,
) -> dict[str, Any]:
    root = _secure_root(root, create=False)
    status = project(root)
    _require_authority(status)
    if scope == "program":
        if actor != status["coordinator"] or task_id:
            raise GuardianProgramError("program evidence requires the coordinator and no task")
    elif scope == "task":
        task = status["tasks"].get(task_id)
        if not task or actor not in {status["coordinator"], task["owner"]}:
            raise GuardianProgramError("task evidence actor or task is invalid")
    else:
        raise GuardianProgramError("evidence scope is invalid")
    candidate = path.expanduser().resolve(strict=True)
    try:
        relative = candidate.relative_to(root.resolve(strict=True))
    except ValueError as error:
        raise GuardianProgramError("evidence must be a real file inside the program root") from error
    if not candidate.is_file() or candidate.is_symlink():
        raise GuardianProgramError("evidence must be a non-symlink regular file")
    kind = _require_identifier(kind, label="evidence kind")
    summary = _require_text(summary, label="evidence summary")
    document = _validate_evidence_document(
        _load_json(candidate), scope=scope, task_id=task_id, kind=kind
    )
    if document["summary"] != summary:
        raise GuardianProgramError("evidence summary does not match its document")
    expected_baseline = (
        status["tasks"][task_id]["base_commit"]
        if scope == "task"
        else f"program:{status['program_id']}"
    )
    if document["baseline"] != expected_baseline:
        raise GuardianProgramError("evidence baseline does not match its authority scope")
    if scope == "task":
        task = status["tasks"][task_id]
        if (
            not task["verification_run_id"]
            or document["run_id"] != task["verification_run_id"]
        ):
            raise GuardianProgramError(
                "task evidence must bind the current coordinator-issued verification run"
            )
    if kind == "requirement_traceability":
        if scope != "task" or set(document["requirements"]) != set(
            status["tasks"][task_id]["requirements"]
        ):
            raise GuardianProgramError(
                "requirement_traceability must bind the task's exact requirement set"
            )
        expected_clauses = {
            (requirement_id, clause)
            for requirement_id in status["tasks"][task_id]["requirements"]
            for clause in status["requirements"][requirement_id]["acceptance"]
        }
        observed_clauses = {
            (row["requirement_id"], row["clause"])
            for row in document["acceptance"]
        }
        if observed_clauses != expected_clauses:
            raise GuardianProgramError(
                "requirement_traceability must bind every acceptance clause exactly"
            )
    if kind == "finding_resolution":
        if scope != "task" or not document["findings"]:
            raise GuardianProgramError(
                "finding_resolution must bind at least one task finding"
            )
        task = status["tasks"][task_id]
        for finding_id in document["findings"]:
            finding = status["findings"].get(finding_id)
            if not finding or (
                finding["task_id"] != task_id
                and finding_id not in task["finding_obligations"]
            ):
                raise GuardianProgramError(
                    "finding_resolution references a finding outside the task obligation"
                )
    artifact_errors = _evidence_artifact_errors(root, document)
    if artifact_errors:
        raise GuardianProgramError("evidence document references an invalid artifact")
    payload = {
        "evidence_id": f"evi-{secrets.token_hex(12)}",
        "scope": scope,
        "task_id": task_id,
        "kind": kind,
        "baseline": document["baseline"],
        "run_id": document["run_id"],
        "path": relative.as_posix(),
        "sha256": _file_digest(candidate),
        "verdict": document["verdict"],
        "requirements": document["requirements"],
        "findings": document["findings"],
        "acceptance": document["acceptance"],
        "summary": summary,
    }
    return _append_event(
        root,
        actor=actor,
        kind="evidence_recorded",
        payload=payload,
        expected_last_sha256=status["last_event_sha256"],
    )


def supersede_evidence(
    root: Path,
    *,
    actor: str,
    evidence_id: str,
    replacement_id: str,
) -> dict[str, Any]:
    root = _secure_root(root, create=False)
    status = project(root, verify_evidence=True)
    _require_authority(status)
    if actor != status["coordinator"]:
        raise GuardianProgramError("only the coordinator may supersede evidence")
    evidence = status["evidence"].get(evidence_id)
    replacement = status["evidence"].get(replacement_id)
    invalid_ids = {
        row["evidence_id"]
        for row in status["evidence_errors"]
        if row.get("reason") != "active_identity_conflict"
    }
    if (
        not evidence
        or evidence["superseded_by"]
        or not replacement
        or replacement["superseded_by"]
        or evidence_id == replacement_id
        or any(
            evidence[field] != replacement[field]
            for field in ("scope", "task_id", "kind", "baseline")
        )
        or replacement["verdict"] != "pass"
        or replacement["recorded_sequence"] <= evidence["recorded_sequence"]
        or not _replacement_preserves_semantics(evidence, replacement)
        or replacement_id in invalid_ids
    ):
        raise GuardianProgramError("evidence supersession authority or binding failed")
    return _append_event(
        root,
        actor=actor,
        kind="evidence_superseded",
        payload={"evidence_id": evidence_id, "replacement_id": replacement_id},
        expected_last_sha256=status["last_event_sha256"],
    )


def record_finding(
    root: Path,
    *,
    actor: str,
    task_id: str,
    finding_id: str,
    symptom: str,
    evidence: str,
    evidence_status: str,
) -> dict[str, Any]:
    root = _secure_root(root, create=False)
    status = project(root)
    _require_authority(status)
    task = status["tasks"].get(task_id)
    if not task or actor not in {status["coordinator"], task["owner"]}:
        raise GuardianProgramError("finding actor or task is invalid")
    payload = {
        "finding_id": _require_identifier(finding_id, label="finding_id"),
        "task_id": task_id,
        "symptom": _require_text(symptom, label="finding symptom"),
        "evidence": _require_text(evidence, label="finding evidence"),
        "evidence_status": _require_identifier(evidence_status, label="evidence_status"),
    }
    if payload["evidence_status"] not in FINDING_EVIDENCE_STATUSES:
        raise GuardianProgramError("finding evidence_status is invalid")
    if finding_id in status["findings"]:
        raise GuardianProgramError("finding is already registered")
    return _append_event(
        root,
        actor=actor,
        kind="finding_recorded",
        payload=payload,
        expected_last_sha256=status["last_event_sha256"],
    )


def resolve_finding(
    root: Path,
    *,
    actor: str,
    finding_id: str,
    disposition: str,
    root_cause: str,
    resolution: str,
    linked_task: str = "",
    evidence_id: str = "",
    human_evidence: str = "",
) -> dict[str, Any]:
    root = _secure_root(root, create=False)
    status = project(root, verify_evidence=True)
    _require_authority(status)
    if actor != status["coordinator"]:
        raise GuardianProgramError("only the coordinator may resolve findings")
    if finding_id not in status["findings"]:
        raise GuardianProgramError("finding does not exist")
    finding = status["findings"][finding_id]
    if finding["resolved_at"]:
        raise GuardianProgramError("finding is already resolved")
    if disposition not in FINDING_DISPOSITIONS:
        raise GuardianProgramError("finding disposition is invalid")
    linked_task = str(linked_task or "").strip()
    evidence_id = str(evidence_id or "").strip()
    human_evidence = str(human_evidence or "").strip()
    _validate_finding_resolution_channels(
        disposition,
        linked_task=linked_task,
        evidence_id=evidence_id,
        human_evidence=human_evidence,
    )
    manifest = _manifest(root)
    if disposition in {"transferred", "new_task"}:
        target = status["tasks"].get(linked_task)
        if (
            not target
            or linked_task == finding["task_id"]
            or target["state"] in {"accepted", "superseded"}
            or _supersession_claimants(status["tasks"], linked_task)
        ):
            raise GuardianProgramError(
                "finding transfer must reference a different non-terminal registered task"
            )
    if disposition == "deferred_human" and (
        not manifest["allow_human_deferred"] or not human_evidence
    ):
        raise GuardianProgramError("human deferral lacks manifest authority or evidence")
    if disposition == "rejected_with_evidence":
        resolution_evidence = status["evidence"].get(evidence_id)
        invalid_evidence_ids = {
            row["evidence_id"] for row in status["evidence_errors"]
        }
        if (
            not resolution_evidence
            or resolution_evidence["scope"] != "task"
            or resolution_evidence["task_id"] != finding["task_id"]
            or resolution_evidence["kind"] != "finding_resolution"
            or finding_id not in resolution_evidence["findings"]
            or resolution_evidence["verdict"] != "pass"
            or resolution_evidence["superseded_by"]
            or resolution_evidence["recorded_sequence"]
            <= finding["recorded_sequence"]
            or evidence_id in invalid_evidence_ids
        ):
            raise GuardianProgramError(
                "rejected finding must reference passing evidence for the same task"
            )
    payload = {
        "finding_id": finding_id,
        "disposition": disposition,
        "root_cause": _require_text(root_cause, label="root_cause"),
        "resolution": _require_text(resolution, label="resolution"),
        "linked_task": linked_task,
        "evidence_id": evidence_id,
        "human_evidence": human_evidence,
    }
    return _append_event(
        root,
        actor=actor,
        kind="finding_resolved",
        payload=payload,
        expected_last_sha256=status["last_event_sha256"],
    )


def transition(
    root: Path,
    *,
    actor: str,
    task_id: str,
    destination: str,
    note: str,
    superseded_by: str = "",
) -> dict[str, Any]:
    root = _secure_root(root, create=False)
    status = project(root, verify_evidence=True)
    _require_authority(status)
    task = status["tasks"].get(task_id)
    if not task:
        raise GuardianProgramError("task does not exist")
    source = task["state"]
    if destination not in TRANSITIONS[source]:
        raise GuardianProgramError("task transition is invalid")
    if destination in {"task_verified", "integrated", "system_verified", "accepted"}:
        if actor != status["coordinator"]:
            raise GuardianProgramError("only the coordinator may verify or accept work")
    elif actor not in {status["coordinator"], task["owner"]}:
        raise GuardianProgramError("task transition actor is unauthorized")
    if destination == "superseded":
        successor = status["tasks"].get(superseded_by)
        if (
            actor != status["coordinator"]
            or not successor
            or task_id not in successor["supersedes"]
        ):
            raise GuardianProgramError("task supersession authority or successor is invalid")
    elif superseded_by:
        raise GuardianProgramError("superseded_by is valid only for superseded transitions")
    if destination in {"ready", "running", "implemented", "task_verified", "integrated", "system_verified", "accepted"}:
        if _supersession_claimants(status["tasks"], task_id):
            raise GuardianProgramError(
                "a registered successor prevents the predecessor from becoming active"
            )
        if any(
            status["tasks"][superseded_id]["state"] != "superseded"
            or status["tasks"][superseded_id]["superseded_by"] != task_id
            for superseded_id in task["supersedes"]
        ):
            raise GuardianProgramError(
                "successor cannot become active before every predecessor is superseded"
            )
        unmet = [
            dependency
            for dependency in task["depends_on"]
            if not _dependency_is_accepted(status["tasks"], dependency)
        ]
        if unmet:
            raise GuardianProgramError("task dependencies are not accepted")
    required = (
        _required_evidence_through(task, destination)
        if destination in EVIDENCE_GATE_ORDER
        else set(task["evidence_gates"].get(destination, []))
    )
    missing = required - _task_evidence_kinds(status, task_id)
    if missing:
        raise GuardianProgramError(f"task transition lacks evidence: {','.join(sorted(missing))}")
    if destination in {"task_verified", "integrated", "system_verified", "accepted"}:
        if _open_findings(status, task_id):
            raise GuardianProgramError("task has unresolved findings")
        unresolved_obligations = set(task["finding_obligations"]) - (
            _finding_resolution_coverage(status, task_id)
        )
        if unresolved_obligations:
            raise GuardianProgramError(
                "task has transferred finding obligations without resolution evidence"
            )
    if destination in EVIDENCE_GATE_ORDER:
        invalid_ids = {row["evidence_id"] for row in status["evidence_errors"]}
        required_rows = [
            row
            for row in status["evidence"].values()
            if row["scope"] == "task"
            and row["task_id"] == task_id
            and row["kind"] in required
        ]
        if any(row["evidence_id"] in invalid_ids for row in required_rows):
            raise GuardianProgramError("task transition evidence is missing or has drifted")
    if source == "blocked" and actor != status["coordinator"]:
        raise GuardianProgramError("only the coordinator may unblock a task")
    if source in EVIDENCE_GATE_ORDER and destination == "running" and actor != status["coordinator"]:
        raise GuardianProgramError("only the coordinator may reopen verified work")
    return _append_event(
        root,
        actor=actor,
        kind="task_transitioned",
        payload={
            "task_id": task_id,
            "from": source,
            "to": destination,
            "note": _require_text(note, label="transition note"),
            "superseded_by": superseded_by,
        },
        expected_last_sha256=status["last_event_sha256"],
    )


def _capture_completion_snapshot(
    root: Path,
    status: dict[str, Any],
    *,
    authority_event_sha256: str,
) -> tuple[str, str]:
    entries: list[dict[str, Any]] = []
    for evidence_id in sorted(status["evidence"]):
        evidence = status["evidence"][evidence_id]
        if evidence["superseded_by"]:
            continue
        document_bytes = _read_bound_bytes(
            root, evidence["path"], evidence["sha256"]
        )
        document = _validate_evidence_document(
            _load_json_bytes(document_bytes, label="completion evidence"),
            scope=evidence["scope"],
            task_id=evidence["task_id"],
            kind=evidence["kind"],
        )
        binding_reason = _evidence_binding_reason(status, evidence, document)
        if binding_reason:
            raise GuardianProgramError(
                f"completion evidence binding failed: {binding_reason}"
            )
        artifacts: list[dict[str, str]] = []
        for artifact in document["artifacts"]:
            artifact_bytes = _read_bound_bytes(
                root, artifact["path"], artifact["sha256"]
            )
            _store_content_addressed(root, "blobs", ".blob", artifact_bytes)
            artifacts.append(dict(artifact))
        _store_content_addressed(root, "blobs", ".blob", document_bytes)
        entries.append(
            {
                "evidence_id": evidence_id,
                "document_sha256": evidence["sha256"],
                "artifacts": artifacts,
            }
        )
    snapshot = {
        "schema": COMPLETION_SNAPSHOT_SCHEMA,
        "program_id": status["program_id"],
        "authority_event_sha256": authority_event_sha256,
        "evidence": entries,
    }
    snapshot_bytes = _canonical(snapshot) + b"\n"
    snapshot_path = _store_content_addressed(
        root, "snapshots", ".json", snapshot_bytes
    )
    return (
        snapshot_path.relative_to(root).as_posix(),
        hashlib.sha256(snapshot_bytes).hexdigest(),
    )


def _validate_completion_payload(payload: Any) -> dict[str, str]:
    if not isinstance(payload, dict) or set(payload) != {
        "final_gate_sha256",
        "evidence_snapshot_path",
        "evidence_snapshot_sha256",
    }:
        raise GuardianProgramError("program completion payload is invalid")
    final_gate_sha256 = _require_sha256(
        payload.get("final_gate_sha256"), label="final_gate_sha256"
    )
    snapshot_sha256 = _require_sha256(
        payload.get("evidence_snapshot_sha256"),
        label="evidence_snapshot_sha256",
    )
    expected_path = (
        Path(COMPLETION_DIRECTORY)
        / "snapshots"
        / f"{snapshot_sha256}.json"
    ).as_posix()
    if payload.get("evidence_snapshot_path") != expected_path:
        raise GuardianProgramError("completion snapshot path is not content-addressed")
    return {
        "final_gate_sha256": final_gate_sha256,
        "evidence_snapshot_path": expected_path,
        "evidence_snapshot_sha256": snapshot_sha256,
    }


def _validate_completion_snapshot(
    root: Path,
    status: dict[str, Any],
    payload: dict[str, Any],
    *,
    authority_event_sha256: str,
) -> dict[str, Any]:
    normalized_payload = _validate_completion_payload(payload)
    expected_path = normalized_payload["evidence_snapshot_path"]
    snapshot_sha256 = normalized_payload["evidence_snapshot_sha256"]
    snapshot_bytes = _read_bound_bytes(
        root, expected_path, snapshot_sha256, immutable=True
    )
    snapshot = _load_json_bytes(snapshot_bytes, label="completion snapshot")
    if set(snapshot) != {
        "schema",
        "program_id",
        "authority_event_sha256",
        "evidence",
    } or snapshot.get("schema") != COMPLETION_SNAPSHOT_SCHEMA:
        raise GuardianProgramError("completion snapshot schema is invalid")
    if (
        snapshot.get("program_id") != status["program_id"]
        or snapshot.get("authority_event_sha256") != authority_event_sha256
    ):
        raise GuardianProgramError("completion snapshot authority binding is invalid")
    raw_entries = snapshot.get("evidence")
    if not isinstance(raw_entries, list):
        raise GuardianProgramError("completion snapshot evidence must be a list")
    active_evidence = {
        evidence_id: evidence
        for evidence_id, evidence in status["evidence"].items()
        if not evidence["superseded_by"]
    }
    observed_ids: list[str] = []
    for entry in raw_entries:
        if not isinstance(entry, dict) or set(entry) != {
            "evidence_id",
            "document_sha256",
            "artifacts",
        }:
            raise GuardianProgramError("completion snapshot evidence entry is invalid")
        evidence_id = _require_identifier(
            entry.get("evidence_id"), label="snapshot evidence_id"
        )
        evidence = active_evidence.get(evidence_id)
        if evidence is None or evidence_id in observed_ids:
            raise GuardianProgramError("completion snapshot evidence set is invalid")
        observed_ids.append(evidence_id)
        document_sha256 = _require_sha256(
            entry.get("document_sha256"), label="snapshot document_sha256"
        )
        if document_sha256 != evidence["sha256"]:
            raise GuardianProgramError("completion snapshot document binding is invalid")
        document_path = (
            Path(COMPLETION_DIRECTORY) / "blobs" / f"{document_sha256}.blob"
        ).as_posix()
        document_bytes = _read_bound_bytes(
            root, document_path, document_sha256, immutable=True
        )
        document = _validate_evidence_document(
            _load_json_bytes(document_bytes, label="snapshot evidence document"),
            scope=evidence["scope"],
            task_id=evidence["task_id"],
            kind=evidence["kind"],
        )
        binding_reason = _evidence_binding_reason(status, evidence, document)
        if binding_reason:
            raise GuardianProgramError(
                f"completion snapshot evidence binding failed: {binding_reason}"
            )
        if entry.get("artifacts") != document["artifacts"]:
            raise GuardianProgramError("completion snapshot artifact set is invalid")
        for artifact in document["artifacts"]:
            artifact_path = (
                Path(COMPLETION_DIRECTORY)
                / "blobs"
                / f"{artifact['sha256']}.blob"
            ).as_posix()
            _read_bound_bytes(
                root, artifact_path, artifact["sha256"], immutable=True
            )
    if observed_ids != sorted(active_evidence):
        raise GuardianProgramError("completion snapshot omits active evidence")
    return snapshot


def _final_gate_projection(
    status: dict[str, Any],
    manifest: dict[str, Any],
    *,
    authority_event_sha256: str,
    evidence_errors: list[dict[str, Any]],
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    for task in status["tasks"].values():
        if task["state"] == "superseded":
            successor = _terminal_successor(status["tasks"], task)
            if successor and successor["state"] == "accepted":
                continue
        if task["state"] != "accepted":
            blockers.append(
                {"kind": "task_state", "id": task["task_id"], "state": task["state"]}
            )
    for finding in _open_findings(status):
        blockers.append({"kind": "open_finding", "id": finding["finding_id"]})
    invalid_evidence_ids = {row["evidence_id"] for row in evidence_errors}
    for finding in status["findings"].values():
        if finding["disposition"] != "rejected_with_evidence":
            continue
        resolution_evidence = status["evidence"].get(
            finding["resolution_evidence_id"]
        )
        terminal_evidence = (
            _terminal_evidence(status["evidence"], resolution_evidence)
            if resolution_evidence
            else None
        )
        if (
            not terminal_evidence
            or terminal_evidence["scope"] != "task"
            or terminal_evidence["task_id"] != finding["task_id"]
            or terminal_evidence["kind"] != "finding_resolution"
            or finding["finding_id"] not in terminal_evidence["findings"]
            or terminal_evidence["verdict"] != "pass"
            or terminal_evidence["evidence_id"] in invalid_evidence_ids
            or terminal_evidence["recorded_sequence"]
            <= status["tasks"][finding["task_id"]]["evidence_floor_sequence"]
            or terminal_evidence["run_id"]
            != status["tasks"][finding["task_id"]]["verification_run_id"]
        ):
            blockers.append(
                {
                    "kind": "finding_resolution_evidence_invalid",
                    "id": finding["finding_id"],
                }
            )
    for task in status["tasks"].values():
        if task["state"] != "accepted" or not task["finding_obligations"]:
            continue
        covered_findings = {
            finding_id
            for evidence in status["evidence"].values()
            if evidence["scope"] == "task"
            and evidence["task_id"] == task["task_id"]
            and evidence["kind"] == "finding_resolution"
            and evidence["verdict"] == "pass"
            and not evidence["superseded_by"]
            and evidence["evidence_id"] not in invalid_evidence_ids
            and evidence["recorded_sequence"] > task["evidence_floor_sequence"]
            and evidence["run_id"] == task["verification_run_id"]
            for finding_id in evidence["findings"]
        }
        for finding_id in sorted(
            set(task["finding_obligations"]) - covered_findings
        ):
            blockers.append(
                {
                    "kind": "finding_obligation_evidence_invalid",
                    "id": finding_id,
                    "task_id": task["task_id"],
                }
            )
    traced_tasks = {
        row["task_id"]
        for row in status["evidence"].values()
        if row["scope"] == "task"
        and row["kind"] == "requirement_traceability"
        and row["verdict"] == "pass"
        and not row["superseded_by"]
        and row["evidence_id"] not in invalid_evidence_ids
        and row["recorded_sequence"]
        > status["tasks"][row["task_id"]]["evidence_floor_sequence"]
        and row["run_id"]
        == status["tasks"][row["task_id"]]["verification_run_id"]
    }
    covered = {
        requirement
        for task in status["tasks"].values()
        if task["state"] == "accepted" and task["task_id"] in traced_tasks
        for requirement in task["requirements"]
    }
    for requirement_id in sorted(set(status["requirements"]) - covered):
        blockers.append({"kind": "uncovered_requirement", "id": requirement_id})
    program_evidence = {
        row["kind"]
        for row in status["evidence"].values()
        if row["scope"] == "program"
        and row["verdict"] == "pass"
        and not row["superseded_by"]
    }
    for kind in sorted(set(manifest["program_evidence_required"]) - program_evidence):
        blockers.append({"kind": "missing_program_evidence", "id": kind})
    blockers.extend(
        {"kind": "invalid_evidence", **row} for row in evidence_errors
    )
    return {
        "schema": "sulde-guardian-program-final-gate-v1",
        "program_id": status["program_id"],
        "authority_event_sha256": authority_event_sha256,
        "ready": not blockers,
        "blockers": blockers,
        "counts": {
            "requirements": len(status["requirements"]),
            "tasks": len(status["tasks"]),
            "findings": len(status["findings"]),
            "evidence": len(status["evidence"]),
        },
    }


def final_gate(root: Path) -> dict[str, Any]:
    status = project(root, verify_evidence=True)
    manifest = _manifest(root)
    authority_event_sha256 = status["last_event_sha256"]
    if status["completion_event_seen"] and status["completion"]:
        authority_event_sha256 = status["completion"]["authority_event_sha256"]
    return _final_gate_projection(
        status,
        manifest,
        authority_event_sha256=authority_event_sha256,
        evidence_errors=status["evidence_errors"],
    )


def complete(root: Path, *, actor: str) -> dict[str, Any]:
    root = _secure_root(root, create=False)
    actor = _require_identifier(actor, label="actor")
    with _control_lock(root):
        events = _read_events(root)
        status = project(root, _events=events, _manifest_value=_manifest(root))
        _require_authority(status)
        if actor != status["coordinator"]:
            raise GuardianProgramError("only the coordinator may complete the program")
        if status["completion_event_seen"]:
            if status["completion"]["integrity"] != "verified":
                raise GuardianProgramError("completed program has failed snapshot integrity")
            return events[-1]
        authority_event_sha256 = status["last_event_sha256"]
        manifest = _manifest(root)
        gate = _final_gate_projection(
            status,
            manifest,
            authority_event_sha256=authority_event_sha256,
            evidence_errors=status["evidence_errors"],
        )
        if not gate["ready"]:
            raise GuardianProgramError("final gate is not ready")
        final_gate_sha256 = _digest(gate)
        prepared = _load_prepared_completion(
            root,
            program_id=status["program_id"],
            authority_event_sha256=authority_event_sha256,
            final_gate_sha256=final_gate_sha256,
        )
        if prepared is None:
            status = project(
                root,
                verify_evidence=True,
                _events=events,
                _manifest_value=manifest,
            )
            verified_gate = _final_gate_projection(
                status,
                manifest,
                authority_event_sha256=authority_event_sha256,
                evidence_errors=status["evidence_errors"],
            )
            if not verified_gate["ready"]:
                raise GuardianProgramError("final gate is not ready")
            if _digest(verified_gate) != final_gate_sha256:
                raise GuardianProgramError("final gate changed during completion prepare")
            snapshot_path, snapshot_sha256 = _capture_completion_snapshot(
                root,
                status,
                authority_event_sha256=authority_event_sha256,
            )
            prepared = _store_prepared_completion(
                root,
                {
                    "schema": PREPARED_COMPLETION_SCHEMA,
                    "program_id": status["program_id"],
                    "authority_event_sha256": authority_event_sha256,
                    "final_gate_sha256": final_gate_sha256,
                    "evidence_snapshot_path": snapshot_path,
                    "evidence_snapshot_sha256": snapshot_sha256,
                },
            )
        payload = _prepared_completion_payload(prepared)
        _validate_completion_snapshot(
            root,
            status,
            payload,
            authority_event_sha256=authority_event_sha256,
        )
        row: dict[str, Any] = {
            "schema": EVENT_SCHEMA,
            "sequence": len(events) + 1,
            "event_id": f"gpe-{secrets.token_hex(12)}",
            "at": _now(),
            "actor": actor,
            "type": "program_completed",
            "payload": payload,
            "previous_sha256": authority_event_sha256,
        }
        row["event_sha256"] = _digest(row)
        candidate_status = project(
            root,
            _events=[*events, row],
            _manifest_value=manifest,
        )
        if (
            not candidate_status["program_completed"]
            or candidate_status["completion"]["integrity"] != "verified"
        ):
            raise GuardianProgramError("completion snapshot changed before commit")
        _write_event_row(root, row)
        committed_status = project(root)
        if not committed_status["program_completed"]:
            raise GuardianProgramError(
                "completion event committed with failed snapshot integrity"
            )
        return row


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    initialize_parser = subparsers.add_parser("init")
    initialize_parser.add_argument("root", type=Path)
    initialize_parser.add_argument("--manifest", type=Path, required=True)
    initialize_parser.add_argument("--actor", required=True)

    authority_parser = subparsers.add_parser("authority-provision")
    authority_parser.add_argument("root", type=Path)

    authority_rotate_parser = subparsers.add_parser("authority-rotate")
    authority_rotate_parser.add_argument("root", type=Path)
    authority_rotate_parser.add_argument("--actor", required=True)
    authority_rotate_parser.add_argument("--expected-last-sha256", required=True)
    authority_rotate_parser.add_argument("--confirmation", required=True)
    authority_rotate_parser.add_argument("--approval-id", required=True)
    authority_rotate_parser.add_argument("--reason", required=True)

    task_parser = subparsers.add_parser("task-add")
    task_parser.add_argument("root", type=Path)
    task_parser.add_argument("--task", type=Path, required=True)
    task_parser.add_argument("--actor", required=True)

    evidence_parser = subparsers.add_parser("evidence-add")
    evidence_parser.add_argument("root", type=Path)
    evidence_parser.add_argument("--actor", required=True)
    evidence_parser.add_argument("--scope", choices=("program", "task"), required=True)
    evidence_parser.add_argument("--task-id", default="")
    evidence_parser.add_argument("--kind", required=True)
    evidence_parser.add_argument("--path", type=Path, required=True)
    evidence_parser.add_argument("--summary", required=True)

    evidence_supersede_parser = subparsers.add_parser("evidence-supersede")
    evidence_supersede_parser.add_argument("root", type=Path)
    evidence_supersede_parser.add_argument("--actor", required=True)
    evidence_supersede_parser.add_argument("--evidence-id", required=True)
    evidence_supersede_parser.add_argument("--replacement-id", required=True)

    finding_parser = subparsers.add_parser("finding-add")
    finding_parser.add_argument("root", type=Path)
    finding_parser.add_argument("--actor", required=True)
    finding_parser.add_argument("--task-id", required=True)
    finding_parser.add_argument("--finding-id", required=True)
    finding_parser.add_argument("--symptom", required=True)
    finding_parser.add_argument("--evidence", required=True)
    finding_parser.add_argument("--evidence-status", required=True)

    resolve_parser = subparsers.add_parser("finding-resolve")
    resolve_parser.add_argument("root", type=Path)
    resolve_parser.add_argument("--actor", required=True)
    resolve_parser.add_argument("--finding-id", required=True)
    resolve_parser.add_argument("--disposition", choices=sorted(FINDING_DISPOSITIONS), required=True)
    resolve_parser.add_argument("--root-cause", required=True)
    resolve_parser.add_argument("--resolution", required=True)
    resolve_parser.add_argument("--linked-task", default="")
    resolve_parser.add_argument("--evidence-id", default="")
    resolve_parser.add_argument("--human-evidence", default="")

    transition_parser = subparsers.add_parser("transition")
    transition_parser.add_argument("root", type=Path)
    transition_parser.add_argument("--actor", required=True)
    transition_parser.add_argument("--task-id", required=True)
    transition_parser.add_argument("--to", choices=TASK_STATES, required=True)
    transition_parser.add_argument("--note", required=True)
    transition_parser.add_argument("--superseded-by", default="")

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("root", type=Path)
    status_parser.add_argument("--verify-evidence", action="store_true")

    final_parser = subparsers.add_parser("final-check")
    final_parser.add_argument("root", type=Path)

    complete_parser = subparsers.add_parser("complete")
    complete_parser.add_argument("root", type=Path)
    complete_parser.add_argument("--actor", required=True)

    materialize_parser = subparsers.add_parser("materialize-completion-permissions")
    materialize_parser.add_argument("root", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "init":
            result = initialize(arguments.root, arguments.manifest, actor=arguments.actor)
        elif arguments.command == "authority-provision":
            result = provision_authority(arguments.root)
        elif arguments.command == "authority-rotate":
            result = rotate_lost_authority(
                arguments.root,
                actor=arguments.actor,
                expected_last_sha256=arguments.expected_last_sha256,
                confirmation=arguments.confirmation,
                approval_id=arguments.approval_id,
                reason=arguments.reason,
            )
        elif arguments.command == "task-add":
            result = register_task(arguments.root, arguments.task, actor=arguments.actor)
        elif arguments.command == "evidence-add":
            result = record_evidence(
                arguments.root,
                actor=arguments.actor,
                scope=arguments.scope,
                task_id=arguments.task_id,
                kind=arguments.kind,
                path=arguments.path,
                summary=arguments.summary,
            )
        elif arguments.command == "evidence-supersede":
            result = supersede_evidence(
                arguments.root,
                actor=arguments.actor,
                evidence_id=arguments.evidence_id,
                replacement_id=arguments.replacement_id,
            )
        elif arguments.command == "finding-add":
            result = record_finding(
                arguments.root,
                actor=arguments.actor,
                task_id=arguments.task_id,
                finding_id=arguments.finding_id,
                symptom=arguments.symptom,
                evidence=arguments.evidence,
                evidence_status=arguments.evidence_status,
            )
        elif arguments.command == "finding-resolve":
            result = resolve_finding(
                arguments.root,
                actor=arguments.actor,
                finding_id=arguments.finding_id,
                disposition=arguments.disposition,
                root_cause=arguments.root_cause,
                resolution=arguments.resolution,
                linked_task=arguments.linked_task,
                evidence_id=arguments.evidence_id,
                human_evidence=arguments.human_evidence,
            )
        elif arguments.command == "transition":
            result = transition(
                arguments.root,
                actor=arguments.actor,
                task_id=arguments.task_id,
                destination=arguments.to,
                note=arguments.note,
                superseded_by=arguments.superseded_by,
            )
        elif arguments.command == "status":
            result = project(arguments.root, verify_evidence=arguments.verify_evidence)
        elif arguments.command == "final-check":
            result = final_gate(arguments.root)
        elif arguments.command == "materialize-completion-permissions":
            result = materialize_completion_permissions(arguments.root)
        else:
            result = complete(arguments.root, actor=arguments.actor)
    except GuardianProgramError as error:
        print(json.dumps({"status": "error", "error": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
