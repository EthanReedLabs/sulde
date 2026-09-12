#!/usr/bin/env python3
"""Digest-bound composition of accepted predecessor worktrees.

This module is deliberately a leaf.  It validates an already-selected predecessor
set, writes a synthetic Git commit through a private temporary index, and publishes
an immutable READY receipt.  It does not select tasks, grant authority, start a
worker, or check out a successor worktree.

The schemas are intentionally closed.  Callers should use :func:`load_plan` for
JSON received across a trust boundary, :func:`load_trusted_authority` to obtain a
provenance-bearing snapshot from the installation-fixed control root, and
:func:`compose`/:func:`verify_receipt` for the composition lifecycle.  Plain JSON
is never upgraded to coordinator authority merely because its digest matches.
"""

from __future__ import annotations

import hashlib
import json
import os
import pwd
import re
import secrets
import stat
import subprocess
import tempfile
import time
import unicodedata
from typing import Any


PLAN_SCHEMA = "sulde-predecessor-composition-plan-v3"
AUTHORITY_SCHEMA = "sulde-coordinator-authority-snapshot-v3"
ACCEPTED_EVENT_SCHEMA = "sulde-coordinator-accepted-event-v1"
RECEIPT_SCHEMA = "sulde-predecessor-composition-receipt-v4"
CONTROL_DEPLOYMENT_SCHEMA = "sulde-kb-control-deployment-v1"
AUTHORITY_KIND_PRODUCTION = "production"
AUTHORITY_KIND_SYNTHETIC = "synthetic"
RESOLVER_KIND_PRODUCTION = "installation"
RESOLVER_KIND_TEST = "test"
ZERO_SHA256 = "0" * 64
AUTHORITY_UNATTESTED = "AUTHORITY_UNATTESTED"
AUTHORITY_INPUT_MISSING = "AUTHORITY_INPUT_MISSING"
_AUTHORITY_GUARD = object()
_CONTROL_ROOT_GUARD = object()
READY_STATES = [
    "DECLARED",
    "VALIDATING",
    "SOURCES_FROZEN",
    "TREE_WRITTEN",
    "READY",
]
SYNTHETIC_READY_STATES = [*READY_STATES[:-1], "SYNTHETIC_READY"]
_HEX_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_HEX_OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_TIMEZONE = re.compile(r"([+-])(\d{2})(\d{2})\Z")
_TEMP_NAME = re.compile(r"\.tmp-[0-9a-f]{32}\Z")
_CONCURRENT_PUBLICATION_TIMEOUT_SECONDS = 1.0
_FORBIDDEN_COMPONENTS = {
    ".git",
    ".codex-agent",
    ".coordinator-authority",
    "authority",
    "authorities",
    "completion-evidence",
    "control-event",
    "control-events",
    "event-control",
    "events.jsonl",
    "completion",
    "completions",
}
_GLOB_OR_MAGIC = frozenset("*?[]{}")
_FAULT_STAGES = {
    "after_validation",
    "after_sources_frozen",
    "after_tree_written",
    "after_receipt_write",
    "after_receipt_fsync",
    "after_content_publish",
    "after_content_fsync",
    "after_staging_unlink",
    "after_staging_fsync",
    "after_target_publish",
    "after_target_fsync",
}


class CompositionError(RuntimeError):
    """Fail-closed validation or publication error."""


class CompositionCrash(CompositionError):
    """Deterministic failure-injection exception used by focused tests."""


class _AuthoritySnapshot:
    """Opaque result of a fixed-root, descriptor-safe authority read."""

    __slots__ = (
        "_guard",
        "_authority_kind",
        "_resolver_kind",
        "_resolver_path",
        "_snapshot_bytes",
        "_raw",
        "_provenance_bytes",
        "_sealed",
    )

    def __init__(
        self,
        guard: object,
        snapshot: dict[str, Any],
        raw: bytes,
        provenance: dict[str, Any],
        resolver: _ControlRootResolver,
        *,
        authority_kind: str,
        resolver_kind: str,
    ) -> None:
        if guard is not _AUTHORITY_GUARD:
            raise TypeError("authority snapshots must come from load_trusted_authority")
        if resolver.resolver_kind != resolver_kind:
            raise TypeError("authority and resolver kinds do not match")
        object.__setattr__(self, "_guard", guard)
        object.__setattr__(self, "_authority_kind", authority_kind)
        object.__setattr__(self, "_resolver_kind", resolver_kind)
        object.__setattr__(self, "_resolver_path", resolver.path)
        object.__setattr__(self, "_snapshot_bytes", _canonical_bytes(snapshot))
        object.__setattr__(self, "_raw", bytes(raw))
        object.__setattr__(self, "_provenance_bytes", _canonical_bytes(provenance))
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("authority tokens are immutable")
        object.__setattr__(self, name, value)

    def __copy__(self) -> _AuthoritySnapshot:
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> _AuthoritySnapshot:
        memo[id(self)] = self
        return self

    @property
    def authority_kind(self) -> str:
        return self._authority_kind

    @property
    def resolver_kind(self) -> str:
        return self._resolver_kind

    @property
    def snapshot(self) -> dict[str, Any]:
        return _parse_json(self._snapshot_bytes, "immutable authority snapshot")

    @property
    def raw(self) -> bytes:
        return self._raw

    @property
    def provenance(self) -> dict[str, Any]:
        return _parse_json(self._provenance_bytes, "immutable authority provenance")


class _ControlRootResolver:
    """Installation-owned control-root dependency.

    Production constructs this from the effective user's OS account.  Tests may
    inject one explicitly in-process; plans, CLI arguments, and environment
    variables never select the trust root.
    """

    __slots__ = ("_guard", "_path", "_resolver_kind", "_sealed")

    def __init__(self, guard: object, path: str, *, resolver_kind: str) -> None:
        if guard is not _CONTROL_ROOT_GUARD:
            raise TypeError("control roots must come from the fixed resolver")
        if resolver_kind not in (RESOLVER_KIND_PRODUCTION, RESOLVER_KIND_TEST):
            raise TypeError("unsupported control-root resolver kind")
        object.__setattr__(self, "_guard", guard)
        object.__setattr__(self, "_path", path)
        object.__setattr__(self, "_resolver_kind", resolver_kind)
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("control-root resolvers are immutable")
        object.__setattr__(self, name, value)

    @property
    def path(self) -> str:
        return self._path

    @property
    def resolver_kind(self) -> str:
        return self._resolver_kind


def _fail(message: str) -> None:
    raise CompositionError(message)


def _authority_input_missing(message: str) -> None:
    raise CompositionError(f"{AUTHORITY_INPUT_MISSING}: {message}")


def _exact_dict(value: Any, where: str) -> dict[str, Any]:
    if type(value) is not dict:
        _fail(f"{where} must be a plain JSON object")
    return value


def _exact_list(value: Any, where: str) -> list[Any]:
    if type(value) is not list:
        _fail(f"{where} must be a plain JSON array")
    return value


def _string(value: Any, where: str, *, nonempty: bool = True) -> str:
    if type(value) is not str:
        _fail(f"{where} must be a JSON string")
    if nonempty and not value:
        _fail(f"{where} must not be empty")
    if "\x00" in value or any(0xD800 <= ord(ch) <= 0xDFFF for ch in value):
        _fail(f"{where} contains an invalid character")
    return value


def _integer(value: Any, where: str, *, minimum: int = 0) -> int:
    # bool is an int subclass, so exact type is part of the contract.
    if type(value) is not int or value < minimum:
        _fail(f"{where} must be an integer >= {minimum}")
    return value


