#!/usr/bin/env python3
"""Run and verify an approved Sulde L3 task through either host provider."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import os
import re
import signal
import shlex
import stat
import subprocess
import sys
import tempfile
import threading
import time
from queue import Empty, Queue
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator

# This entrypoint imports installed sibling modules before it can verify the
# digest-bound native authority. Disable bytecode first so merely loading the
# verifier cannot mutate the sealed runtime and then fail its own tree check.
sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

_KB_MODULE_DIRECTORY = str(Path(__file__).resolve().parent)
if _KB_MODULE_DIRECTORY not in sys.path:
    sys.path.insert(0, _KB_MODULE_DIRECTORY)

from codex_cli_contract import (
    NATIVE_AUTHORITY_SPEC_VERSION,
    AUDITED_CODEX_VERSION,
    CodexCliContractError,
    bound_codex_executable,
    canonical_codex_help_observation,
    codex_probe_environment,
    codex_probe_spec,
    successful_version_identity,
)

from audit_cursor import (
    AuditCursorError,
    cursor_digest,
    load_cursor,
    save_cursor,
    scan_increment,
)

from execution_backend import (
    ExecutionBackend,
    ExecutionBackendError,
    RunHandle,
    recover_incomplete_run,
)
from file_lock import lock_exclusive_nonblocking, unlock
from correction_intervention import (
    CorrectionInterventionError,
    authoritative_snapshot as correction_authoritative_snapshot,
    authoritative_store_bytes as correction_store_bytes,
    load_projection as load_correction_projection,
    queued_corrections,
    restore_authoritative_store as restore_correction_store,
    transition_correction,
)
from command_template import split_command_template
from intent_guardian import (
    GuardianSession,
    IntentGuardianError,
    contract_from_brief,
    event_fingerprint,
    load_contract,
    normalize_hook_event,
    normalize_provider_events,
    write_contract,
)
from intervention import (
    InterventionError,
    begin_attempt,
    canonical_resource_key,
    mark_attempt_result,
)
from intent_critic import (
    TaskCriticScope,
    bind_task_critic_checkpoint_event,
    build_prompt as build_critic_prompt,
    run_critic,
    secret_matches as critic_secret_matches,
)
from runtime_provider import ProviderError, select_provider, task_command
from terminal_invariants import terminal_invariant_failures
from guardian_program import GuardianProgramError, materialize_completion_permissions
import native_agent_broker


STATE_DIRECTORY = ".codex-agent"  # Stable artifact protocol; provider-neutral since WP36.
SKIP_DIRECTORIES = {
    STATE_DIRECTORY,
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".pytest_cache",
}
REPORT_CONTRACT_VERSION = "sulde-worker-report-v1"
REPORT_DIAGNOSTIC_SCHEMA = "sulde-worker-diagnostic-v1"
REPORT_SUPERSESSION_SCHEMA = "sulde-worker-diagnostic-supersession-v1"
REPORT_EVIDENCE_SOURCE_STRENGTH = {
    "worker": 1,
    "nested_host": 1,
    "coordinator": 2,
    "system": 3,
}
REPORT_CONTRACT = {
    "schema": REPORT_CONTRACT_VERSION,
    "headings": (
        "结果",
        "过程",
        "遇到的问题",
        "解决方式",
        "遗留风险与建议",
    ),
    "conditional_heading": "沉淀候选",
    "evidence_schema": (
        "✅ <说明>：`<实际命令>`，exit 0；<可观察结果>；candidate_sha256=<sha256>；"
        "execution_binding_sha256=<sha256>；environment_sha256=<sha256>；"
        "command_sha256=<sha256>；count=<整数>"
    ),
    "coordinator_evidence_fields": (
        "contract_schema",
        "headings",
        "checks",
        "command",
        "exit_code",
        "observable_result",
        "candidate_sha256",
        "execution_binding_sha256",
        "environment_sha256",
        "command_sha256",
        "count",
    ),
}
ARTIFACT_SUFFIXES = (
    "last.md",
    "events.jsonl",
    "stderr.log",
    "status",
    "baseline",
    "guardian.json",
    "run.jsonl",
    "events.cursor.json",
    "heartbeat.json",
    "heartbeat.jsonl",
    "preflight.json",
)

_MAX_CONTROL_BYTES = 2 * 1024 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_OID_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
TASK_V1_SCHEMA = "sulde-guardian-program-task-v1"
TASK_V1_FIELDS = frozenset(
    {
        "schema",
        "task_id",
        "title",
        "owner",
        "capability_tier",
        "base_commit",
        "depends_on",
        "supersedes",
        "owned_paths",
        "requirements",
        "acceptance",
        "evidence_gates",
    }
)
TASK_V1_EVIDENCE_GATES = frozenset(
    {"implemented", "task_verified", "integrated", "system_verified"}
)
EXECUTION_BINDING_SCHEMA = "sulde-guardian-execution-binding-v1"
EXECUTION_BINDING_ARTIFACT_SCHEMA = (
    "sulde-guardian-execution-binding-artifact-v1"
)
EXECUTION_BINDING_FIELDS = frozenset(
    {
        "schema",
        "task_definition_sha256",
        "brief",
        "worktree",
        "git_common_dir",
        "task_id",
        "base_commit",
        "owned_paths",
        "path_schema",
    }
)

# The shared Codex CLI contract is an audited production dependency, not a
# provider selector. In particular, PATH and SULDE_CODEX_EXE are data-only in
# a managed production run. Test fixtures continue to use SULDE_TEST_MODE, but
# can never satisfy the installed-artifact gate below.
NATIVE_AUTHORITY_SCHEMA = "sulde-installed-native-runtime-authority-v1"
PERMISSION_PROFILE_SPEC_VERSION = 4
BROKER_PROTOCOL_SPEC_VERSION = 2
DEPLOYMENT_GENERATION_SCHEMA = "sulde-installed-deployment-generation-v1"
DEPLOYMENT_GENERATION_NAME = "deployment-generation.json"
CODEX_INITIALIZE_MAX_ATTEMPTS = 3
DIAGNOSTIC_STREAM_TARGETS = frozenset(
    {"/dev/stdout", "/dev/stderr", "/dev/fd/1", "/dev/fd/2"}
)


class AgentRuntimeError(RuntimeError):
    """A controlled task-runner or verification failure."""


class CodexPreflightError(AgentRuntimeError):
    """A bounded preflight failure with every initialize attempt attached."""

    def __init__(self, message: str, attempts: list[dict[str, Any]]) -> None:
        super().__init__(message)
        self.initialize_attempts = [dict(row) for row in attempts]


class CodexGitLayoutError(AgentRuntimeError):
    """The repository layout cannot be represented by the Codex profile."""


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        parent_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(parent_descriptor)
        finally:
            os.close(parent_descriptor)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def atomic_write_bytes(path: Path, content: bytes) -> None:
    """Atomically persist opaque control evidence without a text decode."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        parent_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(parent_descriptor)
        finally:
            os.close(parent_descriptor)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _canonical_provider_final_bytes(value: Any) -> bytes:
    """Encode provider final text into the one accepted report byte shape."""
    if type(value) is not str:
        raise AgentRuntimeError("provider final message must be an exact string")
    try:
        raw = value.encode("utf-8", "strict")
    except UnicodeError as error:
        raise AgentRuntimeError("provider final message is not strict UTF-8") from error
    if raw.endswith(b"\r") or raw.endswith(b"\r\n"):
        raise AgentRuntimeError("provider final message has a CR terminal")
    if raw.endswith(b"\n\n"):
        raise AgentRuntimeError("provider final message has multiple terminal LFs")
    return raw if raw.endswith(b"\n") else raw + b"\n"


def _durable_worker_report_relative_path(owned_paths: Any) -> str:
    """Select exactly one canonical durable report from verified task scope."""
    if type(owned_paths) is not list:
        raise AgentRuntimeError("task owned_paths are unavailable for report authority")
    candidates: list[str] = []
    for value in owned_paths:
        if type(value) is not str:
            raise AgentRuntimeError("task owned_paths contain a non-string report path")
        canonical = _canonical_owned_path(value)
        if (
            canonical.startswith(
                (
                    "guardian-r2-program/reports/",
                    "guardian-program/reports/",
                    "life-program/reports/",
                )
            )
            and canonical.endswith(".md")
            and not canonical.endswith("/**")
        ):
            candidates.append(canonical)
    if len(candidates) != 1:
        raise AgentRuntimeError(
            "task must own exactly one supported program durable report"
        )
    return candidates[0]