def _keys(value: dict[str, Any], expected: set[str], where: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        _fail(f"{where} fields mismatch; missing={missing}, unknown={unknown}")


def _sha256(value: Any, where: str, *, zero_allowed: bool = False) -> str:
    text = _string(value, where)
    if not _HEX_SHA256.fullmatch(text):
        _fail(f"{where} must be lowercase SHA-256")
    if not zero_allowed and text == ZERO_SHA256:
        _fail(f"{where} must not use the absent-content sentinel")
    return text


def _oid(value: Any, where: str) -> str:
    text = _string(value, where)
    if not _HEX_OID.fullmatch(text):
        _fail(f"{where} must be a lowercase Git object id")
    return text


def _identifier(value: Any, where: str) -> str:
    text = _string(value, where)
    if not _IDENTIFIER.fullmatch(text):
        _fail(f"{where} is not a canonical identifier")
    return text


def _plain_tree(value: Any, where: str = "JSON") -> None:
    kind = type(value)
    if kind is dict:
        for key, child in value.items():
            if type(key) is not str:
                _fail(f"{where} has a non-string object key")
            _plain_tree(child, f"{where}.{key}")
    elif kind is list:
        for index, child in enumerate(value):
            _plain_tree(child, f"{where}[{index}]")
    elif kind not in (str, int, bool, type(None)):
        _fail(f"{where} contains a non-JSON or magic object")


def _canonical_bytes(value: Any) -> bytes:
    _plain_tree(value)
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise CompositionError(f"cannot canonicalize JSON: {exc}") from exc


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _parse_json(payload: Any, where: str) -> dict[str, Any]:
    if type(payload) is bytes:
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CompositionError(f"{where} is not UTF-8") from exc
    elif type(payload) is str:
        text = payload
    else:
        _fail(f"{where} must be exact str or bytes")
    try:
        value = json.loads(
            text,
            object_pairs_hook=_pairs,
            parse_constant=lambda token: _fail(f"non-finite JSON number: {token}"),
        )
    except CompositionError:
        raise
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise CompositionError(f"invalid {where}: {exc}") from exc
    return _exact_dict(value, where)


def _artifact(value: Any, where: str) -> None:
    item = _exact_dict(value, where)
    _keys(item, {"path", "sha256"}, where)
    _absolute_path(item["path"], f"{where}.path")
    _sha256(item["sha256"], f"{where}.sha256")


def _absolute_path(value: Any, where: str) -> str:
    path = _string(value, where)
    if not path.startswith("/") or path == "/" or "\\" in path:
        _fail(f"{where} must be a canonical absolute POSIX file path")
    pieces = path.split("/")[1:]
    if any(piece in ("", ".", "..") for piece in pieces):
        _fail(f"{where} must not contain empty, dot, or dot-dot components")
    if unicodedata.normalize("NFKC", path) != path:
        _fail(f"{where} must already be NFKC-normalized")
    return path


def _production_control_root_path() -> str:
    """Return the installation-fixed per-effective-user Sulde KB control path."""

    try:
        account = pwd.getpwuid(os.geteuid())
    except KeyError as exc:
        raise CompositionError("effective user has no OS account for Sulde KB control") from exc
    home = _absolute_path(account.pw_dir, "effective user home")
    return _absolute_path(os.path.join(home, ".sulde", "kb", "control"), "Sulde KB control root")


def _production_control_root_resolver() -> _ControlRootResolver:
    return _ControlRootResolver(
        _CONTROL_ROOT_GUARD,
        _production_control_root_path(),
        resolver_kind=RESOLVER_KIND_PRODUCTION,
    )


def _test_control_root_resolver(path: Any) -> _ControlRootResolver:
    """Explicit in-process seam for owner-only synthetic control fixtures."""

    return _ControlRootResolver(
        _CONTROL_ROOT_GUARD,
        _absolute_path(path, "synthetic control root"),
        resolver_kind=RESOLVER_KIND_TEST,
    )


def _tree_entry_path(value: Any, where: str) -> str:
    """Validate the structure shared by paths stored in complete Git trees.

    A complete base tree is historical state, not a declaration that every
    entry may be changed by a predecessor.  In particular, control-path and
    pathspec restrictions belong to delta targets; applying them here would
    reject protected or glob-bearing entries that composition must preserve.
    """

    path = _string(value, where)
    if path.startswith("/") or path.endswith("/") or "\\" in path:
        _fail(f"{where} must be a canonical relative POSIX path")
    pieces = path.split("/")
    if any(piece in ("", ".", "..") for piece in pieces):
        _fail(f"{where} contains an empty, dot, or dot-dot component")
    if unicodedata.normalize("NFKC", path) != path:
        _fail(f"{where} must already be NFKC-normalized")
    if any(ord(char) < 32 or ord(char) == 127 for char in path):
        _fail(f"{where} contains a control character")
    return path


def _delta_path(value: Any, where: str) -> str:
    path = _tree_entry_path(value, where)
    pieces = path.split("/")
    if (
        any(char in path for char in _GLOB_OR_MAGIC)
        or path.startswith(":")
    ):
        _fail(f"{where} contains glob or Git pathspec magic")
    folded = [piece.casefold() for piece in pieces]
    if any(piece in _FORBIDDEN_COMPONENTS for piece in folded):
        _fail(f"{where} targets a permanently protected control path")
    return path


def _validate_commit(value: Any) -> None:
    commit = _exact_dict(value, "plan.commit")
    _keys(
        commit,
        {
            "author_name",
            "author_email",
            "committer_name",
            "committer_email",
            "timestamp",
            "timezone",
            "message",
        },
        "plan.commit",
    )
    for field in ("author_name", "committer_name"):
        text = _string(commit[field], f"plan.commit.{field}")
        if any(char in text for char in "<>\n\r"):
            _fail(f"plan.commit.{field} contains a Git identity delimiter")
    for field in ("author_email", "committer_email"):
        text = _string(commit[field], f"plan.commit.{field}")
        if "@" not in text or any(char in text for char in "<>\n\r"):
            _fail(f"plan.commit.{field} is not a canonical email")
    _integer(commit["timestamp"], "plan.commit.timestamp")
    timezone = _string(commit["timezone"], "plan.commit.timezone")
    match = _TIMEZONE.fullmatch(timezone)
    if not match or int(match.group(2)) > 14 or int(match.group(3)) > 59:
        _fail("plan.commit.timezone must be a valid numeric Git timezone")
    message = _string(commit["message"], "plan.commit.message")
    if not message.endswith("\n") or "\r" in message:
        _fail("plan.commit.message must end in one LF and contain no CR")


def validate_plan(value: Any) -> dict[str, Any]:
    """Validate a plain-object plan and return an immutable-by-copy plain tree."""

    _plain_tree(value, "plan")
    plan = _exact_dict(value, "plan")
    _keys(
        plan,
        {
            "schema",
            "program_id",
            "control_generation",
            "authority_snapshot_id",
            "target_id",
            "successor_task_id",
            "logical_base_commit",
            "successor_task_definition",
            "successor_brief",
            "helper_generation",
            "commit",
            "predecessors",
            "source_roots",
        },
        "plan",
    )
    if _string(plan["schema"], "plan.schema") != PLAN_SCHEMA:
        _fail("unsupported composition plan schema")
    _identifier(plan["program_id"], "plan.program_id")
    _integer(plan["control_generation"], "plan.control_generation", minimum=1)
    _identifier(plan["authority_snapshot_id"], "plan.authority_snapshot_id")
    _identifier(plan["target_id"], "plan.target_id")
    _identifier(plan["successor_task_id"], "plan.successor_task_id")
    _oid(plan["logical_base_commit"], "plan.logical_base_commit")
    _artifact(plan["successor_task_definition"], "plan.successor_task_definition")
    _artifact(plan["successor_brief"], "plan.successor_brief")
    helper_generation = _integer(plan["helper_generation"], "plan.helper_generation", minimum=1)
    _validate_commit(plan["commit"])

    predecessors = _exact_list(plan["predecessors"], "plan.predecessors")
    if not predecessors:
        _fail("plan.predecessors must not be empty")
    seen_tasks: dict[str, dict[str, Any]] = {}
    task_order: list[str] = []
    all_paths: dict[str, str] = {}
    last_path_owner: dict[str, str] = {}
    all_evidence_ids: set[str] = set()
    last_event_sequence = 0
    for index, raw in enumerate(predecessors):
        where = f"plan.predecessors[{index}]"
        item = _exact_dict(raw, where)
        _keys(
            item,
            {
                "task_id",
                "status",
                "verification_run",
                "accepted_event",
                "supersession",
                "task_definition",
                "source_root_id",
                "generation",
                "parent_generation",
                "dependencies",
                "dependency_closure",
                "evidence",
                "delta",
            },
            where,
        )
        task_id = _identifier(item["task_id"], f"{where}.task_id")
        if task_id in seen_tasks:
            _fail(f"duplicate predecessor task id: {task_id}")
        if _string(item["status"], f"{where}.status") != "accepted":
            _fail(f"predecessor {task_id} is not accepted or was superseded")
        run = _exact_dict(item["verification_run"], f"{where}.verification_run")
        _keys(run, {"id", "status"}, f"{where}.verification_run")
        _identifier(run["id"], f"{where}.verification_run.id")
        if _string(run["status"], f"{where}.verification_run.status") != "accepted":
            _fail(f"predecessor {task_id} verification run is not accepted")
        event = _exact_dict(item["accepted_event"], f"{where}.accepted_event")
        _keys(event, {"id", "sequence", "status", "path", "sha256"}, f"{where}.accepted_event")
        _identifier(event["id"], f"{where}.accepted_event.id")
        event_sequence = _integer(event["sequence"], f"{where}.accepted_event.sequence", minimum=1)
        if event_sequence <= last_event_sequence:
            _fail(f"{where}.accepted_event.sequence is not globally increasing")
        last_event_sequence = event_sequence
        if _string(event["status"], f"{where}.accepted_event.status") != "accepted":
            _fail(f"predecessor {task_id} event is not accepted")
        _absolute_path(event["path"], f"{where}.accepted_event.path")
        _sha256(event["sha256"], f"{where}.accepted_event.sha256")
        supersession = _exact_dict(item["supersession"], f"{where}.supersession")
        _keys(supersession, {"status", "superseded_by"}, f"{where}.supersession")
        if _string(supersession["status"], f"{where}.supersession.status") != "current":
            _fail(f"predecessor {task_id} has been superseded")
        if supersession["superseded_by"] is not None:
            _fail(f"predecessor {task_id} has a superseding event")
        _artifact(item["task_definition"], f"{where}.task_definition")
        source_root_id = _identifier(item["source_root_id"], f"{where}.source_root_id")
        generation = _integer(item["generation"], f"{where}.generation", minimum=1)
        parent_generation = _integer(item["parent_generation"], f"{where}.parent_generation")
        dependencies = _exact_list(item["dependencies"], f"{where}.dependencies")
        closure = _exact_list(item["dependency_closure"], f"{where}.dependency_closure")
        if any(type(dep) is not str for dep in dependencies + closure):
            _fail(f"{where} dependencies must contain only strings")
        if len(set(dependencies)) != len(dependencies) or len(set(closure)) != len(closure):
            _fail(f"{where} dependencies contain duplicates")
        for dep in dependencies + closure:
            _identifier(dep, f"{where}.dependency")
            if dep not in seen_tasks:
                _fail(f"{where} is not in topological order: {dep}")
        ordered_dependencies = [task for task in seen_tasks if task in set(dependencies)]
        if dependencies != ordered_dependencies:
            _fail(f"{where}.dependencies are not in canonical topological order")
        expected_closure: set[str] = set()
        for dep in dependencies:
            expected_closure.add(dep)
            expected_closure.update(seen_tasks[dep]["dependency_closure"])
        ordered_closure = [task for task in seen_tasks if task in expected_closure]
        if closure != ordered_closure:
            _fail(f"{where}.dependency_closure does not match its dependency closure")
        expected_parent = max((seen_tasks[dep]["generation"] for dep in dependencies), default=0)
        if parent_generation != expected_parent or generation != parent_generation + 1:
            _fail(f"{where} has a mixed or invalid parent generation")

        evidence = _exact_list(item["evidence"], f"{where}.evidence")
        if not evidence:
            _fail(f"{where}.evidence must not be empty")
        evidence_ids: set[str] = set()
        for evidence_index, raw_evidence in enumerate(evidence):
            evidence_where = f"{where}.evidence[{evidence_index}]"
            evidence_item = _exact_dict(raw_evidence, evidence_where)
            _keys(evidence_item, {"id", "path", "sha256"}, evidence_where)
            evidence_id = _identifier(evidence_item["id"], f"{evidence_where}.id")
            if evidence_id in evidence_ids:
                _fail(f"duplicate evidence id in {where}: {evidence_id}")
            evidence_ids.add(evidence_id)
            if evidence_id in all_evidence_ids:
                _fail(f"evidence id is ambiguous across predecessors: {evidence_id}")
            all_evidence_ids.add(evidence_id)
            _absolute_path(evidence_item["path"], f"{evidence_where}.path")
            _sha256(evidence_item["sha256"], f"{evidence_where}.sha256")

        delta = _exact_list(item["delta"], f"{where}.delta")
        if not delta:
            _fail(f"{where}.delta must not be empty")
        local_paths: set[str] = set()
        for delta_index, raw_delta in enumerate(delta):
            delta_where = f"{where}.delta[{delta_index}]"
            entry = _exact_dict(raw_delta, delta_where)
            _keys(
                entry,
                {
                    "path",
                    "operation",
                    "before_sha256",
                    "after_sha256",
                    "size",
                    "mode",
                    "accepted_blob",
                },
                delta_where,
            )
            path = _delta_path(entry["path"], f"{delta_where}.path")
            if path in local_paths:
                _fail(f"predecessor {task_id} declares path twice: {path}")
            local_paths.add(path)
            collision_key = unicodedata.normalize("NFKC", path).casefold()
            previous = all_paths.get(collision_key)
            if previous is not None and previous != path:
                _fail(f"NFKC/casefold path collision: {previous!r} and {path!r}")
            all_paths[collision_key] = path
            operation = _string(entry["operation"], f"{delta_where}.operation")
            if operation not in ("add", "modify", "delete"):
                _fail(f"{delta_where}.operation is unsupported")
            before = _sha256(entry["before_sha256"], f"{delta_where}.before_sha256", zero_allowed=True)
            after = _sha256(entry["after_sha256"], f"{delta_where}.after_sha256", zero_allowed=True)
            size = _integer(entry["size"], f"{delta_where}.size")
            mode = _integer(entry["mode"], f"{delta_where}.mode")
            if mode not in (0o100644, 0o100755):
                _fail(f"{delta_where}.mode must be 100644 or 100755")
            if operation == "add" and before != ZERO_SHA256:
                _fail(f"{delta_where} add must use an absent before hash")
            if operation == "delete" and (after != ZERO_SHA256 or size != 0):
                _fail(f"{delta_where} delete must use absent after hash and size zero")
            if operation != "delete" and after == ZERO_SHA256:
                _fail(f"{delta_where} non-delete must bind after content")
            accepted_blob = entry["accepted_blob"]
            if operation == "delete":
                if accepted_blob is not None:
                    _fail(f"{delta_where}.accepted_blob must be null for delete")
            else:
                blob = _exact_dict(accepted_blob, f"{delta_where}.accepted_blob")
                _keys(blob, {"sha256", "size"}, f"{delta_where}.accepted_blob")
                blob_sha = _sha256(blob["sha256"], f"{delta_where}.accepted_blob.sha256")
                blob_size = _integer(blob["size"], f"{delta_where}.accepted_blob.size")
                if blob_sha != after or blob_size != size:
                    _fail(f"{delta_where}.accepted_blob does not bind accepted after content")
            previous_owner = last_path_owner.get(path)
            if previous_owner is not None and previous_owner not in closure:
                _fail(f"parallel predecessors {previous_owner} and {task_id} both declare {path}")
            last_path_owner[path] = task_id

        seen_tasks[task_id] = {
            "generation": generation,
            "dependency_closure": set(closure),
            "source_root_id": source_root_id,
            "delta": {entry["path"]: entry for entry in delta},
        }
        task_order.append(task_id)

    source_roots = _exact_list(plan["source_roots"], "plan.source_roots")
    if not source_roots:
        _fail("plan.source_roots must not be empty")
    seen_root_ids: set[str] = set()
    seen_root_paths: set[str] = set()
    assigned_tasks: set[str] = set()
    expected_root_order: list[str] = []
    for task_id in task_order:
        root_id = seen_tasks[task_id]["source_root_id"]
        if root_id not in expected_root_order:
            expected_root_order.append(root_id)
    actual_root_order: list[str] = []
    for root_index, raw_root in enumerate(source_roots):
        root_where = f"plan.source_roots[{root_index}]"
        root = _exact_dict(raw_root, root_where)
        _keys(root, {"id", "path", "task_ids", "cumulative_inventory"}, root_where)
        root_id = _identifier(root["id"], f"{root_where}.id")
        if root_id in seen_root_ids:
            _fail(f"duplicate source root id: {root_id}")
        seen_root_ids.add(root_id)
        actual_root_order.append(root_id)
        root_path = _absolute_path(root["path"], f"{root_where}.path")
        if root_path in seen_root_paths:
            _fail(f"duplicate source root path: {root_path}")
        seen_root_paths.add(root_path)
        task_ids = _exact_list(root["task_ids"], f"{root_where}.task_ids")
        expected_tasks = [
            task_id for task_id in task_order if seen_tasks[task_id]["source_root_id"] == root_id
        ]
        if task_ids != expected_tasks or not task_ids:
            _fail(f"{root_where}.task_ids do not exactly enumerate the root's selected tasks")
        for position, task_id in enumerate(task_ids):
            _identifier(task_id, f"{root_where}.task_ids[{position}]")
            if task_id in assigned_tasks:
                _fail(f"source task is assigned more than once: {task_id}")
            assigned_tasks.add(task_id)
            earlier = task_ids[:position]
            if any(dep not in seen_tasks[task_id]["dependency_closure"] for dep in earlier):
                _fail(f"{root_where} is not cumulative in dependency order at {task_id}")

        inventory = _exact_list(root["cumulative_inventory"], f"{root_where}.cumulative_inventory")
        expected_paths = sorted(
            {
                path
                for task_id in task_ids
                for path in seen_tasks[task_id]["delta"]
            }
        )
        if not inventory:
            _fail(f"{root_where}.cumulative_inventory must not be empty")
        actual_paths: list[str] = []
        for inventory_index, raw_inventory in enumerate(inventory):
            inventory_where = f"{root_where}.cumulative_inventory[{inventory_index}]"
            item = _exact_dict(raw_inventory, inventory_where)
            _keys(
                item,
                {"path", "selected_predecessor", "state", "sha256", "size", "mode"},
                inventory_where,
            )
            path = _delta_path(item["path"], f"{inventory_where}.path")
            actual_paths.append(path)
            selected = _identifier(
                item["selected_predecessor"],
                f"{inventory_where}.selected_predecessor",
            )
            owners = [task_id for task_id in task_ids if path in seen_tasks[task_id]["delta"]]
            if not owners or selected != owners[-1]:
                _fail(f"{inventory_where} does not select the final predecessor for its path")
            delta_entry = seen_tasks[selected]["delta"][path]
            state = _string(item["state"], f"{inventory_where}.state")
            expected_state = "absent" if delta_entry["operation"] == "delete" else "present"
            if state != expected_state:
                _fail(f"{inventory_where}.state does not match the selected predecessor")
            content_sha = _sha256(
                item["sha256"],
                f"{inventory_where}.sha256",
                zero_allowed=True,
            )
            size = _integer(item["size"], f"{inventory_where}.size")
            mode = _integer(item["mode"], f"{inventory_where}.mode")
            if mode not in (0o100644, 0o100755):
                _fail(f"{inventory_where}.mode is invalid")
            if (
                content_sha != delta_entry["after_sha256"]
                or size != delta_entry["size"]
                or mode != delta_entry["mode"]
            ):
                _fail(f"{inventory_where} accepted content identity drift")
        if actual_paths != expected_paths:
            _fail(
                f"{root_where}.cumulative_inventory is not the complete canonical inventory; "
                f"declared={actual_paths}, expected={expected_paths}"
            )

    if actual_root_order != expected_root_order:
        _fail("plan.source_roots are not in first-selected-task order")
    if assigned_tasks != set(task_order):
        _fail("plan.source_roots do not assign every selected predecessor exactly once")

    maximum_generation = max(item["generation"] for item in predecessors)
    if helper_generation != maximum_generation + 1:
        _fail("plan.helper_generation does not follow the predecessor generation")
    # Canonical round-trip prevents a caller from mutating the accepted object tree
    # through references held inside a plain list/dict while composition starts.
    frozen = _parse_json(_canonical_bytes(plan), "canonical plan")
    return frozen


def load_plan(payload: Any) -> dict[str, Any]:
    """Parse strict JSON and validate the closed plan schema."""

    return validate_plan(_parse_json(payload, "composition plan JSON"))


def plan_sha256(plan: Any) -> str:
    frozen = validate_plan(plan)
    return hashlib.sha256(_canonical_bytes(frozen)).hexdigest()


def _authority_projection(
    plan: dict[str, Any],
    *,
    authority_kind: str = AUTHORITY_KIND_PRODUCTION,
    resolver_kind: str = RESOLVER_KIND_PRODUCTION,
) -> dict[str, Any]:
    if (authority_kind, resolver_kind) not in (
        (AUTHORITY_KIND_PRODUCTION, RESOLVER_KIND_PRODUCTION),
        (AUTHORITY_KIND_SYNTHETIC, RESOLVER_KIND_TEST),
    ):
        _fail("authority and resolver kinds are not a supported binding")
    projection = _parse_json(_canonical_bytes(plan), "authority projection")
    projection["schema"] = AUTHORITY_SCHEMA
    projection["authority_kind"] = authority_kind
    projection["resolver_kind"] = resolver_kind
    return projection


def _validate_authority_snapshot(
    value: Any,
    *,
    authority_kind: str,
    resolver_kind: str,
) -> dict[str, Any]:
    snapshot = _exact_dict(value, "authority snapshot")
    _plain_tree(snapshot, "authority snapshot")
    if _string(snapshot.get("schema"), "authority snapshot.schema") != AUTHORITY_SCHEMA:
        _fail("unsupported coordinator authority snapshot schema")
    candidate = _parse_json(_canonical_bytes(snapshot), "canonical authority snapshot")
    actual_authority_kind = _string(
        candidate.pop("authority_kind", None), "authority snapshot.authority_kind"
    )
    actual_resolver_kind = _string(
        candidate.pop("resolver_kind", None), "authority snapshot.resolver_kind"
    )
    if (actual_authority_kind, actual_resolver_kind) != (authority_kind, resolver_kind):
        _fail("authority snapshot kind does not match its resolver")
    candidate["schema"] = PLAN_SCHEMA
    validated = validate_plan(candidate)
    canonical = _authority_projection(
        validated,
        authority_kind=authority_kind,
        resolver_kind=resolver_kind,
    )
    if canonical != snapshot:
        _fail("authority snapshot is not the exact closed plan projection")
    return canonical


def _unattested(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "state": AUTHORITY_UNATTESTED,
        "consumable": False,
        "authority_kind": "unattested",
        "resolver_kind": "none",
        "reason": "a snapshot read from the fixed trusted control root is required",
        "program_id": plan["program_id"],
        "authority_snapshot_id": plan["authority_snapshot_id"],
        "plan_sha256": hashlib.sha256(_canonical_bytes(plan)).hexdigest(),
    }


def _secure_env(index_path: str | None = None) -> dict[str, str]:
    env = os.environ.copy()
    for name in list(env):
        if name.startswith("GIT_"):
            del env[name]
    env.update(
        {
            "LC_ALL": "C",
            "LANG": "C",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_NO_REPLACE_OBJECTS": "1",
            # Repository-local i18n.commitEncoding can otherwise add an encoding
            # header to commit-tree output.  All commit objects are written from
            # explicit raw bytes below, and Git subprocesses receive a fixed UTF-8
            # value as defense in depth.
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "i18n.commitEncoding",
            "GIT_CONFIG_VALUE_0": "UTF-8",
        }
    )
    if index_path is not None:
        env["GIT_INDEX_FILE"] = index_path
    return env


def _git(
    repository: str,
    arguments: list[str],
    *,
    input_bytes: bytes | None = None,
    index_path: str | None = None,
) -> bytes:
    result = subprocess.run(
        ["git", "-C", repository, *arguments],
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_secure_env(index_path),
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip()
        _fail(f"git {' '.join(arguments)} failed: {detail}")
    return result.stdout


def _gate_directory(info: os.stat_result, where: str, *, leaf: bool) -> None:
    if not stat.S_ISDIR(info.st_mode) or info.st_nlink < 1:
        _fail(f"{where} is not a linked directory")
    if leaf:
        if info.st_uid != os.geteuid() or info.st_mode & 0o022:
            _fail(f"{where} has an unsafe owner or writable mode")
        return
    if info.st_uid not in (0, os.geteuid()):
        _fail(f"{where} has an unsafe owner ancestor")
    if info.st_mode & 0o022:
        # Root-owned sticky traversal directories (/tmp and platform equivalents)
        # are the only writable ancestors accepted.
        if info.st_uid != 0 or not info.st_mode & stat.S_ISVTX:
            _fail(f"{where} has an unsafe writable ancestor")


def _open_abs_dir(path: str, where: str, *, owner_leaf: bool = True) -> int:
    _absolute_path(path, where)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    current = os.open("/", flags)
    try:
        _gate_directory(os.fstat(current), f"{where}:/", leaf=False)
        pieces = path.split("/")[1:]
        for index, piece in enumerate(pieces):
            child = os.open(piece, flags, dir_fd=current)
            os.close(current)
            current = child
            _gate_directory(
                os.fstat(current),
                f"{where}:{'/'.join(pieces[: index + 1])}",
                leaf=owner_leaf and index == len(pieces) - 1,
            )
        return current
    except OSError as exc:
        os.close(current)
        raise CompositionError(f"cannot securely open {where}: {exc}") from exc
    except BaseException:
        os.close(current)
        raise


def _stat_identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
        info.st_mode,
        info.st_uid,
        info.st_gid,
        info.st_nlink,
    )


def _gate_regular(info: os.stat_result, where: str, *, expected_mode: int | None = None) -> None:
    if not stat.S_ISREG(info.st_mode):
        _fail(f"{where} is not a regular file")
    if info.st_nlink != 1:
        _fail(f"{where} must not be hardlinked")
    if info.st_uid != os.geteuid() or info.st_mode & 0o022:
        _fail(f"{where} has an unsafe owner or writable mode")
    actual_git_mode = 0o100755 if info.st_mode & 0o111 else 0o100644
    if expected_mode is not None and actual_git_mode != expected_mode:
        _fail(f"{where} mode does not match the plan")


def _gate_receipt_file(info: os.stat_result, where: str) -> None:
    if not stat.S_ISREG(info.st_mode) or info.st_nlink < 1:
        _fail(f"{where} is not a linked regular file")
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600:
        _fail(f"{where} must be owner-only mode 0600")


def _open_relative_file(root_fd: int, path: str, where: str) -> tuple[int, os.stat_result]:
    pieces = path.split("/")
    flags_dir = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    current = os.dup(root_fd)
    try:
        for index, piece in enumerate(pieces[:-1]):
            child = os.open(piece, flags_dir, dir_fd=current)
            os.close(current)
            current = child
            _gate_directory(os.fstat(current), f"{where} parent[{index}]", leaf=True)
        try:
            before = os.stat(pieces[-1], dir_fd=current, follow_symlinks=False)
            descriptor = os.open(
                pieces[-1],
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=current,
            )
        except OSError as exc:
            raise CompositionError(f"cannot securely open {where}: {exc}") from exc
        opened = os.fstat(descriptor)
        if _stat_identity(before) != _stat_identity(opened):
            os.close(descriptor)
            _fail(f"{where} changed while it was opened")
        return descriptor, before
    finally:
        os.close(current)


def _open_absolute_file(path: str, where: str) -> tuple[int, os.stat_result]:
    _absolute_path(path, where)
    pieces = path.split("/")[1:]
    flags_dir = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    current = os.open("/", flags_dir)
    try:
        _gate_directory(os.fstat(current), f"{where} parent[/]", leaf=False)
        for index, piece in enumerate(pieces[:-1]):
            child = os.open(piece, flags_dir, dir_fd=current)
            os.close(current)
            current = child
            _gate_directory(os.fstat(current), f"{where} parent[{index}]", leaf=False)
        try:
            before = os.stat(pieces[-1], dir_fd=current, follow_symlinks=False)
            descriptor = os.open(
                pieces[-1],
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=current,
            )
        except OSError as exc:
            raise CompositionError(f"cannot securely open {where}: {exc}") from exc
        opened = os.fstat(descriptor)
        if _stat_identity(before) != _stat_identity(opened):
            os.close(descriptor)
            _fail(f"{where} changed while it was opened")
        return descriptor, before
    finally:
        os.close(current)


def _stat_relative_file(root_fd: int, path: str, where: str) -> os.stat_result:
    pieces = path.split("/")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    current = os.dup(root_fd)
    try:
        for index, piece in enumerate(pieces[:-1]):
            child = os.open(piece, flags, dir_fd=current)
            os.close(current)
            current = child
            _gate_directory(os.fstat(current), f"{where} parent[{index}]", leaf=True)
        return os.stat(pieces[-1], dir_fd=current, follow_symlinks=False)
    except OSError as exc:
        raise CompositionError(f"cannot securely restat {where}: {exc}") from exc
    finally:
        os.close(current)


def _stat_absolute_file(path: str, where: str) -> os.stat_result:
    pieces = path.split("/")[1:]
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    current = os.open("/", flags)
    try:
        _gate_directory(os.fstat(current), f"{where} parent[/]", leaf=False)
        for index, piece in enumerate(pieces[:-1]):
            child = os.open(piece, flags, dir_fd=current)
            os.close(current)
            current = child
            _gate_directory(os.fstat(current), f"{where} parent[{index}]", leaf=False)
        return os.stat(pieces[-1], dir_fd=current, follow_symlinks=False)
    except OSError as exc:
        raise CompositionError(f"cannot securely restat {where}: {exc}") from exc
    finally:
        os.close(current)


def _stream_file(
    descriptor: int,
    before: os.stat_result,
    where: str,
    *,
    repository: str | None = None,
    write_blob: bool = False,
) -> tuple[str, int, str | None]:
    digest = hashlib.sha256()
    size = 0
    process: subprocess.Popen[bytes] | None = None
    if repository is not None:
        args = ["git", "-C", repository, "hash-object"]
        if write_blob:
            args.append("-w")
        args.append("--stdin")
        process = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_secure_env(),
        )
    drift = False
    try:
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
            if process is not None:
                assert process.stdin is not None
                process.stdin.write(chunk)
        after = os.fstat(descriptor)
        if _stat_identity(before) != _stat_identity(after) or size != before.st_size:
            drift = True
    except BaseException:
        if process is not None:
            try:
                if process.stdin is not None:
                    process.stdin.close()
            except (OSError, ValueError):
                pass
            try:
                process.kill()
            except ProcessLookupError:
                pass
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()
            process.wait()
        raise
    finally:
        os.close(descriptor)
    oid: str | None = None
    if process is not None:
        assert process.stdin is not None and process.stdout is not None and process.stderr is not None
        process.stdin.close()
        stdout = process.stdout.read()
        stderr = process.stderr.read()
        process.stdout.close()
        process.stderr.close()
        returncode = process.wait()
        if returncode != 0:
            _fail(f"git hash-object failed for {where}: {stderr.decode('utf-8', 'replace').strip()}")
        oid = _oid(stdout.decode("ascii").strip(), f"{where} blob oid")
    if drift:
        _fail(f"{where} changed while it was read")
    return digest.hexdigest(), size, oid