def _read_relative_regular_file(
    root: Path,
    relative: str,
    *,
    label: str,
    snapshot: dict[str, Any] | None = None,
    pinned_descriptors: list[int] | None = None,
) -> bytes:
    """Read a bounded repo-relative regular file without following symlinks."""
    canonical = _canonical_owned_path(relative)
    if canonical.endswith("/**"):
        raise AgentRuntimeError(f"{label} must identify one regular file")
    try:
        root_path = _lexical_absolute(root).resolve(strict=True)
    except OSError as error:
        raise AgentRuntimeError(f"{label} root cannot be resolved") from error
    parent_paths = [
        root_path.joinpath(*Path(canonical).parts[:index])
        for index in range(len(Path(canonical).parts))
    ]
    before_parents = [(path, _directory_identity(path)) for path in parent_paths]
    directory_descriptor = -1
    file_descriptor = -1
    try:
        root_metadata = root_path.lstat()
        if not stat.S_ISDIR(root_metadata.st_mode) or stat.S_ISLNK(root_metadata.st_mode):
            raise AgentRuntimeError(f"{label} root is not a real directory")
        directory_descriptor = os.open(
            root_path,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        opened_root = os.fstat(directory_descriptor)
        if (opened_root.st_dev, opened_root.st_ino) != (
            root_metadata.st_dev,
            root_metadata.st_ino,
        ):
            raise AgentRuntimeError(f"{label} root changed before open")
        if pinned_descriptors is not None:
            pinned_descriptors.append(os.dup(directory_descriptor))
        parts = Path(canonical).parts
        for part in parts[:-1]:
            next_descriptor = os.open(
                part,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=directory_descriptor,
            )
            os.close(directory_descriptor)
            directory_descriptor = next_descriptor
            if pinned_descriptors is not None:
                pinned_descriptors.append(os.dup(directory_descriptor))
        file_descriptor = os.open(
            parts[-1],
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=directory_descriptor,
        )
        if pinned_descriptors is not None:
            pinned_descriptors.append(os.dup(file_descriptor))
        before = os.fstat(file_descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise AgentRuntimeError(f"{label} is not a single-link regular file")
        if before.st_size > _MAX_CONTROL_BYTES:
            raise AgentRuntimeError(f"{label} exceeds the fixed byte-size bound")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(file_descriptor, min(remaining, 64 * 1024))
            if not chunk:
                raise AgentRuntimeError(f"{label} changed while being read")
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(file_descriptor)
        if (
            (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            )
            != (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            )
            or len(raw) != before.st_size
        ):
            raise AgentRuntimeError(f"{label} changed while being read")
        linked_after = os.stat(
            parts[-1],
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        if (linked_after.st_dev, linked_after.st_ino) != (
            before.st_dev,
            before.st_ino,
        ):
            raise AgentRuntimeError(f"{label} pathname changed while being read")
        after_parents = [
            (path, _directory_identity(path)) for path in parent_paths
        ]
        if before_parents != after_parents:
            raise AgentRuntimeError(
                f"{label} parent chain changed while being read"
            )
        if snapshot is not None:
            snapshot.update(
                identity=(tuple(before_parents), before.st_dev, before.st_ino,
                          before.st_mode, before.st_nlink),
                version=(before.st_size, before.st_mtime_ns, before.st_ctime_ns),
            )
        return raw
    except AgentRuntimeError:
        raise
    except OSError as error:
        raise AgentRuntimeError(f"{label} cannot be opened without symlink traversal") from error
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        if directory_descriptor >= 0:
            os.close(directory_descriptor)


def _read_codex_output_last_message(root: Path, report: Path) -> str:
    """Read Codex's final-message file as the production output authority."""
    try:
        root_path = _lexical_absolute(root).resolve(strict=True)
        state_path = (root_path / STATE_DIRECTORY).resolve(strict=True)
        report_parent = _lexical_absolute(report).parent.resolve(strict=True)
    except OSError as error:
        raise AgentRuntimeError(
            "Codex output-last-message parent cannot be resolved"
        ) from error
    if (
        report_parent != state_path
        or report.name in {"", ".", ".."}
    ):
        raise AgentRuntimeError(
            "Codex output-last-message path is not a direct state child"
        )
    raw = _read_relative_regular_file(
        state_path,
        report.name,
        label="Codex output-last-message",
    )
    try:
        message = raw.decode("utf-8", "strict")
    except UnicodeDecodeError as error:
        raise AgentRuntimeError(
            "Codex output-last-message is not strict UTF-8"
        ) from error
    if not message:
        raise AgentRuntimeError("Codex output-last-message is empty")
    return message


def _settle_provider_result(
    handle: RunHandle,
    *,
    provider: str,
    test_mode: bool,
    root: Path,
    report: Path,
    observed_status: str,
    returncode: int,
    streamed_final_message: str,
) -> tuple[Any, str]:
    """Select production Codex output authority immediately before settle."""
    final_message = streamed_final_message
    if provider == "codex" and not test_mode:
        if observed_status in {"paused", "awaiting_human", "timeout"}:
            final_message = ""
        else:
            final_message = _canonical_provider_final_bytes(
                _read_codex_output_last_message(root, report)
            ).decode("utf-8", "strict")
    result = handle.settle(
        stop_reason=normalized_stop_reason(observed_status, returncode),
        output=final_message,
    )
    return result, final_message


def _read_durable_worker_report(root: Path, owned_paths: Any) -> tuple[Path, bytes]:
    relative = _durable_worker_report_relative_path(owned_paths)
    raw = _read_relative_regular_file(root, relative, label="durable worker report")
    return root / relative, raw


def _persist_canonical_worker_report(root: Path, path: Path, canonical: bytes) -> bytes:
    root_path = _lexical_absolute(root).resolve(strict=True)
    state_path = (root_path / STATE_DIRECTORY).resolve(strict=True)
    if _lexical_absolute(path).parent.resolve(strict=True) != state_path:
        raise AgentRuntimeError(
            "canonical worker report is not a direct state child"
        )
    root_descriptor = -1
    state_descriptor = -1
    temporary_descriptor = -1
    temporary_name = f".{path.name}.{os.getpid()}.{time.monotonic_ns()}.tmp"
    temporary_exists = False
    try:
        root_before = root_path.lstat()
        root_descriptor = os.open(
            root_path,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        root_opened = os.fstat(root_descriptor)
        if (root_opened.st_dev, root_opened.st_ino) != (
            root_before.st_dev,
            root_before.st_ino,
        ):
            raise AgentRuntimeError(
                "canonical worker report root changed before open"
            )
        state_linked = os.stat(
            STATE_DIRECTORY,
            dir_fd=root_descriptor,
            follow_symlinks=False,
        )
        state_descriptor = os.open(
            STATE_DIRECTORY,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=root_descriptor,
        )
        state_opened = os.fstat(state_descriptor)
        if (state_opened.st_dev, state_opened.st_ino) != (
            state_linked.st_dev,
            state_linked.st_ino,
        ):
            raise AgentRuntimeError(
                "canonical worker report parent changed before open"
            )
        def validate_parent_path() -> None:
            root_after = root_path.lstat()
            state_after = os.stat(
                STATE_DIRECTORY,
                dir_fd=root_descriptor,
                follow_symlinks=False,
            )
            if (
                (root_after.st_dev, root_after.st_ino)
                != (root_opened.st_dev, root_opened.st_ino)
                or (state_after.st_dev, state_after.st_ino)
                != (state_opened.st_dev, state_opened.st_ino)
            ):
                raise AgentRuntimeError(
                    "canonical worker report parent chain changed"
                )
        validate_parent_path()
        temporary_descriptor = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=state_descriptor,
        )
        temporary_exists = True
        offset = 0
        while offset < len(canonical):
            written = os.write(temporary_descriptor, canonical[offset:])
            if written <= 0:
                raise AgentRuntimeError(
                    "canonical worker report temporary write became short"
                )
            offset += written
        os.fsync(temporary_descriptor)
        temporary_metadata = os.fstat(temporary_descriptor)
        validate_parent_path()
        os.rename(
            temporary_name,
            path.name,
            src_dir_fd=state_descriptor,
            dst_dir_fd=state_descriptor,
        )
        temporary_exists = False
        os.fsync(state_descriptor)
        linked = os.stat(
            path.name,
            dir_fd=state_descriptor,
            follow_symlinks=False,
        )
        if (linked.st_dev, linked.st_ino) != (
            temporary_metadata.st_dev,
            temporary_metadata.st_ino,
        ):
            raise AgentRuntimeError(
                "canonical worker report was replaced after rename"
            )
        os.close(temporary_descriptor)
        temporary_descriptor = os.open(
            path.name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=state_descriptor,
        )
        opened = os.fstat(temporary_descriptor)
        if (opened.st_dev, opened.st_ino) != (
            temporary_metadata.st_dev,
            temporary_metadata.st_ino,
        ):
            raise AgentRuntimeError(
                "canonical worker report was replaced before readback"
            )
        chunks: list[bytes] = []
        remaining = opened.st_size
        while remaining:
            block = os.read(temporary_descriptor, min(remaining, 64 * 1024))
            if not block:
                raise AgentRuntimeError(
                    "canonical worker report readback became short"
                )
            chunks.append(block)
            remaining -= len(block)
        rebound = b"".join(chunks)
        validate_parent_path()
        final_metadata = os.fstat(temporary_descriptor)
        if (
            final_metadata.st_size != opened.st_size
            or final_metadata.st_mtime_ns != opened.st_mtime_ns
            or final_metadata.st_ctime_ns != opened.st_ctime_ns
        ):
            raise AgentRuntimeError(
                "canonical worker report changed during readback"
            )
        if rebound != canonical:
            raise AgentRuntimeError(
                "canonical worker report drifted after descriptor-relative write"
            )
        return rebound
    except OSError as error:
        raise AgentRuntimeError(
            "canonical worker report cannot be written safely"
        ) from error
    finally:
        if temporary_descriptor >= 0:
            os.close(temporary_descriptor)
        if temporary_exists and state_descriptor >= 0:
            try:
                os.unlink(temporary_name, dir_fd=state_descriptor)
            except OSError:
                pass
        if state_descriptor >= 0:
            os.close(state_descriptor)
        if root_descriptor >= 0:
            os.close(root_descriptor)



def _close_canonical_worker_report_authority(
    root: Path,
    owned_paths: Any,
    provider_final_text: Any,
    last_path: Path,
) -> bytes:
    canonical = _canonical_provider_final_bytes(provider_final_text)
    relative = _durable_worker_report_relative_path(owned_paths)
    # Only final closure gets this visibility allowance. Never retry an unsafe
    # read, change file identity, or rewrite the durable authority to match.
    # Keep the original inodes alive across sleeps, preventing inode reuse
    # from disguising a replacement as the same authority.
    pins: list[int] = []
    try:
        deadline = time.monotonic() + 0.2
        identity = None
        matched_snapshot = None
        for attempt in range(11):
            snapshot: dict[str, Any] = {}
            durable = _read_relative_regular_file(
                root, relative, label="durable worker report", snapshot=snapshot,
                pinned_descriptors=pins if identity is None else None,
            )
            if identity is None:
                identity = snapshot["identity"]
            elif snapshot["identity"] != identity:
                raise AgentRuntimeError("durable worker report changed identity during closure")
            if time.monotonic() > deadline:
                raise AgentRuntimeError(
                    "durable worker report does not equal stable canonical provider final bytes"
                )
            if matched_snapshot is not None:
                if durable != canonical or snapshot != matched_snapshot:
                    raise AgentRuntimeError("durable worker report changed during closure")
                break
            if durable == canonical:
                matched_snapshot = snapshot
            remaining = deadline - time.monotonic()
            if attempt == 10 or remaining <= 0:
                raise AgentRuntimeError(
                    "durable worker report does not equal stable canonical provider final bytes"
                )
            time.sleep(min(0.02, remaining))
        rebound = _persist_canonical_worker_report(root, last_path, canonical)
        if rebound != canonical:
            raise AgentRuntimeError("canonical report authorities diverged")
        final_snapshot: dict[str, Any] = {}
        durable_after = _read_relative_regular_file(
            root, relative, label="durable worker report", snapshot=final_snapshot,
        )
        if durable_after != canonical or final_snapshot != matched_snapshot:
            raise AgentRuntimeError("durable worker report changed during closure")
        return canonical
    finally:
        for descriptor in pins:
            os.close(descriptor)


HEARTBEAT_SCHEMA = "sulde-managed-phase-heartbeat-v1"
HEARTBEAT_FIELDS = frozenset(
    {
        "schema",
        "run_id",
        "phase_sequence",
        "phase",
        "reason",
        "observed_monotonic_ns",
        "age_ns",
        "expires_after_ns",
        "expires_monotonic_ns",
        "expired",
        "default_action",
        "terminal",
    }
)
HEARTBEAT_DEFAULT_ACTIONS = frozenset(
    {"observe", "interrupt_and_fail_closed", "none"}
)


def validate_phase_heartbeat_rows(
    rows: Any,
    *,
    now_monotonic_ns: int | None = None,
    require_live: bool = False,
) -> dict[str, Any]:
    """Validate monotonic heartbeat history and project current age/expiry."""
    if type(rows) is not list or not rows:
        raise AgentRuntimeError("phase heartbeat history is empty")
    previous_sequence = 0
    previous_monotonic = -1
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if type(row) is not dict or set(row) != HEARTBEAT_FIELDS:
            raise AgentRuntimeError("phase heartbeat fields are invalid")
        sequence = row["phase_sequence"]
        observed = row["observed_monotonic_ns"]
        if type(sequence) is not int or sequence != previous_sequence + 1:
            raise AgentRuntimeError("phase heartbeat sequence repeated or regressed")
        if type(observed) is not int or observed <= previous_monotonic:
            raise AgentRuntimeError("phase heartbeat monotonic time repeated or regressed")
        if (
            row["schema"] != HEARTBEAT_SCHEMA
            or type(row["run_id"]) is not str
            or not row["run_id"]
            or type(row["phase"]) is not str
            or not row["phase"]
            or type(row["reason"]) is not str
            or type(row["terminal"]) is not bool
            or type(row["expired"]) is not bool
            or row["age_ns"] != 0
            or row["expired"] is not False
            or row["default_action"] not in HEARTBEAT_DEFAULT_ACTIONS
        ):
            raise AgentRuntimeError("phase heartbeat value is invalid")
        expires_after = row["expires_after_ns"]
        expires_at = row["expires_monotonic_ns"]
        if row["terminal"]:
            if (
                expires_after is not None
                or expires_at is not None
                or row["default_action"] != "none"
            ):
                raise AgentRuntimeError("terminal phase heartbeat must not expire")
        elif (
            type(expires_after) is not int
            or expires_after <= 0
            or type(expires_at) is not int
            or expires_at != observed + expires_after
            or row["default_action"] == "none"
        ):
            raise AgentRuntimeError("live phase heartbeat expiry is invalid")
        previous_sequence = sequence
        previous_monotonic = observed
        normalized.append(dict(row))
    current = normalized[-1]
    now = time.monotonic_ns() if now_monotonic_ns is None else now_monotonic_ns
    if type(now) is not int or now < current["observed_monotonic_ns"]:
        raise AgentRuntimeError("phase heartbeat age clock regressed")
    current["age_ns"] = now - current["observed_monotonic_ns"]
    current["expired"] = bool(
        not current["terminal"]
        and now >= int(current["expires_monotonic_ns"])
    )
    if require_live and current["expired"]:
        raise AgentRuntimeError(
            "phase heartbeat expired; apply recorded default action "
            + current["default_action"]
        )
    return current


class PhaseHeartbeat:
    """Durably publish observable phases using only the monotonic clock."""

    def __init__(self, current_path: Path, history_path: Path, *, run_id: str) -> None:
        self.current_path = current_path
        self.history_path = history_path
        self.run_id = run_id
        self.sequence = 0
        self.last_monotonic_ns = -1
        self.terminal = False
        self.rows: list[dict[str, Any]] = []

    def publish(
        self,
        phase: str,
        *,
        expires_after_seconds: int = 5,
        default_action: str = "interrupt_and_fail_closed",
        reason: str = "",
        terminal: bool = False,
    ) -> dict[str, Any]:
        if self.terminal:
            raise AgentRuntimeError("phase heartbeat is already terminal")
        if not re.fullmatch(r"[a-z][a-z0-9_]*", phase):
            raise AgentRuntimeError("phase heartbeat name is invalid")
        observed = time.monotonic_ns()
        if observed <= self.last_monotonic_ns:
            observed = self.last_monotonic_ns + 1
        self.sequence += 1
        expires_after_ns = None if terminal else expires_after_seconds * 1_000_000_000
        row = {
            "schema": HEARTBEAT_SCHEMA,
            "run_id": self.run_id,
            "phase_sequence": self.sequence,
            "phase": phase,
            "reason": str(reason)[:256],
            "observed_monotonic_ns": observed,
            "age_ns": 0,
            "expires_after_ns": expires_after_ns,
            "expires_monotonic_ns": (
                None if terminal else observed + int(expires_after_ns)
            ),
            "expired": False,
            "default_action": "none" if terminal else default_action,
            "terminal": terminal,
        }
        validate_phase_heartbeat_rows(
            [*self.rows, row], now_monotonic_ns=observed
        )
        encoded = json.dumps(
            row, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ) + "\n"
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        with self.history_path.open("a", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        atomic_write(self.current_path, encoded)
        self.last_monotonic_ns = observed
        self.terminal = terminal
        self.rows.append(row)
        return row


def validate_slug(slug: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", slug):
        raise AgentRuntimeError(f"invalid slug: {slug}")


def validated_root(path: Path) -> Path:
    lexical = _lexical_absolute(path)
    if lexical.is_symlink():
        raise AgentRuntimeError(f"worktree must not be a symlink: {lexical}")
    root = lexical.resolve()
    if not root.is_dir():
        raise AgentRuntimeError(f"worktree is not a directory: {root}")
    return root


def state_directory(root: Path) -> Path:
    state = root / STATE_DIRECTORY
    if state.is_symlink():
        raise AgentRuntimeError(f"state directory must not be a symlink: {state}")
    created = not state.exists()
    state.mkdir(mode=0o700, parents=False, exist_ok=True)
    if state.resolve() != root / STATE_DIRECTORY:
        raise AgentRuntimeError(f"state directory escaped worktree: {state}")
    metadata = state.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or (hasattr(os, "getuid") and metadata.st_uid != os.getuid())
        or stat.S_IMODE(metadata.st_mode) & 0o022
    ):
        raise AgentRuntimeError(f"state directory owner or mode is unsafe: {state}")
    if created:
        parent_descriptor = os.open(root, os.O_RDONLY)
        try:
            os.fsync(parent_descriptor)
        finally:
            os.close(parent_descriptor)
    return state


def _lexical_absolute(path: Path, *, base: Path | None = None) -> Path:
    expanded = path.expanduser()
    if not expanded.is_absolute():
        expanded = (base or Path.cwd()) / expanded
    return Path(os.path.abspath(expanded))


def _parent_chain(path: Path) -> list[Path]:
    chain: list[Path] = []
    current = path
    while True:
        chain.append(current)
        if current.parent == current:
            break
        current = current.parent
    return list(reversed(chain))


def _directory_identity(path: Path) -> tuple[int, int, int, int]:
    metadata = path.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise AgentRuntimeError(f"control parent is not a real directory: {path}")
    return (
        metadata.st_dev,
        metadata.st_ino,
        getattr(metadata, "st_uid", -1),
        stat.S_IMODE(metadata.st_mode),
    )


def safe_control_read(
    path: Path,
    *,
    allowed_parent: Path,
    expected_sha256: str | None,
    local_static_copy: bool,
) -> tuple[bytes, str, Path]:
    """Read one direct-child control through a bound, no-follow parent dirfd."""
    candidate = _lexical_absolute(path)
    parent = _lexical_absolute(allowed_parent).resolve()
    try:
        candidate_parent = candidate.parent.resolve(strict=True)
    except OSError as error:
        raise AgentRuntimeError("control parent cannot be resolved") from error
    if candidate_parent != parent or candidate.name in {"", ".", ".."}:
        raise AgentRuntimeError(
            f"control must be a direct child of {parent}: {candidate}"
        )
    candidate = parent / candidate.name
    if expected_sha256 is not None and _SHA256_RE.fullmatch(expected_sha256) is None:
        raise AgentRuntimeError("control SHA-256 binding is invalid")
    chain = _parent_chain(parent)
    before_parents = [(item, _directory_identity(item)) for item in chain]
    parent_descriptor = -1
    descriptor = -1
    try:
        parent_metadata = parent.lstat()
        if (
            hasattr(os, "getuid")
            and parent_metadata.st_uid != os.getuid()
        ) or stat.S_IMODE(parent_metadata.st_mode) & 0o022:
            raise AgentRuntimeError("control parent owner or mode is unsafe")
        parent_descriptor = os.open(
            parent,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        opened_parent = os.fstat(parent_descriptor)
        if (opened_parent.st_dev, opened_parent.st_ino) != (
            parent_metadata.st_dev,
            parent_metadata.st_ino,
        ):
            raise AgentRuntimeError("control parent changed before open")
        metadata = os.stat(
            candidate.name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
            raise AgentRuntimeError("control is not a regular file")
        if metadata.st_nlink != 1:
            raise AgentRuntimeError("control hardlink count must be one")
        if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
            raise AgentRuntimeError("control owner does not match the runtime user")
        mode = stat.S_IMODE(metadata.st_mode)
        if local_static_copy:
            if mode != 0o400:
                raise AgentRuntimeError("worktree-local control mode must be 0400")
        elif mode & 0o022:
            raise AgentRuntimeError("external control must not be group/other writable")
        if metadata.st_size <= 0 or metadata.st_size > _MAX_CONTROL_BYTES:
            raise AgentRuntimeError("control size is empty or exceeds the safety bound")
        descriptor = os.open(
            candidate.name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_descriptor,
        )
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino)
        ):
            raise AgentRuntimeError("control inode changed before open")
        payload = bytearray()
        remaining = opened.st_size
        while remaining:
            block = os.read(descriptor, min(1024 * 1024, remaining))
            if not block:
                raise AgentRuntimeError("control became short while reading")
            payload.extend(block)
            remaining -= len(block)
        closed = os.fstat(descriptor)
        if (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
            opened.st_mtime_ns,
            opened.st_ctime_ns,
        ) != (
            closed.st_dev,
            closed.st_ino,
            closed.st_size,
            closed.st_mtime_ns,
            closed.st_ctime_ns,
        ):
            raise AgentRuntimeError("control changed while it was read")
        final_parent = os.fstat(parent_descriptor)
        if (final_parent.st_dev, final_parent.st_ino) != (
            opened_parent.st_dev,
            opened_parent.st_ino,
        ):
            raise AgentRuntimeError("control parent changed while it was read")
    except OSError as error:
        raise AgentRuntimeError(
            f"control cannot be read safely: {type(error).__name__}"
        ) from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if parent_descriptor >= 0:
            os.close(parent_descriptor)
    after_parents = [(item, _directory_identity(item)) for item in chain]
    if before_parents != after_parents:
        raise AgentRuntimeError("control parent chain changed while it was read")
    digest = hashlib.sha256(payload).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise AgentRuntimeError("control SHA-256 binding mismatch")
    return bytes(payload), digest, candidate


def install_static_control(
    state: Path,
    target_name: str,
    payload: bytes,
    *,
    source: Path,
) -> Path:
    """Materialize a 0400 control copy without consuming an existing one."""
    target = state / target_name
    if source == target:
        return target
    if os.path.lexists(target):
        existing, _digest, _path = safe_control_read(
            target,
            allowed_parent=state,
            expected_sha256=hashlib.sha256(payload).hexdigest(),
            local_static_copy=True,
        )
        if existing != payload:
            raise AgentRuntimeError("existing static control has different bytes")
        return target
    descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=state)
    installed = False
    try:
        os.fchmod(descriptor, 0o400)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        # Hard-link publication is the portable no-clobber primitive here.
        # A concurrent local brief must be validated, never overwritten.
        try:
            os.link(temporary, target, follow_symlinks=False)
            installed = True
        except FileExistsError:
            existing, _digest, _path = safe_control_read(
                target,
                allowed_parent=state,
                expected_sha256=hashlib.sha256(payload).hexdigest(),
                local_static_copy=True,
            )
            if existing != payload:
                raise AgentRuntimeError("concurrent static control has different bytes")
            return target
        finally:
            os.unlink(temporary)
        directory_descriptor = os.open(state, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        if installed:
            try:
                os.unlink(target)
            except OSError:
                pass
        raise
    return target


def install_static_brief(
    state: Path,
    slug: str,
    payload: bytes,
    *,
    source: Path,
) -> Path:
    return install_static_control(
        state,
        f"{slug}.brief.md",
        payload,
        source=source,
    )


def read_brief_authority(
    root: Path,
    source: Path,
    *,
    expected_sha256: str | None,
    control_root: Path,
    test_mode: bool = False,
) -> tuple[bytes, str, str, Path]:
    """Authenticate a brief without creating or replacing worktree state."""
    state = root / STATE_DIRECTORY
    candidate = _lexical_absolute(source)
    external_parent = control_root / "briefs"
    try:
        source_parent = candidate.parent.resolve(strict=True)
    except OSError as error:
        raise AgentRuntimeError("brief parent is unavailable") from error
    if source_parent == external_parent.resolve():
        if expected_sha256 is None:
            raise AgentRuntimeError("external brief requires --brief-sha256")
        payload, digest, opened = safe_control_read(
            candidate,
            allowed_parent=external_parent,
            expected_sha256=expected_sha256,
            local_static_copy=False,
        )
        origin = "external_import"
    elif state.is_dir() and source_parent == state.resolve():
        if expected_sha256 is None and not test_mode:
            raise AgentRuntimeError("worktree-local brief requires --brief-sha256")
        if not state.is_dir() or state.is_symlink():
            raise AgentRuntimeError("worktree-local state directory is unavailable")
        payload, digest, opened = safe_control_read(
            candidate,
            allowed_parent=state,
            expected_sha256=expected_sha256,
            local_static_copy=True,
        )
        origin = "local_reuse"
    else:
        raise AgentRuntimeError(
            "brief must be a direct child of the control-root briefs/ or .codex-agent"
        )
    try:
        text = payload.decode("utf-8")
    except UnicodeError as error:
        raise AgentRuntimeError("brief is not valid UTF-8") from error
    return payload, text, origin, opened


def acquire_brief(
    root: Path,
    slug: str,
    source: Path,
    *,
    expected_sha256: str | None,
    control_root: Path,
    test_mode: bool = False,
) -> tuple[Path, str, str]:
    """Authenticate then materialize a 0400 brief control."""
    payload, text, origin, opened = read_brief_authority(
        root,
        source,
        expected_sha256=expected_sha256,
        control_root=control_root,
        test_mode=test_mode,
    )
    state = state_directory(root)
    brief = install_static_brief(state, slug, payload, source=opened)
    installed, _installed_digest, _ = safe_control_read(
        brief,
        allowed_parent=state,
        expected_sha256=hashlib.sha256(payload).hexdigest(),
        local_static_copy=True,
    )
    if installed != payload:
        raise AgentRuntimeError("installed brief bytes changed")
    return brief, text, origin


def report_contract_for_brief(brief: str) -> dict[str, Any]:
    headings = list(REPORT_CONTRACT["headings"])
    if "沉淀候选" in brief:
        headings.append(str(REPORT_CONTRACT["conditional_heading"]))
    return {
        "schema": REPORT_CONTRACT_VERSION,
        "headings": headings,
        "evidence_schema": REPORT_CONTRACT["evidence_schema"],
        "coordinator_evidence_fields": list(
            REPORT_CONTRACT["coordinator_evidence_fields"]
        ),
        "diagnostic_schema": REPORT_DIAGNOSTIC_SCHEMA,
        "diagnostic_supersession_schema": REPORT_SUPERSESSION_SCHEMA,
    }


def report_template(contract: dict[str, Any]) -> str:
    sections = []
    for heading in contract["headings"]:
        body = (
            str(contract["evidence_schema"])
            if heading == "结果"
            else "<内容>"
        )
        sections.append(f"## {heading}\n{body}")
    return "\n".join(sections)



def _report_record_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _report_diagnostic_projection(
    lines: list[str],
    bound_claims: list[dict[str, Any]],
) -> dict[str, Any]:
    """Project explicitly superseded diagnostics without rewriting report bytes."""
    record_pattern = re.compile(
        r"^\s*(?:[-*]\s*)?"
        r"(historical_diagnostic|diagnostic_supersession)\s*=\s*(\{.*\})\s*$"
    )
    diagnostic_rows: dict[str, tuple[int, dict[str, Any], datetime]] = {}
    supersession_rows: list[tuple[int, dict[str, Any], datetime]] = []
    invalid_count = 0

    for index, line in enumerate(lines):
        match = record_pattern.fullmatch(line)
        if match is None:
            continue
        label, encoded = match.groups()
        try:
            row = json.loads(encoded)
        except json.JSONDecodeError:
            invalid_count += 1
            continue
        if not isinstance(row, dict):
            invalid_count += 1
            continue

        observed_at = _report_record_time(row.get("observed_at"))
        record_id = row.get("diagnostic_id")
        scope_sha256 = row.get("scope_sha256")
        source = row.get("source")
        valid_common = bool(
            isinstance(record_id, str)
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", record_id)
            and isinstance(scope_sha256, str)
            and re.fullmatch(r"[0-9a-f]{64}", scope_sha256)
            and source in REPORT_EVIDENCE_SOURCE_STRENGTH
            and observed_at is not None
        )
        if label == "historical_diagnostic":
            valid = bool(
                valid_common
                and row.get("schema") == REPORT_DIAGNOSTIC_SCHEMA
                and row.get("outcome")
                in {"failed", "error", "blocked", "inconclusive"}
                and isinstance(row.get("summary"), str)
                and 0 < len(row["summary"]) <= 500
            )
            if not valid or record_id in diagnostic_rows:
                invalid_count += 1
                continue
            diagnostic_rows[record_id] = (index, row, observed_at)
            continue

        success = row.get("success")
        valid_success = bool(
            isinstance(success, dict)
            and set(success)
            == {
                "candidate_sha256",
                "execution_binding_sha256",
                "environment_sha256",
                "command_sha256",
                "count",
            }
            and all(
                isinstance(success.get(field), str)
                and re.fullmatch(r"[0-9a-f]{64}", success[field])
                for field in (
                    "candidate_sha256",
                    "execution_binding_sha256",
                    "environment_sha256",
                    "command_sha256",
                )
            )
            and isinstance(success.get("count"), int)
            and not isinstance(success.get("count"), bool)
            and success["count"] >= 0
        )
        valid = bool(
            valid_common
            and row.get("schema") == REPORT_SUPERSESSION_SCHEMA
            and valid_success
        )
        if not valid:
            invalid_count += 1
            continue
        supersession_rows.append((index, row, observed_at))

    superseded_indexes: set[int] = set()
    superseded: list[dict[str, Any]] = []
    used_diagnostics: set[str] = set()
    for _index, row, superseding_at in supersession_rows:
        diagnostic_id = str(row["diagnostic_id"])
        diagnostic = diagnostic_rows.get(diagnostic_id)
        if diagnostic is None or diagnostic_id in used_diagnostics:
            invalid_count += 1
            continue
        diagnostic_index, diagnostic_row, diagnostic_at = diagnostic
        same_scope = row["scope_sha256"] == diagnostic_row["scope_sha256"]
        newer = superseding_at > diagnostic_at
        stronger = (
            REPORT_EVIDENCE_SOURCE_STRENGTH[str(row["source"])]
            > REPORT_EVIDENCE_SOURCE_STRENGTH[str(diagnostic_row["source"])]
        )
        success = row["success"]
        matching_claims = [
            claim
            for claim in bound_claims
            if all(claim.get(field) == success[field] for field in success)
        ]
        if not (same_scope and newer and stronger and len(matching_claims) == 1):
            invalid_count += 1
            continue
        used_diagnostics.add(diagnostic_id)
        superseded_indexes.add(diagnostic_index)
        superseded.append(
            {
                "diagnostic_id_sha256": hashlib.sha256(
                    diagnostic_id.encode("utf-8", "strict")
                ).hexdigest(),
                "scope_sha256": row["scope_sha256"],
                "diagnostic_at": diagnostic_at.isoformat(),
                "superseding_at": superseding_at.isoformat(),
                "superseding_source": row["source"],
                "success_command_sha256": success["command_sha256"],
            }
        )

    active_lines = [
        (
            f"superseded_diagnostic_sha256="
            f"{hashlib.sha256(lines[index].encode('utf-8', 'strict')).hexdigest()}"
            if index in superseded_indexes
            else line
        )
        for index, line in enumerate(lines)
    ]
    active_diagnostic_count = len(diagnostic_rows) - len(superseded_indexes)
    return {
        "active_report": "\n".join(active_lines),
        "active_diagnostic_count": active_diagnostic_count,
        "invalid_record_count": invalid_count,
        "superseded": sorted(
            superseded,
            key=lambda row: (
                str(row["superseding_at"]),
                str(row["diagnostic_id_sha256"]),
            ),
        ),
    }


def task_report_verdict(report: str, contract: dict[str, Any]) -> dict[str, Any]:
    """Return the deterministic task-level verdict for provider report bytes."""
    failures: list[str] = []
    headings = [str(heading) for heading in contract.get("headings", [])]
    for heading in headings:
        count = len(
            re.findall(
                rf"^##\s+{re.escape(heading)}\s*$",
                report,
                re.MULTILINE,
            )
        )
        if count != 1:
            failures.append(f"report heading {heading!r} count={count}, expected=1")

    lines = report.splitlines()
    checks = [line for line in lines if line.lstrip().startswith("✅")]
    if not checks:
        failures.append("report has no evidenced ✅ completion check")
    explicit_failures = [
        line for line in lines if re.match(r"^\s*(?:[-*]\s*)?❌", line)
    ]
    if explicit_failures:
        failures.append(
            f"report contains {len(explicit_failures)} explicit failure check(s)"
        )
    missing_evidence = [line for line in checks if not has_check_evidence(line)]
    if missing_evidence:
        failures.append(f"{len(missing_evidence)} ✅ check(s) lack command/exit evidence")

    bound_claims: list[dict[str, Any]] = []
    unbound_claim_count = 0
    field_patterns = {
        "candidate_sha256": r"[0-9a-f]{64}",
        "execution_binding_sha256": r"[0-9a-f]{64}",
        "environment_sha256": r"[0-9a-f]{64}",
        "command_sha256": r"[0-9a-f]{64}",
        "count": r"(?:0|[1-9][0-9]*)",
    }
    for line in checks:
        command_matches = re.findall(r"`([^`\r\n]+)`", line)
        values: dict[str, str] = {}
        valid = len(command_matches) == 1
        for field, pattern in field_patterns.items():
            matches = re.findall(
                rf"(?:^|[；;\s]){field}=({pattern})(?=$|[；;\s])",
                line,
            )
            if len(matches) != 1:
                valid = False
            else:
                values[field] = matches[0]
        if valid:
            command = command_matches[0]
            if values["command_sha256"] != hashlib.sha256(
                command.encode("utf-8", "strict")
            ).hexdigest():
                valid = False
        if not valid:
            unbound_claim_count += 1
            continue
        values["command"] = command_matches[0]
        values["count"] = int(values["count"])
        bound_claims.append(values)
    if unbound_claim_count:
        failures.append(
            f"{unbound_claim_count} ✅ current-success check(s) lack "
            "candidate/execution/environment/command/count binding"
        )
    commands: dict[str, list[int]] = {}
    for claim in bound_claims:
        commands.setdefault(str(claim["command"]), []).append(int(claim["count"]))
    conflicting = sorted(
        command for command, counts in commands.items()
        if len(counts) > 1 and len(set(counts)) > 1
    )
    repeated = sorted(
        command for command, counts in commands.items()
        if len(counts) > 1 and len(set(counts)) == 1
    )
    if conflicting:
        failures.append("report records conflicting counts for repeated command(s)")
    if repeated:
        failures.append("report repeats current-success command(s)")
    candidate_values = {claim["candidate_sha256"] for claim in bound_claims}
    if len(candidate_values) > 1:
        failures.append("report current-success candidate binding is inconsistent")
    expected_binding = contract.get("execution_binding_sha256")
    if contract.get("enforce_current_execution_binding") is True and any(
        claim["execution_binding_sha256"] != expected_binding
        for claim in bound_claims
    ):
        failures.append(
            "report current-success execution binding does not match the run"
        )

    diagnostic_projection = _report_diagnostic_projection(lines, bound_claims)
    active_report = str(diagnostic_projection["active_report"])
    if diagnostic_projection["invalid_record_count"]:
        failures.append(
            "report contains "
            f"{diagnostic_projection['invalid_record_count']} invalid diagnostic "
            "supersession record(s)"
        )
    if diagnostic_projection["active_diagnostic_count"]:
        failures.append(
            "report contains "
            f"{diagnostic_projection['active_diagnostic_count']} current diagnostic "
            "failure record(s)"
        )

    nonzero_exits = sorted(
        {
            int(match.group(1))
            for match in re.finditer(
                r"\bexit\s+([+-]?\d+)\b",
                active_report,
                re.IGNORECASE,
            )
            if int(match.group(1)) != 0
        }
    )
    if nonzero_exits:
        failures.append(
            "report records non-zero exit code(s): "
            + ", ".join(str(code) for code in nonzero_exits)
        )

    incomplete_states = sorted(
        {
            match.group(0).lower()
            for match in re.finditer(
                r"\b(?:partial|blocked)\b", active_report, re.IGNORECASE
            )
        }
    )
    if incomplete_states:
        failures.append(
            "report declares incomplete state(s): " + ", ".join(incomplete_states)
        )

    success_summary = bool(
        re.search(
            r"(?im)^\s*(?:[-*]\s*)?(?:summary|result|outcome|status|结论|总结)"
            r"\s*[:：=]\s*(?:success|succeeded|passed|成功|完成)\s*[。.!]?$",
            active_report,
        )
        or re.search(r"任务(?:已)?完成", active_report)
    )
    failure_summary = bool(
        re.search(
            r"(?im)^\s*(?:[-*]\s*)?(?:summary|result|outcome|status|结论|总结)"
            r"\s*[:：=]\s*(?:fail(?:ed|ure)?|unsuccessful|失败|未完成|未通过)\s*[。.!]?$",
            active_report,
        )
        or re.search(r"任务(?:尚|仍)?未完成|任务失败", active_report)
    )
    failed_required_check = bool(
        re.search(
            r"(?i)\b(?:required|mandatory)?\s*(?:test|check)s?\b[^\r\n]{0,80}"
            r"\b(?:failed|failure)\b",
            active_report,
        )
        or re.search(
            r"(?:必需|必要|必须)?(?:测试|检查)[^\r\n]{0,40}(?:失败|未通过)",
            active_report,
        )
    )
    if success_summary and failure_summary:
        failures.append("report contains contradictory success and failure summaries")
    elif failure_summary:
        failures.append("report summary declares failure")
    if failed_required_check:
        failures.append("report states that a required check failed")

    return {
        "schema": REPORT_CONTRACT_VERSION,
        "passed": not failures,
        "check_count": len(checks),
        "failures": failures,
        "diagnostic_projection": {
            "schema": "sulde-worker-diagnostic-projection-v1",
            "active_count": diagnostic_projection["active_diagnostic_count"],
            "invalid_count": diagnostic_projection["invalid_record_count"],
            "superseded_count": len(diagnostic_projection["superseded"]),
            "superseded": diagnostic_projection["superseded"],
            "report_sha256": hashlib.sha256(
                report.encode("utf-8", "strict")
            ).hexdigest(),
        },
    }


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        mode = path.stat().st_mode & 0o7777
    except (OSError, PermissionError) as error:
        return f"!unreadable:{type(error).__name__}"
    return f"{mode:o}:{digest.hexdigest()}"


def snapshot(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for current, directories, files in os.walk(root):
        directories[:] = sorted(
            name for name in directories if name not in SKIP_DIRECTORIES
        )
        for name in sorted(files):
            path = Path(current, name)
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                try:
                    result[relative] = "@" + os.readlink(path)
                except OSError as error:
                    result[relative] = f"!unreadable:{type(error).__name__}"
            elif path.is_file():
                result[relative] = file_digest(path)
    git_path = root / ".git"
    if git_path.is_file():
        result[".git"] = file_digest(git_path)
    return result


def observable_worktree_snapshot(root: Path) -> dict[str, str]:
    """Hash only git-visible changed files; fall back for synthetic fixtures."""
    # A synthetic fixture can live below a real checkout while deliberately
    # having no Git identity of its own.  Letting ``git status`` walk upward in
    # that case changes the path namespace from fixture-relative to the outer
    # checkout and can make terminal writes disappear from the managed critic
    # batch.  This must match the fixture boundary used by
    # ``_expected_base_commit`` and ``_git_common_directory``.
    if not os.path.lexists(root / ".git"):
        return snapshot(root)
    try:
        completed = subprocess.run(
            ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        completed = None
    if completed is None or completed.returncode != 0:
        return snapshot(root)
    records = completed.stdout.split("\0")
    paths: list[str] = []
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        status = record[:2]
        path = record[3:] if len(record) > 3 else ""
        if path:
            paths.append(path)
        if ("R" in status or "C" in status) and index < len(records):
            original = records[index]
            index += 1
            if "R" in status and original:
                paths.append(original)
    result: dict[str, str] = {}
    for relative in sorted(set(paths)):
        if set(Path(relative).parts) & SKIP_DIRECTORIES:
            continue
        path = root / relative
        if path.is_symlink():
            try:
                result[relative] = "@" + os.readlink(path)
            except OSError:
                result[relative] = "!unreadable:symlink"
        else:
            result[relative] = file_digest(path) if path.is_file() else "!missing"
    return result


def static_control_snapshot(paths: list[Path]) -> dict[str, str]:
    return {str(path): file_digest(path) for path in paths if path.is_file()}


def static_controls_unchanged(paths: list[Path], expected: dict[str, str]) -> bool:
    current = static_control_snapshot(paths)
    return current == expected


def changed_paths(before: dict[str, str], after: dict[str, str]) -> list[str]:
    changes: list[str] = []
    for path in sorted(set(before) | set(after)):
        if path not in before:
            changes.append(f"A {path}")
        elif path not in after:
            changes.append(f"D {path}")
        elif before[path] != after[path]:
            changes.append(f"M {path}")
    return changes


def _owned_path_contains(owned: str, target: str) -> bool:
    if owned.endswith("/**"):
        prefix = owned[:-3].rstrip("/")
        return target == prefix or target.startswith(prefix + "/")
    return target == owned


def _critic_baseline_snapshot(
    root: Path,
    *,
    base_commit: str,
    owned_paths: list[str],
    frozen_snapshot: dict[str, str],
    test_mode: bool,
) -> dict[str, str]:
    """Build the exact base fingerprints a task-scoped critic may read."""
    selected = {
        path: digest
        for path, digest in frozen_snapshot.items()
        if any(_owned_path_contains(owned, path) for owned in owned_paths)
    }
    literal_paths = [owned for owned in owned_paths if not owned.endswith("/**")]
    if test_mode and base_commit == "fixture":
        for path in literal_paths:
            selected.setdefault(path, "!missing")
        return dict(sorted(selected.items()))

    try:
        tree = subprocess.run(
            ["git", "ls-tree", "-r", "-z", base_commit],
            cwd=root,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise AgentRuntimeError("critic task baseline tree is unavailable") from error
    if tree.returncode != 0:
        raise AgentRuntimeError("critic task baseline tree lookup failed")
    selected = {}
    for raw in tree.stdout.split(b"\0"):
        if not raw:
            continue
        metadata, separator, encoded_path = raw.partition(b"\t")
        fields = metadata.split()
        try:
            relative = os.fsdecode(encoded_path)
        except UnicodeError as error:
            raise AgentRuntimeError("critic task baseline path is not decodable") from error
        if (
            not separator
            or len(fields) != 3
            or fields[1] != b"blob"
            or fields[0] not in {b"100644", b"100755"}
            or not any(_owned_path_contains(owned, relative) for owned in owned_paths)
        ):
            continue
        try:
            blob = subprocess.run(
                ["git", "cat-file", "blob", fields[2].decode("ascii")],
                cwd=root,
                capture_output=True,
                timeout=30,
                check=False,
            )
        except (OSError, UnicodeError, subprocess.SubprocessError) as error:
            raise AgentRuntimeError("critic task baseline blob is unavailable") from error
        if blob.returncode != 0:
            raise AgentRuntimeError("critic task baseline blob lookup failed")
        permissions = int(fields[0], 8) & 0o7777
        selected[relative] = (
            f"{permissions:o}:{hashlib.sha256(blob.stdout).hexdigest()}"
        )
    for path in literal_paths:
        selected.setdefault(path, "!missing")
    for path in frozen_snapshot:
        if any(_owned_path_contains(owned, path) for owned in owned_paths):
            selected.setdefault(path, "!missing")
    return dict(sorted(selected.items()))


def _managed_critic_scope(
    *,
    task: dict[str, Any],
    owned_paths: list[str],
    baseline_snapshot: dict[str, str],
    execution_binding_sha256: str,
) -> TaskCriticScope:
    return TaskCriticScope(
        task_id=str(task["task_id"]),
        baseline=str(task["base_commit"]),
        run_id=execution_binding_sha256,
        owned_paths=tuple(owned_paths),
        baseline_snapshot=dict(baseline_snapshot),
        evidence_floor_sequence=0,
        registered_evidence=(),
    )


def _fixture_critic_result(
    contract: dict[str, Any],
    event: dict[str, Any],
    *,
    provider: str,
) -> dict[str, Any]:
    """Exercise the real critic command in a synthetic non-git test fixture."""
    scope = contract.get("critic", {}).get("task_scope", {})
    targets = event.get("write_targets")
    if not isinstance(scope, dict) or not isinstance(targets, list) or not targets:
        raise IntentGuardianError("fixture critic scope or terminal batch is invalid")
    root = Path(str(contract["workspace_root"])).resolve(strict=True)
    evidence: list[str] = []
    for target in targets:
        if not isinstance(target, str) or not any(
            _owned_path_contains(str(owned), target)
            for owned in scope.get("owned_paths", [])
        ):
            raise IntentGuardianError("fixture critic target is outside task authority")
        candidate = root / target
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(root)
            metadata = resolved.lstat()
            if resolved.is_symlink() or not stat.S_ISREG(metadata.st_mode):
                raise IntentGuardianError("fixture critic target is not a regular file")
            payload = resolved.read_bytes()
        except (OSError, ValueError) as error:
            raise IntentGuardianError("fixture critic target cannot be read safely") from error
        if len(payload) > 1_000_000 or b"\0" in payload:
            raise IntentGuardianError("fixture critic target exceeds the text evidence bound")
        try:
            rendered = payload.decode("utf-8")
        except UnicodeDecodeError as error:
            raise IntentGuardianError("fixture critic target is not UTF-8") from error
        evidence.append(f"TARGET: {target}\n\nINCREMENT:\n{rendered}")
    evidence_text = "\n\n--- TASK-OWNED INCREMENT ---\n\n".join(evidence)
    matches = critic_secret_matches(evidence_text)
    if matches:
        raise IntentGuardianError("fixture critic evidence contains a secret pattern")
    prompt = build_critic_prompt(contract, event, evidence_text, [])
    override = os.environ.get("SULDE_GUARDIAN_CRITIC_CMD", "").strip()
    if not override:
        raise IntentGuardianError("fixture critic command is unavailable")
    command = split_command_template(override)
    if not command or not all(type(item) is str and item for item in command):
        raise IntentGuardianError("fixture critic command is invalid")
    try:
        completed = subprocess.run(
            command,
            input=prompt,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=float(contract["critic"]["timeout_seconds"]),
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise IntentGuardianError("fixture critic command failed to start") from error
    if completed.returncode != 0:
        raise IntentGuardianError(
            f"fixture critic failed exit={completed.returncode}: {completed.stderr[-500:]}"
        )
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise IntentGuardianError("fixture critic returned invalid JSON") from error
    if not isinstance(value, dict):
        raise IntentGuardianError("fixture critic JSON root must be an object")
    return value


def _managed_critic_runner(
    scope: TaskCriticScope,
    *,
    test_mode: bool,
) -> Any:
    def evaluate(
        contract: dict[str, Any],
        event: dict[str, Any],
        *,
        provider: str,
    ) -> dict[str, Any]:
        bound = bind_task_critic_checkpoint_event(event, scope)
        if test_mode and scope.baseline == "fixture":
            return _fixture_critic_result(contract, bound, provider=provider)
        return run_critic(contract, bound, provider=provider)

    return evaluate


def archive_previous(state: Path, slug: str) -> None:
    if not any((state / f"{slug}.{suffix}").exists() for suffix in ARTIFACT_SUFFIXES):
        return
    round_number = 1
    while any(
        (state / f"{slug}.round{round_number}.{suffix}").exists()
        for suffix in ARTIFACT_SUFFIXES
    ):
        round_number += 1
    for suffix in ARTIFACT_SUFFIXES:
        source = state / f"{slug}.{suffix}"
        if source.exists():
            source.replace(state / f"{slug}.round{round_number}.{suffix}")


def terminate_process(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            process.terminate()
        else:
            os.killpg(process.pid, signal.SIGTERM)
    except OSError:
        pass
    try:
        process.wait(timeout=5)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        if os.name == "nt":
            process.kill()
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except OSError:
        pass
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass


def _bounded_diagnostic_stream_event(event: dict[str, Any]) -> dict[str, Any]:
    """Downgrade only exact stdout/stderr device writes to diagnostics.

    The command parser remains conservative.  A compound command that also
    names any ordinary file keeps its local-write/unknown classification, so a
    diagnostic alias cannot carry an artifact or broaden owned-path authority.
    """
    targets = event.get("write_targets")
    if (
        event.get("effect") != "local_write"
        or not isinstance(targets, list)
        or not targets
        or len(targets) > len(DIAGNOSTIC_STREAM_TARGETS)
        or any(type(target) is not str for target in targets)
        or not all(
            native_agent_broker.is_bounded_diagnostic_stream_target(target)
            for target in targets
        )
    ):
        return event
    normalized = dict(event)
    normalized["effect"] = "read"
    normalized["target"] = "[bounded-diagnostic-stream]"
    normalized["diagnostic_streams"] = sorted(set(targets))
    normalized.pop("write_targets", None)
    return normalized


def _managed_effect_store_path(contract_path: Path) -> Path:
    if contract_path.suffix != ".json":
        raise AgentRuntimeError("intent contract path cannot identify its effect store")
    return contract_path.with_name(
        contract_path.name[:-5] + ".interventions.jsonl"
    )


def _record_managed_integrity_breach(
    guardian: GuardianSession,
    reason: str,
) -> None:
    """Isolate provider bytes, restore the trusted prefix, then pause durably."""
    store = _managed_effect_store_path(guardian.path)
    expected = guardian._expected_effect_store
    current = store.read_bytes() if store.is_file() else b""
    if current != expected:
        untrusted = current[len(expected):] if current.startswith(expected) else current
        digest = hashlib.sha256(untrusted).hexdigest()
        quarantine = store.with_name(
            store.name + f".integrity-breach-{digest[:24]}.bin"
        )
        if quarantine.is_file():
            if quarantine.read_bytes() != untrusted:
                raise AgentRuntimeError("effect-store quarantine digest collision")
        else:
            atomic_write_bytes(quarantine, untrusted)
            if quarantine.read_bytes() != untrusted:
                raise AgentRuntimeError("effect-store quarantine readback drifted")
        atomic_write_bytes(store, expected)
        if store.read_bytes() != expected:
            raise AgentRuntimeError("trusted effect-store prefix was not restored")
    guardian.record_integrity_breach(reason)


def observe_managed_provider_line(
    guardian: GuardianSession,
    line: str,
) -> Any:
    """Observe one provider line with the managed runtime's device boundary."""
    if guardian.provider != "codex":
        return guardian.observe_provider_line(line)
    if guardian.authoritative_memory and not guardian.integrity_ok():
        _record_managed_integrity_breach(
            guardian,
            "provider modified authoritative intent, audit, approval, or external-effect truth",
        )
        guardian.last_observed_events = []
        return SimpleNamespace(action="deny", awaiting_human=False)
    try:
        record = json.loads(line)
    except (json.JSONDecodeError, TypeError):
        guardian.last_observed_events = []
        return None
    if not isinstance(record, dict):
        guardian.last_observed_events = []
        return None
    events = [
        _bounded_diagnostic_stream_event(event)
        for event in normalize_provider_events(record, provider=guardian.provider)
    ]
    filtered: list[dict[str, Any]] = []
    for event in events:
        if guardian.session_id and not event.get("session_id"):
            event["session_id"] = guardian.session_id
        call_id = str(event.get("call_id") or "")
        if (
            event.get("observation_source")
            == "explicit_skill_registration_stream"
            and event.get("registration_command") == "skill-start"
        ):
            marker = call_id or str(event.get("event_id") or "")
            if marker in guardian._seen_explicit_skill_starts:
                continue
            guardian._seen_explicit_skill_starts.add(marker)
        if call_id and event.get("phase") == "started":
            guardian._provider_inflight[call_id] = dict(event)
        filtered.append(event)
    guardian.last_observed_events = filtered
    decisions = [guardian.observe(event) for event in filtered]
    return next(
        (decision for decision in decisions if decision.action == "deny"),
        decisions[-1] if decisions else None,
    )


def _uncertain_external_completion(event: dict[str, Any]) -> bool:
    return bool(
        event.get("phase") == "completed"
        and event.get("success") is False
        and (
            event.get("effect") == "external_write"
            or (event.get("kind") == "mcp" and event.get("effect") != "read")
        )
    )


def _persist_unmatched_external_completion(
    guardian: GuardianSession,
    event: dict[str, Any],
) -> dict[str, Any]:
    """Repair only the managed completion-gap path with a typed identity."""
    if not _uncertain_external_completion(event):
        raise IntentGuardianError("event is not an uncertain external completion")
    target = str(event.get("target") or event.get("result_target") or "")
    if not target:
        raise IntentGuardianError("unmatched external completion has no resource target")
    resource_context: dict[str, str] | None = None
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target):
        resource_key = canonical_resource_key(target, kind="uri")
    elif event.get("kind") == "mcp" and str(event.get("server") or ""):
        resource_context = {
            "server": str(event["server"]),
            "resource_kind": str(event.get("resource_kind") or "opaque"),
            "identifier": target,
        }
        resource_key = canonical_resource_key(
            (
                resource_context["server"],
                resource_context["resource_kind"],
                resource_context["identifier"],
            ),
            kind="mcp",
        )
    else:
        resource_context = {"schema": "exact", "value": target}
        resource_key = canonical_resource_key(target, kind="opaque")
    fingerprint = event_fingerprint(event)
    call_identity = str(event.get("call_id") or f"event:{event.get('event_id')}")
    try:
        attempt = begin_attempt(
            guardian.path,
            intent_id=guardian.contract["intent_id"],
            intent_revision=guardian.contract["revision"],
            fingerprint=fingerprint,
            operation_arguments_digest=str(event.get("arguments_digest") or fingerprint),
            source_event_id=str(event.get("event_id") or ""),
            capability=str(event.get("capability") or "unknown"),
            target=target,
            resource_key=resource_key,
            resource_base=None,
            resource_context=resource_context,
            effect=str(event.get("effect") or "unknown"),
            provider=str(event.get("provider") or guardian.provider),
            session_id=str(event.get("session_id") or guardian.session_id),
            task_id=(
                guardian.contract["intent_id"]
                if str(guardian.contract["intent_id"]).startswith("l3:")
                else ""
            ),
            idempotency_key=(
                f"completion-gap:{event.get('provider') or guardian.provider}:"
                f"{event.get('session_id') or guardian.session_id}:"
                f"{call_identity}:{fingerprint}"
            ),
            observation_gap=True,
            verification_kind=str(event.get("verification_kind") or "unsupported"),
            verification_sha256=str(event.get("verification_sha256") or ""),
        )
        mark_attempt_result(
            guardian.path,
            str(attempt["attempt_id"]),
            success=False,
            reason="observable completion callback reported failure",
        )
        guardian._expected_effect_store = (
            _managed_effect_store_path(guardian.path).read_bytes()
        )
        summary = guardian.summary()
    except (InterventionError, IntentGuardianError, OSError, UnicodeError) as error:
        raise IntentGuardianError(
            f"cannot durably project unmatched external completion: {error}"
        ) from error
    if not summary["interventions_open"] or not summary["effect_unknown"]:
        raise IntentGuardianError(
            "unmatched external completion did not replay as authoritative unknown debt"
        )
    return summary


def monitor_process(
    handle: RunHandle,
    *,
    prompt: str,
    events_path: Path,
    cursor_path: Path,
    cursor_generation: str,
    guardian: GuardianSession,
    root: Path,
    initial_side_effects: dict[str, str],
    initial_correction_store: bytes,
    initial_correction_sequence: int,
    timeout: float,
    heartbeat: PhaseHeartbeat,
    require_reader_termination: bool = False,
) -> tuple[int, str, str, IntentGuardianError | None]:
    """Stream provider events through the guardian without losing timeouts."""
    process = handle.process
    assert process.stdin is not None
    assert process.stdout is not None
    process.stdin.write(prompt)
    process.stdin.close()
    queue: Queue[str | None] = Queue()

    def read_stdout() -> None:
        try:
            for line in iter(process.stdout.readline, ""):
                queue.put(line)
        finally:
            queue.put(None)

    reader = threading.Thread(target=read_stdout, name="sulde-agent-events", daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout
    terminal = "running"
    final_message = ""
    last_side_effects = initial_side_effects
    accepted_correction_store = initial_correction_store
    accepted_correction_sequence = initial_correction_sequence
    correction_integrity_breach = False
    post_terminal_error: IntentGuardianError | None = None
    event_cursor = None
    event_cursor_digest: str | None = None
    last_heartbeat_ns = 0

    def publish_running_heartbeat(*, force: bool = False) -> None:
        nonlocal last_heartbeat_ns
        now = time.monotonic_ns()
        if force or now - last_heartbeat_ns >= 1_000_000_000:
            heartbeat.publish(
                "provider_running",
                expires_after_seconds=5,
                default_action="interrupt_and_fail_closed",
            )
            last_heartbeat_ns = now

    def request_interrupt(reason: str) -> None:
        heartbeat.publish(
            "interrupt_requested",
            expires_after_seconds=5,
            default_action="interrupt_and_fail_closed",
            reason=reason,
        )
        handle.interrupt(reason)

    publish_running_heartbeat(force=True)

    def inspect_correction_store() -> None:
        nonlocal accepted_correction_store
        nonlocal accepted_correction_sequence
        nonlocal correction_integrity_breach
        payload = correction_store_bytes(guardian.path)
        if not payload.startswith(accepted_correction_store):
            reason = "provider rewrote or truncated the correction intervention store"
            restore_correction_store(guardian.path, accepted_correction_store)
            guardian.record_integrity_breach(reason)
            request_interrupt("correction_store_integrity")
            correction_integrity_breach = True
            return
        if payload == accepted_correction_store:
            return
        projection = load_correction_projection(guardian.path)
        transitions = [
            transition
            for intervention in projection["interventions"].values()
            for transition in intervention.get("transitions", [])
            if int(transition.get("sequence") or 0) > accepted_correction_sequence
        ]
        forged_terminal = next(
            (
                transition
                for transition in transitions
                if transition.get("state")
                in {"applied", "rejected", "unsupported", "cancelled"}
            ),
            None,
        )
        if forged_terminal is not None:
            reason = "a correction terminal state appeared outside the parent monitor"
            restore_correction_store(guardian.path, accepted_correction_store)
            guardian.record_integrity_breach(reason)
            request_interrupt("correction_store_integrity")
            correction_integrity_breach = True
            return
        accepted_correction_store = payload
        accepted_correction_sequence = int(projection["sequence"])

    def apply_managed_correction() -> bool:
        nonlocal accepted_correction_store, accepted_correction_sequence
        inspect_correction_store()
        if correction_integrity_breach:
            return True
        queued = queued_corrections(
            guardian.path,
            provider=guardian.provider,
            session_id=guardian.session_id,
        )
        if not queued:
            return False
        identifiers = [str(row["intervention_id"]) for row in queued]
        # Persist the policy pause before dispatching the interrupt.  The
        # queued correction remains non-terminal if interruption itself fails.
        guardian.pause_for_correction(identifiers)
        request_interrupt("correction_intervention")
        for intervention_id in identifiers:
            transition_correction(
                guardian.path,
                intervention_id,
                state="applied",
                boundary="managed_run_monitor",
                reason_code="managed_process_tree_interrupted",
            )
        accepted_correction_store = correction_store_bytes(guardian.path)
        accepted_correction_sequence = int(
            load_correction_projection(guardian.path)["sequence"]
        )
        return True

    def observe_side_effects(
        reported: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], bool]:
        nonlocal last_side_effects
        current = observable_worktree_snapshot(root)
        changes = changed_paths(last_side_effects, current)
        last_side_effects = current
        reported_targets = {
            str(event.get("target") or "")
            for event in reported
            if event.get("effect") == "local_write"
        }
        synthetic: list[dict[str, Any]] = []
        denied = False
        for change in changes:
            target = change[2:]
            if target in reported_targets:
                continue
            event = normalize_hook_event(
                {
                    "client": guardian.provider,
                    "session_id": guardian.session_id,
                    "tool_name": "file_change",
                    "tool_input": {"target": target},
                    "success": True,
                    "observation_source": "worktree_snapshot",
                },
                phase="completed",
                provider=guardian.provider,
            )
            synthetic.append(event)
            observed_decision = guardian.observe(event)
            if (
                observed_decision.action == "deny"
                or (
                    guardian.contract.get("mode") == "enforce"
                    and observed_decision.would_action == "deny"
                )
            ):
                denied = True
        return synthetic, denied

    with events_path.open("w", encoding="utf-8") as events_handle:
        while True:
            publish_running_heartbeat()
            if apply_managed_correction():
                terminal = "paused"
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                terminal = "timeout"
                request_interrupt("timeout")
                break
            try:
                line = queue.get(timeout=min(0.2, remaining))
            except Empty:
                if process.poll() is not None and not reader.is_alive():
                    break
                continue
            if line is None:
                break
            events_handle.write(line)
            events_handle.flush()
            os.fsync(events_handle.fileno())
            advanced = scan_increment(
                events_path,
                runtime_generation=cursor_generation,
                cursor=event_cursor,
                max_bytes=max(1024 * 1024, len(line.encode("utf-8")) * 2),
                enforce_event_generation=False,
            )
            event_cursor_digest = save_cursor(
                cursor_path,
                advanced.cursor,
                expected_digest=event_cursor_digest,
            )
            event_cursor = advanced.cursor
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                record = None
            if isinstance(record, dict) and record.get("type") == "result":
                result = record.get("result")
                if isinstance(result, str):
                    final_message = result
            try:
                decision = observe_managed_provider_line(guardian, line)
            except IntentGuardianError as error:
                # An unmatched external completion can make its append-only
                # intervention durable before a later contract/audit step
                # fails. Replay that authority independently before exposing
                # a terminal state; only then carry the exception outward as
                # post-terminal diagnostic context.
                effect_summary = guardian.summary()
                if not (
                    effect_summary["interventions_open"]
                    and effect_summary["effect_unknown"]
                ):
                    candidates = [
                        event
                        for event in guardian.last_observed_events
                        if _uncertain_external_completion(event)
                    ]
                    if len(candidates) == 1:
                        effect_summary = _persist_unmatched_external_completion(
                            guardian,
                            candidates[0],
                        )
                if (
                    effect_summary["interventions_open"]
                    and effect_summary["effect_unknown"]
                ):
                    guardian._expected_effect_store = (
                        _managed_effect_store_path(guardian.path).read_bytes()
                    )
                    terminal = "awaiting_human"
                    post_terminal_error = error
                    request_interrupt("external_effect_outcome_unknown")
                    break
                raise
            if decision is not None and (
                decision.action == "deny"
                or (
                    guardian.contract.get("mode") == "enforce"
                    and decision.would_action == "deny"
                )
            ):
                terminal = "awaiting_human" if decision.awaiting_human else "paused"
                request_interrupt(terminal)
                break
            observed = list(guardian.last_observed_events)
            uncertain_external_completion = any(
                _uncertain_external_completion(event) for event in observed
            )
            if uncertain_external_completion:
                # The provider's failure flag cannot prove that an external
                # write did not happen.  Guardian observation above has already
                # converted that uncertainty into an append-only intervention;
                # independently replay it before making awaiting_human durable.
                effect_summary = guardian.summary()
                if effect_summary["interventions_open"]:
                    terminal = "awaiting_human"
                    request_interrupt("external_effect_outcome_unknown")
                    break
            should_snapshot = any(
                event["phase"] == "completed"
                and event["effect"] in {"local_write", "unknown"}
                for event in observed
            )
            synthetic: list[dict[str, Any]] = []
            snapshot_denied = False
            if should_snapshot:
                synthetic, snapshot_denied = observe_side_effects(observed)
            if snapshot_denied:
                terminal = "paused"
                request_interrupt(terminal)
                break
            if terminal in {"paused", "awaiting_human"}:
                break
    if process.poll() is None:
        try:
            process.wait(timeout=max(0.01, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            terminal = "timeout"
            request_interrupt("timeout")
    reader.join(timeout=1)
    if require_reader_termination and reader.is_alive():
        raise IntentGuardianError(
            "Codex provider stdout reader did not terminate after process exit"
        )
    if apply_managed_correction():
        terminal = "paused"
    if terminal == "running":
        _synthetic, snapshot_denied = observe_side_effects([])
        if snapshot_denied:
            terminal = "paused"
    return int(process.returncode or 0), terminal, final_message, post_terminal_error


def normalized_stop_reason(observed_status: str, returncode: int) -> str:
    if observed_status == "timeout":
        return "timeout"
    if observed_status == "paused":
        return "policy_paused"
    if observed_status == "awaiting_human":
        return "awaiting_human"
    return "completed" if returncode == 0 else "error"


def execution_prompt(
    brief: str,
    root: Path,
    *,
    provider: str,
    intent_path: Path,
    intent_id: str,
    resume_context: dict[str, Any] | None = None,
) -> str:
    contract = report_contract_for_brief(brief)
    skill_boundary = ""
    if provider == "codex":
        guardian_cli = Path(__file__).with_name("intent-guardian.py")
        skill_session = f"managed:{intent_id}"
        skill_boundary = f"""
Codex 当前没有可依赖的原生 Skill 生命周期事件。每次读取/采用一个 Skill 前，必须先执行：
`python3 {shlex.quote(str(guardian_cli))} skill-start <skill-name> --skill-path <absolute-SKILL.md> --provider codex --contract {shlex.quote(str(intent_path))} --session-id {shlex.quote(skill_session)}`
采用结束后必须执行同参数的 `skill-end`。这两条命令是监督谱系登记，不扩大任务权限。
本次受管执行只开放 shell command 工具；文件修改也必须通过 shell command 完成。
不要调用 apply_patch、file_change 或子代理工具。每条 shell command 都会由宿主 hook
自动改写到单层原生沙箱中；不要自行添加或嵌套 sandbox-exec。
"""
    else:
        skill_boundary = "\nClaude 的原生 Skill 工具事件由运行时流直接监督，不要重复伪造登记。\n"
    intervention_boundary = ""
    if resume_context:
        instructions = []
        for row in resume_context.get("interventions", []):
            if not isinstance(row, dict):
                continue
            decision = str(row.get("decision") or "")
            identity = str(row.get("intervention_id") or "unknown")
            capability = str(row.get("capability") or "unknown")
            intervention_provider = str(row.get("provider") or "unknown")
            target_sha256 = str(row.get("target_sha256") or "unknown")
            if decision in {"human_attested_success", "system_verified"}:
                action = "该外部操作已被独立确认成功，禁止重复执行；只继续后续步骤"
            elif decision == "retry_authorized":
                action = "仅允许按原参数重试一次，随后必须独立读取验证；不得扩大为其他写入"
            elif decision == "reprobe_authorized":
                action = "只允许独立读取/探测，不得重做写入；验证成功后才继续"
            else:
                action = "停止并保持现状"
            instructions.append(
                f"- intervention={identity} provider={intervention_provider} "
                f"capability={capability} "
                f"target_sha256={target_sha256}：{action}。"
            )
        intervention_boundary = (
            "\n这是人工处置后的新 provider session，不继承上一会话隐藏上下文。"
            "以下持久化处置决定优先于原任务书，必须按 attempt identity 执行：\n"
            + "\n".join(instructions)
            + "\n"
        )
    return f"""{brief.rstrip()}

--- Sulde 执行协议（优先级高于任务书中的效率建议） ---
你正在隔离 git worktree `{root}` 中执行已获人工批准的任务。
只能修改该 worktree；禁止 commit、push、修改全局配置或触碰主工作区。
所有 Skill、MCP、工具调用与副作用都必须保持 intent_id={intent_id} 的同一可审计谱系。
MCP/外部写入成功后必须独立读取并核对结果；工具返回 success 本身不算验收证据。
{skill_boundary.rstrip()}
{intervention_boundary.rstrip()}
最终回复必须满足版本化 report contract `{contract['schema']}`。
标题必须逐字、各出现一次；✅ 证据必须包含实际命令、exit 0 和可观察结果。
使用以下同源模板（不要翻译、编号或改名）：
{report_template(contract)}
"""


def load_resume_context(path: Path | None, state: Path, slug: str) -> dict[str, Any] | None:
    if path is None:
        return None
    resolved = path.expanduser().resolve()
    if resolved.parent != state.resolve() or not resolved.is_file():
        raise AgentRuntimeError(f"resume context must be a file inside {state}: {resolved}")
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise AgentRuntimeError(f"invalid intervention resume context: {error}") from error
    if (
        not isinstance(value, dict)
        or value.get("schema") != "sulde-intervention-resume-context-v1"
        or value.get("slug") != slug
        or not isinstance(value.get("interventions"), list)
        or not value["interventions"]
    ):
        raise AgentRuntimeError("intervention resume context has an invalid schema, slug or empty decision set")
    allowed = {
        "human_attested_success",
        "system_verified",
        "retry_authorized",
        "reprobe_authorized",
    }
    for row in value["interventions"]:
        if not isinstance(row, dict) or row.get("decision") not in allowed:
            raise AgentRuntimeError("intervention resume context contains a non-resumable decision")
        if not re.fullmatch(r"int-[0-9a-f]{24}", str(row.get("intervention_id") or "")):
            raise AgentRuntimeError("intervention resume context has an invalid intervention identity")
        if not re.fullmatch(r"att-[0-9a-f]{24}", str(row.get("attempt_id") or "")):
            raise AgentRuntimeError("intervention resume context has an invalid attempt identity")
        if not re.fullmatch(
            r"[A-Za-z0-9_.:-]{1,256}",
            str(row.get("capability") or ""),
        ):
            raise AgentRuntimeError("intervention resume context has an invalid capability")
        if row.get("provider") not in {"claude", "codex"}:
            raise AgentRuntimeError("intervention resume context has an invalid provider")
        for digest_name in ("target_sha256", "evidence_sha256"):
            if not re.fullmatch(r"[0-9a-f]{64}", str(row.get(digest_name) or "")):
                raise AgentRuntimeError(
                    f"intervention resume context has an invalid {digest_name}"
                )
    return value


def claude_result_message(events: Path) -> str:
    if not events.is_file():
        return ""
    result = ""
    for line in events.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("type") == "result" and isinstance(row.get("result"), str):
            result = row["result"]
    return result


def prepare_intent_contract(
    state: Path,
    slug: str,
    brief_text: str,
    root: Path,
    *,
    mode: str,
    explicit: Path | None,
    semantic_critic: bool,
    owned_paths: list[str],
    execution_binding_sha256: str,
    critic_scope: TaskCriticScope | None,
) -> Path:
    if not owned_paths:
        raise AgentRuntimeError("intent contract cannot have an empty allowed_paths boundary")
    target = state / f"{slug}.intent.json"
    if explicit is not None:
        source = explicit.expanduser().resolve()
        contract = load_contract(source)
        if contract["intent_id"] != f"l3:{slug}":
            raise AgentRuntimeError(
                f"intent contract id mismatch: expected l3:{slug}, got {contract['intent_id']}"
            )
        if mode != "shadow":
            contract["mode"] = mode
        if semantic_critic:
            contract["critic"]["enabled"] = True
    else:
        contract = contract_from_brief(
            brief_text,
            slug=slug,
            workspace=root,
            mode=mode,
            confirmed_by="human-l3-approval",
            semantic_critic=semantic_critic,
        )
    # L3 authority is the validated task worktree itself.  The generic intent
    # helper deliberately discovers an enclosing repository, which is useful
    # for hooks but would let a nested test/isolated worktree critic read the
    # coordinator checkout instead of the managed root.
    contract["workspace_root"] = str(root)
    constraints = contract.setdefault("constraints", {})
    if not isinstance(constraints, dict):
        raise AgentRuntimeError("intent contract constraints are invalid")
    constraints["allowed_paths"] = list(owned_paths)
    if semantic_critic:
        if critic_scope is None:
            raise AgentRuntimeError("semantic critic requires a task-bound scope")
        contract["critic"]["task_scope"] = critic_scope.as_projection()
    contract["execution_binding"] = {
        "schema": EXECUTION_BINDING_SCHEMA,
        "sha256": execution_binding_sha256,
    }
    if target.exists():
        existing = load_contract(target)
        if existing["intent_id"] != contract["intent_id"]:
            raise AgentRuntimeError(f"intent contract collision: {target}")
        changed = False
        if existing.get("workspace_root") != str(root):
            existing["workspace_root"] = str(root)
            changed = True
        if mode != "shadow" and existing["mode"] != mode:
            existing["mode"] = mode
            changed = True
        if semantic_critic and not existing["critic"]["enabled"]:
            existing["critic"]["enabled"] = True
            changed = True
        if semantic_critic:
            if critic_scope is None:
                raise AgentRuntimeError("semantic critic requires a task-bound scope")
            expected_scope = critic_scope.as_projection()
            if existing["critic"].get("task_scope") != expected_scope:
                existing["critic"]["task_scope"] = expected_scope
                changed = True
        existing_constraints = existing.setdefault("constraints", {})
        if existing_constraints.get("allowed_paths") != list(owned_paths):
            existing_constraints["allowed_paths"] = list(owned_paths)
            changed = True
        expected_binding = {
            "schema": EXECUTION_BINDING_SCHEMA,
            "sha256": execution_binding_sha256,
        }
        if existing.get("execution_binding") != expected_binding:
            existing["execution_binding"] = expected_binding
            changed = True
        if changed:
            write_contract(target, existing)
        return target
    write_contract(target, contract)
    return target


def project_run_ledger_binding(
    path: Path,
    *,
    run_id: str,
    binding_sha256: str,
) -> None:
    """Bind the durable requested event before monitor/provider events are consumed."""
    try:
        payload = path.read_text(encoding="utf-8")
        rows = [json.loads(line) for line in payload.splitlines()]
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise AgentRuntimeError("run ledger cannot receive execution binding") from error
    if (
        len(rows) < 2
        or not all(isinstance(row, dict) for row in rows)
        or rows[0].get("type") != "execution.requested"
        or rows[0].get("run_id") != run_id
    ):
        raise AgentRuntimeError("run ledger requested event is unavailable for binding")
    existing = rows[0].get("execution_binding_sha256")
    if existing not in {None, binding_sha256}:
        raise AgentRuntimeError("run ledger execution binding already drifted")
    rows[0]["execution_binding_sha256"] = binding_sha256
    atomic_write(
        path,
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
        ),
    )


def verify_run_ledger_binding(path: Path, binding_sha256: str) -> None:
    try:
        first = path.read_text(encoding="utf-8").splitlines()[0]
        row = json.loads(first)
    except (OSError, UnicodeError, json.JSONDecodeError, IndexError) as error:
        raise ExecutionBackendError(
            "run ledger execution binding cannot be parsed"
        ) from error
    if (
        not isinstance(row, dict)
        or row.get("type") != "execution.requested"
        or row.get("execution_binding_sha256") != binding_sha256
    ):
        raise AgentRuntimeError("run ledger execution binding drifted")


def _canonical_owned_path(value: str) -> str:
    subtree = value.endswith("/**")
    lexical = value[:-3] if subtree else value
    if (
        not lexical
        or lexical.startswith(("/", "\\"))
        or "\\" in lexical
        or any(part in {"", ".", ".."} for part in lexical.split("/"))
        or any(marker in lexical for marker in ("*", "?", "[", "]", "{"))
        or lexical == ".git"
        or lexical == ".codex-agent"
        or lexical.startswith((".git/", ".codex-agent/"))
    ):
        raise AgentRuntimeError(
            f"Codex OS profile requires an exact canonical owned path: {value!r}"
        )
    return value


def _git_probe(root: Path, *arguments: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise AgentRuntimeError("git authority probe is unavailable") from error
    value = completed.stdout.strip()
    if completed.returncode != 0 or not value:
        raise AgentRuntimeError("git authority probe failed")
    return value


def _git_capture(
    root: Path,
    *arguments: str,
    allowed_returncodes: tuple[int, ...] = (0,),
    timeout: float = 30.0,
) -> bytes:
    """Run one argv-only Git command and return exact stdout bytes."""
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *arguments],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise AgentRuntimeError("git lifecycle command is unavailable") from error
    if completed.returncode not in allowed_returncodes:
        detail = completed.stderr.decode(
            "utf-8", errors="replace"
        ).strip().replace("\n", " ")[:500]
        raise AgentRuntimeError(
            f"git lifecycle command failed ({completed.returncode}): {detail or arguments[0]}"
        )
    return completed.stdout


def _git_text(root: Path, *arguments: str, timeout: float = 30.0) -> str:
    try:
        return _git_capture(root, *arguments, timeout=timeout).decode("utf-8").strip()
    except UnicodeDecodeError as error:
        raise AgentRuntimeError("git lifecycle output is not valid UTF-8") from error


def _git_nul_paths(root: Path, *arguments: str) -> list[str]:
    payload = _git_capture(root, *arguments)
    try:
        values = payload.decode("utf-8").split("\0")
    except UnicodeDecodeError as error:
        raise AgentRuntimeError("git lifecycle paths are not valid UTF-8") from error
    if values and values[-1] == "":
        values.pop()
    if any(not value for value in values):
        raise AgentRuntimeError("git lifecycle returned an empty path")
    return values


def _lifecycle_git_common_directory(root: Path) -> Path:
    raw = _git_text(root, "rev-parse", "--git-common-dir")
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    lexical = candidate.absolute()
    if lexical.is_symlink():
        raise AgentRuntimeError("git common directory must not be a symlink")
    try:
        common = lexical.resolve(strict=True)
    except OSError as error:
        raise AgentRuntimeError("git common directory is unavailable") from error
    metadata = common.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or (hasattr(os, "geteuid") and metadata.st_uid != os.geteuid())
    ):
        raise AgentRuntimeError("git common directory identity is unsafe")
    return common


@contextmanager
def _git_lifecycle_lock(root: Path) -> Iterator[None]:
    """Serialize all structured writes sharing one Git common directory."""
    common = _lifecycle_git_common_directory(root)
    lock_path = common / "sulde-git-lifecycle.lock"
    if lock_path.is_symlink():
        raise AgentRuntimeError("git lifecycle lock must not be a symlink")
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(lock_path, flags, 0o600)
    handle = os.fdopen(descriptor, "r+", encoding="utf-8")
    try:
        metadata = os.fstat(handle.fileno())
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or (hasattr(os, "geteuid") and metadata.st_uid != os.geteuid())
        ):
            raise AgentRuntimeError("git lifecycle lock identity is unsafe")
        os.fchmod(handle.fileno(), 0o600)
        try:
            lock_exclusive_nonblocking(handle)
        except BlockingIOError as error:
            raise AgentRuntimeError(
                "another structured Git lifecycle mutation is active"
            ) from error
        yield
    finally:
        try:
            unlock(handle)
        finally:
            handle.close()


def _canonical_git_lifecycle_paths(root: Path, values: list[str]) -> list[str]:
    if not values:
        raise AgentRuntimeError("git lifecycle requires at least one exact path")
    normalized: list[str] = []
    resolved_root = root.resolve(strict=True)
    for value in values:
        if (
            not value
            or value.startswith(("/", "\\", "-", ":"))
            or "\\" in value
            or any(character in value for character in ("*", "?", "[", "]", "{", "}"))
            or any(ord(character) < 32 for character in value)
            or any(part in {"", ".", "..", ".git", ".codex-agent"} for part in value.split("/"))
        ):
            raise AgentRuntimeError(
                f"git lifecycle path is not exact and canonical: {value!r}"
            )
        target = root / value
        try:
            target.resolve(strict=False).relative_to(resolved_root)
        except (OSError, ValueError) as error:
            raise AgentRuntimeError(
                f"git lifecycle path escaped the worktree: {value!r}"
            ) from error
        current = root
        for part in Path(value).parts[:-1]:
            current = current / part
            if current.is_symlink():
                raise AgentRuntimeError(
                    f"git lifecycle path crosses a symlink: {value!r}"
                )
        if value not in normalized:
            normalized.append(value)
    if len(normalized) != len(values):
        raise AgentRuntimeError("git lifecycle paths must be unique")
    return sorted(normalized)


def _require_clean_worktree(root: Path, *, label: str) -> None:
    status = _git_capture(
        root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
    )
    if status:
        raise AgentRuntimeError(f"{label} worktree is not clean")


def _materialize_program_if_present(root: Path) -> dict[str, Any] | None:
    program = root / "guardian-program"
    if not program.exists() and not program.is_symlink():
        return None
    try:
        return materialize_completion_permissions(program)
    except GuardianProgramError as error:
        raise AgentRuntimeError(
            f"completion permission materialization failed: {error}"
        ) from error


def _worktree_records(repository: Path) -> list[dict[str, str]]:
    text = _git_text(repository, "worktree", "list", "--porcelain")
    records: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in text.splitlines():
        if not line:
            if current:
                records.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value
    if current:
        records.append(current)
    return records


def provision_worktree(args: argparse.Namespace) -> int:
    repository = validated_root(args.repository)
    if _git_text(repository, "rev-parse", "--show-toplevel") != str(repository):
        raise AgentRuntimeError("provision repository must be its primary worktree root")
    if args.base_ref != "dev":
        raise AgentRuntimeError("task execution roots must start from dev")
    if not _GIT_OID_RE.fullmatch(args.base_commit):
        raise AgentRuntimeError("provision base commit must be a full Git object id")
    if not re.fullmatch(
        r"(?:fix|task|feature|repair)/[A-Za-z0-9][A-Za-z0-9._/-]{0,180}",
        args.branch,
    ) or any(marker in args.branch for marker in ("..", "@{", "//")):
        raise AgentRuntimeError("provision branch is not a canonical task branch")
    lexical_target = _lexical_absolute(args.worktree)
    if lexical_target.is_symlink() or os.path.lexists(lexical_target):
        raise AgentRuntimeError("provision worktree path must be absent")
    worktrees_root = repository / ".worktrees"
    if worktrees_root.is_symlink() or not worktrees_root.is_dir():
        raise AgentRuntimeError("repository-local .worktrees directory is unavailable")
    if lexical_target.parent.resolve(strict=True) != worktrees_root.resolve(strict=True):
        raise AgentRuntimeError("provision target must be a direct child of .worktrees")
    if lexical_target.name != args.branch.rsplit("/", 1)[-1] and not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]{0,180}", lexical_target.name
    ):
        raise AgentRuntimeError("provision worktree name is not canonical")

    with _git_lifecycle_lock(repository):
        base_commit = _git_text(
            repository,
            "rev-parse",
            "--verify",
            f"refs/heads/{args.base_ref}^{{commit}}",
        )
        if base_commit != args.base_commit:
            raise AgentRuntimeError("provision dev base changed before creation")
        if any(
            record.get("branch") == f"refs/heads/{args.branch}"
            or Path(record.get("worktree", "")).resolve(strict=False) == lexical_target
            for record in _worktree_records(repository)
        ):
            raise AgentRuntimeError("provision branch or worktree already exists")
        branch_exists = subprocess.run(
            [
                "git", "-C", str(repository), "show-ref", "--verify", "--quiet",
                f"refs/heads/{args.branch}",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
        if branch_exists.returncode == 0:
            raise AgentRuntimeError("provision branch already exists")
        if branch_exists.returncode != 1:
            raise AgentRuntimeError("provision branch absence cannot be proved")
        with tempfile.TemporaryDirectory(
            prefix=f".{lexical_target.name}.provision-",
            dir=worktrees_root,
        ) as staging_parent:
            staged = Path(staging_parent) / "execution-root"
            _git_capture(
                repository,
                "clone",
                "--no-local",
                "--no-checkout",
                "--no-tags",
                "--origin",
                "sulde-source",
                "--",
                str(repository),
                str(staged),
                timeout=60,
            )
            staged = validated_root(staged)
            staged_git = staged / ".git"
            try:
                staged_git_metadata = staged_git.lstat()
            except OSError as error:
                raise AgentRuntimeError("provision clone has no internal Git metadata") from error
            if (
                staged_git.is_symlink()
                or not stat.S_ISDIR(staged_git_metadata.st_mode)
                or _lifecycle_git_common_directory(staged) != staged_git.resolve(strict=True)
                or _git_text(staged, "rev-parse", "--show-toplevel") != str(staged)
            ):
                raise AgentRuntimeError("provision clone Git metadata layout is unsupported")
            cloned_base = _git_text(
                staged,
                "rev-parse",
                "--verify",
                f"refs/remotes/sulde-source/{args.base_ref}^{{commit}}",
            )
            if cloned_base != args.base_commit:
                raise AgentRuntimeError("provision clone base does not match exact dev ref")
            source_url = _git_text(staged, "remote", "get-url", "sulde-source")
            try:
                source_identity = Path(source_url).expanduser().resolve(strict=True)
            except OSError as error:
                raise AgentRuntimeError("provision clone source identity is unavailable") from error
            if source_identity != repository:
                raise AgentRuntimeError("provision clone source identity changed")
            _git_capture(
                staged,
                "checkout",
                "--no-track",
                "-b",
                args.branch,
                args.base_commit,
                timeout=60,
            )
            if (
                _git_text(staged, "rev-parse", "HEAD") != args.base_commit
                or _git_text(staged, "branch", "--show-current") != args.branch
            ):
                raise AgentRuntimeError("provision staged checkout does not match its binding")
            materialization = _materialize_program_if_present(staged)
            _require_clean_worktree(staged, label="provisioned")
            if _git_text(
                repository,
                "rev-parse",
                "--verify",
                f"refs/heads/{args.base_ref}^{{commit}}",
            ) != args.base_commit:
                raise AgentRuntimeError("provision dev base changed during creation")
            os.rename(staged, lexical_target)
        created = validated_root(lexical_target)
        created_git = created / ".git"
        if (
            _git_text(created, "rev-parse", "HEAD") != args.base_commit
            or _git_text(created, "branch", "--show-current") != args.branch
            or _git_text(created, "rev-parse", "--show-toplevel") != str(created)
            or not created_git.is_dir()
            or created_git.is_symlink()
            or _lifecycle_git_common_directory(created) != created_git.resolve(strict=True)
        ):
            raise AgentRuntimeError("provision postcondition does not match its binding")
        _require_clean_worktree(created, label="provisioned")

    print(
        json.dumps(
            {
                "schema": "sulde-git-lifecycle-result-v1",
                "action": "provision",
                "repository": str(repository),
                "worktree": str(created),
                "branch": args.branch,
                "head": args.base_commit,
                "git_layout": "full-clone-internal-git",
                "completion_permissions": materialization,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def commit_worktree(args: argparse.Namespace) -> int:
    root = validated_root(args.worktree)
    expected_paths = _canonical_git_lifecycle_paths(root, list(args.path))
    if not _GIT_OID_RE.fullmatch(args.expected_head):
        raise AgentRuntimeError("commit expected head must be a full Git object id")
    if not args.message or "\n" in args.message or len(args.message) > 200:
        raise AgentRuntimeError("commit message must be one bounded non-empty line")
    branch = _git_text(root, "branch", "--show-current")
    if branch in {"", "main", "dev"}:
        raise AgentRuntimeError("commit requires a non-release task branch")

    with _git_lifecycle_lock(root):
        if _git_text(root, "rev-parse", "HEAD") != args.expected_head:
            raise AgentRuntimeError("commit parent changed before mutation")
        staged = sorted(
            _git_nul_paths(
                root,
                "diff",
                "--cached",
                "--name-only",
                "--diff-filter=ACDMRTUXB",
                "-z",
            )
        )
        if staged != expected_paths:
            raise AgentRuntimeError("commit staged paths do not match the sealed path set")
        unstaged = _git_capture(root, "diff", "--name-only", "-z")
        untracked = _git_capture(
            root, "ls-files", "--others", "--exclude-standard", "-z"
        )
        if unstaged or untracked:
            raise AgentRuntimeError("commit worktree has unsealed unstaged or untracked changes")
        expected_tree = _git_text(root, "write-tree")
        _git_capture(
            root,
            "commit",
            "--no-gpg-sign",
            "-m",
            args.message,
            timeout=60,
        )
        new_head = _git_text(root, "rev-parse", "HEAD")
        if new_head == args.expected_head:
            raise AgentRuntimeError("commit did not advance the task branch")
        if _git_text(root, "rev-parse", f"{new_head}^1") != args.expected_head:
            raise AgentRuntimeError("commit parent postcondition changed")
        if _git_text(root, "rev-parse", f"{new_head}^{{tree}}") != expected_tree:
            raise AgentRuntimeError("commit tree does not match the sealed index")
        committed_paths = sorted(
            _git_nul_paths(
                root,
                "diff-tree",
                "--no-commit-id",
                "--name-only",
                "-r",
                "-z",
                new_head,
            )
        )
        if committed_paths != expected_paths:
            raise AgentRuntimeError("commit path postcondition changed")
        _require_clean_worktree(root, label="committed")

    print(
        json.dumps(
            {
                "schema": "sulde-git-lifecycle-result-v1",
                "action": "commit",
                "worktree": str(root),
                "branch": branch,
                "parent": args.expected_head,
                "head": new_head,
                "tree": expected_tree,
                "paths": expected_paths,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def merge_worktree(args: argparse.Namespace) -> int:
    root = validated_root(args.worktree)
    expected_paths = _canonical_git_lifecycle_paths(root, list(args.path))
    if not _GIT_OID_RE.fullmatch(args.expected_target_head) or not _GIT_OID_RE.fullmatch(
        args.expected_source_head
    ):
        raise AgentRuntimeError("merge heads must be full Git object ids")
    if args.target_branch not in {"dev", "main"}:
        raise AgentRuntimeError("merge target must be dev or main")
    if args.target_branch == "main" and args.source_ref != "dev":
        raise AgentRuntimeError("main may only fast-forward from dev")
    if args.target_branch == "dev" and not re.fullmatch(
        r"(?:fix|task|feature|repair)/[A-Za-z0-9][A-Za-z0-9._/-]{0,180}",
        args.source_ref,
    ):
        raise AgentRuntimeError("dev may only fast-forward from a task branch")
    if any(marker in args.source_ref for marker in ("..", "@{", "//")):
        raise AgentRuntimeError("merge source ref is not canonical")

    with _git_lifecycle_lock(root):
        if _git_text(root, "branch", "--show-current") != args.target_branch:
            raise AgentRuntimeError("merge target branch binding changed")
        if _git_text(root, "rev-parse", "HEAD") != args.expected_target_head:
            raise AgentRuntimeError("merge target head changed before mutation")
        source_head = _git_text(
            root, "rev-parse", "--verify", f"refs/heads/{args.source_ref}^{{commit}}"
        )
        if source_head != args.expected_source_head:
            raise AgentRuntimeError("merge source head changed before mutation")
        records = _worktree_records(root)
        source_record = next(
            (
                record
                for record in records
                if record.get("branch") == f"refs/heads/{args.source_ref}"
            ),
            None,
        )
        if source_record is not None:
            _require_clean_worktree(
                validated_root(Path(source_record["worktree"])), label="source"
            )
        _require_clean_worktree(root, label="merge target")
        changed_paths = sorted(
            _git_nul_paths(
                root,
                "diff",
                "--name-only",
                "-z",
                args.expected_target_head,
                args.expected_source_head,
            )
        )
        if changed_paths != expected_paths:
            raise AgentRuntimeError("merge diff paths do not match the sealed path set")
        ancestor = subprocess.run(
            [
                "git", "-C", str(root), "merge-base", "--is-ancestor",
                args.expected_target_head, args.expected_source_head,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
        if ancestor.returncode != 0:
            raise AgentRuntimeError("merge is not a fast-forward")
        _git_capture(
            root,
            "merge",
            "--ff-only",
            "--no-edit",
            args.expected_source_head,
            timeout=60,
        )
        if _git_text(root, "rev-parse", "HEAD") != args.expected_source_head:
            raise AgentRuntimeError("merge head postcondition changed")
        materialization = _materialize_program_if_present(root)
        _require_clean_worktree(root, label="merged")

    print(
        json.dumps(
            {
                "schema": "sulde-git-lifecycle-result-v1",
                "action": "merge",
                "worktree": str(root),
                "target_branch": args.target_branch,
                "source_ref": args.source_ref,
                "before": args.expected_target_head,
                "head": args.expected_source_head,
                "paths": expected_paths,
                "completion_permissions": materialization,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0



def _full_clone_control_source_matches(root: Path, control: Path) -> bool:
    try:
        root_common = Path(_git_common_directory(root, test_mode=False))
        lexical_git = root / ".git"
        internal_git = lexical_git.resolve(strict=True)
        if (
            root_common != internal_git
            or lexical_git.is_symlink()
            or not internal_git.is_dir()
        ):
            return False
        urls = [
            value.strip()
            for value in _git_probe(
                root, "remote", "get-url", "--all", "sulde-source"
            ).splitlines()
            if value.strip()
        ]
        if len(urls) != 1:
            return False
        source = Path(urls[0]).expanduser().resolve(strict=True)
        source_top = Path(
            _git_probe(source, "rev-parse", "--show-toplevel")
        ).resolve(strict=True)
        if source != source_top:
            return False
        source_common = Path(
            _git_probe(source, "rev-parse", "--git-common-dir")
        )
        if not source_common.is_absolute():
            source_common = source / source_common
        control_common = Path(
            _git_probe(control, "rev-parse", "--git-common-dir")
        )
        if not control_common.is_absolute():
            control_common = control / control_common
        return source_common.resolve(strict=True) == control_common.resolve(strict=True)
    except (AgentRuntimeError, OSError, RuntimeError):
        return False


def coordinator_control_root(
    root: Path,
    supplied: Path | None,
    *,
    test_mode: bool,
) -> Path:
    if supplied is None:
        if not test_mode:
            raise AgentRuntimeError("run requires --control-root authority")
        return root / "guardian-program"
    lexical = _lexical_absolute(supplied)
    if lexical.is_symlink():
        raise AgentRuntimeError("coordinator control root must not be a symlink")
    control = lexical.resolve(strict=True)
    if control.name != "guardian-program":
        raise AgentRuntimeError("coordinator control root must be guardian-program/")
    metadata = control.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or (hasattr(os, "getuid") and metadata.st_uid != os.getuid())
        or stat.S_IMODE(metadata.st_mode) & 0o022
    ):
        raise AgentRuntimeError("coordinator control root owner or mode is unsafe")
    if not test_mode:
        worktree_common = Path(_git_probe(root, "rev-parse", "--git-common-dir"))
        control_common = Path(_git_probe(control, "rev-parse", "--git-common-dir"))
        if not worktree_common.is_absolute():
            worktree_common = (root / worktree_common).resolve()
        if not control_common.is_absolute():
            control_common = (control / control_common).resolve()
        if (
            worktree_common != control_common
            and not _full_clone_control_source_matches(root, control)
        ):
            raise AgentRuntimeError(
                "control root is not authenticated by the worktree Git source"
            )
    return control


def _validate_owned_path_against_worktree(root: Path, value: str) -> None:
    subtree = value.endswith("/**")
    lexical = value[:-3] if subtree else value
    target = root / lexical
    current = root
    for part in Path(lexical).parts:
        current = current / part
        if os.path.lexists(current) and current.is_symlink():
            raise AgentRuntimeError(f"owned path parent chain contains a symlink: {value}")
    anchor = target if target.exists() else target.parent
    try:
        resolved = anchor.resolve(strict=True)
        resolved_root = root.resolve(strict=True)
    except OSError as error:
        raise AgentRuntimeError(f"owned path parent is unavailable: {value}") from error
    try:
        # macOS exposes /var as a lexical alias of /private/var.  Compare
        # both sides in the same physical identity layer; otherwise a valid
        # descendant under the host default TMPDIR is rejected as escaped.
        resolved.relative_to(resolved_root)
    except ValueError as error:
        raise AgentRuntimeError(f"owned path escaped the worktree: {value}") from error
    if target.is_symlink():
        raise AgentRuntimeError(f"owned path must not be a symlink: {value}")
    if target.is_file() and target.lstat().st_nlink != 1:
        raise AgentRuntimeError(f"owned path hardlink count must be one: {value}")
    if subtree and target.exists() and not target.is_dir():
        raise AgentRuntimeError(f"owned subtree root is not a directory: {value}")


def _expected_base_commit(root: Path, *, test_mode: bool) -> str:
    if test_mode and not os.path.lexists(root / ".git"):
        return "fixture"
    return _git_probe(root, "rev-parse", "HEAD")


def _git_common_directory(root: Path, *, test_mode: bool) -> str:
    if test_mode and not os.path.lexists(root / ".git"):
        return "test-fixture"
    common = Path(_git_probe(root, "rev-parse", "--git-common-dir"))
    if not common.is_absolute():
        common = root / common
    return str(common.resolve(strict=True))


def _opened_directory_identity(path: Path, *, label: str) -> dict[str, Any]:
    """Bind one canonical directory pathname to the inode opened without follow."""
    canonical = path.resolve(strict=True)
    if canonical.is_symlink():
        raise AgentRuntimeError(f"{label} must not be a symlink")
    descriptor = -1
    try:
        before = canonical.lstat()
        if not stat.S_ISDIR(before.st_mode) or stat.S_ISLNK(before.st_mode):
            raise AgentRuntimeError(f"{label} is not a real directory")
        descriptor = os.open(
            canonical,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise AgentRuntimeError(f"{label} changed before open")
        rebound = canonical.resolve(strict=True)
        after = rebound.lstat()
        if rebound != canonical or (after.st_dev, after.st_ino) != (
            opened.st_dev,
            opened.st_ino,
        ):
            raise AgentRuntimeError(f"{label} pathname identity changed")
        return {
            "path": str(canonical),
            "device": int(opened.st_dev),
            "inode": int(opened.st_ino),
        }
    except OSError as error:
        raise AgentRuntimeError(
            f"{label} identity cannot be opened safely: {type(error).__name__}"
        ) from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _worktree_identity(root: Path) -> dict[str, Any]:
    return _opened_directory_identity(root, label="worktree")


def _git_common_directory_identity(
    root: Path,
    *,
    test_mode: bool,
) -> dict[str, Any]:
    common = _git_common_directory(root, test_mode=test_mode)
    if common == "test-fixture":
        return {"path": common, "device": 0, "inode": 0}
    return _opened_directory_identity(Path(common), label="Git common-dir")


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _strict_string_list(
    value: Any,
    *,
    label: str,
    allow_empty: bool,
    item_pattern: re.Pattern[str] | None = None,
) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise AgentRuntimeError(f"task definition {label} is invalid")
    if any(
        not isinstance(item, str)
        or not item.strip()
        or (item_pattern is not None and item_pattern.fullmatch(item) is None)
        for item in value
    ):
        raise AgentRuntimeError(f"task definition {label} contains an invalid item")
    if len(set(value)) != len(value):
        raise AgentRuntimeError(f"task definition {label} contains duplicates")
    return list(value)


def _canonical_brief_relative_identity(value: Any) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise AgentRuntimeError("task definition brief relative identity is invalid")
    parts = value.split("/")
    if (
        len(parts) != 2
        or parts[0] != "briefs"
        or parts[1] in {"", ".", ".."}
        or any(marker in parts[1] for marker in ("/", "\\", "*", "?", "[", "]", "{"))
    ):
        raise AgentRuntimeError(
            "task definition brief must identify one direct briefs/ child"
        )
    return value


def _parse_task_definition(
    payload: bytes,
    root: Path,
    *,
    expected_task_id: str | None,
    test_mode: bool,
) -> tuple[dict[str, Any], list[str]]:
    try:
        task = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise AgentRuntimeError("task definition is invalid JSON") from error
    if not isinstance(task, dict) or task.get("schema") != TASK_V1_SCHEMA:
        raise AgentRuntimeError("task definition schema is unsupported")
    if set(task) != TASK_V1_FIELDS:
        missing = sorted(TASK_V1_FIELDS - set(task))
        extra = sorted(set(task) - TASK_V1_FIELDS)
        raise AgentRuntimeError(
            "task definition fields do not match strict task-v1"
            f" (missing={missing}, extra={extra})"
        )
    task_id = task.get("task_id")
    if not isinstance(task_id, str) or re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]*", task_id
    ) is None:
        raise AgentRuntimeError("task definition task ID is invalid")
    if expected_task_id is not None and task_id != expected_task_id:
        raise AgentRuntimeError("task definition task ID does not match --task-id")
    for field in ("title", "owner"):
        value = task.get(field)
        if not isinstance(value, str) or not value.strip() or len(value) > 500:
            raise AgentRuntimeError(f"task definition {field} is invalid")
    if task.get("capability_tier") not in {"light", "balanced", "deep"}:
        raise AgentRuntimeError("task definition capability_tier is invalid")
    base_commit = task.get("base_commit")
    if not isinstance(base_commit, str) or (
        base_commit != "fixture"
        and re.fullmatch(r"[0-9a-f]{40}", base_commit) is None
    ):
        raise AgentRuntimeError("task definition base commit is invalid")
    if task.get("base_commit") != _expected_base_commit(root, test_mode=test_mode):
        raise AgentRuntimeError("task definition base commit does not match worktree HEAD")
    task_id_pattern = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
    depends_on = _strict_string_list(
        task.get("depends_on"),
        label="depends_on",
        allow_empty=True,
        item_pattern=task_id_pattern,
    )
    supersedes = _strict_string_list(
        task.get("supersedes"),
        label="supersedes",
        allow_empty=True,
        item_pattern=task_id_pattern,
    )
    if task_id in depends_on or task_id in supersedes:
        raise AgentRuntimeError("task definition cannot depend on or supersede itself")
    if set(depends_on) & set(supersedes):
        raise AgentRuntimeError(
            "task definition dependency and supersession fields overlap"
        )
    task_paths = task.get("owned_paths")
    if not isinstance(task_paths, list) or not task_paths:
        raise AgentRuntimeError("task definition has no owned_paths")
    if any(not isinstance(item, str) for item in task_paths):
        raise AgentRuntimeError("task definition owned_paths contain a non-string")
    parsed = [_canonical_owned_path(item) for item in task_paths]
    if len(set(parsed)) != len(parsed):
        raise AgentRuntimeError("task definition owned_paths contain duplicates")
    for path in parsed:
        _validate_owned_path_against_worktree(root, path)
    _strict_string_list(
        task.get("requirements"),
        label="requirements",
        allow_empty=True,
    )
    _strict_string_list(
        task.get("acceptance"),
        label="acceptance",
        allow_empty=False,
    )
    evidence_gates = task.get("evidence_gates")
    if not isinstance(evidence_gates, dict) or set(evidence_gates) != (
        TASK_V1_EVIDENCE_GATES
    ):
        raise AgentRuntimeError("task definition evidence_gates are invalid")
    for gate in sorted(TASK_V1_EVIDENCE_GATES):
        _strict_string_list(
            evidence_gates.get(gate),
            label=f"evidence_gates.{gate}",
            allow_empty=False,
            item_pattern=re.compile(r"[a-z][a-z0-9_]*"),
        )
    return task, parsed


def execution_binding_envelope(
    *,
    task_payload: bytes,
    task: dict[str, Any],
    brief_relative_path: str,
    brief_sha256: str,
    root: Path,
    owned_paths: list[str],
    test_mode: bool,
) -> dict[str, Any]:
    relative = _canonical_brief_relative_identity(brief_relative_path)
    if _SHA256_RE.fullmatch(brief_sha256) is None:
        raise AgentRuntimeError("execution binding brief SHA-256 is invalid")
    return {
        "schema": EXECUTION_BINDING_SCHEMA,
        "task_definition_sha256": hashlib.sha256(task_payload).hexdigest(),
        "brief": {"relative_path": relative, "sha256": brief_sha256},
        "worktree": _worktree_identity(root),
        "git_common_dir": _git_common_directory_identity(
            root,
            test_mode=test_mode,
        ),
        "task_id": task["task_id"],
        "base_commit": task["base_commit"],
        "owned_paths": list(owned_paths),
        "path_schema": "canonical-worktree-relative-v1",
    }


def execution_binding_digest(binding: dict[str, Any]) -> str:
    if not isinstance(binding, dict) or set(binding) != EXECUTION_BINDING_FIELDS:
        raise AgentRuntimeError("execution binding envelope fields are invalid")
    return hashlib.sha256(_canonical_json_bytes(binding)).hexdigest()


def execution_binding_artifact(binding: dict[str, Any]) -> tuple[bytes, str]:
    digest = execution_binding_digest(binding)
    artifact = {
        "schema": EXECUTION_BINDING_ARTIFACT_SCHEMA,
        "binding": binding,
        "binding_sha256": digest,
    }
    return _canonical_json_bytes(artifact) + b"\n", digest


def parse_execution_binding_artifact(
    payload: bytes,
) -> tuple[dict[str, Any], str]:
    try:
        artifact = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise AgentRuntimeError("execution binding artifact is invalid JSON") from error
    if (
        not isinstance(artifact, dict)
        or set(artifact) != {"schema", "binding", "binding_sha256"}
        or artifact.get("schema") != EXECUTION_BINDING_ARTIFACT_SCHEMA
        or not isinstance(artifact.get("binding"), dict)
    ):
        raise AgentRuntimeError("execution binding artifact fields are invalid")
    binding = artifact["binding"]
    digest = execution_binding_digest(binding)
    if artifact.get("binding_sha256") != digest:
        raise AgentRuntimeError("execution binding canonical digest drifted")
    return binding, digest


def validate_execution_binding(
    payload: bytes,
    *,
    expected: dict[str, Any],
) -> str:
    binding, digest = parse_execution_binding_artifact(payload)
    if binding != expected:
        raise AgentRuntimeError("execution binding envelope drifted")
    return digest


def read_task_authority(
    args: argparse.Namespace,
    root: Path,
    control_root: Path,
    *,
    brief_origin: str,
    test_mode: bool,
) -> tuple[bytes, dict[str, Any], list[str], str, Path]:
    explicit_paths = [_canonical_owned_path(item) for item in (args.owned_path or [])]
    if args.task_definition is None:
        if not test_mode:
            raise AgentRuntimeError("run requires a digest-bound --task-definition")
        paths = explicit_paths or ["base.txt"]
        for path in paths:
            _validate_owned_path_against_worktree(root, path)
        task = {
            "schema": TASK_V1_SCHEMA,
            "task_id": args.task_id or "test-fixture",
            "title": "Test fixture task",
            "owner": "test-runtime",
            "capability_tier": "light",
            "base_commit": _expected_base_commit(root, test_mode=test_mode),
            "depends_on": [],
            "supersedes": [],
            "owned_paths": list(dict.fromkeys(paths)),
            "requirements": [],
            "acceptance": ["fixture provider completes"],
            "evidence_gates": {
                "implemented": ["task_report"],
                "task_verified": ["targeted_tests"],
                "integrated": ["integration_tests"],
                "system_verified": ["system_tests"],
            },
        }
        payload = (
            json.dumps(task, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        return payload, task, task["owned_paths"], "test-fixture", _lexical_absolute(args.brief)
    if args.task_definition_sha256 is None:
        raise AgentRuntimeError("task definition requires --task-definition-sha256")
    candidate = _lexical_absolute(args.task_definition)
    external_parent = control_root / "task-definitions"
    local_parent = root / STATE_DIRECTORY
    candidate_parent = candidate.parent.resolve(strict=True)
    if candidate_parent == external_parent.resolve(strict=True):
        local = False
        allowed_parent = external_parent
        origin = "external_import"
    elif local_parent.is_dir() and candidate_parent == local_parent.resolve(strict=True):
        local = True
        allowed_parent = local_parent
        origin = "local_reuse"
    else:
        raise AgentRuntimeError(
            "task definition must be a direct child of control-root task-definitions/ or .codex-agent"
        )
    payload, digest, opened = safe_control_read(
        candidate,
        allowed_parent=allowed_parent,
        expected_sha256=args.task_definition_sha256,
        local_static_copy=local,
    )
    if not isinstance(args.task_id, str) or not args.task_id:
        raise AgentRuntimeError("run requires --task-id authority")
    if local != (brief_origin == "local_reuse"):
        raise AgentRuntimeError("task definition and brief authority origins do not match")
    task, parsed = _parse_task_definition(
        payload,
        root,
        expected_task_id=args.task_id,
        test_mode=test_mode,
    )
    if not local and candidate.name != f"{args.task_id}.json":
        raise AgentRuntimeError("task definition filename does not match the task ID")
    if explicit_paths and explicit_paths != parsed:
        raise AgentRuntimeError("--owned-path does not match task definition")
    return payload, task, parsed, origin + ":" + digest, opened


def codex_permission_config(
    owned_paths: list[str],
    *,
    worktree: Path | None = None,
    git_common_dir: Path | None = None,
) -> list[str]:
    if (worktree is None) != (git_common_dir is None):
        raise CodexGitLayoutError(
            "Codex Git layout validation requires both worktree and common-dir"
        )
    if worktree is not None and git_common_dir is not None:
        validate_codex_git_layout(worktree, git_common_dir, owned_paths)
    try:
        return native_agent_broker.render_permission_profile_arguments(owned_paths)
    except native_agent_broker.ProtocolError as error:
        raise AgentRuntimeError(f"invalid Codex permission profile: {error}") from error


def validate_codex_git_layout(
    worktree: Path,
    git_common_dir: Path,
    owned_paths: list[str],
) -> tuple[str, str]:
    """Translate the broker's typed layout rejection at the runtime boundary."""
    try:
        validated_worktree, validated_common_dir = (
            native_agent_broker.validate_supported_git_layout(
                str(worktree),
                str(git_common_dir),
                owned_paths=owned_paths,
            )
        )
        return (
            str(Path(validated_worktree).resolve(strict=True)),
            str(Path(validated_common_dir).resolve(strict=True)),
        )
    except native_agent_broker.UnsupportedGitLayout as error:
        raise CodexGitLayoutError(str(error)) from error
    except native_agent_broker.ProtocolError as error:
        raise AgentRuntimeError(f"invalid Codex Git layout facts: {error}") from error


def permission_profile_spec() -> dict[str, Any]:
    """Return the installed, versioned rule used to render task profiles."""
    return {
        "schema": "sulde-codex-permission-profile-spec-v1",
        "spec_version": PERMISSION_PROFILE_SPEC_VERSION,
        "profile_name": "sulde-owned-paths",
        "codex_parent_sandbox": "danger-full-access",
        "command_boundary": "pre-tool-use-updated-input-single-seatbelt-v1",
        "shell_startup_policy": "sealed-empty-zdotdir-v1",
        "non_command_write_tools": "deny",
        "filesystem_default_write": "deny",
        "owned_path_permission": "literal-file-write-star",
        "scratch_permission": "codex-agent-native-command-scratch-subpath",
        "network_enabled": False,
        "path_rendering": "physical-canonical-exact-owned-full-clone-v4",
        "native_destructive_boundary": "global-file-write-star-deny-v1",
    }


def permission_profile_spec_sha256() -> str:
    return hashlib.sha256(_canonical_json_bytes(permission_profile_spec())).hexdigest()


def permission_profile_bytes(
    owned_paths: list[str],
    *,
    worktree: Path | None = None,
    git_common_dir: Path | None = None,
) -> bytes:
    """Bind the exact raw profile bytes enforced around provider commands."""
    if worktree is None or git_common_dir is None:
        raise AgentRuntimeError("native command profile requires canonical Git layout facts")
    validate_codex_git_layout(worktree, git_common_dir, owned_paths)
    return native_agent_broker.permission_profile_bytes(
        owned_paths, worktree=str(worktree)
    )


def codex_help_contract() -> dict[str, Any]:
    return {
        "schema": "sulde-codex-cli-help-contract-v1",
        "codex_version": AUDITED_CODEX_VERSION,
        "global_required": ["--config", "--strict-config"],
        "exec_required": [
            "--ignore-user-config",
            "--ignore-rules",
            "--dangerously-bypass-hook-trust",
            "--config",
            "--strict-config",
        ],
        "app_server_required": ["--config", "--strict-config", "--listen"],
        "initialize_protocol": "jsonl-stdio-v1",
    }


def codex_help_contract_sha256() -> str:
    return hashlib.sha256(_canonical_json_bytes(codex_help_contract())).hexdigest()


def _regular_file_sha256(path: Path, *, label: str) -> str:
    try:
        metadata = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise AgentRuntimeError(f"{label} is not a sealed regular file: {path}")
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise AgentRuntimeError(f"cannot read sealed {label}: {path}: {error}") from error


def _installed_runtime_tree_sha256(root: Path) -> str:
    if root.is_symlink() or not root.is_dir():
        raise AgentRuntimeError(f"installed runtime tree is unavailable: {root}")
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise AgentRuntimeError(f"installed runtime contains a symlink: {path}")
        relative_parts = path.relative_to(root).parts
        if "__pycache__" in relative_parts or path.suffix.casefold() == ".pyc":
            raise AgentRuntimeError(f"installed runtime contains Python bytecode: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


_NATIVE_AUTHORITY_FIELDS = {
    "schema",
    "spec_version",
    "provider",
    "production_codex_executable",
    "production_codex_resolved_executable",
    "codex_version",
    "codex_executable_sha256",
    "codex_help_contract_sha256",
    "codex_help_observation_sha256",
    "permission_profile_spec_version",
    "permission_profile_spec_sha256",
    "broker_protocol_spec_version",
    "broker_path",
    "broker_sha256",
    "agent_runtime_path",
    "agent_runtime_sha256",
    "codex_cli_contract_path",
    "codex_cli_contract_sha256",
    "runtime_generation",
    "runtime_tree_sha256",
    "authority_sha256",
}


def native_authority_sha256(authority: dict[str, Any]) -> str:
    unsigned = dict(authority)
    supplied = unsigned.pop("authority_sha256", None)
    if supplied is not None and not isinstance(supplied, str):
        raise AgentRuntimeError("installed native authority digest is invalid")
    return hashlib.sha256(_canonical_json_bytes(unsigned)).hexdigest()


def load_installed_native_authority() -> dict[str, Any]:
    """Load and independently verify the only production launch authority."""
    kb_home = Path(
        os.environ.get(
            "SULDE_KB_HOME",
            str(Path.home() / ".sulde" / "data" / "kb"),
        )
    ).expanduser()
    descriptor_path = kb_home / DEPLOYMENT_GENERATION_NAME
    try:
        raw = descriptor_path.read_bytes()
        deployment = json.loads(raw.decode("utf-8", "strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise AgentRuntimeError(
            f"installed deployment descriptor is unavailable: {descriptor_path}: {error}"
        ) from error
    if not isinstance(deployment, dict) or (
        deployment.get("schema") != DEPLOYMENT_GENERATION_SCHEMA
        or deployment.get("schema_version") != 1
        or deployment.get("provider") != "codex"
    ):
        raise AgentRuntimeError("installed deployment descriptor envelope is invalid")
    authority = deployment.get("native_runtime_authority")
    if not isinstance(authority, dict) or set(authority) != _NATIVE_AUTHORITY_FIELDS:
        raise AgentRuntimeError("installed native runtime authority fields are invalid")
    if (
        authority.get("schema") != NATIVE_AUTHORITY_SCHEMA
        or authority.get("spec_version") != NATIVE_AUTHORITY_SPEC_VERSION
        or authority.get("provider") != "codex"
        or authority.get("codex_version") != AUDITED_CODEX_VERSION
        or authority.get("codex_help_contract_sha256")
        != codex_help_contract_sha256()
        or not isinstance(authority.get("codex_help_observation_sha256"), str)
        or _SHA256_RE.fullmatch(authority["codex_help_observation_sha256"]) is None
        or authority.get("permission_profile_spec_version")
        != PERMISSION_PROFILE_SPEC_VERSION
        or authority.get("permission_profile_spec_sha256")
        != permission_profile_spec_sha256()
        or authority.get("broker_protocol_spec_version")
        != BROKER_PROTOCOL_SPEC_VERSION
        or authority.get("runtime_generation") != deployment.get("generation")
        or authority.get("runtime_tree_sha256")
        != deployment.get("runtime_tree_sha256")
        or authority.get("authority_sha256") != native_authority_sha256(authority)
        or deployment.get("native_runtime_authority_sha256")
        != authority.get("authority_sha256")
    ):
        raise AgentRuntimeError("installed native runtime authority drifted")
    runtime_root = Path(str(deployment.get("runtime_root", "")))
    current_runtime_root = Path(__file__).resolve().parents[2]
    if runtime_root != current_runtime_root:
        raise AgentRuntimeError("agent runtime is not from the installed generation")
    if _installed_runtime_tree_sha256(runtime_root) != authority["runtime_tree_sha256"]:
        raise AgentRuntimeError("installed runtime generation bytes drifted")
    expected_runtime = runtime_root / "scripts" / "kb" / "agent-runtime.py"
    expected_contract = runtime_root / "scripts" / "kb" / "codex_cli_contract.py"
    expected_broker = runtime_root / "scripts" / "kb" / "native_agent_broker.py"
    try:
        resolved_codex = bound_codex_executable(authority)
    except CodexCliContractError as error:
        raise AgentRuntimeError(str(error)) from error
    if (
        Path(authority["agent_runtime_path"]) != expected_runtime
        or Path(authority["codex_cli_contract_path"]) != expected_contract
        or Path(authority["broker_path"]) != expected_broker
        or _regular_file_sha256(expected_runtime, label="agent runtime")
        != authority["agent_runtime_sha256"]
        or _regular_file_sha256(expected_contract, label="Codex CLI contract")
        != authority["codex_cli_contract_sha256"]
        or _regular_file_sha256(expected_broker, label="native broker")
        != authority["broker_sha256"]
        or authority["production_codex_resolved_executable"] != str(resolved_codex)
        or _regular_file_sha256(resolved_codex, label="Codex executable")
        != authority["codex_executable_sha256"]
    ):
        raise AgentRuntimeError(
            "installed runtime, shared contract, broker, or Codex digest drifted"
        )
    return authority


def codex_profile_command(command: list[str], owned_paths: list[str]) -> list[str]:
    return _codex_profile_command_with_arguments(
        command,
        codex_permission_config(owned_paths),
    )


def _codex_profile_command_with_arguments(
    command: list[str],
    profile_arguments: list[str],
) -> list[str]:
    result = list(command)
    if "--sandbox" in result:
        index = result.index("--sandbox")
        del result[index : index + 2]
    result = [
        item
        for item in result
        if item not in {"--ignore-user-config", "--strict-config"}
    ]
    if any("sandbox_mode" in item for item in result):
        raise AgentRuntimeError("permission profile cannot be combined with sandbox_mode")
    if len(result) < 2 or result[1] != "exec":
        raise AgentRuntimeError("Codex task command has an unsupported CLI shape")
    result[2:2] = [
        "--ignore-user-config",
        "--strict-config",
        *profile_arguments,
    ]
    return result


def _codex_app_server_initialize(
    command: list[str],
    *,
    initialize_request: str,
    initialized_notification: str,
    cwd: Path | None,
    environment: dict[str, str],
    timeout: float = 10,
) -> subprocess.CompletedProcess[str]:
    """Perform the app-server initialize exchange without racing stdin EOF."""
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=cwd,
        env=environment,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None
    stdout_lines: list[str] = []
    stderr_parts: list[str] = []
    responses: Queue[str | None] = Queue()

    def read_stdout() -> None:
        try:
            for line in iter(process.stdout.readline, ""):
                stdout_lines.append(line)
                responses.put(line)
        finally:
            responses.put(None)

    def read_stderr() -> None:
        stderr_parts.append(process.stderr.read())

    stdout_reader = threading.Thread(target=read_stdout, daemon=True)
    stderr_reader = threading.Thread(target=read_stderr, daemon=True)
    stdout_reader.start()
    stderr_reader.start()
    deadline = time.monotonic() + timeout
    initialized = False
    timed_out = False
    try:
        process.stdin.write(initialize_request)
        process.stdin.flush()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            try:
                line = responses.get(timeout=min(0.1, remaining))
            except Empty:
                if process.poll() is not None:
                    break
                continue
            if line is None:
                break
            try:
                response = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (
                isinstance(response, dict)
                and response.get("id") == 0
                and isinstance(response.get("result"), dict)
                and "error" not in response
            ):
                initialized = True
                process.stdin.write(initialized_notification)
                process.stdin.flush()
                break
    except (BrokenPipeError, OSError):
        pass
    finally:
        try:
            process.stdin.close()
        except OSError:
            pass

    remaining = max(0.0, deadline - time.monotonic())
    try:
        process.wait(timeout=remaining)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.terminate()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1)
    stdout_reader.join(timeout=1)
    stderr_reader.join(timeout=1)
    stdout = "".join(stdout_lines)
    stderr = "".join(stderr_parts)
    process.stdout.close()
    process.stderr.close()
    if timed_out and not initialized:
        raise subprocess.TimeoutExpired(
            command,
            timeout,
            output=stdout,
            stderr=stderr,
        )
    return subprocess.CompletedProcess(
        command,
        int(process.returncode if process.returncode is not None else -1),
        stdout,
        stderr,
    )


def codex_capability_preflight(
    executable: str,
    profile_arguments: list[str],
    *,
    test_mode: bool,
    planned_command: list[str] | None = None,
    worktree: Path | None = None,
    installed_authority: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Reject unsupported profile clients before the provider receives a prompt."""
    if test_mode:
        return {
            "supported": True,
            "evidence": "test-fixture-profile-construction",
            "execution_prevented": False,
        }
    if installed_authority is None:
        installed_authority = load_installed_native_authority()
    try:
        bound_executable = bound_codex_executable(installed_authority)
    except CodexCliContractError as error:
        raise AgentRuntimeError(str(error)) from error
    if executable != str(bound_executable):
        raise AgentRuntimeError(
            f"Codex executable is not the installation-bound audited {AUDITED_CODEX_VERSION} target"
        )
    try:
        probe_spec = codex_probe_spec(os.environ)
        version = subprocess.run(
            [executable, "--version"],
            input=probe_spec.stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
            env=probe_spec.environment,
        )
        # Codex may emit a non-fatal PATH-alias warning on stderr when the
        # enclosing sandbox cannot update its alias directory.  Executable
        # identity is independently digest/path bound; version identity is the
        # exact stdout contract and must not be contaminated by diagnostics.
        version_surface = successful_version_identity(
            version.returncode, version.stdout
        )
        if version_surface != AUDITED_CODEX_VERSION:
            raise AgentRuntimeError(
                f"Codex CLI version is not exactly audited {AUDITED_CODEX_VERSION}"
            )
        global_help = subprocess.run(
            [executable, "--help"],
            input=probe_spec.stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
            env=probe_spec.environment,
        )
        exec_help = subprocess.run(
            [executable, "exec", "--help"],
            input=probe_spec.stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
            env=probe_spec.environment,
        )
        app_help = subprocess.run(
            [executable, "app-server", "--help"],
            input=probe_spec.stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
            env=probe_spec.environment,
        )
        try:
            canonical_surfaces, help_observation_sha256 = (
                canonical_codex_help_observation(
                    (
                        (
                            global_help.returncode,
                            global_help.stdout,
                            global_help.stderr,
                        ),
                        (exec_help.returncode, exec_help.stdout, exec_help.stderr),
                        (app_help.returncode, app_help.stdout, app_help.stderr),
                    )
                )
            )
        except CodexCliContractError as error:
            message = "Codex CLI help surface cannot express the required launch"
            if installed_authority is not None:
                message = "Codex CLI help bytes drifted from installed authority"
            raise AgentRuntimeError(message) from error
        global_surface, exec_surface, app_surface = (
            surface.decode("utf-8", "strict") for surface in canonical_surfaces
        )
        if (
            "--config" not in global_surface
            or "--strict-config" not in global_surface
            or "--ignore-user-config" not in exec_surface
            or "--ignore-rules" not in exec_surface
            or "--dangerously-bypass-hook-trust" not in exec_surface
            or "--config" not in exec_surface
            or "--strict-config" not in exec_surface
            or "--config" not in app_surface
            or "--strict-config" not in app_surface
            or "--listen" not in app_surface
        ):
            raise AgentRuntimeError("Codex CLI help surface cannot express the required launch")
        if (
            installed_authority is not None
            and help_observation_sha256
            != installed_authority.get("codex_help_observation_sha256")
        ):
            raise AgentRuntimeError("Codex CLI help bytes drifted from installed authority")
        base_command = planned_command or [
            executable,
            "exec",
            "--ignore-user-config",
            "--ignore-rules",
            "--ephemeral",
            "--skip-git-repo-check",
            "--json",
            "-",
        ]
        exact_exec = _codex_profile_command_with_arguments(
            base_command,
            profile_arguments,
        )
        if exact_exec[-1] != "-":
            raise AgentRuntimeError("Codex task command has no stdin prompt boundary")
        exec_probe_command = [
            *exact_exec[:-1],
            "--dangerously-bypass-hook-trust",
            "-c",
            (
                'hooks.PreToolUse=[{matcher=".*",hooks=['
                '{type="command",command="/usr/bin/true",timeout=1}]}]'
            ),
            "--help",
        ]
        probe = subprocess.run(
            exec_probe_command,
            input=probe_spec.stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
            cwd=worktree,
            env=probe_spec.environment,
        )
        if probe.returncode != 0:
            detail = (probe.stderr or probe.stdout).strip().splitlines()[:1]
            raise AgentRuntimeError(
                "Codex rejected the exact permission profile before launch"
                + (f": {detail[0]}" if detail else "")
            )
        initialize_request = (
            json.dumps(
                {
                    "method": "initialize",
                    "id": 0,
                    "params": {
                        "clientInfo": {
                            "name": "sulde_runtime_preflight",
                            "title": "Sulde runtime preflight",
                            "version": "1",
                        }
                    },
                },
                separators=(",", ":"),
            )
            + "\n"
        )
        initialized_notification = (
            json.dumps(
                {"method": "initialized", "params": {}},
                separators=(",", ":"),
            )
            + "\n"
        )
        bootstrap_command = [
            executable,
            "app-server",
            "--strict-config",
            *profile_arguments,
            "--listen",
            "stdio://",
        ]
        initialize_attempts: list[dict[str, Any]] = []
        initialized = False
        with tempfile.TemporaryDirectory(prefix="sulde-codex-preflight-") as parent:
            for attempt in range(1, CODEX_INITIALIZE_MAX_ATTEMPTS + 1):
                codex_home = Path(parent) / f"attempt-{attempt}"
                codex_home.mkdir(mode=0o700)
                probe_environment = os.environ.copy()
                probe_environment["CODEX_HOME"] = str(codex_home)
                try:
                    bootstrap = _codex_app_server_initialize(
                        bootstrap_command,
                        initialize_request=initialize_request,
                        initialized_notification=initialized_notification,
                        timeout=10,
                        cwd=worktree,
                        environment=probe_environment,
                    )
                    response_initialized = False
                    for line in bootstrap.stdout.splitlines():
                        try:
                            response = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if (
                            isinstance(response, dict)
                            and response.get("id") == 0
                            and isinstance(response.get("result"), dict)
                            and "error" not in response
                        ):
                            response_initialized = True
                            break
                    initialize_attempts.append(
                        {
                            "attempt": attempt,
                            "returncode": bootstrap.returncode,
                            "initialized": response_initialized,
                            "stdout_sha256": hashlib.sha256(
                                bootstrap.stdout.encode("utf-8", "strict")
                            ).hexdigest(),
                            "stderr_sha256": hashlib.sha256(
                                bootstrap.stderr.encode("utf-8", "strict")
                            ).hexdigest(),
                        }
                    )
                    if bootstrap.returncode == 0 and response_initialized:
                        initialized = True
                        break
                except subprocess.TimeoutExpired:
                    initialize_attempts.append(
                        {
                            "attempt": attempt,
                            "returncode": None,
                            "initialized": False,
                            "stdout_sha256": hashlib.sha256(b"").hexdigest(),
                            "stderr_sha256": hashlib.sha256(b"").hexdigest(),
                            "timeout": True,
                        }
                    )
        if not initialized:
            raise CodexPreflightError(
                "Codex app-server bootstrap/IPC capability is unavailable; "
                "bounded initialize attempts="
                + json.dumps(
                    initialize_attempts,
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                initialize_attempts,
            )
    except subprocess.TimeoutExpired as error:
        raise AgentRuntimeError("Codex capability preflight timed out") from error
    return {
        "supported": True,
        "evidence": (
            f"{AUDITED_CODEX_VERSION.replace(' ', '-')}-real-help+strict-profile+hook-parse+"
            "app-server-initialize(exec-local-ignore-user-config;"
            "subcommand-local-strict-config-and-config-overrides)"
        ),
        "execution_prevented": False,
        "help_observation_sha256": help_observation_sha256,
        "initialize_attempts": initialize_attempts,
    }


def _broker_blob_summary(raw: bytes) -> dict[str, Any]:
    return {
        "present": bool(raw),
        "raw_byte_count": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _broker_jsonl_summary(path: Path) -> dict[str, Any]:
    raw = path.read_bytes() if path.is_file() else b""
    lines = raw.splitlines()
    valid_count = 0
    terminals: list[str] = []
    for raw_line in lines:
        try:
            value = json.loads(raw_line.decode("utf-8", "strict"))
        except (UnicodeError, json.JSONDecodeError):
            continue
        valid_count += 1
        if isinstance(value, dict) and value.get("type") in {
            "turn.completed",
            "turn.failed",
        }:
            terminals.append(value["type"])
    if len(terminals) > 1:
        raise AgentRuntimeError(
            "native broker JSONL terminal event count is contradictory"
        )
    return {
        "line_count": len(lines),
        "valid_json_line_count": valid_count,
        "terminal_event": terminals[0] if terminals else "none",
        "terminal_event_count": len(terminals),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _run_ledger_local_interruption_evidence(
    path: Path,
    *,
    run_id: str,
) -> dict[str, Any]:
    raw = path.read_bytes()
    rows: list[dict[str, Any]] = []
    for line in raw.splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise AgentRuntimeError("local interruption ledger is invalid JSONL") from error
        if not isinstance(row, dict):
            raise AgentRuntimeError("local interruption ledger row is invalid")
        rows.append(row)
    matching = [row for row in rows if row.get("run_id") == run_id]
    typed: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for index, row in enumerate(matching):
        typed.setdefault(str(row.get("type") or ""), []).append((index, row))
    required = (
        "execution.interrupt_requested",
        "execution.result",
        "execution.disposed",
    )
    if any(len(typed.get(event_type, [])) != 1 for event_type in required):
        raise AgentRuntimeError(
            "zero provider terminal requires one matching interrupt/result/disposed"
        )
    interrupt_index, interrupt = typed[required[0]][0]
    result_index, result = typed[required[1]][0]
    disposed_index, disposed = typed[required[2]][0]
    interrupt_reason = interrupt.get("reason")
    result_reason = result.get("stop_reason")
    if (
        native_agent_broker.local_interruption_stop_reason(interrupt_reason)
        != result_reason
        or type(result_reason) is not str
        or not (interrupt_index < result_index < disposed_index)
        or disposed.get("quiescent") is not True
        or type(result.get("returncode")) is not int
    ):
        raise AgentRuntimeError(
            "local interruption evidence is mismatched, out of order, or not quiescent"
        )
    return {
        "schema": "sulde-local-interruption-evidence-v1",
        "run_id": run_id,
        "interrupt_reason": interrupt_reason,
        "result_stop_reason": result_reason,
        "result_returncode": result["returncode"],
        "interrupt_event_index": interrupt_index,
        "result_event_index": result_index,
        "disposed_event_index": disposed_index,
        "quiescent": True,
        "result_before_disposed": True,
        "run_ledger_sha256": hashlib.sha256(raw).hexdigest(),
    }


def _persist_codex_preflight_failure(
    state: Path,
    slug: str,
    error: CodexPreflightError,
) -> dict[str, Any]:
    evidence = {
        "schema": "sulde-codex-preflight-evidence-v1",
        "supported": False,
        "provider_launch_prevented": True,
        "initialize_attempts": error.initialize_attempts,
        "failure_reason": "app_server_initialize_exhausted",
    }
    path = state / f"{slug}.preflight.json"
    encoded = (
        json.dumps(
            evidence,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    atomic_write(path, encoded)
    if path.read_text(encoding="utf-8", errors="strict") != encoded:
        raise AgentRuntimeError("Codex preflight evidence readback drifted")
    return evidence


def run_task(args: argparse.Namespace) -> int:
    validate_slug(args.slug)
    root = validated_root(args.worktree)
    test_mode = os.environ.get("SULDE_TEST_MODE") == "1"
    control_root = coordinator_control_root(
        root,
        args.control_root,
        test_mode=test_mode,
    )
    brief_payload, brief_text, brief_origin, brief_source = read_brief_authority(
        root,
        args.brief,
        expected_sha256=args.brief_sha256,
        control_root=control_root,
        test_mode=test_mode,
    )
    brief_authority_sha256 = hashlib.sha256(brief_payload).hexdigest()
    external_brief_relative_identity = (
        brief_source.relative_to(control_root).as_posix()
        if brief_origin == "external_import"
        else None
    )
    (
        task_payload,
        task_definition,
        owned_paths,
        task_origin,
        task_source,
    ) = read_task_authority(
        args,
        root,
        control_root,
        brief_origin=brief_origin,
        test_mode=test_mode,
    )
    binding_path = root / STATE_DIRECTORY / f"{args.slug}.task-binding.json"
    if brief_origin == "local_reuse":
        if not os.path.lexists(binding_path):
            if not test_mode or args.task_definition is not None:
                raise AgentRuntimeError(
                    "local retry requires the frozen execution binding artifact"
                )
            brief_relative_identity = f"briefs/{brief_source.name}"
            binding_payload = b""
        else:
            binding_payload, _binding_file_digest, _ = safe_control_read(
                binding_path,
                allowed_parent=root / STATE_DIRECTORY,
                expected_sha256=None,
                local_static_copy=True,
            )
            frozen_binding, _frozen_binding_digest = (
                parse_execution_binding_artifact(binding_payload)
            )
            brief_relative_identity = _canonical_brief_relative_identity(
                frozen_binding.get("brief", {}).get("relative_path")
                if isinstance(frozen_binding.get("brief"), dict)
                else None
            )
    else:
        if external_brief_relative_identity is None:
            raise AgentRuntimeError("external brief relative identity is unavailable")
        brief_relative_identity = external_brief_relative_identity
        binding_payload = b""
    binding = execution_binding_envelope(
        task_payload=task_payload,
        task=task_definition,
        brief_relative_path=brief_relative_identity,
        brief_sha256=brief_authority_sha256,
        root=root,
        owned_paths=owned_paths,
        test_mode=test_mode,
    )
    expected_binding_payload, execution_binding_sha256 = (
        execution_binding_artifact(binding)
    )
    if binding_payload:
        validate_execution_binding(binding_payload, expected=binding)
    else:
        binding_payload = expected_binding_payload
    requested = args.provider or os.environ.get("SULDE_AGENT_PROVIDER")
    configured_provider = (
        requested
        or os.environ.get("SULDE_LLM_PROVIDER")
        or os.environ.get("SULDE_HOST_PROVIDER")
        or "auto"
    ).strip().lower()
    codex_host_only = configured_provider == "auto" and any(
        os.environ.get(name) for name in ("CODEX_THREAD_ID", "CODEX_CI")
    ) and not any(
        os.environ.get(name)
        for name in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_SESSION_ID")
    )
    if not test_mode and (configured_provider == "codex" or codex_host_only):
        # Do not even resolve a caller projection or PATH alias in production.
        provider, selected_executable = "codex", ""
    else:
        provider, selected_executable = select_provider(requested)
    executable = selected_executable
    installed_authority: dict[str, Any] | None = None
    broker_request: dict[str, Any] | None = None
    broker_probe_evidence: dict[str, Any] | None = None
    broker_launch_plan: dict[str, Any] | None = None
    broker_frozen: dict[str, Any] | None = None
    broker_terminal: dict[str, Any] | None = None
    native_zdotdir: str | None = None
    if provider == "codex" and not test_mode:
        installed_authority = load_installed_native_authority()
        executable = str(installed_authority["production_codex_executable"])
    planned_report = root / STATE_DIRECTORY / f"{args.slug}.last.md"
    command = task_command(
        provider,
        executable,
        worktree=root,
        report=planned_report,
        effort=args.effort,
    )
    state = state_directory(root)
    profile_preflight = {
        "supported": provider != "codex",
        "evidence": "provider-does-not-use-codex-profiles",
        "execution_prevented": False,
    }
    if provider == "codex":
        profile_git_common = (
            None
            if test_mode and not os.path.lexists(root / ".git")
            else Path(_git_common_directory(root, test_mode=test_mode))
        )
        profile_arguments = codex_permission_config(
            owned_paths,
            worktree=root if profile_git_common is not None else None,
            git_common_dir=profile_git_common,
        )
        try:
            profile_preflight = codex_capability_preflight(
                executable,
                profile_arguments,
                test_mode=test_mode,
                planned_command=command,
                worktree=root,
                installed_authority=installed_authority,
            )
        except CodexPreflightError as error:
            _persist_codex_preflight_failure(state, args.slug, error)
            raise
        command = _codex_profile_command_with_arguments(command, profile_arguments)
    if provider == "codex" and not test_mode:
        if installed_authority is None:
            raise AgentRuntimeError("installed native runtime authority is missing")
        git_common_dir = Path(_git_common_directory(root, test_mode=test_mode))
        native_scratch = Path(
            native_agent_broker.native_command_scratch_path(str(root))
        )
        if os.path.lexists(native_scratch):
            if native_scratch.is_symlink() or not native_scratch.is_dir():
                raise AgentRuntimeError("native command scratch is not a real directory")
        else:
            native_scratch.mkdir(mode=0o700)
        native_scratch.chmod(0o700)
        native_startup = state / ".native-shell-startup"
        if os.path.lexists(native_startup):
            if native_startup.is_symlink() or not native_startup.is_dir():
                raise AgentRuntimeError("native shell startup path is not a real directory")
            if any(native_startup.iterdir()):
                raise AgentRuntimeError("native shell startup path must remain empty")
        else:
            native_startup.mkdir(mode=0o500)
        native_startup.chmod(0o500)
        native_zdotdir = str(native_startup)
        profile_raw = permission_profile_bytes(
            owned_paths,
            worktree=root,
            git_common_dir=git_common_dir,
        )
        broker_frozen = {
            "task_id": task_definition["task_id"],
            "base_commit": task_definition["base_commit"],
            "task_definition_sha256": hashlib.sha256(task_payload).hexdigest(),
            "brief_sha256": brief_authority_sha256,
            "worktree_canonical_path": str(root),
            "git_common_dir_canonical_path": str(git_common_dir),
            "owned_paths": owned_paths,
            "report_relative_path": f"{STATE_DIRECTORY}/{args.slug}.last.md",
            "model_reasoning_effort": args.effort,
            "codex_executable": installed_authority[
                "production_codex_executable"
            ],
            "codex_version": installed_authority["codex_version"],
            "codex_executable_sha256": installed_authority[
                "codex_executable_sha256"
            ],
            "broker_generation": installed_authority[
                "broker_protocol_spec_version"
            ],
            "broker_sha256": installed_authority["broker_sha256"],
            "provider_generation": installed_authority["spec_version"],
            "permission_profile_name": "sulde-owned-paths",
            "permission_profile_bytes_sha256": hashlib.sha256(profile_raw).hexdigest(),
            "permission_profile_spec_sha256": installed_authority[
                "permission_profile_spec_sha256"
            ],
            "installed_descriptor_sha256": installed_authority[
                "authority_sha256"
            ],
            "runtime_generation": installed_authority["runtime_generation"],
            "runtime_tree_sha256": installed_authority["runtime_tree_sha256"],
            "agent_runtime_sha256": installed_authority["agent_runtime_sha256"],
            "nonce": hashlib.sha256(os.urandom(32)).hexdigest(),
        }
        try:
            broker_request = native_agent_broker.build_request(broker_frozen)
            broker_probe_evidence = native_agent_broker.execute_native_profile_probe(
                broker_request,
                broker_frozen,
                evidence_path=str(state / f"{args.slug}.native-probe.json"),
            )
            probe_receipt = broker_probe_evidence["probe_receipt"]
            broker_launch_plan = native_agent_broker.build_launch_plan(
                broker_request,
                probe_receipt,
                broker_frozen,
            )
            command = native_agent_broker.validate_provider_command(
                broker_launch_plan["command"], broker_request, broker_frozen
            )
        except native_agent_broker.ProtocolError as error:
            raise AgentRuntimeError(f"native broker failed closed: {error}") from error
    brief = install_static_brief(
        state,
        args.slug,
        brief_payload,
        source=brief_source,
    )
    frozen_task = install_static_control(
        state,
        f"{args.slug}.task.json",
        task_payload,
        source=task_source,
    )
    frozen_binding = install_static_control(
        state,
        f"{args.slug}.task-binding.json",
        binding_payload,
        source=binding_path if binding_path.exists() else task_source,
    )
    worker_report_contract = report_contract_for_brief(brief_text)
    worker_report_contract["execution_binding_sha256"] = (
        execution_binding_sha256
    )
    worker_report_contract["enforce_current_execution_binding"] = (
        not test_mode
    )
    legacy_lock = state / f"{args.slug}.lock.d"
    if legacy_lock.exists():
        raise AgentRuntimeError(
            f"legacy task lock requires human inspection before migration: {legacy_lock}"
        )
    lock = state / f"{args.slug}.lock"
    lock_handle = lock.open("a+", encoding="utf-8")
    try:
        lock_exclusive_nonblocking(lock_handle)
    except BlockingIOError as error:
        lock_handle.close()
        raise AgentRuntimeError(f"task lock is already held: {lock}") from error

    report = state / f"{args.slug}.last.md"
    events = state / f"{args.slug}.events.jsonl"
    events_cursor = state / f"{args.slug}.events.cursor.json"
    stderr_path = state / f"{args.slug}.stderr.log"
    status_path = state / f"{args.slug}.status"
    baseline_path = state / f"{args.slug}.baseline"
    run_ledger_path = state / f"{args.slug}.run.jsonl"
    started = time.monotonic()
    status = "failed"
    returncode = 2
    observed_status = "running"
    phase_heartbeat: PhaseHeartbeat | None = None
    guardian: GuardianSession | None = None
    try:
        recovered_baseline: str | None = None
        if run_ledger_path.is_file():
            try:
                verify_run_ledger_binding(
                    run_ledger_path,
                    execution_binding_sha256,
                )
                recovered_run = recover_incomplete_run(run_ledger_path)
            except ExecutionBackendError as error:
                atomic_write(
                    status_path,
                    "status=awaiting_human rc=2 recovery=inconclusive "
                    f"reason=invalid_run_ledger last={report}\n",
                )
                with stderr_path.open("a", encoding="utf-8") as handle:
                    handle.write(f"ExecutionBackendError: {error}\n")
                print(
                    f"SULDE AGENT RECOVERY BLOCKED slug={args.slug}: {error}",
                    file=sys.stderr,
                )
                return 1
            if recovered_run is not None and not recovered_run.terminal:
                atomic_write(
                    status_path,
                    "status=awaiting_human rc=2 recovery=unknown "
                    f"run={recovered_run.run_id} reason=process_tree_observable "
                    f"last={report}\n",
                )
                print(
                    "SULDE AGENT RECOVERY BLOCKED "
                    f"slug={args.slug}: previous process tree remains observable",
                    file=sys.stderr,
                )
                return 1
            if (
                recovered_run is not None
                and recovered_run.result is not None
                and recovered_run.result.get("recovered_from_crash") is True
                and baseline_path.is_file()
            ):
                recovered_baseline = baseline_path.read_text(encoding="utf-8")
        archive_previous(state, args.slug)
        baseline_text = (
            recovered_baseline
            if recovered_baseline is not None
            else json.dumps(snapshot(root), ensure_ascii=False, sort_keys=True) + "\n"
        )
        atomic_write(baseline_path, baseline_text)
        try:
            frozen_worktree_snapshot = json.loads(baseline_text)
        except json.JSONDecodeError as error:
            raise AgentRuntimeError("frozen worktree baseline is invalid JSON") from error
        if not isinstance(frozen_worktree_snapshot, dict) or not all(
            isinstance(path, str) and isinstance(digest, str)
            for path, digest in frozen_worktree_snapshot.items()
        ):
            raise AgentRuntimeError("frozen worktree baseline has invalid entries")
        # Local retry/reuse is revalidated after archive and immediately before
        # any provider selection or launch.
        brief_payload, brief_digest, _ = safe_control_read(
            brief,
            allowed_parent=state,
            expected_sha256=hashlib.sha256(brief_text.encode("utf-8")).hexdigest(),
            local_static_copy=True,
        )
        brief_text = brief_payload.decode("utf-8")
        checked_task, task_digest, _ = safe_control_read(
            frozen_task,
            allowed_parent=state,
            expected_sha256=hashlib.sha256(task_payload).hexdigest(),
            local_static_copy=True,
        )
        if checked_task != task_payload:
            raise AgentRuntimeError("frozen task definition bytes changed")
        checked_binding, binding_artifact_digest, _ = safe_control_read(
            frozen_binding,
            allowed_parent=state,
            expected_sha256=hashlib.sha256(binding_payload).hexdigest(),
            local_static_copy=True,
        )
        checked_task_definition, checked_owned_paths = _parse_task_definition(
            checked_task,
            root,
            expected_task_id=args.task_id,
            test_mode=test_mode,
        )
        checked_binding_envelope = execution_binding_envelope(
            task_payload=checked_task,
            task=checked_task_definition,
            brief_relative_path=brief_relative_identity,
            brief_sha256=brief_digest,
            root=root,
            owned_paths=checked_owned_paths,
            test_mode=test_mode,
        )
        if (
            validate_execution_binding(
                checked_binding,
                expected=checked_binding_envelope,
            )
            != execution_binding_sha256
        ):
            raise AgentRuntimeError("execution binding digest changed during retry")
        resume_context = load_resume_context(args.resume_context, state, args.slug)
        critic_scope = None
        if args.semantic_critic:
            critic_baseline = _critic_baseline_snapshot(
                root,
                base_commit=str(checked_task_definition["base_commit"]),
                owned_paths=owned_paths,
                frozen_snapshot=frozen_worktree_snapshot,
                test_mode=test_mode,
            )
            critic_scope = _managed_critic_scope(
                task=checked_task_definition,
                owned_paths=owned_paths,
                baseline_snapshot=critic_baseline,
                execution_binding_sha256=execution_binding_sha256,
            )
        intent_path = prepare_intent_contract(
            state,
            args.slug,
            brief_text,
            root,
            mode=args.guardian_mode,
            explicit=args.intent_contract,
            semantic_critic=args.semantic_critic,
            owned_paths=owned_paths,
            execution_binding_sha256=execution_binding_sha256,
            critic_scope=critic_scope,
        )
        guardian = GuardianSession(
            intent_path,
            authoritative_memory=True,
            session_id=f"managed:{load_contract(intent_path)['intent_id']}",
        )
        if resume_context and any(
            row.get("provider") != provider
            for row in resume_context.get("interventions", [])
            if isinstance(row, dict)
        ):
            raise AgentRuntimeError(
                "selected provider does not match the adjudicated effect attempt"
            )
        guardian.provider = provider
        prompt = execution_prompt(
            brief_text,
            root,
            provider=provider,
            intent_path=intent_path,
            intent_id=guardian.contract["intent_id"],
            resume_context=resume_context,
        )
        initial_side_effects = observable_worktree_snapshot(root)
        static_controls = [baseline_path, brief, frozen_task, frozen_binding]
        if args.resume_context is not None:
            static_controls.append(args.resume_context.expanduser().resolve())
        control_before = static_control_snapshot(static_controls)
        backend = ExecutionBackend()
        initial_correction_store, initial_correction_projection = (
            correction_authoritative_snapshot(intent_path)
        )
        run_result = None
        cleanup_result = None
        returncode = 2
        final_message = ""
        monitor_terminal_error: IntentGuardianError | None = None
        broker_started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        provider_pid: int | None = None
        stderr_fsync_completed = False
        with stderr_path.open("wb") as stderr_handle:
            handle = backend.start(
                command,
                cwd=root,
                ledger_path=run_ledger_path,
                provider=provider,
                stdout=subprocess.PIPE,
                stderr=stderr_handle,
                environment={
                    **os.environ,
                    **({"ZDOTDIR": native_zdotdir} if native_zdotdir else {}),
                    "SULDE_INTENT_CONTRACT": str(intent_path),
                    "SULDE_GUARDIAN_STREAM_OWNER": "1",
                    "SULDE_GUARDIAN_STREAM_PROVIDER": provider,
                },
            )
            provider_pid = handle.process.pid
            phase_heartbeat = PhaseHeartbeat(
                state / f"{args.slug}.heartbeat.json",
                state / f"{args.slug}.heartbeat.jsonl",
                run_id=handle.id,
            )
            phase_heartbeat.publish(
                "provider_starting",
                expires_after_seconds=5,
                default_action="interrupt_and_fail_closed",
            )
            try:
                project_run_ledger_binding(
                    run_ledger_path,
                    run_id=handle.id,
                    binding_sha256=execution_binding_sha256,
                )
                (
                    returncode,
                    observed_status,
                    final_message,
                    monitor_terminal_error,
                ) = monitor_process(
                    handle,
                    prompt=prompt,
                    events_path=events,
                    cursor_path=events_cursor,
                    cursor_generation=hashlib.sha256(
                        (
                            provider
                            + "\0"
                            + str(guardian.contract.get("task_epoch") or "")
                        ).encode("utf-8")
                    ).hexdigest(),
                    guardian=guardian,
                    root=root,
                    initial_side_effects=initial_side_effects,
                    initial_correction_store=initial_correction_store,
                    initial_correction_sequence=int(
                        initial_correction_projection["sequence"]
                    ),
                    timeout=args.timeout,
                    heartbeat=phase_heartbeat,
                    require_reader_termination=(provider == "codex" and not test_mode),
                )
                run_result, final_message = _settle_provider_result(
                    handle,
                    provider=provider,
                    test_mode=test_mode,
                    root=root,
                    report=report,
                    observed_status=observed_status,
                    returncode=returncode,
                    streamed_final_message=final_message,
                )
                phase_heartbeat.publish(
                    "result_persisted",
                    expires_after_seconds=5,
                    default_action="interrupt_and_fail_closed",
                    reason=run_result.stop_reason,
                )
                if observed_status in {"timeout", "paused", "awaiting_human"}:
                    status = observed_status
                if (
                    monitor_terminal_error is not None
                    and observed_status != "awaiting_human"
                ):
                    raise monitor_terminal_error
            except Exception:
                if handle.process.poll() is None:
                    phase_heartbeat.publish(
                        "interrupt_requested",
                        expires_after_seconds=5,
                        default_action="interrupt_and_fail_closed",
                        reason="monitor_error",
                    )
                    handle.interrupt("monitor_error")
                if handle.process.poll() is not None and handle.result is None:
                    run_result = handle.settle(stop_reason="error")
                    phase_heartbeat.publish(
                        "result_persisted",
                        expires_after_seconds=5,
                        default_action="interrupt_and_fail_closed",
                        reason=run_result.stop_reason,
                    )
                raise
            finally:
                if handle.result is None and handle.process.poll() is None:
                    phase_heartbeat.publish(
                        "interrupt_requested",
                        expires_after_seconds=5,
                        default_action="interrupt_and_fail_closed",
                        reason="unsettled_finalizer",
                    )
                    handle.interrupt("unsettled_finalizer")
                if handle.result is None and handle.process.poll() is not None:
                    run_result = handle.settle(stop_reason="error")
                    phase_heartbeat.publish(
                        "result_persisted",
                        expires_after_seconds=5,
                        default_action="interrupt_and_fail_closed",
                        reason=run_result.stop_reason,
                    )
                if handle.result is None:
                    raise ExecutionBackendError(
                        "refusing to persist disposed without execution.result"
                    )
                cleanup_result = handle.dispose()
                phase_heartbeat.publish(
                    "disposed",
                    expires_after_seconds=30,
                    default_action="observe",
                    reason=("quiescent" if cleanup_result.quiescent else "not_quiescent"),
                )
                if (
                    observed_status in {"timeout", "paused", "awaiting_human"}
                    and stderr_handle.tell() == 0
                ):
                    stderr_handle.write(
                        (
                            "managed local interruption: " + observed_status + "\n"
                        ).encode("utf-8", "strict")
                    )
                stderr_handle.flush()
                os.fsync(stderr_handle.fileno())
                stderr_fsync_completed = True
        if provider == "codex" and not test_mode:
            if (
                broker_request is None
                or broker_frozen is None
                or broker_probe_evidence is None
                or broker_launch_plan is None
                or run_result is None
                or cleanup_result is None
                or provider_pid is None
            ):
                raise AgentRuntimeError("native broker terminal authority is incomplete")
            stderr_raw = stderr_path.read_bytes()
            jsonl_summary = _broker_jsonl_summary(events)
            production_local_interruption = observed_status in {
                "timeout",
                "paused",
                "awaiting_human",
            }
            if production_local_interruption:
                report_raw = b""
                output_raw = b""
                local_interruption_evidence = (
                    _run_ledger_local_interruption_evidence(
                        run_ledger_path,
                        run_id=run_result.run_id,
                    )
                )
                terminal_status = "interrupted"
                termination_domain = "local_interruption"
                termination_reason = run_result.stop_reason
            else:
                canonical_report_raw = _close_canonical_worker_report_authority(
                    root,
                    owned_paths,
                    final_message,
                    report,
                )
                report_raw = canonical_report_raw
                output_raw = canonical_report_raw
                local_interruption_evidence = None
                terminal_status = "succeeded" if returncode == 0 else "failed"
                termination_domain = "provider_natural"
                termination_reason = (
                    "provider_completed"
                    if terminal_status == "succeeded"
                    else "provider_failed"
                )
            broker_terminal = native_agent_broker.build_provider_receipt(
                broker_request,
                broker_probe_evidence["probe_receipt"],
                broker_launch_plan,
                broker_frozen,
                started_at=broker_started_at,
                terminated_at=time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                ),
                provider_pid=provider_pid,
                provider_run_id=run_result.run_id,
                terminal_status=terminal_status,
                termination_domain=termination_domain,
                termination_reason=termination_reason,
                local_interruption_evidence=local_interruption_evidence,
                exit_code=returncode,
                quiescence_confirmed=cleanup_result.quiescent,
                stderr_path=f"{STATE_DIRECTORY}/{args.slug}.stderr.log",
                stderr_raw_bytes=stderr_raw,
                stderr_fsync_completed=stderr_fsync_completed,
                jsonl_summary=jsonl_summary,
                output_summary=_broker_blob_summary(output_raw),
                report_summary=_broker_blob_summary(report_raw),
                observed_denial=False,
                execution_prevented=False,
            )
            native_agent_broker.validate_provider_receipt(
                broker_terminal,
                broker_request,
                broker_probe_evidence["probe_receipt"],
                broker_launch_plan,
                broker_frozen,
            )
            atomic_write(
                state / f"{args.slug}.native-receipt.json",
                native_agent_broker.canonical_json_bytes(broker_terminal).decode(
                    "utf-8", "strict"
                )
                + "\n",
            )
            phase_heartbeat.publish(
                "receipt_persisted",
                expires_after_seconds=30,
                default_action="observe",
                reason=broker_terminal["terminal_status"],
            )
        integrity_breach = False
        try:
            safe_control_read(
                brief,
                allowed_parent=state,
                expected_sha256=brief_digest,
                local_static_copy=True,
            )
            safe_control_read(
                frozen_task,
                allowed_parent=state,
                expected_sha256=task_digest,
                local_static_copy=True,
            )
            safe_control_read(
                frozen_binding,
                allowed_parent=state,
                expected_sha256=binding_artifact_digest,
                local_static_copy=True,
            )
            controls_safe = True
        except AgentRuntimeError:
            controls_safe = False
        if not controls_safe or not static_controls_unchanged(static_controls, control_before):
            _record_managed_integrity_breach(
                guardian,
                "provider modified a frozen control or execution baseline"
            )
            integrity_breach = True
        elif not guardian.integrity_ok():
            _record_managed_integrity_breach(
                guardian,
                "provider modified the intent contract or guardian audit log"
            )
            integrity_breach = True
        if integrity_breach:
            status = "paused"
        finalized = guardian.finalize_lane(
            critic_runner=(
                _managed_critic_runner(critic_scope, test_mode=test_mode)
                if critic_scope is not None
                else None
            )
        )
        if finalized.get("critic", {}).get("paused"):
            status = "paused"
        if provider == "claude" and events.is_file():
            if not final_message:
                final_message = claude_result_message(events)
            atomic_write(report, final_message)
        if provider == "codex" and not test_mode and production_local_interruption:
            report_text = ""
        elif provider == "codex" and not test_mode:
            report_text = _read_relative_regular_file(
                report.parent,
                report.name,
                label="canonical worker report",
            ).decode("utf-8", "strict")
        else:
            report_text = (
                report.read_text(encoding="utf-8", errors="replace")
                if report.is_file()
                else ""
            )
        report_verdict = task_report_verdict(report_text, worker_report_contract)
        summary = guardian.summary()
        summary["report_contract"] = worker_report_contract
        summary["task_report_verdict"] = report_verdict
        summary["execution_binding"] = {
            "schema": EXECUTION_BINDING_SCHEMA,
            "sha256": execution_binding_sha256,
            "artifact": frozen_binding.name,
            "artifact_sha256": binding_artifact_digest,
        }
        summary["native_broker"] = {
            "installed_authority_sha256": (
                installed_authority.get("authority_sha256")
                if installed_authority is not None
                else None
            ),
            "runtime_generation": (
                installed_authority.get("runtime_generation")
                if installed_authority is not None
                else None
            ),
            "broker_sha256": (
                installed_authority.get("broker_sha256")
                if installed_authority is not None
                else None
            ),
            "request_sha256": (
                broker_request.get("request_sha256")
                if broker_request is not None
                else None
            ),
            "probe_receipt_sha256": (
                broker_probe_evidence.get("probe_receipt", {}).get("receipt_sha256")
                if broker_probe_evidence is not None
                else None
            ),
            "observed_denial": (
                bool(broker_probe_evidence.get("observed_denial"))
                if broker_probe_evidence is not None
                else False
            ),
            "policy_pause": (
                bool(broker_probe_evidence.get("policy_pause"))
                if broker_probe_evidence is not None
                else False
            ),
            "execution_prevented": (
                bool(broker_probe_evidence.get("execution_prevented"))
                if broker_probe_evidence is not None
                else False
            ),
            "terminal_receipt_sha256": (
                broker_terminal.get("receipt_sha256")
                if broker_terminal is not None
                else None
            ),
            "terminal_domain": (
                broker_terminal.get("termination_domain")
                if broker_terminal is not None
                else None
            ),
            "terminal_reason": (
                broker_terminal.get("termination_reason")
                if broker_terminal is not None
                else None
            ),
        }
        summary["brief"] = {
            "origin": brief_origin,
            "sha256": hashlib.sha256(brief_text.encode("utf-8")).hexdigest(),
            "relative_path": brief_relative_identity,
            "mode": "0400-static-control",
        }
        summary["task_authority"] = {
            "origin": task_origin,
            "sha256": task_digest,
            "task_id": task_definition["task_id"],
            "base_commit": task_definition["base_commit"],
            "brief_sha256": brief_digest,
            "brief_relative_path": brief_relative_identity,
            "worktree": str(root),
            "git_common_dir": _git_common_directory(root, test_mode=test_mode),
            "control_root": str(control_root),
            "owned_paths": owned_paths,
            "path_schema": "canonical-worktree-relative-v1",
            "execution_binding_sha256": execution_binding_sha256,
            "binding_artifact": frozen_binding.name,
            "mode": "0400-static-control",
        }
        summary["policy_enforcement"] = {
            "profile": "sulde-owned-paths" if provider == "codex" else "provider-native",
            "profile_supported": bool(profile_preflight.get("supported")),
            "preflight_evidence": str(profile_preflight.get("evidence") or ""),
            "initialize_attempts": list(
                profile_preflight.get("initialize_attempts") or []
            ),
            "owned_paths": owned_paths,
            "network_enabled": False if provider == "codex" else None,
            "tmpdir": "deny" if provider == "codex" else None,
            "slash_tmp": "deny" if provider == "codex" else None,
            "observed_denial": bool(summary.get("findings")),
            "execution_prevented": bool(
                broker_probe_evidence.get("execution_prevented")
                if broker_probe_evidence is not None
                else profile_preflight.get("execution_prevented")
            ),
            "policy_pause": bool(
                broker_probe_evidence.get("policy_pause")
                if broker_probe_evidence is not None
                else False
            ),
        }
        summary["execution"] = {
            "run_id": run_result.run_id if run_result else None,
            "returncode": run_result.returncode if run_result else None,
            "stop_reason": run_result.stop_reason if run_result else "error",
            "output_present": run_result.output_present if run_result else False,
            "cleanup_quiescent": (
                cleanup_result.quiescent if cleanup_result else False
            ),
            "cleanup_error_count": (
                len(cleanup_result.errors) if cleanup_result else 1
            ),
            "tree_scope": cleanup_result.tree_scope if cleanup_result else "unknown",
            "phase_heartbeat": (
                validate_phase_heartbeat_rows(phase_heartbeat.rows)
                if phase_heartbeat is not None and phase_heartbeat.rows
                else None
            ),
        }
        invariant_failures = terminal_invariant_failures(summary, run_ledger_path)
        summary["terminal_invariants"] = {
            "quiescent": not invariant_failures,
            "failure_count": len(invariant_failures),
            "failures": invariant_failures,
        }
        if (
            finalized["intervention_ids"]
            or summary["interventions_open"]
            or summary["approvals_open"]
            or summary["corrections_open"]
        ):
            status = "awaiting_human"
        atomic_write(
            state / f"{args.slug}.guardian.json",
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
        if status not in {"timeout", "paused", "awaiting_human"}:
            status = (
                "success" if (
                    returncode == 0
                    and report_verdict["passed"]
                    and not invariant_failures
                )
                else "failed"
            )
        duration = int(time.monotonic() - started)
        atomic_write(
            status_path,
            f"status={status} rc={returncode} duration={duration}s "
            f"sandbox={'permission-profile' if provider == 'codex' else 'provider-native'} "
            f"provider={provider} guardian={args.guardian_mode} "
            f"observed_denial={str(bool(summary.get('findings'))).lower()} "
            f"execution_prevented={str(bool(summary['policy_enforcement']['execution_prevented'])).lower()} "
            f"report_verdict={'passed' if report_verdict['passed'] else 'failed'} "
            f"report_failure_count={len(report_verdict['failures'])} "
            f"run={run_result.run_id if run_result else 'unknown'} "
            f"stop={run_result.stop_reason if run_result else 'error'} "
            f"quiescent={str(bool(cleanup_result and cleanup_result.quiescent)).lower()} "
            f"intent={intent_path} last={report}\n",
        )
        if phase_heartbeat is not None and not phase_heartbeat.terminal:
            phase_heartbeat.publish(
                "run_finalized",
                reason=status,
                terminal=True,
            )
        print(
            f"SULDE AGENT DONE slug={args.slug} provider={provider} "
            f"status={status} rc={returncode} duration={duration}s"
        )
        if not report_verdict["passed"]:
            for failure in report_verdict["failures"]:
                print(f"REPORT VERDICT: FAIL: {failure}")
        return 0 if status == "success" else 1
    except (
        AgentRuntimeError,
        ExecutionBackendError,
        ProviderError,
        IntentGuardianError,
        CorrectionInterventionError,
        AuditCursorError,
        OSError,
        UnicodeError,
        subprocess.SubprocessError,
    ) as error:
        duration = int(time.monotonic() - started)
        preserved_status = (
            status
            if status in {"paused", "awaiting_human"}
            else observed_status
            if observed_status in {"paused", "awaiting_human"}
            else ""
        )
        if phase_heartbeat is not None and not phase_heartbeat.terminal:
            phase_heartbeat.publish(
                "run_finalized",
                reason=(
                    f"{preserved_status}:post_terminal_{type(error).__name__}"
                    if preserved_status
                    else f"failed:{type(error).__name__}"
                ),
                terminal=True,
            )
        if preserved_status and guardian is not None:
            try:
                terminal_summary = guardian.summary()
                terminal_summary["report_contract"] = worker_report_contract
                terminal_summary["terminal_preservation"] = {
                    "status": preserved_status,
                    "reason": f"post_terminal_{type(error).__name__}",
                    "error": str(error)[:2_000],
                }
                atomic_write(
                    state / f"{args.slug}.guardian.json",
                    json.dumps(
                        terminal_summary,
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n",
                )
            except (
                IntentGuardianError,
                OSError,
                UnicodeError,
            ):
                # Status preservation is based only on the parent monitor's
                # already-observed terminal, never on provider-authored bytes.
                pass
        atomic_write(
            status_path,
            f"status={preserved_status or 'failed'} "
            f"rc={returncode if preserved_status else 2} duration={duration}s "
            f"sandbox={'permission-profile' if provider == 'codex' else 'provider-native'} "
            f"provider={provider} guardian={args.guardian_mode} "
            f"reason={'post_terminal_' + type(error).__name__ if preserved_status else type(error).__name__} "
            f"last={report}\n",
        )
        with stderr_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{type(error).__name__}: {error}\n")
        print(f"SULDE AGENT FAILED slug={args.slug}: {error}", file=sys.stderr)
        return 1
    finally:
        try:
            unlock(lock_handle)
        finally:
            lock_handle.close()


def has_check_evidence(line: str) -> bool:
    if not line.lstrip().startswith("✅"):
        return False
    command = re.search(r"`[^`\r\n]+`", line)
    succeeded = re.search(r"\bexit\s+0\b", line, re.IGNORECASE)
    observable = re.search(
        r"\bexit\s+0\b\s*(?:，|,|；|;)\s*(?!<可观察结果>)(?=\S).+\S",
        line,
        re.IGNORECASE,
    )
    return command is not None and succeeded is not None and observable is not None


def verify_task(args: argparse.Namespace) -> int:
    validate_slug(args.slug)
    root = validated_root(args.worktree)
    test_mode = os.environ.get("SULDE_TEST_MODE") == "1"
    state = root / STATE_DIRECTORY
    if not state.is_dir() or state.is_symlink():
        raise AgentRuntimeError(f"state directory is unavailable: {state}")
    brief_path = state / f"{args.slug}.brief.md"
    if not os.path.lexists(brief_path):
        brief_path = state / f"{args.slug}.md"
    brief_payload, brief_digest, _ = safe_control_read(
        brief_path,
        allowed_parent=state,
        expected_sha256=args.brief_sha256,
        local_static_copy=True,
    )
    try:
        brief_text = brief_payload.decode("utf-8")
    except UnicodeError as error:
        raise AgentRuntimeError("brief is not valid UTF-8") from error
    frozen_task_path = state / f"{args.slug}.task.json"
    if not os.path.lexists(frozen_task_path):
        raise AgentRuntimeError("strict verify requires the frozen task authority artifact")
    if not test_mode and not args.task_id:
        raise AgentRuntimeError("strict verify requires --task-id authority")
    task_payload, verified_task_digest, _ = safe_control_read(
        frozen_task_path,
        allowed_parent=state,
        expected_sha256=args.task_definition_sha256,
        local_static_copy=True,
    )
    frozen_task, verified_owned_paths = _parse_task_definition(
        task_payload,
        root,
        expected_task_id=args.task_id,
        test_mode=test_mode,
    )
    frozen_binding_path = state / f"{args.slug}.task-binding.json"
    if not os.path.lexists(frozen_binding_path):
        raise AgentRuntimeError(
            "strict verify requires the frozen execution binding artifact"
        )
    binding_payload, binding_artifact_digest, _ = safe_control_read(
        frozen_binding_path,
        allowed_parent=state,
        expected_sha256=None,
        local_static_copy=True,
    )
    frozen_binding, _artifact_binding_digest = parse_execution_binding_artifact(
        binding_payload
    )
    brief_authority = frozen_binding.get("brief")
    if not isinstance(brief_authority, dict):
        raise AgentRuntimeError("execution binding brief authority is invalid")
    brief_relative_identity = _canonical_brief_relative_identity(
        brief_authority.get("relative_path")
    )
    expected_binding = execution_binding_envelope(
        task_payload=task_payload,
        task=frozen_task,
        brief_relative_path=brief_relative_identity,
        brief_sha256=brief_digest,
        root=root,
        owned_paths=verified_owned_paths,
        test_mode=test_mode,
    )
    execution_binding_sha256 = validate_execution_binding(
        binding_payload,
        expected=expected_binding,
    )
    worker_report_contract = report_contract_for_brief(brief_text)
    worker_report_contract["execution_binding_sha256"] = (
        execution_binding_sha256
    )
    worker_report_contract["enforce_current_execution_binding"] = (
        not test_mode
    )
    status_path = state / f"{args.slug}.status"
    baseline_path = state / f"{args.slug}.baseline"
    report_path = state / f"{args.slug}.last.md"
    guardian_path = state / f"{args.slug}.guardian.json"
    run_ledger_path = state / f"{args.slug}.run.jsonl"
    failures: list[str] = []

    status = (
        status_path.read_text(encoding="utf-8", errors="replace")
        if status_path.is_file()
        else ""
    )
    if not status.startswith("status=success "):
        failures.append("terminal status is missing or not success")
    try:
        guardian = json.loads(guardian_path.read_text(encoding="utf-8"))
        if not isinstance(guardian, dict):
            raise ValueError("guardian summary root is not an object")
        failures.extend(
            terminal_invariant_failures(guardian, run_ledger_path)
        )
        if guardian.get("report_contract") != worker_report_contract:
            failures.append("guardian report contract does not match the brief contract")
        task_authority = guardian.get("task_authority")
        policy = guardian.get("policy_enforcement")
        brief_evidence = guardian.get("brief")
        guardian_binding = guardian.get("execution_binding")
        if (
            not isinstance(task_authority, dict)
            or not isinstance(policy, dict)
            or not isinstance(brief_evidence, dict)
        ):
            failures.append("guardian task authority evidence is missing")
        else:
            expected_authority = {
                "sha256": verified_task_digest,
                "task_id": frozen_task["task_id"],
                "base_commit": frozen_task["base_commit"],
                "brief_sha256": brief_digest,
                "brief_relative_path": brief_relative_identity,
                "worktree": str(root),
                "git_common_dir": _git_common_directory(root, test_mode=test_mode),
                "owned_paths": verified_owned_paths,
                "path_schema": "canonical-worktree-relative-v1",
                "execution_binding_sha256": execution_binding_sha256,
                "binding_artifact": frozen_binding_path.name,
                "mode": "0400-static-control",
            }
            for key, expected in expected_authority.items():
                if task_authority.get(key) != expected:
                    failures.append(f"guardian task authority {key} drifted")
            if not isinstance(task_authority.get("control_root"), str) or not Path(
                task_authority.get("control_root") or "."
            ).is_absolute():
                failures.append("guardian task authority control_root is invalid")
            if policy.get("owned_paths") != verified_owned_paths:
                failures.append("provider policy owned_paths drifted")
            if not policy.get("owned_paths"):
                failures.append("provider policy owned_paths are empty")
            if brief_evidence.get("sha256") != brief_digest:
                failures.append("guardian brief digest drifted")
            if brief_evidence.get("relative_path") != brief_relative_identity:
                failures.append("guardian brief relative identity drifted")
            if brief_evidence.get("mode") != "0400-static-control":
                failures.append("guardian brief mode is not frozen")
            expected_guardian_binding = {
                "schema": EXECUTION_BINDING_SCHEMA,
                "sha256": execution_binding_sha256,
                "artifact": frozen_binding_path.name,
                "artifact_sha256": binding_artifact_digest,
            }
            if guardian_binding != expected_guardian_binding:
                failures.append("guardian execution binding drifted")
        intent = load_contract(state / f"{args.slug}.intent.json")
        intent_allowed = intent.get("constraints", {}).get("allowed_paths")
        if intent_allowed != verified_owned_paths:
            failures.append("intent allowed_paths do not match frozen task authority")
        if not intent_allowed:
            failures.append("intent allowed_paths are empty")
        if intent.get("execution_binding") != {
            "schema": EXECUTION_BINDING_SCHEMA,
            "sha256": execution_binding_sha256,
        }:
            failures.append("intent execution binding drifted")
        try:
            verify_run_ledger_binding(
                run_ledger_path,
                execution_binding_sha256,
            )
        except (AgentRuntimeError, ExecutionBackendError) as error:
            failures.append(str(error))
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
        IntentGuardianError,
    ) as error:
        failures.append(f"guardian summary cannot be verified: {error}")
    try:
        before = json.loads(baseline_path.read_text(encoding="utf-8"))
        if not isinstance(before, dict):
            raise ValueError("baseline root is not an object")
        changes = changed_paths(before, snapshot(root))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        failures.append(f"baseline cannot be verified: {error}")
        changes = []

    def task_allows(relative: str) -> bool:
        for owned in verified_owned_paths:
            if owned.endswith("/**"):
                base = owned[:-3]
                if relative == base or relative.startswith(base + "/"):
                    return True
            elif relative == owned:
                return True
        return False

    violations = [line for line in changes if not task_allows(line[2:])]
    if violations:
        failures.append("out-of-scope changes: " + ", ".join(violations))

    if not test_mode:
        try:
            _durable_report_path, durable_report_raw = _read_durable_worker_report(
                root,
                verified_owned_paths,
            )
            report_raw = _read_relative_regular_file(
                report_path.parent,
                report_path.name,
                label="canonical worker report",
            )
            report_text = report_raw.decode("utf-8", "strict")
            if _canonical_provider_final_bytes(report_text) != report_raw:
                failures.append("canonical worker report byte shape drifted")
            if durable_report_raw != report_raw:
                failures.append("durable worker report changed after receipt binding")
            report = report_text
        except (AgentRuntimeError, UnicodeError) as error:
            failures.append(str(error))
            report = ""
    else:
        report = (
            report_path.read_text(encoding="utf-8", errors="replace")
            if report_path.is_file()
            else ""
        )
    report_verdict = task_report_verdict(report, worker_report_contract)
    failures.extend(report_verdict["failures"])

    print("=== 终态 ===")
    print(status.strip() or "（缺失）")
    print("=== 本轮改动 ===")
    print("\n".join(changes) if changes else "（无改动）")
    print("=== 汇报正文 ===")
    print(report.rstrip() or "（缺失）")
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        print("=== VERIFY: FAIL ===")
        return 1
    print("=== VERIFY: PASS ===")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    run_parser = actions.add_parser("run", help="run one approved task")
    run_parser.add_argument("worktree", type=Path)
    run_parser.add_argument("slug")
    run_parser.add_argument("brief", type=Path)
    run_parser.add_argument("--brief-sha256")
    run_parser.add_argument(
        "--control-root",
        type=Path,
        help="coordinator guardian-program root containing briefs/ and task-definitions/",
    )
    run_parser.add_argument("--task-definition", type=Path)
    run_parser.add_argument("--task-definition-sha256")
    run_parser.add_argument("--task-id")
    run_parser.add_argument(
        "--owned-path",
        action="append",
        default=[],
        help="exact task-owned path; must match --task-definition when both are used",
    )
    run_parser.add_argument("--provider", choices=("auto", "claude", "codex"))
    run_parser.add_argument("--effort", choices=("low", "medium", "high"), default="high")
    run_parser.add_argument(
        "--guardian-mode",
        choices=("off", "shadow", "enforce"),
        default=os.environ.get("SULDE_GUARDIAN_MODE", "shadow"),
    )
    run_parser.add_argument("--intent-contract", type=Path)
    run_parser.add_argument("--resume-context", type=Path)
    run_parser.add_argument(
        "--semantic-critic",
        action="store_true",
        help="opt in to extra provider calls over changed local artifacts after secret scanning",
    )
    run_parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("SULDE_AGENT_TIMEOUT", "900")),
    )
    verify_parser = actions.add_parser("verify", help="verify one task artifact set")
    verify_parser.add_argument("worktree", type=Path)
    verify_parser.add_argument("slug")
    verify_parser.add_argument("--allowed-paths", default=".*")
    verify_parser.add_argument("--brief-sha256")
    verify_parser.add_argument("--task-definition-sha256")
    verify_parser.add_argument("--task-id")

    provision_parser = actions.add_parser(
        "provision", help="create one exact repository-local task worktree"
    )
    provision_parser.add_argument("repository", type=Path)
    provision_parser.add_argument("worktree", type=Path)
    provision_parser.add_argument("--branch", required=True)
    provision_parser.add_argument("--base-ref", required=True)
    provision_parser.add_argument("--base-commit", required=True)

    commit_parser = actions.add_parser(
        "commit", help="commit one exact staged task path set"
    )
    commit_parser.add_argument("worktree", type=Path)
    commit_parser.add_argument("--expected-head", required=True)
    commit_parser.add_argument("--message", required=True)
    commit_parser.add_argument("--path", action="append", required=True)

    merge_parser = actions.add_parser(
        "merge", help="fast-forward one exact task or release ref"
    )
    merge_parser.add_argument("worktree", type=Path)
    merge_parser.add_argument("--target-branch", choices=("dev", "main"), required=True)
    merge_parser.add_argument("--source-ref", required=True)
    merge_parser.add_argument("--expected-target-head", required=True)
    merge_parser.add_argument("--expected-source-head", required=True)
    merge_parser.add_argument("--path", action="append", required=True)
    args = parser.parse_args()
    if getattr(args, "timeout", 1) <= 0:
        parser.error("--timeout must be greater than zero")
    return args


def main() -> int:
    args = parse_args()
    try:
        handlers = {
            "run": run_task,
            "verify": verify_task,
            "provision": provision_worktree,
            "commit": commit_worktree,
            "merge": merge_worktree,
        }
        return handlers[args.action](args)
    except (
        AgentRuntimeError,
        ExecutionBackendError,
        ProviderError,
        AuditCursorError,
        OSError,
        UnicodeError,
    ) as error:
        print(f"SULDE AGENT RUNTIME: FAIL: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