def _read_artifact(spec: dict[str, Any], role: str) -> dict[str, Any]:
    descriptor, before = _open_absolute_file(spec["path"], role)
    _gate_regular(before, role)
    digest, size, _ = _stream_file(descriptor, before, role)
    after = _stat_absolute_file(spec["path"], role)
    if _stat_identity(before) != _stat_identity(after):
        _fail(f"{role} changed after it was read")
    _gate_regular(after, role)
    if digest != spec["sha256"]:
        _fail(f"{role} SHA-256 drift")
    return {
        "role": role,
        "path": spec["path"],
        "sha256": digest,
        "size": size,
        "mode": stat.S_IMODE(before.st_mode),
        "dev": before.st_dev,
        "inode": before.st_ino,
        "uid": before.st_uid,
        "nlink": before.st_nlink,
        "mtime_ns": before.st_mtime_ns,
    }


def _read_control_deployment(root_fd: int) -> tuple[dict[str, Any], dict[str, Any]]:
    role = "control deployment binding"
    descriptor, before = _open_relative_file(root_fd, "deployment.json", role)
    try:
        _gate_regular(before, role)
        if stat.S_IMODE(before.st_mode) != 0o600:
            _fail("control deployment binding must use mode 0600")
        content = bytearray()
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            content.extend(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    rebound = _stat_relative_file(root_fd, "deployment.json", role)
    if _stat_identity(before) != _stat_identity(after) or _stat_identity(before) != _stat_identity(rebound):
        _fail("control deployment binding changed while it was read")
    _gate_regular(rebound, role)
    raw = bytes(content)
    document = _parse_json(raw, "control deployment binding JSON")
    _keys(document, {"schema", "generation"}, "control deployment binding")
    if _string(document["schema"], "control deployment binding.schema") != CONTROL_DEPLOYMENT_SCHEMA:
        _fail("unsupported control deployment binding schema")
    generation = _integer(document["generation"], "control deployment binding.generation", minimum=1)
    if raw != _canonical_bytes(document) + b"\n":
        _fail("control deployment binding is not canonical JSON")
    return document, {
        "deployment_generation": generation,
        "deployment_sha256": hashlib.sha256(raw).hexdigest(),
        "deployment_size": len(raw),
        "deployment_dev": before.st_dev,
        "deployment_inode": before.st_ino,
        "deployment_uid": before.st_uid,
        "deployment_mode": stat.S_IMODE(before.st_mode),
        "deployment_mtime_ns": before.st_mtime_ns,
    }


def _open_control_root(resolver: _ControlRootResolver) -> tuple[int, dict[str, Any]]:
    if type(resolver) is not _ControlRootResolver or resolver._guard is not _CONTROL_ROOT_GUARD:
        _fail("control root was not produced by the installation resolver")
    path = _absolute_path(resolver.path, "trusted_control_root")
    if os.path.realpath(path) != path:
        _fail("trusted control root is not its canonical physical path")
    root_fd = _open_abs_dir(path, "trusted_control_root")
    try:
        root_info = os.fstat(root_fd)
        if root_info.st_uid != os.geteuid() or stat.S_IMODE(root_info.st_mode) != 0o700:
            _fail("trusted control root must be owned by the effective user with mode 0700")
        rebound_fd = _open_abs_dir(path, "trusted_control_root rebound")
        try:
            rebound_info = os.fstat(rebound_fd)
        finally:
            os.close(rebound_fd)
        if _stat_identity(root_info) != _stat_identity(rebound_info):
            _fail("trusted control root or ancestor identity drift before authority read")
        _, deployment = _read_control_deployment(root_fd)
        identity = {
            "path": path,
            "dev": root_info.st_dev,
            "inode": root_info.st_ino,
            "uid": root_info.st_uid,
            "mode": stat.S_IMODE(root_info.st_mode),
            "nlink": root_info.st_nlink,
            "mtime_ns": root_info.st_mtime_ns,
            **deployment,
        }
        return root_fd, identity
    except BaseException:
        os.close(root_fd)
        raise


def _read_trusted_snapshot_bytes(
    program_id: str,
    snapshot_id: str,
    resolver: _ControlRootResolver,
) -> tuple[bytes, os.stat_result, str, dict[str, Any]]:
    _identifier(program_id, "program_id")
    _identifier(snapshot_id, "authority_snapshot_id")
    root_fd, control_root = _open_control_root(resolver)
    relative = f"snapshots/{program_id}/{snapshot_id}.json"
    descriptor = -1
    try:
        descriptor, before = _open_relative_file(root_fd, relative, "trusted authority snapshot")
        _gate_regular(before, "trusted authority snapshot")
        if stat.S_IMODE(before.st_mode) != 0o600:
            _fail("trusted authority snapshot must use mode 0600")
        content = bytearray()
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            content.extend(chunk)
        after = os.fstat(descriptor)
        rebound = _stat_relative_file(root_fd, relative, "trusted authority snapshot")
        if _stat_identity(before) != _stat_identity(after) or _stat_identity(before) != _stat_identity(rebound):
            _fail("trusted authority snapshot changed while it was read")
        _gate_regular(rebound, "trusted authority snapshot")
        root_after = os.fstat(root_fd)
        if (
            root_after.st_dev != control_root["dev"]
            or root_after.st_ino != control_root["inode"]
            or root_after.st_uid != control_root["uid"]
            or stat.S_IMODE(root_after.st_mode) != control_root["mode"]
        ):
            _fail("trusted control root identity drift")
        return bytes(content), before, os.path.join(resolver.path, relative), control_root
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(root_fd)


def _load_authority(
    program_id: Any,
    snapshot_id: Any,
    *,
    resolver: _ControlRootResolver,
    authority_kind: str,
    resolver_kind: str,
) -> _AuthoritySnapshot:
    program = _identifier(program_id, "program_id")
    identifier = _identifier(snapshot_id, "authority_snapshot_id")
    if resolver.resolver_kind != resolver_kind:
        _fail("control-root resolver kind drift")
    raw, info, path, control_root = _read_trusted_snapshot_bytes(program, identifier, resolver)
    snapshot = _validate_authority_snapshot(
        _parse_json(raw, "trusted authority snapshot JSON"),
        authority_kind=authority_kind,
        resolver_kind=resolver_kind,
    )
    if raw != _canonical_bytes(snapshot) + b"\n":
        _fail("trusted authority snapshot is not canonical JSON")
    if snapshot["program_id"] != program or snapshot["authority_snapshot_id"] != identifier:
        _fail("trusted authority snapshot path binding drift")
    if snapshot["control_generation"] != control_root["deployment_generation"]:
        _fail("trusted authority snapshot deployment generation drift")
    provenance = {
        "schema": AUTHORITY_SCHEMA,
        "authority_kind": authority_kind,
        "resolver_kind": resolver_kind,
        "consumable": authority_kind == AUTHORITY_KIND_PRODUCTION,
        "program_id": program,
        "snapshot_id": identifier,
        "path": path,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size": len(raw),
        "dev": info.st_dev,
        "inode": info.st_ino,
        "uid": info.st_uid,
        "mode": stat.S_IMODE(info.st_mode),
        "mtime_ns": info.st_mtime_ns,
        "control_root": control_root,
    }
    return _AuthoritySnapshot(
        _AUTHORITY_GUARD,
        snapshot,
        raw,
        provenance,
        resolver,
        authority_kind=authority_kind,
        resolver_kind=resolver_kind,
    )


def load_trusted_authority(program_id: Any, snapshot_id: Any) -> _AuthoritySnapshot:
    """Read production authority only from the installation-derived control root.

    There is intentionally no resolver, root, path, environment, or caller
    capability parameter on this production entry point.
    """

    return _load_authority(
        program_id,
        snapshot_id,
        resolver=_production_control_root_resolver(),
        authority_kind=AUTHORITY_KIND_PRODUCTION,
        resolver_kind=RESOLVER_KIND_PRODUCTION,
    )


def _load_synthetic_authority_for_test(
    program_id: Any,
    snapshot_id: Any,
    *,
    capability: _ControlRootResolver,
) -> _AuthoritySnapshot:
    """Explicit test-only loader whose results can never become production READY."""

    if (
        type(capability) is not _ControlRootResolver
        or capability._guard is not _CONTROL_ROOT_GUARD
        or capability.resolver_kind != RESOLVER_KIND_TEST
    ):
        raise TypeError("a test control-root capability is required")
    return _load_authority(
        program_id,
        snapshot_id,
        resolver=capability,
        authority_kind=AUTHORITY_KIND_SYNTHETIC,
        resolver_kind=RESOLVER_KIND_TEST,
    )


def _resolver_for_authority(authority: _AuthoritySnapshot) -> _ControlRootResolver:
    if authority._authority_kind == AUTHORITY_KIND_PRODUCTION:
        # Production always rederives the installation resolver.  No resolver
        # object or path retained in a caller-visible token is trusted.
        resolver = _production_control_root_resolver()
        if resolver.path != authority._resolver_path:
            _fail("installation control-root path drift")
        return resolver
    if authority._authority_kind == AUTHORITY_KIND_SYNTHETIC:
        return _test_control_root_resolver(authority._resolver_path)
    _fail("authority token kind is invalid")


def _refresh_authority(plan: dict[str, Any], authority: _AuthoritySnapshot) -> _AuthoritySnapshot:
    if type(authority) is not _AuthoritySnapshot or authority._guard is not _AUTHORITY_GUARD:
        _fail("authority token was not produced by the fixed trusted control root loader")
    if authority._authority_kind == AUTHORITY_KIND_PRODUCTION:
        fresh = load_trusted_authority(plan["program_id"], plan["authority_snapshot_id"])
    elif authority._authority_kind == AUTHORITY_KIND_SYNTHETIC:
        fresh = _load_synthetic_authority_for_test(
            plan["program_id"],
            plan["authority_snapshot_id"],
            capability=_resolver_for_authority(authority),
        )
    else:
        _fail("authority token kind is invalid")
    if fresh.raw != authority.raw or fresh.provenance != authority.provenance:
        _fail("trusted authority snapshot changed after attestation")
    expected = _authority_projection(
        plan,
        authority_kind=authority._authority_kind,
        resolver_kind=authority._resolver_kind,
    )
    if fresh.snapshot != expected:
        _fail("plan is not the exact projection of trusted coordinator authority")
    return fresh


def _binding_sha(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _accepted_event_document(plan: dict[str, Any], predecessor: dict[str, Any]) -> dict[str, Any]:
    event = predecessor["accepted_event"]
    return {
        "schema": ACCEPTED_EVENT_SCHEMA,
        "program_id": plan["program_id"],
        "task_id": predecessor["task_id"],
        "event_id": event["id"],
        "sequence": event["sequence"],
        "task_state": predecessor["status"],
        "verification_run": predecessor["verification_run"],
        "supersession": predecessor["supersession"],
        "generation": predecessor["generation"],
        "parent_generation": predecessor["parent_generation"],
        "task_definition_sha256": predecessor["task_definition"]["sha256"],
        "evidence_binding_sha256": _binding_sha(predecessor["evidence"]),
        "delta_binding_sha256": _binding_sha(predecessor["delta"]),
    }


def _read_accepted_event(plan: dict[str, Any], predecessor: dict[str, Any], role: str) -> dict[str, Any]:
    spec = predecessor["accepted_event"]
    descriptor, before = _open_absolute_file(spec["path"], role)
    _gate_regular(before, role)
    content = bytearray()
    try:
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            content.extend(chunk)
        after = os.fstat(descriptor)
        if _stat_identity(before) != _stat_identity(after):
            _fail(f"{role} changed while it was read")
    finally:
        os.close(descriptor)
    rebound = _stat_absolute_file(spec["path"], role)
    if _stat_identity(before) != _stat_identity(rebound):
        _fail(f"{role} changed after it was read")
    raw = bytes(content)
    if hashlib.sha256(raw).hexdigest() != spec["sha256"]:
        _fail(f"{role} SHA-256 drift")
    parsed = _parse_json(raw, f"{role} JSON")
    expected = _accepted_event_document(plan, predecessor)
    if raw != _canonical_bytes(parsed) + b"\n":
        _fail(f"{role} is not canonical JSON")
    if parsed != expected:
        _fail(f"{role} does not project accepted coordinator authority")
    return {
        "role": role,
        "path": spec["path"],
        "sha256": spec["sha256"],
        "size": len(raw),
        "mode": stat.S_IMODE(before.st_mode),
        "dev": before.st_dev,
        "inode": before.st_ino,
        "uid": before.st_uid,
        "nlink": before.st_nlink,
        "mtime_ns": before.st_mtime_ns,
    }


def _read_accepted_blob(
    control_fd: int,
    entry: dict[str, Any],
    task_id: str,
    repository: str,
    *,
    write_blob: bool,
) -> dict[str, Any]:
    digest = entry["accepted_blob"]["sha256"]
    relative = f"accepted-blobs/{digest[:2]}/{digest}"
    role = f"{task_id}:{entry['path']}:accepted-blob"
    descriptor = -1
    try:
        descriptor, before = _open_relative_file(control_fd, relative, role)
        _gate_regular(before, role)
        if stat.S_IMODE(before.st_mode) != 0o600:
            _authority_input_missing(f"{role} must use owner-only mode 0600")
        streaming_descriptor = descriptor
        descriptor = -1
        raw_sha, raw_size, blob_oid = _stream_file(
            streaming_descriptor,
            before,
            role,
            repository=repository,
            write_blob=write_blob,
        )
        rebound = _stat_relative_file(control_fd, relative, role)
        if _stat_identity(before) != _stat_identity(rebound):
            _authority_input_missing(f"{role} changed after it was read")
        _gate_regular(rebound, role)
        if stat.S_IMODE(rebound.st_mode) != 0o600:
            _authority_input_missing(f"{role} mode drift")
        if raw_sha != digest or raw_size != entry["accepted_blob"]["size"]:
            _authority_input_missing(f"{role} size or SHA-256 drift")
        if raw_sha != entry["after_sha256"] or raw_size != entry["size"]:
            _authority_input_missing(f"{role} no longer matches accepted task authority")
        assert blob_oid is not None
        return {
            "blob_oid": blob_oid,
            "raw_sha256": raw_sha,
            "size": raw_size,
            "accepted_blob_relative_path": relative,
            "dev": before.st_dev,
            "inode": before.st_ino,
            "uid": before.st_uid,
            "file_mode": stat.S_IMODE(before.st_mode),
            "nlink": before.st_nlink,
            "mtime_ns": before.st_mtime_ns,
        }
    except CompositionError as exc:
        if str(exc).startswith(f"{AUTHORITY_INPUT_MISSING}:"):
            raise
        _authority_input_missing(f"{role} unavailable or unsafe: {exc}")
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _assert_absent(root_fd: int, path: str, where: str) -> None:
    pieces = path.split("/")
    flags_dir = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    current = os.dup(root_fd)
    try:
        for index, piece in enumerate(pieces[:-1]):
            try:
                child = os.open(piece, flags_dir, dir_fd=current)
            except FileNotFoundError:
                return
            os.close(current)
            current = child
            _gate_directory(os.fstat(current), f"{where} parent[{index}]", leaf=True)
        try:
            os.stat(pieces[-1], dir_fd=current, follow_symlinks=False)
        except FileNotFoundError:
            return
        _fail(f"{where} delete target still exists")
    except OSError as exc:
        raise CompositionError(f"cannot securely prove absence for {where}: {exc}") from exc
    finally:
        os.close(current)


def _git_paths(repository: str, base: str) -> list[str]:
    # Bind all three Git-visible views.  A staged-only path can disappear from the
    # commit-to-worktree net diff when the worktree is restored to base, while an
    # unstaged path can disappear from the cached view.  The union rejects both.
    safe_diff = ["--no-ext-diff", "--no-textconv", "--name-only", "-z", "--no-renames"]
    worktree = _git(repository, ["diff", *safe_diff, base, "--"])
    cached = _git(repository, ["diff", "--cached", *safe_diff, base, "--"])
    unstaged = _git(repository, ["diff", *safe_diff, "--"])
    untracked = _git(repository, ["ls-files", "--others", "--exclude-standard", "-z", "--"])
    paths: set[str] = set()
    for raw in worktree.split(b"\0") + cached.split(b"\0") + unstaged.split(b"\0") + untracked.split(b"\0"):
        if not raw:
            continue
        try:
            path = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CompositionError("Git-visible dirty path is not UTF-8") from exc
        paths.add(_delta_path(path, "Git-visible dirty path"))
    collisions: dict[str, str] = {}
    for path in paths:
        key = unicodedata.normalize("NFKC", path).casefold()
        if key in collisions and collisions[key] != path:
            _fail(f"Git-visible NFKC/casefold collision: {collisions[key]!r} and {path!r}")
        collisions[key] = path
    return sorted(paths)


def _tree_entries(repository: str, treeish: str) -> dict[str, tuple[int, str]]:
    output = _git(repository, ["ls-tree", "-r", "-z", treeish])
    result: dict[str, tuple[int, str]] = {}
    for record in output.split(b"\0"):
        if not record:
            continue
        try:
            header, raw_path = record.split(b"\t", 1)
            raw_mode, raw_type, raw_oid = header.split(b" ", 2)
            path = raw_path.decode("utf-8")
            mode = int(raw_mode, 8)
            object_type = raw_type.decode("ascii")
            oid = raw_oid.decode("ascii")
        except (ValueError, UnicodeError) as exc:
            raise CompositionError("Git returned an invalid tree entry") from exc
        _tree_entry_path(path, "Git tree path")
        if object_type != "blob":
            # Untouched submodules may remain in the base, but a delta can never
            # target them.  Keeping them in the full entry set preserves the tree.
            if object_type != "commit" or mode != 0o160000:
                _fail(f"unsupported Git tree entry at {path}")
        result[path] = (mode, _oid(oid, f"tree entry {path}"))
    _assert_no_path_collisions(result, "Git tree")
    return result


def _assert_no_path_collisions(paths: Any, where: str) -> None:
    collisions: dict[str, str] = {}
    for path in paths:
        key = unicodedata.normalize("NFKC", path).casefold()
        previous = collisions.get(key)
        if previous is not None and previous != path:
            _fail(f"{where} NFKC/casefold collision: {previous!r} and {path!r}")
        collisions[key] = path


def _blob_sha256(repository: str, oid: str) -> str:
    process = subprocess.Popen(
        ["git", "-C", repository, "cat-file", "blob", oid],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_secure_env(),
    )
    assert process.stdout is not None and process.stderr is not None
    digest = hashlib.sha256()
    while True:
        chunk = process.stdout.read(1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
    stderr = process.stderr.read()
    process.stdout.close()
    process.stderr.close()
    returncode = process.wait()
    if returncode != 0:
        _fail(f"git cat-file failed: {stderr.decode('utf-8', 'replace').strip()}")
    return digest.hexdigest()


def _entry_set_sha(entries: dict[str, tuple[int, str]]) -> str:
    serial = [
        {"mode": mode, "oid": oid, "path": path}
        for path, (mode, oid) in sorted(entries.items())
    ]
    return hashlib.sha256(_canonical_bytes(serial)).hexdigest()


def _prepare(
    plan: dict[str, Any],
    repository: str,
    authority: _AuthoritySnapshot,
    *,
    write_blobs: bool,
) -> dict[str, Any]:
    root_fd = _open_abs_dir(repository, "repository")
    repository_before = os.fstat(root_fd)
    os.close(root_fd)
    resolved = _git(repository, ["rev-parse", "--verify", f"{plan['logical_base_commit']}^{{commit}}"])
    if resolved.decode("ascii").strip() != plan["logical_base_commit"]:
        _fail("logical base commit did not resolve exactly")
    base_entries = _tree_entries(repository, plan["logical_base_commit"])
    final_entries = dict(base_entries)
    raw_sha_cache: dict[str, str] = {}
    artifacts = [
        _read_artifact(plan["successor_task_definition"], "successor-task-definition"),
        _read_artifact(plan["successor_brief"], "successor-brief"),
    ]
    source_roots: list[dict[str, Any]] = []
    blobs: list[dict[str, Any]] = []
    task_by_id = {item["task_id"]: item for item in plan["predecessors"]}
    control_fd, control_root = _open_control_root(_resolver_for_authority(authority))
    try:
        if control_root != authority.provenance["control_root"]:
            _fail("trusted control root or deployment generation drift")
        for predecessor in plan["predecessors"]:
            task_id = predecessor["task_id"]
            artifacts.append(_read_artifact(predecessor["task_definition"], f"{task_id}:task-definition"))
            artifacts.append(
                _read_accepted_event(
                    plan,
                    predecessor,
                    f"{task_id}:accepted-event:{predecessor['accepted_event']['sequence']}",
                )
            )
            for evidence in predecessor["evidence"]:
                artifacts.append(_read_artifact(evidence, f"{task_id}:evidence:{evidence['id']}"))

            for entry in predecessor["delta"]:
                path = entry["path"]
                operation = entry["operation"]
                current = final_entries.get(path)
                if current is None:
                    current_sha = ZERO_SHA256
                else:
                    current_mode, current_oid = current
                    if current_mode not in (0o100644, 0o100755):
                        _fail(f"delta targets unsupported base entry at {path}")
                    cache_key = f"{current_oid}"
                    if cache_key not in raw_sha_cache:
                        raw_sha_cache[cache_key] = _blob_sha256(repository, current_oid)
                    current_sha = raw_sha_cache[cache_key]
                if entry["before_sha256"] != current_sha:
                    _fail(f"{task_id}:{path} before SHA-256 does not match staged content")

                if operation == "add" and current is not None:
                    _fail(f"{task_id}:{path} add targets an existing entry")
                if operation in ("modify", "delete") and current is None:
                    _fail(f"{task_id}:{path} {operation} targets an absent entry")
                if operation == "delete":
                    assert current is not None
                    if entry["mode"] != current[0]:
                        _fail(f"{task_id}:{path} delete mode does not match staged content")
                    del final_entries[path]
                    blob_oid: str | None = None
                    raw_sha = ZERO_SHA256
                    raw_size = 0
                    accepted_relative = None
                    raw_dev = raw_inode = raw_uid = raw_file_mode = raw_nlink = raw_mtime_ns = None
                else:
                    accepted = _read_accepted_blob(
                        control_fd,
                        entry,
                        task_id,
                        repository,
                        write_blob=write_blobs,
                    )
                    blob_oid = accepted["blob_oid"]
                    raw_sha = accepted["raw_sha256"]
                    raw_size = accepted["size"]
                    final_entries[path] = (entry["mode"], blob_oid)
                    raw_sha_cache[blob_oid] = raw_sha
                    accepted_relative = accepted["accepted_blob_relative_path"]
                    raw_dev = accepted["dev"]
                    raw_inode = accepted["inode"]
                    raw_uid = accepted["uid"]
                    raw_file_mode = accepted["file_mode"]
                    raw_nlink = accepted["nlink"]
                    raw_mtime_ns = accepted["mtime_ns"]
                record = {
                    "task_id": task_id,
                    "path": path,
                    "operation": operation,
                    "raw_sha256": raw_sha,
                    "size": raw_size,
                    "mode": entry["mode"],
                    "blob_oid": blob_oid,
                    "accepted_blob_relative_path": accepted_relative,
                    "dev": raw_dev,
                    "inode": raw_inode,
                    "uid": raw_uid,
                    "file_mode": raw_file_mode,
                    "nlink": raw_nlink,
                    "mtime_ns": raw_mtime_ns,
                }
                blobs.append(record)

        for source in plan["source_roots"]:
            root_id = source["id"]
            root_path = source["path"]
            root_fd = _open_abs_dir(root_path, f"{root_id}:source-root")
            try:
                root_before = os.fstat(root_fd)
                dirty_paths = _git_paths(root_path, plan["logical_base_commit"])
                declared_paths = [item["path"] for item in source["cumulative_inventory"]]
                if dirty_paths != declared_paths:
                    _fail(
                        f"{root_id} Git-visible cumulative inventory mismatch; "
                        f"declared={declared_paths}, actual={dirty_paths}"
                    )
                observed: list[dict[str, Any]] = []
                for item in source["cumulative_inventory"]:
                    path = item["path"]
                    role = f"{root_id}:{path}:cumulative-inventory"
                    if item["state"] == "absent":
                        _assert_absent(root_fd, path, role)
                        observed.append(
                            {
                                "path": path,
                                "selected_predecessor": item["selected_predecessor"],
                                "state": "absent",
                                "sha256": ZERO_SHA256,
                                "size": 0,
                                "mode": item["mode"],
                                "dev": None,
                                "inode": None,
                                "uid": None,
                                "nlink": None,
                                "mtime_ns": None,
                            }
                        )
                        continue
                    descriptor, before = _open_relative_file(root_fd, path, role)
                    _gate_regular(before, role, expected_mode=item["mode"])
                    digest, size, _ = _stream_file(descriptor, before, role)
                    rebound = _stat_relative_file(root_fd, path, role)
                    if _stat_identity(before) != _stat_identity(rebound):
                        _fail(f"{role} changed after it was read")
                    _gate_regular(rebound, role, expected_mode=item["mode"])
                    if digest != item["sha256"] or size != item["size"]:
                        _fail(f"{role} does not match final accepted content identity")
                    observed.append(
                        {
                            "path": path,
                            "selected_predecessor": item["selected_predecessor"],
                            "state": "present",
                            "sha256": digest,
                            "size": size,
                            "mode": item["mode"],
                            "dev": before.st_dev,
                            "inode": before.st_ino,
                            "uid": before.st_uid,
                            "nlink": before.st_nlink,
                            "mtime_ns": before.st_mtime_ns,
                        }
                    )
                root_after = os.fstat(root_fd)
                if _stat_identity(root_before) != _stat_identity(root_after):
                    _fail(f"{root_id} source root changed during inventory")
                _gate_directory(root_after, f"{root_id}:source-root", leaf=True)
                if root_before.st_nlink != root_after.st_nlink or root_before.st_uid != root_after.st_uid:
                    _fail(f"{root_id} source root identity drift")
                rebound_fd = _open_abs_dir(root_path, f"{root_id}:source-root-rebind")
                try:
                    if _stat_identity(root_before) != _stat_identity(os.fstat(rebound_fd)):
                        _fail(f"{root_id} source root path was rebound")
                finally:
                    os.close(rebound_fd)
                source_roots.append(
                    {
                        "root_id": root_id,
                        "task_ids": source["task_ids"],
                        "path": root_path,
                        "dev": root_before.st_dev,
                        "inode": root_before.st_ino,
                        "mode": stat.S_IMODE(root_before.st_mode),
                        "uid": root_before.st_uid,
                        "nlink": root_before.st_nlink,
                        "size": root_before.st_size,
                        "mtime_ns": root_before.st_mtime_ns,
                        "dirty_paths_sha256": hashlib.sha256(_canonical_bytes(dirty_paths)).hexdigest(),
                        "declared_inventory_sha256": hashlib.sha256(
                            _canonical_bytes(source["cumulative_inventory"])
                        ).hexdigest(),
                        "observed_inventory_sha256": hashlib.sha256(
                            _canonical_bytes(observed)
                        ).hexdigest(),
                    }
                )
            finally:
                os.close(root_fd)

        rebound_control_fd, rebound_control = _open_control_root(_resolver_for_authority(authority))
        os.close(rebound_control_fd)
        if rebound_control != control_root:
            _fail("trusted control root changed during accepted blob reads")
    finally:
        os.close(control_fd)

    # A dependency closure containing a task that never precedes the current task
    # is already rejected by validate_plan.  Touch the map here to keep preparation
    # explicitly tied to the full selected set rather than a filtered subset.
    if set(task_by_id) != {item["task_id"] for item in plan["predecessors"]}:
        _fail("predecessor set changed during validation")
    _assert_no_path_collisions(final_entries, "synthetic final tree")
    repository_fd = _open_abs_dir(repository, "repository-rebind")
    try:
        if _stat_identity(repository_before) != _stat_identity(os.fstat(repository_fd)):
            _fail("repository root path was rebound during composition")
    finally:
        os.close(repository_fd)
    return {
        "artifacts": artifacts,
        "source_roots": source_roots,
        "blobs": blobs,
        "final_entries": final_entries,
        "entry_set_sha256": _entry_set_sha(final_entries),
    }


def _write_tree_commit(plan: dict[str, Any], repository: str, prepared: dict[str, Any]) -> tuple[str, str]:
    with tempfile.TemporaryDirectory(prefix="sulde-predecessor-index-") as temporary:
        index_path = os.path.join(temporary, "index")
        _git(repository, ["read-tree", plan["logical_base_commit"]], index_path=index_path)
        for record in prepared["blobs"]:
            if record["operation"] == "delete":
                _git(
                    repository,
                    ["update-index", "--force-remove", "--", record["path"]],
                    index_path=index_path,
                )
            else:
                _git(
                    repository,
                    [
                        "update-index",
                        "--add",
                        "--cacheinfo",
                        f"{record['mode']:o},{record['blob_oid']},{record['path']}",
                    ],
                    index_path=index_path,
                )
        tree_oid = _oid(
            _git(repository, ["write-tree"], index_path=index_path).decode("ascii").strip(),
            "synthetic tree oid",
        )
    # Never ask commit-tree to interpret repository config.  Write the exact raw
    # object whose bytes are independently derived from the closed plan.
    commit_bytes = _expected_commit_bytes(plan, tree_oid)
    commit_oid = _oid(
        _git(
            repository,
            ["hash-object", "-t", "commit", "-w", "--stdin"],
            input_bytes=commit_bytes,
        ).decode("ascii").strip(),
        "synthetic commit oid",
    )
    return tree_oid, commit_oid


def _receipt_paths(receipt_root: str, target_id: str, receipt_sha: str | None = None) -> tuple[str, str | None]:
    target_name = hashlib.sha256(target_id.encode("utf-8")).hexdigest() + ".ready"
    target_path = os.path.join(receipt_root, "targets", target_name)
    content_path = None if receipt_sha is None else os.path.join(receipt_root, "receipts", receipt_sha + ".json")
    return target_path, content_path


def _ensure_child_dir(parent_fd: int, name: str) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        os.mkdir(name, 0o700, dir_fd=parent_fd)
        os.fsync(parent_fd)
    except FileExistsError:
        pass
    child = os.open(name, flags, dir_fd=parent_fd)
    info = os.fstat(child)
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700 or info.st_nlink < 1:
        os.close(child)
        _fail(f"receipt directory {name} is not owner-only")
    return child


def _validate_receipt_root(receipt_root: str) -> None:
    descriptor = _open_abs_dir(receipt_root, "receipt_root")
    try:
        info = os.fstat(descriptor)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700 or info.st_nlink < 1:
            _fail("receipt_root must be an owner-only linked directory")
    finally:
        os.close(descriptor)


def _fault(selected: str | None, stage: str) -> None:
    if selected == stage:
        raise CompositionCrash(f"injected crash at {stage}")


def _read_dir_file(directory_fd: int, name: str, where: str) -> tuple[bytes, os.stat_result]:
    descriptor = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd)
    try:
        before = os.fstat(descriptor)
        _gate_receipt_file(before, where)
        if before.st_uid != os.geteuid() or stat.S_IMODE(before.st_mode) != 0o600:
            _fail(f"{where} has unsafe ownership or mode")
        content = bytearray()
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            content.extend(chunk)
        after = os.fstat(descriptor)
        if _stat_identity(before) != _stat_identity(after):
            _fail(f"{where} changed while it was read")
        return bytes(content), before
    finally:
        os.close(descriptor)


def _validate_candidate_bytes(raw: bytes, expected: bytes, where: str) -> None:
    if raw != expected:
        _fail(f"{where} content drift")
    parsed = _validate_receipt(_parse_json(raw, f"{where} JSON"))
    if raw != _canonical_bytes(parsed) + b"\n":
        _fail(f"{where} is not canonical JSON")


def _discard_staging(root_fd: int, temporary_name: str) -> None:
    try:
        os.unlink(temporary_name, dir_fd=root_fd)
    except FileNotFoundError:
        return
    os.fsync(root_fd)


def _content_candidate(
    root_fd: int,
    receipts_fd: int,
    content_name: str,
    receipt_bytes: bytes,
    fault_stage: str | None,
    *,
    recover_staging: bool,
) -> os.stat_result:
    """Return one durable content candidate with no staging hardlink."""

    temporary_names = (
        sorted(name for name in os.listdir(root_fd) if name.startswith(".tmp-"))
        if recover_staging
        else []
    )
    if any(not _TEMP_NAME.fullmatch(name) for name in temporary_names):
        _fail("receipt root contains an uncontrolled staging alias")
    try:
        content_raw, content_info = _read_dir_file(receipts_fd, content_name, "content candidate")
        _validate_candidate_bytes(content_raw, receipt_bytes, "content candidate")
        content_exists = True
    except FileNotFoundError:
        content_info = None
        content_exists = False

    if temporary_names:
        if len(temporary_names) != 1:
            _fail("receipt root contains ambiguous staging aliases")
        temporary_name = temporary_names[0]
        temporary_raw, temporary_info = _read_dir_file(root_fd, temporary_name, "staging receipt")
        _validate_candidate_bytes(temporary_raw, receipt_bytes, "staging receipt")
        if content_exists:
            assert content_info is not None
            if (temporary_info.st_dev, temporary_info.st_ino) != (content_info.st_dev, content_info.st_ino):
                _fail("staging alias is not the content candidate inode")
        else:
            if temporary_info.st_nlink != 1:
                _fail("standalone staging receipt has an unknown hardlink")
            temporary_fd = os.open(
                temporary_name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=root_fd,
            )
            try:
                os.fsync(temporary_fd)
            finally:
                os.close(temporary_fd)
            try:
                os.link(
                    temporary_name,
                    content_name,
                    src_dir_fd=root_fd,
                    dst_dir_fd=receipts_fd,
                    follow_symlinks=False,
                )
            except FileExistsError:
                _fail("content candidate raced with staging recovery")
            _fault(fault_stage, "after_content_publish")
            os.fsync(receipts_fd)
            _fault(fault_stage, "after_content_fsync")
            content_raw, content_info = _read_dir_file(receipts_fd, content_name, "content candidate")
            _validate_candidate_bytes(content_raw, receipt_bytes, "content candidate")
            _, temporary_info = _read_dir_file(root_fd, temporary_name, "staging receipt")
        assert content_info is not None
        if temporary_info.st_nlink != 2 or content_info.st_nlink != 2:
            _fail("staging recovery found an unknown hardlink")
        os.unlink(temporary_name, dir_fd=root_fd)
        _fault(fault_stage, "after_staging_unlink")
        os.fsync(root_fd)
        _fault(fault_stage, "after_staging_fsync")
        _, content_info = _read_dir_file(receipts_fd, content_name, "content candidate")
        if content_info.st_nlink != 1:
            _fail("content candidate has an unknown hardlink before READY")
        return content_info

    if content_exists:
        assert content_info is not None
        if content_info.st_nlink not in (1, 2):
            _fail("content candidate has an unknown hardlink before READY")
        return content_info

    temporary_name = ".tmp-" + secrets.token_hex(16)
    descriptor = os.open(
        temporary_name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
        dir_fd=root_fd,
    )
    try:
        view = memoryview(receipt_bytes)
        written = 0
        while written < len(view):
            count = os.write(descriptor, view[written:])
            if count <= 0:
                _fail("receipt write made no progress")
            written += count
        _fault(fault_stage, "after_receipt_write")
        os.fsync(descriptor)
        _fault(fault_stage, "after_receipt_fsync")
    except BaseException:
        _discard_staging(root_fd, temporary_name)
        raise
    finally:
        os.close(descriptor)
    try:
        raw, temporary_info = _read_dir_file(root_fd, temporary_name, "staging receipt")
        _validate_candidate_bytes(raw, receipt_bytes, "staging receipt")
    except BaseException:
        _discard_staging(root_fd, temporary_name)
        raise
    try:
        os.link(
            temporary_name,
            content_name,
            src_dir_fd=root_fd,
            dst_dir_fd=receipts_fd,
            follow_symlinks=False,
        )
    except FileExistsError:
        existing_raw, existing_info = _read_dir_file(receipts_fd, content_name, "content candidate")
        _validate_candidate_bytes(existing_raw, receipt_bytes, "content candidate")
        os.unlink(temporary_name, dir_fd=root_fd)
        os.fsync(root_fd)
        if existing_info.st_nlink not in (1, 2):
            _fail("concurrent content candidate has an unknown hardlink")
        return existing_info
    except BaseException:
        _discard_staging(root_fd, temporary_name)
        raise
    _fault(fault_stage, "after_content_publish")
    os.fsync(receipts_fd)
    _fault(fault_stage, "after_content_fsync")
    _, temporary_info = _read_dir_file(root_fd, temporary_name, "staging receipt")
    _, content_info = _read_dir_file(receipts_fd, content_name, "content candidate")
    if temporary_info.st_nlink != 2 or content_info.st_nlink != 2:
        _fail("new content candidate acquired an unknown hardlink")
    os.unlink(temporary_name, dir_fd=root_fd)
    _fault(fault_stage, "after_staging_unlink")
    os.fsync(root_fd)
    _fault(fault_stage, "after_staging_fsync")
    _, content_info = _read_dir_file(receipts_fd, content_name, "content candidate")
    if content_info.st_nlink != 1:
        _fail("content candidate has an unknown hardlink before READY")
    return content_info


def _publish_receipt(
    receipt_root: str,
    target_id: str,
    receipt_bytes: bytes,
    receipt_sha: str,
    fault_stage: str | None,
    *,
    recover_staging: bool = False,
) -> tuple[str, str]:
    root_fd = _open_abs_dir(receipt_root, "receipt_root")
    targets_fd = receipts_fd = -1
    try:
        if stat.S_IMODE(os.fstat(root_fd).st_mode) != 0o700:
            _fail("receipt_root must be owner-only mode 0700")
        targets_fd = _ensure_child_dir(root_fd, "targets")
        receipts_fd = _ensure_child_dir(root_fd, "receipts")
        target_name = hashlib.sha256(target_id.encode("utf-8")).hexdigest() + ".ready"
        content_name = receipt_sha + ".json"
        content_info = _content_candidate(
            root_fd,
            receipts_fd,
            content_name,
            receipt_bytes,
            fault_stage,
            recover_staging=recover_staging,
        )

        if content_info.st_nlink == 2:
            deadline = time.monotonic() + _CONCURRENT_PUBLICATION_TIMEOUT_SECONDS
            while True:
                try:
                    target_raw, target_info = _read_dir_file(
                        targets_fd, target_name, "READY target"
                    )
                except FileNotFoundError:
                    content_raw, current_info = _read_dir_file(
                        receipts_fd, content_name, "content candidate"
                    )
                    _validate_candidate_bytes(
                        content_raw, receipt_bytes, "content candidate"
                    )
                    if (current_info.st_dev, current_info.st_ino) != (
                        content_info.st_dev,
                        content_info.st_ino,
                    ):
                        _fail("concurrent content candidate inode changed")
                    if current_info.st_nlink == 1:
                        content_info = current_info
                        break
                    if current_info.st_nlink != 2:
                        _fail("concurrent content candidate has an unknown hardlink")
                    if time.monotonic() >= deadline:
                        _fail("concurrent READY publication did not settle")
                    time.sleep(0.001)
                    continue
                _validate_candidate_bytes(target_raw, receipt_bytes, "READY target")
                if (target_info.st_dev, target_info.st_ino) != (
                    content_info.st_dev,
                    content_info.st_ino,
                ):
                    _fail("content candidate has an uncontrolled second hardlink")
                os.fsync(targets_fd)
                target_path, content_path = _receipt_paths(
                    receipt_root, target_id, receipt_sha
                )
                assert content_path is not None
                return target_path, content_path

        # Every content/source/object/conflict check above is complete.  This
        # no-replace hardlink is the sole READY linearization point.
        try:
            os.link(
                content_name,
                target_name,
                src_dir_fd=receipts_fd,
                dst_dir_fd=targets_fd,
                follow_symlinks=False,
            )
        except FileExistsError:
            target_raw, target_info = _read_dir_file(targets_fd, target_name, "READY target")
            try:
                _validate_candidate_bytes(target_raw, receipt_bytes, "READY target")
                same_inode = (target_info.st_dev, target_info.st_ino) == (content_info.st_dev, content_info.st_ino)
                if not same_inode:
                    _fail("target is already bound to a different composition plan")
            except CompositionError:
                if content_info.st_nlink == 1:
                    os.unlink(content_name, dir_fd=receipts_fd)
                    os.fsync(receipts_fd)
                raise
        _fault(fault_stage, "after_target_publish")
        os.fsync(targets_fd)
        _fault(fault_stage, "after_target_fsync")
        target_path, content_path = _receipt_paths(receipt_root, target_id, receipt_sha)
        assert content_path is not None
        return target_path, content_path
    except CompositionError:
        raise
    except OSError as exc:
        raise CompositionError(f"receipt durable publication failed: {exc}") from exc
    finally:
        if receipts_fd >= 0:
            os.close(receipts_fd)
        if targets_fd >= 0:
            os.close(targets_fd)
        os.close(root_fd)


def _validate_receipt(value: Any) -> dict[str, Any]:
    receipt = _exact_dict(value, "receipt")
    _keys(
        receipt,
        {
            "schema",
            "state",
            "state_history",
            "consumable",
            "authority_kind",
            "resolver_kind",
            "plan_sha256",
            "target_id",
            "successor_task_id",
            "logical_base_commit",
            "task_definition_sha256",
            "brief_sha256",
            "helper_generation",
            "authority",
            "artifacts",
            "source_roots",
            "blobs",
            "tree_oid",
            "commit_oid",
            "entry_set_sha256",
        },
        "receipt",
    )
    if _string(receipt["schema"], "receipt.schema") != RECEIPT_SCHEMA:
        _fail("unsupported receipt schema")
    receipt_state = _string(receipt["state"], "receipt.state")
    authority_kind = _string(receipt["authority_kind"], "receipt.authority_kind")
    resolver_kind = _string(receipt["resolver_kind"], "receipt.resolver_kind")
    if type(receipt["consumable"]) is not bool:
        _fail("receipt.consumable must be a JSON boolean")
    production_binding = (
        receipt_state == "READY"
        and receipt["consumable"] is True
        and authority_kind == AUTHORITY_KIND_PRODUCTION
        and resolver_kind == RESOLVER_KIND_PRODUCTION
    )
    synthetic_binding = (
        receipt_state == "SYNTHETIC_READY"
        and receipt["consumable"] is False
        and authority_kind == AUTHORITY_KIND_SYNTHETIC
        and resolver_kind == RESOLVER_KIND_TEST
    )
    if not (production_binding or synthetic_binding):
        _fail("receipt authority disposition is inconsistent or consumable synthetic authority")
    history = _exact_list(receipt["state_history"], "receipt.state_history")
    expected_history = READY_STATES if production_binding else SYNTHETIC_READY_STATES
    if history != expected_history or any(type(item) is not str for item in history):
        _fail("receipt state history is invalid")
    _sha256(receipt["plan_sha256"], "receipt.plan_sha256")
    _identifier(receipt["target_id"], "receipt.target_id")
    _identifier(receipt["successor_task_id"], "receipt.successor_task_id")
    _oid(receipt["logical_base_commit"], "receipt.logical_base_commit")
    _sha256(receipt["task_definition_sha256"], "receipt.task_definition_sha256")
    _sha256(receipt["brief_sha256"], "receipt.brief_sha256")
    _integer(receipt["helper_generation"], "receipt.helper_generation", minimum=1)
    authority = _exact_dict(receipt["authority"], "receipt.authority")
    _keys(
        authority,
        {
            "schema",
            "authority_kind",
            "resolver_kind",
            "consumable",
            "program_id",
            "snapshot_id",
            "path",
            "sha256",
            "size",
            "dev",
            "inode",
            "uid",
            "mode",
            "mtime_ns",
            "control_root",
        },
        "receipt.authority",
    )
    if _string(authority["schema"], "receipt.authority.schema") != AUTHORITY_SCHEMA:
        _fail("receipt authority schema is invalid")
    if (
        _string(authority["authority_kind"], "receipt.authority.authority_kind")
        != authority_kind
        or _string(authority["resolver_kind"], "receipt.authority.resolver_kind")
        != resolver_kind
        or type(authority["consumable"]) is not bool
        or authority["consumable"] is not receipt["consumable"]
    ):
        _fail("receipt authority provenance disposition drift")
    _identifier(authority["program_id"], "receipt.authority.program_id")
    _identifier(authority["snapshot_id"], "receipt.authority.snapshot_id")
    _absolute_path(authority["path"], "receipt.authority.path")
    _sha256(authority["sha256"], "receipt.authority.sha256")
    for field in ("size", "dev", "inode", "uid", "mode", "mtime_ns"):
        _integer(authority[field], f"receipt.authority.{field}")
    control_root = _exact_dict(authority["control_root"], "receipt.authority.control_root")
    _keys(
        control_root,
        {
            "path",
            "dev",
            "inode",
            "uid",
            "mode",
            "nlink",
            "mtime_ns",
            "deployment_generation",
            "deployment_sha256",
            "deployment_size",
            "deployment_dev",
            "deployment_inode",
            "deployment_uid",
            "deployment_mode",
            "deployment_mtime_ns",
        },
        "receipt.authority.control_root",
    )
    _absolute_path(control_root["path"], "receipt.authority.control_root.path")
    _sha256(control_root["deployment_sha256"], "receipt.authority.control_root.deployment_sha256")
    for field in set(control_root) - {"path", "deployment_sha256"}:
        _integer(control_root[field], f"receipt.authority.control_root.{field}")
    if authority["mode"] != 0o600:
        _fail("receipt authority snapshot mode is not owner-only")
    if (
        control_root["mode"] != 0o700
        or control_root["deployment_mode"] != 0o600
        or control_root["nlink"] < 1
        or control_root["deployment_generation"] < 1
    ):
        _fail("receipt control-root provenance is unsafe")
    artifacts = _exact_list(receipt["artifacts"], "receipt.artifacts")
    for index, raw in enumerate(artifacts):
        where = f"receipt.artifacts[{index}]"
        item = _exact_dict(raw, where)
        _keys(item, {"role", "path", "sha256", "size", "mode", "dev", "inode", "uid", "nlink", "mtime_ns"}, where)
        _string(item["role"], f"{where}.role")
        _absolute_path(item["path"], f"{where}.path")
        _sha256(item["sha256"], f"{where}.sha256")
        for field in ("size", "mode", "dev", "inode", "uid", "nlink", "mtime_ns"):
            _integer(item[field], f"{where}.{field}")

    source_roots = _exact_list(receipt["source_roots"], "receipt.source_roots")
    source_ids: set[str] = set()
    for index, raw in enumerate(source_roots):
        where = f"receipt.source_roots[{index}]"
        item = _exact_dict(raw, where)
        _keys(
            item,
            {
                "root_id",
                "task_ids",
                "path",
                "dev",
                "inode",
                "mode",
                "uid",
                "nlink",
                "size",
                "mtime_ns",
                "dirty_paths_sha256",
                "declared_inventory_sha256",
                "observed_inventory_sha256",
            },
            where,
        )
        root_id = _identifier(item["root_id"], f"{where}.root_id")
        if root_id in source_ids:
            _fail(f"duplicate receipt source root: {root_id}")
        source_ids.add(root_id)
        task_ids = _exact_list(item["task_ids"], f"{where}.task_ids")
        if not task_ids or any(type(task_id) is not str for task_id in task_ids):
            _fail(f"{where}.task_ids must contain selected task identifiers")
        if len(set(task_ids)) != len(task_ids):
            _fail(f"{where}.task_ids contain duplicates")
        for task_index, task_id in enumerate(task_ids):
            _identifier(task_id, f"{where}.task_ids[{task_index}]")
        _absolute_path(item["path"], f"{where}.path")
        for field in ("dev", "inode", "mode", "uid", "nlink", "size", "mtime_ns"):
            _integer(item[field], f"{where}.{field}")
        _sha256(item["dirty_paths_sha256"], f"{where}.dirty_paths_sha256")
        _sha256(item["declared_inventory_sha256"], f"{where}.declared_inventory_sha256")
        _sha256(item["observed_inventory_sha256"], f"{where}.observed_inventory_sha256")

    blobs = _exact_list(receipt["blobs"], "receipt.blobs")
    for index, raw in enumerate(blobs):
        where = f"receipt.blobs[{index}]"
        item = _exact_dict(raw, where)
        _keys(
            item,
            {
                "task_id",
                "path",
                "operation",
                "raw_sha256",
                "size",
                "mode",
                "blob_oid",
                "accepted_blob_relative_path",
                "dev",
                "inode",
                "uid",
                "file_mode",
                "nlink",
                "mtime_ns",
            },
            where,
        )
        _identifier(item["task_id"], f"{where}.task_id")
        _delta_path(item["path"], f"{where}.path")
        operation = _string(item["operation"], f"{where}.operation")
        if operation not in ("add", "modify", "delete"):
            _fail(f"{where}.operation is unsupported")
        raw_sha = _sha256(item["raw_sha256"], f"{where}.raw_sha256", zero_allowed=True)
        size = _integer(item["size"], f"{where}.size")
        mode = _integer(item["mode"], f"{where}.mode")
        if mode not in (0o100644, 0o100755):
            _fail(f"{where}.mode is invalid")
        if operation == "delete":
            if raw_sha != ZERO_SHA256 or size != 0:
                _fail(f"{where} delete raw binding is invalid")
            for field in (
                "blob_oid",
                "accepted_blob_relative_path",
                "dev",
                "inode",
                "uid",
                "file_mode",
                "nlink",
                "mtime_ns",
            ):
                if item[field] is not None:
                    _fail(f"{where}.{field} must be null for delete")
        else:
            if raw_sha == ZERO_SHA256:
                _fail(f"{where} raw SHA-256 is absent")
            _oid(item["blob_oid"], f"{where}.blob_oid")
            relative = _string(item["accepted_blob_relative_path"], f"{where}.accepted_blob_relative_path")
            expected_relative = f"accepted-blobs/{raw_sha[:2]}/{raw_sha}"
            if relative != expected_relative:
                _fail(f"{where}.accepted_blob_relative_path is not digest-derived")
            for field in ("dev", "inode", "uid", "file_mode", "nlink", "mtime_ns"):
                _integer(item[field], f"{where}.{field}")
            if item["file_mode"] != 0o600 or item["nlink"] != 1:
                _fail(f"{where} accepted blob provenance is unsafe")
    _oid(receipt["tree_oid"], "receipt.tree_oid")
    _oid(receipt["commit_oid"], "receipt.commit_oid")
    _sha256(receipt["entry_set_sha256"], "receipt.entry_set_sha256")
    # Exact receipt substructure is enforced by comparing it to a freshly derived
    # receipt during verification; recursively reject subclasses here first.
    _plain_tree(receipt, "receipt")
    return receipt


def load_receipt(payload: Any) -> dict[str, Any]:
    """Parse and validate the closed plain-JSON receipt schema."""

    return _validate_receipt(_parse_json(payload, "composition receipt JSON"))


def _receipt_document(
    plan: dict[str, Any],
    plan_digest: str,
    prepared: dict[str, Any],
    tree_oid: str,
    commit_oid: str,
    authority: _AuthoritySnapshot,
) -> dict[str, Any]:
    production = authority._authority_kind == AUTHORITY_KIND_PRODUCTION
    return {
        "schema": RECEIPT_SCHEMA,
        "state": "READY" if production else "SYNTHETIC_READY",
        "state_history": list(READY_STATES if production else SYNTHETIC_READY_STATES),
        "consumable": production,
        "authority_kind": authority._authority_kind,
        "resolver_kind": authority._resolver_kind,
        "plan_sha256": plan_digest,
        "target_id": plan["target_id"],
        "successor_task_id": plan["successor_task_id"],
        "logical_base_commit": plan["logical_base_commit"],
        "task_definition_sha256": plan["successor_task_definition"]["sha256"],
        "brief_sha256": plan["successor_brief"]["sha256"],
        "helper_generation": plan["helper_generation"],
        "authority": authority.provenance,
        "artifacts": prepared["artifacts"],
        "source_roots": prepared["source_roots"],
        "blobs": prepared["blobs"],
        "tree_oid": tree_oid,
        "commit_oid": commit_oid,
        "entry_set_sha256": prepared["entry_set_sha256"],
    }


def _read_receipt_file(path: str) -> tuple[dict[str, Any], bytes, os.stat_result]:
    descriptor, before = _open_absolute_file(path, "receipt file")
    _gate_receipt_file(before, "receipt file")
    content = bytearray()
    try:
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            content.extend(chunk)
        after = os.fstat(descriptor)
        if _stat_identity(before) != _stat_identity(after):
            _fail("receipt changed while it was read")
    finally:
        os.close(descriptor)
    raw = bytes(content)
    parsed = _validate_receipt(_parse_json(raw, "receipt JSON"))
    if raw != _canonical_bytes(parsed) + b"\n":
        _fail("receipt is not canonical JSON")
    return parsed, raw, before


def _expected_commit_bytes(plan: dict[str, Any], tree_oid: str) -> bytes:
    commit = plan["commit"]
    header = (
        f"tree {tree_oid}\n"
        f"parent {plan['logical_base_commit']}\n"
        f"author {commit['author_name']} <{commit['author_email']}> {commit['timestamp']} {commit['timezone']}\n"
        f"committer {commit['committer_name']} <{commit['committer_email']}> {commit['timestamp']} {commit['timezone']}\n"
        "\n"
    ).encode("utf-8")
    return header + commit["message"].encode("utf-8")


def _verify_commit(plan: dict[str, Any], repository: str, receipt: dict[str, Any]) -> None:
    actual = _git(repository, ["cat-file", "commit", receipt["commit_oid"]])
    expected = _expected_commit_bytes(plan, receipt["tree_oid"])
    if actual != expected:
        _fail("synthetic commit content drift")
    calculated = _git(repository, ["hash-object", "-t", "commit", "--stdin"], input_bytes=actual)
    if calculated.decode("ascii").strip() != receipt["commit_oid"]:
        _fail("synthetic commit object id drift")


def _verify_generated_objects(
    plan: dict[str, Any],
    repository: str,
    prepared: dict[str, Any],
    tree_oid: str,
    commit_oid: str,
) -> None:
    actual_entries = _tree_entries(repository, tree_oid)
    if actual_entries != prepared["final_entries"]:
        _fail("synthetic tree entries drift before READY")
    if _entry_set_sha(actual_entries) != prepared["entry_set_sha256"]:
        _fail("synthetic entry-set digest drift before READY")
    raw_tree = _git(repository, ["cat-file", "tree", tree_oid])
    calculated_tree = _git(repository, ["hash-object", "-t", "tree", "--stdin"], input_bytes=raw_tree)
    if calculated_tree.decode("ascii").strip() != tree_oid:
        _fail("synthetic tree raw object drift before READY")
    for record in prepared["blobs"]:
        if record["blob_oid"] is None:
            continue
        raw_blob = _git(repository, ["cat-file", "blob", record["blob_oid"]])
        if len(raw_blob) != record["size"] or hashlib.sha256(raw_blob).hexdigest() != record["raw_sha256"]:
            _fail(f"synthetic blob content drift before READY at {record['path']}")
        calculated_blob = _git(repository, ["hash-object", "-t", "blob", "--stdin"], input_bytes=raw_blob)
        if calculated_blob.decode("ascii").strip() != record["blob_oid"]:
            _fail(f"synthetic blob object id drift before READY at {record['path']}")
    receipt_stub = {"tree_oid": tree_oid, "commit_oid": commit_oid}
    _verify_commit(plan, repository, receipt_stub)


def _result_disposition(
    authority: _AuthoritySnapshot,
    *,
    bound: bool = False,
) -> dict[str, Any]:
    production = authority._authority_kind == AUTHORITY_KIND_PRODUCTION
    if production:
        state = "BOUND_TO_RUN" if bound else "READY"
    else:
        state = "SYNTHETIC_BOUND_TO_RUN" if bound else "SYNTHETIC_READY"
    return {
        "state": state,
        "consumable": production,
        "authority_kind": authority._authority_kind,
        "resolver_kind": authority._resolver_kind,
    }


def verify_receipt(
    plan: Any,
    repository: Any,
    receipt_root: Any,
    *,
    bind_run_id: Any = None,
    authority: Any = None,
) -> dict[str, Any]:
    """Independently verify READY authority and optionally return a run binding.

    ``bind_run_id`` is a pure return-value binding.  It neither edits the immutable
    receipt nor grants approval/Intent authority.
    """

    frozen = validate_plan(plan)
    if type(authority) is not _AuthoritySnapshot or authority._guard is not _AUTHORITY_GUARD:
        return _unattested(frozen)
    attested = _refresh_authority(frozen, authority)
    repository_path = _absolute_path(repository, "repository")
    receipt_root_path = _absolute_path(receipt_root, "receipt_root")
    _validate_receipt_root(receipt_root_path)
    if bind_run_id is not None:
        _identifier(bind_run_id, "bind_run_id")
    plan_digest = hashlib.sha256(_canonical_bytes(frozen)).hexdigest()
    target_path, _ = _receipt_paths(receipt_root_path, frozen["target_id"])
    try:
        receipt, raw, target_info = _read_receipt_file(target_path)
    except FileNotFoundError as exc:
        raise CompositionError("READY target receipt does not exist") from exc
    if receipt["plan_sha256"] != plan_digest:
        _fail("target is bound to a different composition plan")
    receipt_sha = hashlib.sha256(raw).hexdigest()
    _, content_path = _receipt_paths(receipt_root_path, frozen["target_id"], receipt_sha)
    assert content_path is not None
    try:
        content_receipt, content_raw, content_info = _read_receipt_file(content_path)
    except FileNotFoundError as exc:
        raise CompositionError("content-addressed receipt alias is missing") from exc
    if content_raw != raw or content_receipt != receipt:
        _fail("content-addressed receipt alias drift")
    if _stat_identity(target_info) != _stat_identity(content_info):
        _fail("target and content-addressed receipt are not the same write-once file")
    if target_info.st_nlink != 2 or content_info.st_nlink != 2:
        _fail("READY receipt must have exactly its target and content-addressed links")

    prepared = _prepare(frozen, repository_path, attested, write_blobs=False)
    actual_entries = _tree_entries(repository_path, receipt["tree_oid"])
    if actual_entries != prepared["final_entries"]:
        _fail("synthetic tree entries drift")
    if prepared["entry_set_sha256"] != receipt["entry_set_sha256"]:
        _fail("synthetic entry-set digest drift")
    for record in prepared["blobs"]:
        if record["blob_oid"] is None:
            continue
        object_size_text = _git(repository_path, ["cat-file", "-s", record["blob_oid"]])
        try:
            object_size = int(object_size_text.decode("ascii").strip())
        except (ValueError, UnicodeError) as exc:
            raise CompositionError("Git returned an invalid synthetic blob size") from exc
        if object_size != record["size"] or _blob_sha256(repository_path, record["blob_oid"]) != record["raw_sha256"]:
            _fail(f"synthetic blob content drift at {record['path']}")
    expected = _receipt_document(
        frozen,
        plan_digest,
        prepared,
        receipt["tree_oid"],
        receipt["commit_oid"],
        attested,
    )
    if receipt != expected:
        _fail("receipt content drift")
    _verify_commit(frozen, repository_path, receipt)
    result = {
        **_result_disposition(attested, bound=bind_run_id is not None),
        "receipt_path": content_path,
        "target_path": target_path,
        "receipt_sha256": receipt_sha,
        "tree_oid": receipt["tree_oid"],
        "commit_oid": receipt["commit_oid"],
        "plan_sha256": plan_digest,
    }
    if bind_run_id is not None:
        result["run_id"] = bind_run_id
    return result


def compose(
    plan: Any,
    repository: Any,
    receipt_root: Any,
    *,
    fault_stage: Any = None,
    authority: Any = None,
) -> dict[str, Any]:
    """Publish one READY winner, or return AUTHORITY_UNATTESTED without a token."""

    frozen = validate_plan(plan)
    if type(authority) is not _AuthoritySnapshot or authority._guard is not _AUTHORITY_GUARD:
        return _unattested(frozen)
    attested = _refresh_authority(frozen, authority)
    repository_path = _absolute_path(repository, "repository")
    receipt_root_path = _absolute_path(receipt_root, "receipt_root")
    _validate_receipt_root(receipt_root_path)
    if fault_stage is not None:
        if type(fault_stage) is not str or fault_stage not in _FAULT_STAGES:
            _fail("fault_stage must be a supported exact string")
    plan_digest = hashlib.sha256(_canonical_bytes(frozen)).hexdigest()
    target_path, _ = _receipt_paths(receipt_root_path, frozen["target_id"])
    if os.path.lexists(target_path):
        return recover(frozen, repository_path, receipt_root_path, authority=attested)

    _fault(fault_stage, "after_validation")
    prepared = _prepare(frozen, repository_path, attested, write_blobs=True)
    _fault(fault_stage, "after_sources_frozen")
    tree_oid, commit_oid = _write_tree_commit(frozen, repository_path, prepared)
    _fault(fault_stage, "after_tree_written")
    _verify_generated_objects(frozen, repository_path, prepared, tree_oid, commit_oid)
    # Git objects come only from accepted blobs.  Re-read those blobs, the shared
    # roots' cumulative current inventories, and every attestation before READY.
    confirmed = _prepare(frozen, repository_path, attested, write_blobs=False)
    if confirmed != prepared:
        _fail("source, task, evidence, or event drift before READY")
    attested = _refresh_authority(frozen, attested)
    receipt = _receipt_document(frozen, plan_digest, prepared, tree_oid, commit_oid, attested)
    _validate_receipt(receipt)
    receipt_bytes = _canonical_bytes(receipt) + b"\n"
    receipt_sha = hashlib.sha256(receipt_bytes).hexdigest()
    target_path, content_path = _publish_receipt(
        receipt_root_path,
        frozen["target_id"],
        receipt_bytes,
        receipt_sha,
        fault_stage,
    )
    return {
        **_result_disposition(attested),
        "receipt_path": content_path,
        "target_path": target_path,
        "receipt_sha256": receipt_sha,
        "tree_oid": tree_oid,
        "commit_oid": commit_oid,
        "plan_sha256": plan_digest,
    }


def _compose_recovery(
    frozen: dict[str, Any],
    repository_path: str,
    receipt_root_path: str,
    authority: _AuthoritySnapshot,
) -> dict[str, Any]:
    """Rebuild all fallible inputs before touching a pre-READY candidate."""

    plan_digest = hashlib.sha256(_canonical_bytes(frozen)).hexdigest()
    prepared = _prepare(frozen, repository_path, authority, write_blobs=True)
    tree_oid, commit_oid = _write_tree_commit(frozen, repository_path, prepared)
    _verify_generated_objects(frozen, repository_path, prepared, tree_oid, commit_oid)
    confirmed = _prepare(frozen, repository_path, authority, write_blobs=False)
    if confirmed != prepared:
        _fail("source, task, evidence, or event drift before recovery publication")
    attested = _refresh_authority(frozen, authority)
    receipt = _receipt_document(frozen, plan_digest, prepared, tree_oid, commit_oid, attested)
    _validate_receipt(receipt)
    receipt_bytes = _canonical_bytes(receipt) + b"\n"
    receipt_sha = hashlib.sha256(receipt_bytes).hexdigest()
    target_path, content_path = _publish_receipt(
        receipt_root_path,
        frozen["target_id"],
        receipt_bytes,
        receipt_sha,
        None,
        recover_staging=True,
    )
    return {
        **_result_disposition(attested),
        "receipt_path": content_path,
        "target_path": target_path,
        "receipt_sha256": receipt_sha,
        "tree_oid": tree_oid,
        "commit_oid": commit_oid,
        "plan_sha256": plan_digest,
    }


def recover(
    plan: Any,
    repository: Any,
    receipt_root: Any,
    *,
    authority: Any = None,
) -> dict[str, Any]:
    """Recover a publication crash, or return AUTHORITY_UNATTESTED without a token.

    A crash before READY has no consumable target.  In that case recovery performs
    the same deterministic composition; unreachable Git objects are harmless.
    """

    frozen = validate_plan(plan)
    if type(authority) is not _AuthoritySnapshot or authority._guard is not _AUTHORITY_GUARD:
        return _unattested(frozen)
    attested = _refresh_authority(frozen, authority)
    repository_path = _absolute_path(repository, "repository")
    receipt_root_path = _absolute_path(receipt_root, "receipt_root")
    _validate_receipt_root(receipt_root_path)
    target_path, _ = _receipt_paths(receipt_root_path, frozen["target_id"])
    if os.path.lexists(target_path):
        # target is the final linearization point, so a READY target must already
        # have its content alias.  Recovery never creates authority from target.
        return verify_receipt(
            frozen,
            repository_path,
            receipt_root_path,
            authority=attested,
        )
    return _compose_recovery(frozen, repository_path, receipt_root_path, attested)


__all__ = [
    "ACCEPTED_EVENT_SCHEMA",
    "AUTHORITY_SCHEMA",
    "AUTHORITY_INPUT_MISSING",
    "AUTHORITY_KIND_PRODUCTION",
    "AUTHORITY_KIND_SYNTHETIC",
    "AUTHORITY_UNATTESTED",
    "CONTROL_DEPLOYMENT_SCHEMA",
    "CompositionCrash",
    "CompositionError",
    "PLAN_SCHEMA",
    "READY_STATES",
    "RESOLVER_KIND_PRODUCTION",
    "RESOLVER_KIND_TEST",
    "RECEIPT_SCHEMA",
    "SYNTHETIC_READY_STATES",
    "ZERO_SHA256",
    "compose",
    "load_plan",
    "load_receipt",
    "load_trusted_authority",
    "plan_sha256",
    "recover",
    "validate_plan",
    "verify_receipt",
]
