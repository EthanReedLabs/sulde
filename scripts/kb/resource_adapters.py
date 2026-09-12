#!/usr/bin/env python3
"""Strict H04 typed-resource adapters.

Classification, authorization, execution and verification are separate. All
authority-bearing documents are exact plain JSON and reject unknown fields.
External effects require an injected adapter; only local temporary-repository
Git has a concrete executor.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import threading
from typing import Any, Callable, Iterator, TypedDict
from urllib.parse import parse_qs, urlparse

from command_template import (
    git_execution_passthrough,
    has_unquoted_shell_control,
    literal_git_add_arguments,
    literal_git_resource_action,
    literal_git_worktree_lifecycle_action,
    split_command_template,
)
from human_grant import EXECUTION_AUTHORITY_SCHEMA
from local_file_operations import (
    LocalFileOperationError,
    canonical_existing_local_target,
)

RESOURCE_ACTION_SCHEMA = "sulde-typed-resource-action-v1"
AUTHORIZATION_SCHEMA = "sulde-typed-resource-authorization-v1"
EXECUTION_RECEIPT_SCHEMA = "sulde-typed-resource-execution-receipt-v1"
VERIFIER_RECEIPT_SCHEMA = "sulde-typed-resource-verifier-receipt-v1"
GIT_RESOURCE_SCHEMA = "sulde-git-metadata-resource-v1"
GIT_WORKTREE_LIFECYCLE_RESOURCE_SCHEMA = (
    "sulde-git-worktree-lifecycle-resource-v1"
)
DELETE_RESOURCE_SCHEMA = "sulde-local-delete-resource-v1"
WORKSPACE_RESOURCE_SCHEMA = "sulde-workspace-resource-v1"
FIGMA_RESOURCE_SCHEMA = "sulde-figma-resource-v1"
DEVICE_RESOURCE_SCHEMA = "sulde-device-resource-v1"
BROKER_DISPATCH_SCHEMA = "sulde-grant-broker-dispatch-intent-v1"

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_OID = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_REF = re.compile(r"^refs/heads/[A-Za-z0-9][A-Za-z0-9._/-]*$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,255}$")
_PATH_META = frozenset("*?[]{}")
_GIT_READS = frozenset({"status", "diff", "rev-parse", "show"})
_GIT_WRITES = frozenset({"add", "commit", "merge"})
_DEVICE_ALLOWED = frozenset({"install", "read", "cleanup_test_data", "run_test"})
_DEVICE_DENIED = frozenset({
    "purchase", "uninstall", "data_clear", "clear_data",
    "delete_original_user_data", "delete_user_data",
})

_RESOURCE_FIELDS = {
    GIT_RESOURCE_SCHEMA: frozenset({
        "schema", "kind", "resource_id", "worktree_root", "gitdir",
        "common_gitdir", "index_path", "head_path", "ref_path", "head_ref",
        "head_oid", "index_sha256", "ref_sha256", "gitdir_identity",
        "common_identity",
    }),
    GIT_WORKTREE_LIFECYCLE_RESOURCE_SCHEMA: frozenset({
        "schema", "kind", "resource_id", "operation", "repository_root",
        "common_gitdir", "common_gitdir_identity", "worktrees_root",
        "target_path", "target_parent_identity", "branch_ref", "base_ref",
        "base_oid", "primary_worktree", "dev_worktree",
        "primary_status_sha256", "dev_status_sha256", "branch_state",
        "branch_checked_out", "target_absent",
    }),
    DELETE_RESOURCE_SCHEMA: frozenset({
        "schema", "kind", "resource_id", "target", "parent", "target_type",
        "target_identity", "parent_identity", "size", "tree_sha256",
        "allowed_effect", "workspace_root",
    }),
    WORKSPACE_RESOURCE_SCHEMA: frozenset({
        "schema", "kind", "resource_id", "workspace_root", "workspace_identity",
        "repository_id", "original_workspace", "provider", "session_id",
    }),
    FIGMA_RESOURCE_SCHEMA: frozenset({
        "schema", "kind", "resource_id", "provider", "file_key", "page_id",
        "node_id", "effect", "mutation_kind", "payload_sha256",
        "readback_sha256",
    }),
    DEVICE_RESOURCE_SCHEMA: frozenset({
        "schema", "kind", "resource_id", "provider", "serial", "package",
        "artifact_path", "artifact_sha256", "data_namespace",
        "original_user_data",
    }),
}
_ACTION_FIELDS = frozenset({
    "schema", "action_id", "resource_schema", "resource_kind", "resource_id",
    "action", "subject", "constraints", "world_state", "grant_identity",
    "dispatch_identity", "provider", "session_id", "task_epoch", "verifier",
})
_AUTHORITY_FIELDS = frozenset({
    "schema", "grant_sha256", "binding_sha256", "authority_sha256", "provider",
    "session_id", "task_epoch", "subject", "capability", "effect", "constraints",
    "world_state", "expires_at", "verifier", "receipt_id",
    "execution_authorized", "default_policy_recheck_required",
})
_DISPATCH_FIELDS = frozenset({
    "schema", "transaction_id", "dispatch_id", "consumer_id", "provider",
    "session_id", "task_epoch", "authority_sha256", "effect",
    "execution_authorized", "default_policy_recheck_required",
})


class ResourceAdapterError(ValueError):
    """A typed boundary failed closed."""


class GitMetadataResource(TypedDict):
    schema: str
    kind: str
    resource_id: str
    worktree_root: str
    gitdir: str
    common_gitdir: str
    index_path: str
    head_path: str
    ref_path: str
    head_ref: str
    head_oid: str
    index_sha256: str
    ref_sha256: str
    gitdir_identity: str
    common_identity: str


class GitWorktreeLifecycleResource(TypedDict):
    schema: str
    kind: str
    resource_id: str
    operation: str
    repository_root: str
    common_gitdir: str
    common_gitdir_identity: str
    worktrees_root: str
    target_path: str
    target_parent_identity: str
    branch_ref: str
    base_ref: str
    base_oid: str
    primary_worktree: str
    dev_worktree: str
    primary_status_sha256: str
    dev_status_sha256: str
    branch_state: str
    branch_checked_out: bool
    target_absent: bool


class LocalDeleteResource(TypedDict):
    schema: str
    kind: str
    resource_id: str
    target: str
    parent: str
    target_type: str
    target_identity: str
    parent_identity: str
    size: int
    tree_sha256: str
    allowed_effect: str
    workspace_root: str


class WorkspaceResource(TypedDict):
    schema: str
    kind: str
    resource_id: str
    workspace_root: str
    workspace_identity: str
    repository_id: str
    original_workspace: str
    provider: str
    session_id: str


class FigmaResource(TypedDict):
    schema: str
    kind: str
    resource_id: str
    provider: str
    file_key: str
    page_id: str
    node_id: str
    effect: str
    mutation_kind: str
    payload_sha256: str
    readback_sha256: str


class DeviceResource(TypedDict):
    schema: str
    kind: str
    resource_id: str
    provider: str
    serial: str
    package: str
    artifact_path: str
    artifact_sha256: str
    data_namespace: str
    original_user_data: bool


def _plain(value: Any, name: str = "value") -> None:
    if type(value) in {type(None), str, int, bool}:
        return
    if type(value) is float:
        if math.isfinite(value):
            return
        raise ResourceAdapterError(f"{name} contains a non-finite number")
    if type(value) is list:
        for index, item in enumerate(value):
            _plain(item, f"{name}[{index}]")
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise ResourceAdapterError(f"{name} has a non-string key")
            _plain(item, f"{name}.{key}")
        return
    raise ResourceAdapterError(f"{name} must contain exact plain JSON values")


def _object(value: Any, name: str, fields: frozenset[str] | None = None) -> dict[str, Any]:
    _plain(value, name)
    if type(value) is not dict:
        raise ResourceAdapterError(f"{name} must be an exact object")
    if fields is not None and frozenset(value) != fields:
        missing = sorted(fields - frozenset(value))
        extra = sorted(frozenset(value) - fields)
        raise ResourceAdapterError(f"{name} fields invalid: missing={missing}; extra={extra}")
    return value


def _text(value: Any, name: str) -> str:
    if type(value) is not str or not value.strip() or "\x00" in value:
        raise ResourceAdapterError(f"{name} must be one exact non-empty string")
    return value


def _digest(value: Any, name: str, *, optional: bool = False) -> str:
    if optional and value == "":
        return ""
    selected = _text(value, name)
    if _DIGEST.fullmatch(selected) is None:
        raise ResourceAdapterError(f"{name} must be a canonical sha256 identity")
    return selected


def _absolute_path(value: Any, name: str, *, optional: bool = False) -> str:
    if optional and value == "":
        return ""
    selected = _text(value, name)
    if not Path(selected).is_absolute():
        raise ResourceAdapterError(f"{name} must be absolute")
    return selected


def _validate_resource_semantics(value: dict[str, Any]) -> None:
    schema = value["schema"]
    expected_kind = {
        GIT_RESOURCE_SCHEMA: "git_metadata",
        GIT_WORKTREE_LIFECYCLE_RESOURCE_SCHEMA: "git_worktree_lifecycle",
        DELETE_RESOURCE_SCHEMA: "local_delete",
        WORKSPACE_RESOURCE_SCHEMA: "workspace",
        FIGMA_RESOURCE_SCHEMA: "figma",
        DEVICE_RESOURCE_SCHEMA: "device",
    }[schema]
    if value["kind"] != expected_kind:
        raise ResourceAdapterError("resource kind does not match its schema")
    _digest(value["resource_id"], "resource.resource_id")
    if schema == GIT_RESOURCE_SCHEMA:
        for field in (
            "worktree_root", "gitdir", "common_gitdir", "index_path",
            "head_path", "ref_path",
        ):
            _absolute_path(value[field], f"resource.{field}")
        if (
            value["head_ref"] != "DETACHED"
            and _REF.fullmatch(_text(value["head_ref"], "resource.head_ref")) is None
        ):
            raise ResourceAdapterError("resource.head_ref is malformed")
        if _OID.fullmatch(_text(value["head_oid"], "resource.head_oid")) is None:
            raise ResourceAdapterError("resource.head_oid is malformed")
        for field in (
            "index_sha256", "ref_sha256", "gitdir_identity", "common_identity",
        ):
            _digest(value[field], f"resource.{field}")
    elif schema == GIT_WORKTREE_LIFECYCLE_RESOURCE_SCHEMA:
        for field in (
            "repository_root", "common_gitdir", "worktrees_root",
            "target_path", "primary_worktree", "dev_worktree",
        ):
            _absolute_path(value[field], f"resource.{field}")
        if value["operation"] not in {"attach_existing", "create_branch"}:
            raise ResourceAdapterError("worktree lifecycle operation is invalid")
        for field in ("branch_ref", "base_ref"):
            if _REF.fullmatch(_text(value[field], f"resource.{field}")) is None:
                raise ResourceAdapterError(f"resource.{field} is malformed")
        if _OID.fullmatch(_text(value["base_oid"], "resource.base_oid")) is None:
            raise ResourceAdapterError("resource.base_oid is malformed")
        for field in (
            "common_gitdir_identity", "target_parent_identity",
            "primary_status_sha256", "dev_status_sha256",
        ):
            _digest(value[field], f"resource.{field}")
        expected_state = (
            "present" if value["operation"] == "attach_existing" else "absent"
        )
        if value["branch_state"] != expected_state:
            raise ResourceAdapterError("worktree lifecycle branch state is invalid")
        if type(value["branch_checked_out"]) is not bool:
            raise ResourceAdapterError("branch_checked_out must be exact bool")
        if value["branch_checked_out"]:
            raise ResourceAdapterError("worktree lifecycle branch is already checked out")
        if value["target_absent"] is not True:
            raise ResourceAdapterError("worktree lifecycle target must be absent")
    elif schema == DELETE_RESOURCE_SCHEMA:
        for field in ("target", "parent", "workspace_root"):
            _absolute_path(value[field], f"resource.{field}")
        if value["target_type"] not in {"file", "directory"}:
            raise ResourceAdapterError("delete target_type is invalid")
        if type(value["size"]) is not int or value["size"] < 0:
            raise ResourceAdapterError("delete size must be a non-negative integer")
        if value["allowed_effect"] not in {"delete_file", "delete_tree"}:
            raise ResourceAdapterError("delete allowed_effect is invalid")
        for field in ("target_identity", "parent_identity", "tree_sha256"):
            _digest(value[field], f"resource.{field}")
    elif schema == WORKSPACE_RESOURCE_SCHEMA:
        for field in ("workspace_root", "original_workspace"):
            _absolute_path(value[field], f"resource.{field}")
        for field in ("workspace_identity", "repository_id"):
            _digest(value[field], f"resource.{field}")
        _text(value["provider"], "resource.provider")
        _text(value["session_id"], "resource.session_id")
    elif schema == FIGMA_RESOURCE_SCHEMA:
        _text(value["provider"], "resource.provider")
        if _SAFE_ID.fullmatch(_text(value["file_key"], "resource.file_key")) is None:
            raise ResourceAdapterError("Figma file key is malformed")
        for field in ("page_id", "node_id", "mutation_kind"):
            if value[field] and _SAFE_ID.fullmatch(value[field]) is None:
                raise ResourceAdapterError(f"Figma {field} is malformed")
        if value["effect"] not in {"read", "external_write"}:
            raise ResourceAdapterError("Figma effect is invalid")
        if value["effect"] == "external_write" and not value["mutation_kind"]:
            raise ResourceAdapterError("Figma write has no mutation kind")
        for field in ("payload_sha256", "readback_sha256"):
            _digest(value[field], f"resource.{field}")
    elif schema == DEVICE_RESOURCE_SCHEMA:
        for field in ("provider", "serial", "package"):
            if _SAFE_ID.fullmatch(_text(value[field], f"resource.{field}")) is None:
                raise ResourceAdapterError(f"device {field} is malformed")
        _absolute_path(value["artifact_path"], "resource.artifact_path", optional=True)
        _digest(value["artifact_sha256"], "resource.artifact_sha256", optional=True)
        if type(value["data_namespace"]) is not str or "\x00" in value["data_namespace"]:
            raise ResourceAdapterError("device data namespace is malformed")
        if type(value["original_user_data"]) is not bool:
            raise ResourceAdapterError("device original_user_data must be bool")


def canonical_json(value: Any) -> str:
    _plain(value)
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


def canonical_digest(domain: str, value: Any) -> str:
    _text(domain, "domain")
    return "sha256:" + hashlib.sha256(
        canonical_json({"domain": domain, "value": value}).encode("utf-8")
    ).hexdigest()


def _file_digest(path: Path) -> str:
    try:
        if not stat.S_ISREG(path.lstat().st_mode):
            raise ResourceAdapterError(f"not a regular file: {path}")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return "sha256:" + digest.hexdigest()
    except OSError as error:
        raise ResourceAdapterError(f"cannot digest file: {path}") from error


def _optional_file_digest(path: Path) -> str:
    try:
        return _file_digest(path)
    except ResourceAdapterError:
        return canonical_digest("missing-file", str(path))


def _stat_identity(path: Path) -> str:
    try:
        value = path.lstat()
    except OSError as error:
        raise ResourceAdapterError(f"cannot identify path: {path}") from error
    return canonical_digest("filesystem-object", {
        "device": int(value.st_dev), "inode": int(value.st_ino),
        "mode": int(stat.S_IFMT(value.st_mode)),
    })


def _no_symlink_components(root: Path, target: Path) -> bool:
    try:
        relative = target.relative_to(root)
        cursor = root
        if stat.S_ISLNK(root.lstat().st_mode):
            return False
        for part in relative.parts:
            cursor /= part
            if stat.S_ISLNK(cursor.lstat().st_mode):
                return False
        return True
    except (OSError, ValueError):
        return False


def _bounded_text(path: Path, *, required: bool = True) -> str:
    try:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise ResourceAdapterError(f"metadata path is not regular: {path}")
        if metadata.st_size <= 0 or metadata.st_size > 4096:
            raise ResourceAdapterError(f"metadata path has unsafe size: {path}")
        value = path.read_text(encoding="utf-8").strip()
        if not value or "\x00" in value or "\r" in value or "\n" in value:
            raise ResourceAdapterError(f"metadata path is not one line: {path}")
        return value
    except FileNotFoundError:
        if not required:
            return ""
        raise ResourceAdapterError(f"metadata path is missing: {path}")
    except (OSError, UnicodeError) as error:
        raise ResourceAdapterError(f"cannot read metadata path: {path}") from error


def _git_output(root: Path, *arguments: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *arguments], cwd=root, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=5, check=False,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ResourceAdapterError("bounded Git metadata read failed") from error
    if completed.returncode != 0:
        raise ResourceAdapterError(f"Git metadata read rejected: {' '.join(arguments)}")
    return completed.stdout.strip()


def _git_returncode(root: Path, *arguments: str) -> int:
    try:
        completed = subprocess.run(
            ["git", *arguments], cwd=root, capture_output=True, timeout=5,
            check=False, env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ResourceAdapterError("bounded Git state probe failed") from error
    return int(completed.returncode)


def _git_status_digest(root: Path) -> str:
    try:
        completed = subprocess.run(
            [
                "git", "status", "--porcelain=v1", "-z",
                "--untracked-files=all", "--", ".", ":(exclude).worktrees",
            ],
            cwd=root, capture_output=True, timeout=5, check=False,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ResourceAdapterError("bounded Git status probe failed") from error
    if completed.returncode != 0:
        raise ResourceAdapterError("Git status probe was rejected")
    return "sha256:" + hashlib.sha256(completed.stdout).hexdigest()


def _git_worktree_records(root: Path) -> list[dict[str, str]]:
    raw = _git_output(root, "worktree", "list", "--porcelain")
    records: list[dict[str, str]] = []
    for paragraph in raw.split("\n\n"):
        if not paragraph.strip():
            continue
        record: dict[str, str] = {}
        for line in paragraph.splitlines():
            key, separator, value = line.partition(" ")
            if key in {"detached", "bare"} and not separator:
                record[key] = "true"
            elif key in {"worktree", "HEAD", "branch"} and separator and value:
                record[key] = value
        if "worktree" not in record or "HEAD" not in record:
            raise ResourceAdapterError("Git worktree inventory is malformed")
        path = Path(record["worktree"])
        if not path.is_absolute() or _OID.fullmatch(record["HEAD"].lower()) is None:
            raise ResourceAdapterError("Git worktree inventory identity is malformed")
        records.append(record)
    if not records or len({row["worktree"] for row in records}) != len(records):
        raise ResourceAdapterError("Git worktree inventory is empty or duplicated")
    return records


def _canonical_local_branch(root: Path, value: str, *, role: str) -> str:
    branch = _text(value, f"{role} branch")
    if branch in {"main", "master", "dev"} and role == "target":
        raise ResourceAdapterError("release or integration branch cannot be a task target")
    if branch.startswith("refs/") or _git_returncode(
        root, "check-ref-format", "--branch", branch,
    ) != 0:
        raise ResourceAdapterError(f"{role} branch is not canonical")
    return f"refs/heads/{branch}"


def _local_ref_oid(root: Path, ref: str) -> str:
    if _git_returncode(root, "show-ref", "--verify", "--quiet", ref) != 0:
        raise ResourceAdapterError("required local branch does not exist")
    oid = _git_output(root, "rev-parse", "--verify", f"{ref}^{{commit}}").lower()
    if _OID.fullmatch(oid) is None:
        raise ResourceAdapterError("local branch commit identity is malformed")
    return oid


def _local_branch_refs(root: Path) -> list[str]:
    raw = _git_output(
        root, "for-each-ref", "--format=%(refname)", "refs/heads",
    )
    refs = sorted(line for line in raw.splitlines() if line)
    if any(_REF.fullmatch(ref) is None for ref in refs) or len(refs) != len(set(refs)):
        raise ResourceAdapterError("local branch inventory is malformed")
    return refs


def decode_resource(value: Any) -> dict[str, Any]:
    raw = _object(value, "resource")
    schema = raw.get("schema")
    fields = _RESOURCE_FIELDS.get(schema)
    if fields is None:
        raise ResourceAdapterError("resource schema is unknown")
    selected = deepcopy(_object(raw, "resource", fields))
    claimed = selected.pop("resource_id")
    if claimed != canonical_digest(str(schema), selected):
        raise ResourceAdapterError("resource identity was substituted or tampered")
    selected["resource_id"] = claimed
    _validate_resource_semantics(selected)
    return selected


def _seal_resource(document: dict[str, Any]) -> dict[str, Any]:
    schema = _text(document.get("schema"), "resource.schema")
    fields = _RESOURCE_FIELDS.get(schema)
    if fields is None:
        raise ResourceAdapterError("cannot seal unknown resource schema")
    material = _object(document, "resource material", fields - {"resource_id"})
    sealed = deepcopy(material)
    sealed["resource_id"] = canonical_digest(schema, material)
    return decode_resource(sealed)


def classify_git_metadata(worktree: str | Path) -> GitMetadataResource:
    """Bind a standalone or linked worktree without granting .git writes."""
    lexical = Path(os.path.abspath(Path(worktree).expanduser()))
    try:
        root = lexical.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ResourceAdapterError("worktree does not resolve") from error
    if not root.is_dir() or lexical != root:
        raise ResourceAdapterError("worktree must be one canonical directory")
    marker = root / ".git"
    try:
        marker_metadata = marker.lstat()
    except OSError as error:
        raise ResourceAdapterError("worktree has no exact .git marker") from error
    if stat.S_ISLNK(marker_metadata.st_mode):
        raise ResourceAdapterError("symlinked .git markers are forbidden")
    if stat.S_ISDIR(marker_metadata.st_mode):
        gitdir = marker.resolve(strict=True)
        common = gitdir
    elif stat.S_ISREG(marker_metadata.st_mode):
        line = _bounded_text(marker)
        if not line.startswith("gitdir: "):
            raise ResourceAdapterError("linked-worktree marker is malformed")
        raw_admin = line.removeprefix("gitdir: ").strip()
        admin = Path(raw_admin).expanduser()
        if not admin.is_absolute():
            admin = root / admin
        gitdir = admin.resolve(strict=True)
        reverse = Path(_bounded_text(gitdir / "gitdir")).expanduser()
        if not reverse.is_absolute():
            reverse = gitdir / reverse
        if reverse.resolve(strict=True) != marker.resolve(strict=True):
            raise ResourceAdapterError("linked-worktree reverse pointer was substituted")
        common_line = _bounded_text(gitdir / "commondir")
        common_candidate = Path(common_line)
        if not common_candidate.is_absolute():
            common_candidate = gitdir / common_candidate
        common = common_candidate.resolve(strict=True)
        try:
            relative_admin = gitdir.relative_to((common / "worktrees").resolve(strict=True))
        except (OSError, ValueError) as error:
            raise ResourceAdapterError("linked gitdir is outside common worktrees") from error
        if len(relative_admin.parts) != 1:
            raise ResourceAdapterError("linked gitdir is not one worktree entry")
    else:
        raise ResourceAdapterError(".git marker type is unsupported")
    if not gitdir.is_dir() or not common.is_dir():
        raise ResourceAdapterError("Git administrative directories are unavailable")
    if not _no_symlink_components(common, gitdir):
        raise ResourceAdapterError("Git administrative path traverses a symlink")
    index_path = gitdir / "index"
    head_path = gitdir / "HEAD"
    head_value = _bounded_text(head_path)
    if head_value.startswith("ref: "):
        head_ref = head_value.removeprefix("ref: ").strip()
        if _REF.fullmatch(head_ref) is None:
            raise ResourceAdapterError("HEAD symbolic ref is unsafe")
        ref_path = common / head_ref
        try:
            ref_path.relative_to(common)
        except ValueError as error:
            raise ResourceAdapterError("HEAD ref escapes the common gitdir") from error
    elif _OID.fullmatch(head_value):
        head_ref = "DETACHED"
        ref_path = head_path
    else:
        raise ResourceAdapterError("HEAD identity is malformed")
    head_oid = _git_output(root, "rev-parse", "--verify", "HEAD^{commit}").lower()
    if _OID.fullmatch(head_oid) is None:
        raise ResourceAdapterError("HEAD object identity is malformed")
    ref_material = {
        "head": head_value, "oid": head_oid, "ref": head_ref,
        "ref_file": _bounded_text(ref_path, required=False),
        "packed_refs": _optional_file_digest(common / "packed-refs"),
    }
    sealed = _seal_resource({
        "schema": GIT_RESOURCE_SCHEMA, "kind": "git_metadata",
        "worktree_root": str(root), "gitdir": str(gitdir),
        "common_gitdir": str(common), "index_path": str(index_path),
        "head_path": str(head_path), "ref_path": str(ref_path),
        "head_ref": head_ref, "head_oid": head_oid,
        "index_sha256": _optional_file_digest(index_path),
        "ref_sha256": canonical_digest("git-ref-state", ref_material),
        "gitdir_identity": _stat_identity(gitdir),
        "common_identity": _stat_identity(common),
    })
    return GitMetadataResource(**sealed)


def classify_git_worktree_lifecycle(
    repository: str | Path,
    target: str | Path,
    *,
    operation: str,
    branch: str,
    base: str,
) -> GitWorktreeLifecycleResource:
    """Bind one exact worktree attach/create pre-state without `.git` authority."""
    lexical_repository = Path(
        os.path.abspath(Path(repository).expanduser())
    )
    try:
        execution_root = lexical_repository.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ResourceAdapterError("worktree repository does not resolve") from error
    if lexical_repository != execution_root or not execution_root.is_dir():
        raise ResourceAdapterError("worktree repository may not be aliased")
    try:
        repository_root = Path(
            _git_output(execution_root, "rev-parse", "--show-toplevel")
        ).resolve(strict=True)
        execution_root.relative_to(repository_root)
    except (OSError, ValueError) as error:
        raise ResourceAdapterError("worktree repository root is unavailable") from error
    repository_resource = classify_git_metadata(repository_root)
    common = Path(repository_resource["common_gitdir"])
    records = _git_worktree_records(repository_root)

    primary_candidates: list[Path] = []
    for record in records:
        candidate = Path(record["worktree"])
        marker = candidate / ".git"
        try:
            if marker.is_dir() and not marker.is_symlink() and marker.resolve(
                strict=True
            ) == common:
                primary_candidates.append(candidate.resolve(strict=True))
        except OSError:
            continue
    if len(primary_candidates) != 1:
        raise ResourceAdapterError("primary worktree identity is ambiguous")
    primary = primary_candidates[0]
    worktrees_root = primary / ".worktrees"
    try:
        if worktrees_root.is_symlink() or not worktrees_root.is_dir():
            raise ResourceAdapterError("repository-local .worktrees is unavailable")
        canonical_worktrees = worktrees_root.resolve(strict=True)
    except OSError as error:
        raise ResourceAdapterError("repository-local .worktrees is unavailable") from error

    raw_target = Path(target).expanduser()
    candidate_target = (
        raw_target if raw_target.is_absolute() else execution_root / raw_target
    )
    lexical_target = Path(os.path.abspath(candidate_target))
    try:
        resolved_target = lexical_target.resolve(strict=False)
        if (
            lexical_target != resolved_target
            or resolved_target.parent != canonical_worktrees
            or os.path.lexists(lexical_target)
            or any(
                Path(record["worktree"]).resolve(strict=False)
                == resolved_target
                for record in records
            )
            or re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9._-]{0,180}",
                resolved_target.name,
            ) is None
            or resolved_target.name.casefold() in {".git", ".worktrees"}
        ):
            raise ResourceAdapterError(
                "worktree target must be one absent direct child of .worktrees"
            )
    except (OSError, RuntimeError) as error:
        raise ResourceAdapterError("worktree target identity is unavailable") from error

    selected_operation = _text(operation, "worktree lifecycle operation")
    if selected_operation not in {"attach_existing", "create_branch"}:
        raise ResourceAdapterError("worktree lifecycle operation is invalid")
    branch_ref = _canonical_local_branch(
        repository_root, branch, role="target",
    )
    base_ref = _canonical_local_branch(repository_root, base, role="base")
    branch_code = _git_returncode(
        repository_root, "show-ref", "--verify", "--quiet", branch_ref,
    )
    if branch_code not in {0, 1}:
        raise ResourceAdapterError("target branch state cannot be proved")
    branch_checked_out = any(
        record.get("branch") == branch_ref for record in records
    )
    if selected_operation == "attach_existing":
        if branch_ref != base_ref or branch_code != 0:
            raise ResourceAdapterError("attach requires one existing local branch")
        if branch_checked_out:
            raise ResourceAdapterError("attach branch is already checked out")
        base_oid = _local_ref_oid(repository_root, branch_ref)
        branch_state = "present"
    else:
        if branch_code != 1:
            raise ResourceAdapterError("create target branch already exists")
        if any(
            existing.startswith(branch_ref + "/")
            or branch_ref.startswith(existing + "/")
            for existing in _local_branch_refs(repository_root)
        ):
            raise ResourceAdapterError("create target branch namespace conflicts")
        base_oid = _local_ref_oid(repository_root, base_ref)
        branch_state = "absent"

    dev_record = next(
        (row for row in records if row.get("branch") == "refs/heads/dev"),
        None,
    )
    if dev_record is None:
        raise ResourceAdapterError("dev worktree identity is unavailable")
    try:
        dev_worktree = Path(dev_record["worktree"]).resolve(strict=True)
    except OSError as error:
        raise ResourceAdapterError("dev worktree identity is unavailable") from error
    sealed = _seal_resource({
        "schema": GIT_WORKTREE_LIFECYCLE_RESOURCE_SCHEMA,
        "kind": "git_worktree_lifecycle",
        "operation": selected_operation,
        "repository_root": str(repository_root),
        "common_gitdir": str(common),
        "common_gitdir_identity": _stat_identity(common),
        "worktrees_root": str(canonical_worktrees),
        "target_path": str(resolved_target),
        "target_parent_identity": _stat_identity(canonical_worktrees),
        "branch_ref": branch_ref,
        "base_ref": base_ref,
        "base_oid": base_oid,
        "primary_worktree": str(primary),
        "dev_worktree": str(dev_worktree),
        "primary_status_sha256": _git_status_digest(primary),
        "dev_status_sha256": _git_status_digest(dev_worktree),
        "branch_state": branch_state,
        "branch_checked_out": branch_checked_out,
        "target_absent": True,
    })
    return GitWorktreeLifecycleResource(**sealed)


def verify_git_worktree_lifecycle(resource: Any) -> dict[str, Any]:
    """Independently prove the exact post-state of one lifecycle dispatch."""
    selected = decode_resource(resource)
    if selected["schema"] != GIT_WORKTREE_LIFECYCLE_RESOURCE_SCHEMA:
        raise ResourceAdapterError(
            "worktree lifecycle verifier requires its typed resource"
        )
    evidence: dict[str, Any] = {"resource_id": selected["resource_id"]}
    passed = False
    try:
        repository = Path(selected["repository_root"])
        target = Path(selected["target_path"])
        current_common = Path(
            classify_git_metadata(repository)["common_gitdir"]
        )
        target_resource = classify_git_metadata(target)
        records = _git_worktree_records(repository)
        target_records = [
            row for row in records
            if Path(row["worktree"]).resolve(strict=True) == target
        ]
        dev_records = [
            row for row in records
            if row.get("branch") == "refs/heads/dev"
        ]
        branch_oid = _local_ref_oid(repository, selected["branch_ref"])
        base_oid = _local_ref_oid(repository, selected["base_ref"])
        primary_status = _git_status_digest(
            Path(selected["primary_worktree"])
        )
        dev_status = _git_status_digest(Path(selected["dev_worktree"]))
        target_clean = _git_status_digest(target) == (
            "sha256:" + hashlib.sha256(b"").hexdigest()
        )
        passed = bool(
            len(target_records) == 1
            and target_records[0].get("branch") == selected["branch_ref"]
            and target_records[0]["HEAD"].lower() == selected["base_oid"]
            and target_resource["head_ref"] == selected["branch_ref"]
            and target_resource["head_oid"] == selected["base_oid"]
            and Path(target_resource["common_gitdir"]) == current_common
            and current_common == Path(selected["common_gitdir"])
            and _stat_identity(current_common)
            == selected["common_gitdir_identity"]
            and _stat_identity(Path(selected["worktrees_root"]))
            == selected["target_parent_identity"]
            and branch_oid == selected["base_oid"]
            and base_oid == selected["base_oid"]
            and primary_status == selected["primary_status_sha256"]
            and dev_status == selected["dev_status_sha256"]
            and len(dev_records) == 1
            and Path(dev_records[0]["worktree"]).resolve(strict=True)
            == Path(selected["dev_worktree"])
            and target_clean
        )
        evidence.update({
            "target_records": len(target_records),
            "head_oid": target_resource["head_oid"],
            "head_ref": target_resource["head_ref"],
            "branch_oid": branch_oid,
            "base_oid": base_oid,
            "primary_status_unchanged": (
                primary_status == selected["primary_status_sha256"]
            ),
            "dev_status_unchanged": (
                dev_status == selected["dev_status_sha256"]
            ),
            "dev_record_unchanged": bool(
                len(dev_records) == 1
                and Path(dev_records[0]["worktree"]).resolve(strict=True)
                == Path(selected["dev_worktree"])
            ),
            "target_clean": target_clean,
        })
    except (OSError, ResourceAdapterError, RuntimeError, ValueError) as error:
        evidence["reason"] = str(error)
    receipt = {
        "schema": "sulde-git-worktree-lifecycle-verifier-receipt-v1",
        "resource_id": selected["resource_id"],
        "status": "passed" if passed else "failed",
        "evidence": evidence,
        "reusable_authority": False,
    }
    receipt["receipt_sha256"] = canonical_digest(
        "git-worktree-lifecycle-verifier-receipt", receipt,
    )
    return receipt


def _tree_digest(target: Path) -> tuple[int, str]:
    entries: list[dict[str, Any]] = []
    total = 0
    for root, directories, files in os.walk(target, topdown=True, followlinks=False):
        root_path = Path(root)
        directories.sort()
        files.sort()
        for name in list(directories):
            path = root_path / name
            if stat.S_ISLNK(path.lstat().st_mode):
                raise ResourceAdapterError("delete tree contains a symlink")
            entries.append({"path": path.relative_to(target).as_posix() + "/", "type": "directory"})
        for name in files:
            path = root_path / name
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise ResourceAdapterError("delete tree has non-regular content")
            size = int(metadata.st_size)
            total += size
            entries.append({
                "path": path.relative_to(target).as_posix(), "type": "file",
                "size": size, "sha256": _file_digest(path),
            })
    return total, canonical_digest("portable-delete-tree", entries)


def _unsafe_literal_path(value: str) -> bool:
    return (
        not value or "\x00" in value or "$" in value
        or any(char in value for char in _PATH_META)
    )


def classify_local_delete(
    target: str | Path, *, workspace_root: str | Path, allowed_effect: str
) -> LocalDeleteResource:
    raw = str(target)
    if _unsafe_literal_path(raw):
        raise ResourceAdapterError("delete target is not one literal path")
    try:
        facts = canonical_existing_local_target(raw, parent=workspace_root)
        workspace = Path(workspace_root).expanduser().resolve(strict=True)
        resolved = Path(str(facts["path"]))
        parent = Path(str(facts["parent"]))
        metadata = resolved.lstat()
    except (LocalFileOperationError, OSError, RuntimeError) as error:
        raise ResourceAdapterError("delete target must canonically exist") from error
    if resolved in {Path("/").resolve(), Path.home().resolve(), workspace}:
        raise ResourceAdapterError("root, home, workspace root, aliases and symlinks are forbidden")
    if not _no_symlink_components(workspace, resolved):
        raise ResourceAdapterError("delete path traverses a symlink")
    if {part.casefold() for part in resolved.relative_to(workspace).parts} & {
        ".git", ".codex-agent",
    }:
        raise ResourceAdapterError("delete control paths are forbidden")
    if not (stat.S_ISREG(metadata.st_mode) or stat.S_ISDIR(metadata.st_mode)):
        raise ResourceAdapterError("delete target type is unsupported")
    if allowed_effect not in {"delete_file", "delete_tree"}:
        raise ResourceAdapterError("delete effect is outside the taxonomy")
    target_type = "directory" if stat.S_ISDIR(metadata.st_mode) else "file"
    if (target_type == "directory") != (allowed_effect == "delete_tree"):
        raise ResourceAdapterError("delete effect does not match target type")
    if target_type == "directory":
        size, tree_sha = _tree_digest(resolved)
    else:
        size, tree_sha = int(metadata.st_size), _file_digest(resolved)
    sealed = _seal_resource({
        "schema": DELETE_RESOURCE_SCHEMA, "kind": "local_delete",
        "target": str(resolved), "parent": str(parent), "target_type": target_type,
        "target_identity": _stat_identity(resolved), "parent_identity": _stat_identity(parent),
        "size": size, "tree_sha256": tree_sha, "allowed_effect": allowed_effect,
        "workspace_root": str(workspace),
    })
    return LocalDeleteResource(**sealed)


def classify_workspace(
    workspace: str | Path, *, original_workspace: str | Path,
    provider: str, session_id: str, require_repository: bool = True,
) -> WorkspaceResource:
    root_lexical = Path(os.path.abspath(Path(workspace).expanduser()))
    original_lexical = Path(os.path.abspath(Path(original_workspace).expanduser()))
    root = root_lexical.resolve(strict=True)
    original = original_lexical.resolve(strict=True)
    if root != root_lexical or original != original_lexical:
        raise ResourceAdapterError("workspace aliases and symlinks are forbidden")
    if not root.is_dir() or root == original:
        raise ResourceAdapterError("cross-project resource must name another workspace")
    for child, ancestor in ((root, original), (original, root)):
        try:
            child.relative_to(ancestor)
        except ValueError:
            continue
        raise ResourceAdapterError("cross-project workspaces may not contain each other")
    repository_id = classify_git_metadata(root)["resource_id"] if require_repository else ""
    sealed = _seal_resource({
        "schema": WORKSPACE_RESOURCE_SCHEMA, "kind": "workspace",
        "workspace_root": str(root), "workspace_identity": _stat_identity(root),
        "repository_id": repository_id, "original_workspace": str(original),
        "provider": _text(provider, "provider"), "session_id": _text(session_id, "session_id"),
    })
    return WorkspaceResource(**sealed)


def _figma_url_parts(value: str) -> tuple[str, str]:
    if not value:
        return "", ""
    try:
        parsed = urlparse(value)
    except ValueError:
        return "", ""
    match = re.search(r"/(?:file|design)/([A-Za-z0-9_-]+)", parsed.path)
    query = parse_qs(parsed.query)
    node = (query.get("node-id") or query.get("node_id") or [""])[0]
    return (match.group(1) if match else ""), node


_FIGMA_READ_ONLY_MEMBER_CALLS = frozenset({
    "all", "at", "concat", "entries", "every", "exportAsync", "filter",
    "find", "findAll", "findAllWithCriteria", "findChild", "findChildren",
    "findIndex", "findOne", "findWidgetNodesByWidgetId", "flat", "flatMap",
    "forEach", "from", "getAvailableLibraryVariableCollectionsAsync",
    "getCSSAsync", "getLocalComponentSetsAsync", "getLocalComponentsAsync",
    "getLocalEffectStylesAsync", "getLocalGridStylesAsync",
    "getLocalPaintStylesAsync", "getLocalTextStylesAsync",
    "getLocalVariableCollectionsAsync", "getLocalVariablesAsync",
    "getMainComponentAsync", "getNodeByIdAsync", "getPluginData",
    "getPluginDataKeys", "getRangeAllFontNames", "getRangeBoundVariable",
    "getRangeFills", "getRangeFontName", "getRangeFontSize",
    "getRangeHyperlink", "getRangeIndentation", "getRangeLetterSpacing",
    "getRangeLineHeight", "getRangeListOptions", "getRangeTextCase",
    "getRangeTextDecoration", "getRangeTextStyleId", "getRangeType",
    "getSelectionColors", "getSharedPluginData", "getSharedPluginDataKeys",
    "getStyleByIdAsync", "getStyledTextSegments",
    "getVariablesInLibraryCollectionAsync", "includes", "indexOf", "isArray",
    "join", "keys", "lastIndexOf", "listAvailableFontsAsync", "map", "match",
    "reduce", "replace", "setCurrentPageAsync", "slice", "some", "split",
    "startsWith", "stringify", "toLowerCase", "toUpperCase", "trim", "values",
})


def _javascript_structure(source: str) -> str:
    """Remove literal/comment bodies while preserving executable punctuation."""
    output: list[str] = []
    index = 0
    quote = ""
    while index < len(source):
        char = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""
        if quote:
            output.append(" ")
            if char == "\\":
                if following:
                    output.append(" ")
                    index += 2
                    continue
            elif char == quote:
                quote = ""
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            output.append(" ")
            index += 1
            continue
        if char == "/" and following == "/":
            while index < len(source) and source[index] not in "\r\n":
                output.append(" ")
                index += 1
            continue
        if char == "/" and following == "*":
            output.extend((" ", " "))
            index += 2
            while index < len(source):
                if source[index:index + 2] == "*/":
                    output.extend((" ", " "))
                    index += 2
                    break
                output.append("\n" if source[index] == "\n" else " ")
                index += 1
            continue
        output.append(char)
        index += 1
    return "".join(output)


def figma_use_script_is_read_only(code: Any) -> bool:
    """Prove one narrow Plugin API inspection script has no persistent writes."""
    if not isinstance(code, str) or not code.strip() or len(code) > 100_000:
        return False
    # Template interpolation and computed calls are intentionally outside the
    # proof language. They remain external_write instead of being guessed.
    if "`" in code:
        return False
    source = _javascript_structure(code)
    if re.search(r"\b(?:delete|eval|Function|Reflect\s*\.\s*set)\b", source):
        return False
    assignment = r"(?:\+\+|--|[+\-*/%&|^]=|(?<![=!<>])=(?!=|>))"
    if re.search(rf"\.\s*[A-Za-z_$][\w$]*\s*{assignment}", source):
        return False
    if re.search(rf"\]\s*(?:\(|{assignment})", source):
        return False
    if re.search(r"(?:\+\+|--)", source):
        return False
    calls = re.findall(r"\.\s*([A-Za-z_$][\w$]*)\s*\(", source)
    if any(name not in _FIGMA_READ_ONLY_MEMBER_CALLS for name in calls):
        return False
    bare_calls = re.findall(r"(?<![.\w$])([A-Za-z_$][\w$]*)\s*\(", source)
    allowed_bare = {
        "Array", "BigInt", "Boolean", "Number", "String", "isFinite",
        "isNaN", "parseFloat", "parseInt",
    }
    keywords = {"catch", "for", "if", "switch", "while", "with"}
    if any(name not in allowed_bare | keywords for name in bare_calls):
        return False
    return True


def classify_figma(action: str, tool_input: Any, *, provider: str = "figma") -> FigmaResource:
    data = _object(tool_input, "figma input")
    allowed = frozenset({
        "fileKey", "file_key", "url", "pageId", "page_id", "nodeId", "node_id",
        "mutationKind", "mutation_kind", "payload", "readback", "code",
        "description", "skillNames",
    })
    if not frozenset(data).issubset(allowed):
        raise ResourceAdapterError("Figma input has unknown authority fields")
    raw_action = _text(action, "figma action").lower()
    read = raw_action in {
        "get_metadata", "get_design_context", "get_screenshot",
        "get_variable_defs", "get_code_connect_map", "download_assets",
    }
    scripted_read = (
        raw_action == "use_figma"
        and figma_use_script_is_read_only(data.get("code"))
    )
    read = read or scripted_read
    write = raw_action in {"use_figma", "create_new_file", "generate_diagram"} and not scripted_read
    if not (read or write):
        raise ResourceAdapterError("Figma action is outside the taxonomy")
    url_key, url_node = _figma_url_parts(str(data.get("url") or ""))
    file_key = str(data.get("fileKey") or data.get("file_key") or url_key)
    node_id = str(data.get("nodeId") or data.get("node_id") or url_node)
    page_id = str(data.get("pageId") or data.get("page_id") or "")
    if not file_key or _SAFE_ID.fullmatch(file_key) is None:
        raise ResourceAdapterError("Figma fileKey is missing or malformed")
    for label, value in (("page", page_id), ("node", node_id)):
        if value and _SAFE_ID.fullmatch(value) is None:
            raise ResourceAdapterError(f"Figma {label} identity is malformed")
    mutation = str(data.get("mutationKind") or data.get("mutation_kind") or "")
    payload = data.get("payload", {})
    readback = data.get("readback", {})
    if write:
        if not node_id and not page_id:
            raise ResourceAdapterError("Figma write requires an exact page or node")
        if not mutation or _SAFE_ID.fullmatch(mutation) is None:
            raise ResourceAdapterError("Figma write requires a mutation kind")
        _plain(payload, "figma payload")
        if type(payload) is not dict:
            raise ResourceAdapterError("Figma mutation payload must be an object")
        _plain(readback, "figma readback")
        if type(readback) is not dict or not readback:
            raise ResourceAdapterError("Figma write requires an independent readback")
    else:
        mutation, payload, readback = "", {}, {}
    sealed = _seal_resource({
        "schema": FIGMA_RESOURCE_SCHEMA, "kind": "figma", "provider": provider,
        "file_key": file_key, "page_id": page_id, "node_id": node_id,
        "effect": "read" if read else "external_write", "mutation_kind": mutation,
        "payload_sha256": canonical_digest("figma-payload", payload),
        "readback_sha256": canonical_digest("figma-readback", readback),
    })
    return FigmaResource(**sealed)


def classify_device(
    *, provider: str, serial: str, package: str,
    artifact: str | Path | None = None, artifact_sha256: str = "",
    data_namespace: str = "", original_user_data: bool = False,
) -> DeviceResource:
    provider_value = _text(provider, "device provider")
    serial_value = _text(serial, "device serial")
    package_value = _text(package, "device package")
    if _SAFE_ID.fullmatch(serial_value) is None or _SAFE_ID.fullmatch(package_value) is None:
        raise ResourceAdapterError("device serial/package identity is malformed")
    digest = artifact_sha256
    artifact_path = ""
    if artifact is not None:
        lexical = Path(os.path.abspath(Path(artifact).expanduser()))
        resolved = lexical.resolve(strict=True)
        if lexical != resolved or stat.S_ISLNK(lexical.lstat().st_mode):
            raise ResourceAdapterError("device artifact may not be aliased")
        artifact_path = str(resolved)
        digest = _file_digest(resolved)
    if digest and _DIGEST.fullmatch(digest) is None:
        raise ResourceAdapterError("artifact digest is malformed")
    if type(original_user_data) is not bool:
        raise ResourceAdapterError("original_user_data must be exact bool")
    sealed = _seal_resource({
        "schema": DEVICE_RESOURCE_SCHEMA, "kind": "device", "provider": provider_value,
        "serial": serial_value, "package": package_value,
        "artifact_path": artifact_path, "artifact_sha256": digest,
        "data_namespace": str(data_namespace), "original_user_data": original_user_data,
    })
    return DeviceResource(**sealed)


def resource_world_state(resource: Any) -> dict[str, Any]:
    selected = decode_resource(resource)
    schema = selected["schema"]
    if schema == GIT_RESOURCE_SCHEMA:
        keys = ("resource_id", "head_oid", "head_ref", "index_sha256", "ref_sha256", "gitdir_identity", "common_identity")
    elif schema == GIT_WORKTREE_LIFECYCLE_RESOURCE_SCHEMA:
        keys = (
            "resource_id", "operation", "common_gitdir_identity",
            "target_parent_identity", "branch_ref", "base_ref", "base_oid",
            "primary_status_sha256", "dev_status_sha256", "branch_state",
            "branch_checked_out", "target_absent",
        )
    elif schema == DELETE_RESOURCE_SCHEMA:
        keys = ("resource_id", "target_identity", "parent_identity", "target_type", "size", "tree_sha256")
    elif schema == WORKSPACE_RESOURCE_SCHEMA:
        keys = ("resource_id", "workspace_identity", "repository_id")
    else:
        keys = tuple(selected)
    return {key: deepcopy(selected[key]) for key in keys}


def build_resource_action(
    resource: Any, action: str, *, subject: Any, constraints: Any,
    grant_identity: str, dispatch_identity: str, provider: str,
    session_id: str, task_epoch: str, verifier: Any,
) -> dict[str, Any]:
    selected = decode_resource(resource)
    subject_value = deepcopy(_object(subject, "subject"))
    constraints_value = deepcopy(_object(constraints, "constraints"))
    verifier_value = deepcopy(_object(verifier, "verifier"))
    if not subject_value or not verifier_value:
        raise ResourceAdapterError("subject and verifier must not be empty")
    material = {
        "schema": RESOURCE_ACTION_SCHEMA,
        "resource_schema": selected["schema"], "resource_kind": selected["kind"],
        "resource_id": selected["resource_id"], "action": _text(action, "action"),
        "subject": subject_value, "constraints": constraints_value,
        "world_state": resource_world_state(selected),
        "grant_identity": _text(grant_identity, "grant_identity"),
        "dispatch_identity": _text(dispatch_identity, "dispatch_identity"),
        "provider": _text(provider, "provider"),
        "session_id": _text(session_id, "session_id"),
        "task_epoch": _text(task_epoch, "task_epoch"), "verifier": verifier_value,
    }
    material["action_id"] = canonical_digest("typed-resource-action", material)
    return decode_resource_action(material)


def decode_resource_action(value: Any) -> dict[str, Any]:
    selected = deepcopy(_object(value, "resource action", _ACTION_FIELDS))
    if selected["schema"] != RESOURCE_ACTION_SCHEMA:
        raise ResourceAdapterError("resource action schema is invalid")
    action_id = selected.pop("action_id")
    if action_id != canonical_digest("typed-resource-action", selected):
        raise ResourceAdapterError("resource action identity was tampered")
    selected["action_id"] = action_id
    _digest(selected["action_id"], "resource action.action_id")
    if selected["resource_schema"] not in _RESOURCE_FIELDS:
        raise ResourceAdapterError("resource action schema is unknown")
    expected_kind = {
        GIT_RESOURCE_SCHEMA: "git_metadata",
        GIT_WORKTREE_LIFECYCLE_RESOURCE_SCHEMA: "git_worktree_lifecycle",
        DELETE_RESOURCE_SCHEMA: "local_delete",
        WORKSPACE_RESOURCE_SCHEMA: "workspace",
        FIGMA_RESOURCE_SCHEMA: "figma",
        DEVICE_RESOURCE_SCHEMA: "device",
    }[selected["resource_schema"]]
    if selected["resource_kind"] != expected_kind:
        raise ResourceAdapterError("resource action kind/schema mismatch")
    _digest(selected["resource_id"], "resource action.resource_id")
    for field in ("action", "grant_identity", "dispatch_identity", "provider",
                  "session_id", "task_epoch"):
        _text(selected[field], f"resource action.{field}")
    for field in ("subject", "constraints", "world_state", "verifier"):
        _object(selected[field], f"resource action.{field}")
    return selected


def _expected_effect(action: dict[str, Any], resource: dict[str, Any]) -> dict[str, str]:
    operation = action["action"]
    if resource["schema"] in {
        GIT_RESOURCE_SCHEMA, GIT_WORKTREE_LIFECYCLE_RESOURCE_SCHEMA,
    }:
        kind = "read" if operation in _GIT_READS else "local_write"
    elif resource["schema"] == DELETE_RESOURCE_SCHEMA:
        kind = "destructive"
    elif resource["schema"] == WORKSPACE_RESOURCE_SCHEMA:
        kind = "read"
    elif resource["schema"] == FIGMA_RESOURCE_SCHEMA:
        kind = resource["effect"]
    elif resource["schema"] == DEVICE_RESOURCE_SCHEMA:
        kind = (
            "read" if operation == "read"
            else "destructive" if operation == "cleanup_test_data"
            else "external_write"
        )
    else:
        raise ResourceAdapterError("resource effect is unknown")
    return {"kind": kind}


def prepare_git_action(
    resource: Any, operation: str, *, grant_identity: str, dispatch_identity: str,
    provider: str, session_id: str, task_epoch: str, paths: list[str] | None = None,
    message: str = "", parent_oids: list[str] | None = None, merge_ref: str = "",
    read_arguments: list[str] | None = None, lease_id: str = "",
) -> dict[str, Any]:
    git = decode_resource(resource)
    if git["schema"] != GIT_RESOURCE_SCHEMA:
        raise ResourceAdapterError("Git action requires GitMetadataResource")
    op = _text(operation, "Git operation").lower()
    if op not in _GIT_READS | _GIT_WRITES:
        raise ResourceAdapterError("Git operation is not allowed")
    if op in _GIT_WRITES and git["head_ref"] in {
        "refs/heads/main", "refs/heads/master",
    }:
        raise ResourceAdapterError("Git writes to the release branch are forbidden")
    constraints: dict[str, Any] = {"operation": op}
    if op == "add":
        operands = literal_git_add_arguments(["--", *(paths or [])])
        if operands is None:
            raise ResourceAdapterError("git add requires literal operands")
        root = Path(git["worktree_root"])
        exact: list[str] = []
        for operand in operands:
            target = root / operand
            try:
                metadata = target.lstat()
                relative = target.resolve(strict=True).relative_to(root).as_posix()
            except (OSError, ValueError) as error:
                raise ResourceAdapterError("git add operand is missing or outside") from error
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise ResourceAdapterError("git add operand must be a regular file")
            if not _no_symlink_components(root, target):
                raise ResourceAdapterError("git add operand traverses a symlink")
            if any(part.casefold() in {".git", ".codex-agent"} for part in Path(relative).parts):
                raise ResourceAdapterError("git add control paths are forbidden")
            exact.append(relative)
        if _git_output(root, "diff", "--cached", "--name-only", "--"):
            raise ResourceAdapterError("git add requires an initially clean index")
        constraints.update({
            "paths": exact,
            "files": [
                {"path": value, "sha256": _file_digest(root / value)}
                for value in exact
            ],
            "single_writer_lease": _text(lease_id, "lease_id"),
        })
        verifier = {"kind": "git_index_paths", "expected_paths": exact, "independent_read": "git diff --cached --name-only"}
    elif op == "commit":
        if not message or "\x00" in message or "\n" in message:
            raise ResourceAdapterError("commit message must be one exact line")
        parents = parent_oids or [git["head_oid"]]
        if parents != [git["head_oid"]]:
            raise ResourceAdapterError("commit parent must equal current HEAD")
        if not _git_output(
            Path(git["worktree_root"]), "diff", "--cached", "--name-only", "--"
        ):
            raise ResourceAdapterError("commit requires an exact non-empty index")
        constraints.update({
            "message": message, "parent_oids": parents, "expected_ref": git["head_ref"],
            "single_writer_lease": _text(lease_id, "lease_id"),
        })
        verifier = {"kind": "git_commit", "expected_parent_oids": parents, "message": message, "expected_ref": git["head_ref"]}
    elif op == "merge":
        parents = parent_oids or []
        if len(parents) != 2 or parents[0] != git["head_oid"] or any(_OID.fullmatch(value) is None for value in parents):
            raise ResourceAdapterError("merge requires exact parent OIDs")
        if not merge_ref or _SAFE_ID.fullmatch(merge_ref) is None or merge_ref.startswith("-") or ".." in merge_ref:
            raise ResourceAdapterError("merge ref is malformed")
        if not message or "\x00" in message or "\n" in message:
            raise ResourceAdapterError("merge message must be one exact line")
        resolved_merge = _git_output(
            Path(git["worktree_root"]), "rev-parse", "--verify",
            f"{merge_ref}^{{commit}}",
        ).lower()
        if resolved_merge != parents[1]:
            raise ResourceAdapterError("merge ref does not match its approved parent")
        if _git_output(Path(git["worktree_root"]), "status", "--porcelain"):
            raise ResourceAdapterError("merge requires a clean worktree and index")
        constraints.update({
            "merge_ref": merge_ref, "message": message, "parent_oids": parents,
            "expected_ref": git["head_ref"], "single_writer_lease": _text(lease_id, "lease_id"),
        })
        verifier = {"kind": "git_merge", "expected_parent_oids": parents, "message": message, "expected_ref": git["head_ref"]}
    else:
        arguments = list(read_arguments or [])
        if any(type(value) is not str or "\x00" in value for value in arguments):
            raise ResourceAdapterError("Git read arguments are malformed")
        if op == "status" and any(value not in {"--short", "--porcelain", "--branch"} for value in arguments):
            raise ResourceAdapterError("status arguments exceed finite read policy")
        if any(
            value in {
                "--output", "--exec", "--ext-diff", "--textconv", "--no-index",
                "--pathspec-from-file", "--pathspec-file-nul",
            }
            or value.startswith("--output=")
            or any(part == ".." for part in Path(value).parts)
            for value in arguments
        ):
            raise ResourceAdapterError("Git read may not write output")
        constraints["arguments"] = arguments
        verifier = {"kind": "finite_git_read", "operation": op, "repository_id": git["resource_id"]}
    return build_resource_action(
        git, op, subject={"resource_id": git["resource_id"], "operation": op},
        constraints=constraints, grant_identity=grant_identity,
        dispatch_identity=dispatch_identity, provider=provider,
        session_id=session_id, task_epoch=task_epoch, verifier=verifier,
    )


def prepare_delete_action(
    resource: Any, *, recursive: bool, grant_identity: str, dispatch_identity: str,
    provider: str, session_id: str, task_epoch: str,
) -> dict[str, Any]:
    selected = decode_resource(resource)
    if selected["schema"] != DELETE_RESOURCE_SCHEMA:
        raise ResourceAdapterError("delete action requires LocalDeleteResource")
    if recursive is not (selected["target_type"] == "directory"):
        raise ResourceAdapterError("recursive flag does not match target")
    return build_resource_action(
        selected, selected["allowed_effect"],
        subject={"resource_id": selected["resource_id"], "target": selected["target"]},
        constraints={"recursive": recursive, "exact_target_only": True},
        grant_identity=grant_identity, dispatch_identity=dispatch_identity,
        provider=provider, session_id=session_id, task_epoch=task_epoch,
        verifier={"kind": "path_absent_parent_same", "target": selected["target"], "parent_identity": selected["parent_identity"]},
    )


def prepare_workspace_action(
    resource: Any, *, grant_identity: str, dispatch_identity: str,
    provider: str, session_id: str, task_epoch: str,
) -> dict[str, Any]:
    selected = decode_resource(resource)
    if selected["schema"] != WORKSPACE_RESOURCE_SCHEMA:
        raise ResourceAdapterError("workspace action requires WorkspaceResource")
    if provider != selected["provider"] or session_id != selected["session_id"]:
        raise ResourceAdapterError("workspace provider/session drift")
    return build_resource_action(
        selected, "access",
        subject={"resource_id": selected["resource_id"], "workspace_root": selected["workspace_root"]},
        constraints={"exact_workspace_only": True, "siblings_included": False, "future_scope_enlarged": False},
        grant_identity=grant_identity, dispatch_identity=dispatch_identity,
        provider=provider, session_id=session_id, task_epoch=task_epoch,
        verifier={"kind": "workspace_identity_readback", "workspace_identity": selected["workspace_identity"], "repository_id": selected["repository_id"]},
    )


def prepare_figma_action(
    resource: Any, *, grant_identity: str, dispatch_identity: str,
    provider: str, session_id: str, task_epoch: str,
) -> dict[str, Any]:
    selected = decode_resource(resource)
    if selected["schema"] != FIGMA_RESOURCE_SCHEMA:
        raise ResourceAdapterError("Figma action requires FigmaResource")
    if provider != selected["provider"]:
        raise ResourceAdapterError("Figma provider drift")
    operation = "read" if selected["effect"] == "read" else selected["mutation_kind"]
    return build_resource_action(
        selected, operation,
        subject={"resource_id": selected["resource_id"], "file_key": selected["file_key"], "page_id": selected["page_id"], "node_id": selected["node_id"]},
        constraints={
            "mutation_kind": selected["mutation_kind"],
            "payload_sha256": selected["payload_sha256"],
            "readback_sha256": selected["readback_sha256"],
        },
        grant_identity=grant_identity, dispatch_identity=dispatch_identity,
        provider=provider, session_id=session_id, task_epoch=task_epoch,
        verifier={
            "kind": "figma_readback", "resource_id": selected["resource_id"],
            "payload_sha256": selected["payload_sha256"],
            "readback_sha256": selected["readback_sha256"],
        },
    )


def prepare_device_action(
    resource: Any, operation: str, *, grant_identity: str, dispatch_identity: str,
    provider: str, session_id: str, task_epoch: str,
) -> dict[str, Any]:
    selected = decode_resource(resource)
    if selected["schema"] != DEVICE_RESOURCE_SCHEMA:
        raise ResourceAdapterError("device action requires DeviceResource")
    if provider != selected["provider"]:
        raise ResourceAdapterError("device provider drift")
    op = _text(operation, "device operation").lower()
    if op in _DEVICE_DENIED or op not in _DEVICE_ALLOWED:
        raise ResourceAdapterError("device operation is denied")
    if op == "install" and (
        not selected["artifact_path"] or not selected["artifact_sha256"]
    ):
        raise ResourceAdapterError("install requires an exact artifact and digest")
    if op == "cleanup_test_data" and (
        selected["original_user_data"] or not selected["data_namespace"].startswith("test:")
    ):
        raise ResourceAdapterError("cleanup is limited to test data")
    return build_resource_action(
        selected, op,
        subject={"resource_id": selected["resource_id"], "serial": selected["serial"], "package": selected["package"]},
        constraints={
            "artifact_path": selected["artifact_path"],
            "artifact_sha256": selected["artifact_sha256"],
            "data_namespace": selected["data_namespace"],
            "original_user_data": selected["original_user_data"],
        },
        grant_identity=grant_identity, dispatch_identity=dispatch_identity,
        provider=provider, session_id=session_id, task_epoch=task_epoch,
        verifier={"kind": "device_readback", "operation": op, "resource_id": selected["resource_id"]},
    )


class DispatchLedger:
    """Exact-once dispatch consumer for one execution runtime."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._consumed: set[str] = set()

    def consume(self, dispatch_id: str) -> None:
        with self._lock:
            if dispatch_id in self._consumed:
                raise ResourceAdapterError("dispatch replay is forbidden")
            self._consumed.add(dispatch_id)


def authorize_resource_action(
    action: Any, current_resource: Any, *, authority: Any, dispatch: Any,
    ledger: DispatchLedger | None = None,
) -> dict[str, Any]:
    """Bind an exact H01 authority and H02 dispatch to current state."""
    selected = decode_resource_action(action)
    current = decode_resource(current_resource)
    grant = _object(authority, "execution authority", _AUTHORITY_FIELDS)
    claimed = _object(dispatch, "dispatch", _DISPATCH_FIELDS)
    if grant["schema"] != EXECUTION_AUTHORITY_SCHEMA or claimed["schema"] != BROKER_DISPATCH_SCHEMA:
        raise ResourceAdapterError("authority/dispatch schema is invalid")
    if grant["execution_authorized"] is not True or grant["default_policy_recheck_required"] is not False:
        raise ResourceAdapterError("HumanGrantV2 does not authorize execution")
    if claimed["execution_authorized"] is not True or claimed["default_policy_recheck_required"] is not False:
        raise ResourceAdapterError("broker dispatch does not authorize execution")
    if ledger is None:
        raise ResourceAdapterError("exact-once dispatch ledger is required")
    expected_capability = {
        "resource_schema": selected["resource_schema"],
        "resource_kind": selected["resource_kind"],
        "action": selected["action"],
    }
    expected_effect = _expected_effect(selected, current)
    comparisons = (
        (grant["authority_sha256"], selected["grant_identity"]),
        (claimed["dispatch_id"], selected["dispatch_identity"]),
        (claimed["authority_sha256"], grant["authority_sha256"]),
        (grant["provider"], selected["provider"]),
        (grant["session_id"], selected["session_id"]),
        (grant["task_epoch"], selected["task_epoch"]),
        (grant["capability"], expected_capability),
        (grant["effect"], expected_effect),
        (claimed["effect"], expected_effect),
        (claimed["provider"], selected["provider"]),
        (claimed["session_id"], selected["session_id"]),
        (claimed["task_epoch"], selected["task_epoch"]),
        (grant["subject"], selected["subject"]),
        (grant["constraints"], selected["constraints"]),
        (grant["world_state"], selected["world_state"]),
        (grant["verifier"], selected["verifier"]),
        (resource_world_state(current), selected["world_state"]),
        (current["resource_id"], selected["resource_id"]),
    )
    if any(type(observed) is not type(expected) or observed != expected for observed, expected in comparisons):
        raise ResourceAdapterError("authority, dispatch, or world state drifted")
    ledger.consume(str(claimed["dispatch_id"]))
    material = {
        "schema": AUTHORIZATION_SCHEMA, "action_id": selected["action_id"],
        "resource_id": selected["resource_id"],
        "authority_sha256": grant["authority_sha256"],
        "dispatch_id": claimed["dispatch_id"], "execution_authorized": True,
    }
    material["authorization_sha256"] = canonical_digest("typed-resource-authorization", material)
    return material


def _validate_authorization(action: dict[str, Any], authorization: Any) -> dict[str, Any]:
    fields = frozenset({
        "schema", "action_id", "resource_id", "authority_sha256", "dispatch_id",
        "execution_authorized", "authorization_sha256",
    })
    selected = deepcopy(_object(authorization, "authorization", fields))
    digest = selected.pop("authorization_sha256")
    if selected["schema"] != AUTHORIZATION_SCHEMA or selected["execution_authorized"] is not True:
        raise ResourceAdapterError("authorization is not executable")
    if digest != canonical_digest("typed-resource-authorization", selected):
        raise ResourceAdapterError("authorization was tampered")
    if selected["action_id"] != action["action_id"] or selected["resource_id"] != action["resource_id"]:
        raise ResourceAdapterError("authorization belongs to another action")
    selected["authorization_sha256"] = digest
    return selected


_GIT_LEASE_LOCK = threading.Lock()
_GIT_ACTIVE: set[str] = set()


@contextmanager
def git_write_lease(resource: Any, lease_id: str) -> Iterator[None]:
    selected = decode_resource(resource)
    if selected["schema"] != GIT_RESOURCE_SCHEMA or not lease_id:
        raise ResourceAdapterError("Git lease identity is invalid")
    key = selected["common_identity"]
    with _GIT_LEASE_LOCK:
        if key in _GIT_ACTIVE:
            raise ResourceAdapterError("common gitdir already has one active writer")
        _GIT_ACTIVE.add(key)
    try:
        yield
    finally:
        with _GIT_LEASE_LOCK:
            _GIT_ACTIVE.discard(key)


def execute_git_action(action: Any, resource: Any, authorization: Any) -> dict[str, Any]:
    """Execute one exact local Git action after a second state read."""
    selected = decode_resource_action(action)
    before = decode_resource(resource)
    auth = _validate_authorization(selected, authorization)
    current = classify_git_metadata(before["worktree_root"])
    if resource_world_state(current) != selected["world_state"]:
        raise ResourceAdapterError("Git world state drifted before execution")
    op = selected["action"]
    constraints = selected["constraints"]
    if op == "add":
        root = Path(before["worktree_root"])
        if constraints.get("files") != [
            {"path": value, "sha256": _file_digest(root / value)}
            for value in constraints["paths"]
        ]:
            raise ResourceAdapterError("git add file content drifted")
        argv = ["git", "add", "--", *constraints["paths"]]
    elif op == "commit":
        argv = ["git", "commit", "-m", constraints["message"]]
    elif op == "merge":
        resolved_merge = _git_output(
            Path(before["worktree_root"]), "rev-parse", "--verify",
            f"{constraints['merge_ref']}^{{commit}}",
        ).lower()
        if resolved_merge != constraints["parent_oids"][1]:
            raise ResourceAdapterError("merge target drifted before execution")
        argv = ["git", "merge", "--no-ff", "-m", constraints["message"], constraints["merge_ref"]]
    elif op in _GIT_READS:
        argv = ["git", op, *constraints["arguments"]]
    else:
        raise ResourceAdapterError("Git action is not executable")
    def run() -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                argv, cwd=before["worktree_root"], capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=15, check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise ResourceAdapterError("Git execution adapter failed") from error
    if op in _GIT_WRITES:
        with git_write_lease(before, constraints["single_writer_lease"]):
            completed = run()
    else:
        completed = run()
    receipt = {
        "schema": EXECUTION_RECEIPT_SCHEMA, "action_id": selected["action_id"],
        "dispatch_id": auth["dispatch_id"],
        "status": "succeeded" if completed.returncode == 0 else "failed",
        "returncode": int(completed.returncode),
        "stdout_sha256": canonical_digest("stdout", completed.stdout),
        "stderr_sha256": canonical_digest("stderr", completed.stderr),
    }
    receipt["receipt_sha256"] = canonical_digest("typed-resource-execution-receipt", receipt)
    return receipt


def execute_with_adapter(
    action: Any, resource: Any, authorization: Any,
    adapter: Callable[[dict[str, Any], dict[str, Any]], Any],
) -> dict[str, Any]:
    """External/deletion effects exist only through an injected fake/host port."""
    selected = decode_resource_action(action)
    current = decode_resource(resource)
    auth = _validate_authorization(selected, authorization)
    if selected["resource_id"] != current["resource_id"]:
        raise ResourceAdapterError("adapter resource substitution")
    if current["schema"] == DELETE_RESOURCE_SCHEMA:
        observed = classify_local_delete(
            current["target"],
            workspace_root=current["workspace_root"],
            allowed_effect=current["allowed_effect"],
        )
        if resource_world_state(observed) != selected["world_state"]:
            raise ResourceAdapterError("delete target or parent identity drifted")
    elif current["schema"] == WORKSPACE_RESOURCE_SCHEMA:
        observed = classify_workspace(
            current["workspace_root"],
            original_workspace=current["original_workspace"],
            provider=current["provider"], session_id=current["session_id"],
        )
        if resource_world_state(observed) != selected["world_state"]:
            raise ResourceAdapterError("workspace identity drifted")
    elif current["schema"] == DEVICE_RESOURCE_SCHEMA and current["artifact_path"]:
        observed = classify_device(
            provider=current["provider"], serial=current["serial"],
            package=current["package"], artifact=current["artifact_path"],
            data_namespace=current["data_namespace"],
            original_user_data=current["original_user_data"],
        )
        if resource_world_state(observed) != selected["world_state"]:
            raise ResourceAdapterError("device artifact or identity drifted")
    result = adapter(deepcopy(selected), deepcopy(current))
    _plain(result, "adapter result")
    receipt = {
        "schema": EXECUTION_RECEIPT_SCHEMA, "action_id": selected["action_id"],
        "dispatch_id": auth["dispatch_id"], "status": "succeeded",
        "result": deepcopy(result),
    }
    receipt["receipt_sha256"] = canonical_digest("typed-resource-execution-receipt", receipt)
    return receipt


def verify_git_action(action: Any, before: Any, execution_receipt: Any) -> dict[str, Any]:
    selected = decode_resource_action(action)
    original = decode_resource(before)
    receipt = _decode_execution_receipt(execution_receipt)
    if receipt.get("schema") != EXECUTION_RECEIPT_SCHEMA or receipt.get("action_id") != selected["action_id"]:
        raise ResourceAdapterError("execution receipt is foreign")
    after = classify_git_metadata(original["worktree_root"])
    passed = receipt.get("status") == "succeeded"
    evidence: dict[str, Any] = {"before": original["resource_id"], "after": after["resource_id"]}
    op = selected["action"]
    if op == "add":
        output = _git_output(Path(original["worktree_root"]), "diff", "--cached", "--name-only", "--")
        staged = sorted(line for line in output.splitlines() if line)
        expected = sorted(selected["constraints"]["paths"])
        passed = passed and staged == expected and after["head_oid"] == original["head_oid"]
        evidence.update({"staged_paths": staged, "expected_paths": expected})
    elif op in {"commit", "merge"}:
        parents = _git_output(Path(original["worktree_root"]), "show", "-s", "--format=%P", "HEAD").split()
        message = _git_output(Path(original["worktree_root"]), "show", "-s", "--format=%s", "HEAD")
        passed = (
            passed and parents == selected["verifier"]["expected_parent_oids"]
            and message == selected["verifier"]["message"]
            and after["head_ref"] == selected["verifier"]["expected_ref"]
        )
        evidence.update({"parent_oids": parents, "message": message, "head_ref": after["head_ref"]})
    elif op in _GIT_READS:
        passed = passed and after["resource_id"] == original["resource_id"]
    return _verifier_receipt(selected, receipt, passed, evidence)


def verify_resource_readback(
    action: Any, execution_receipt: Any, readback: Any,
) -> dict[str, Any]:
    selected = decode_resource_action(action)
    receipt = _decode_execution_receipt(execution_receipt)
    evidence = deepcopy(_object(readback, "independent readback"))
    if receipt.get("schema") != EXECUTION_RECEIPT_SCHEMA or receipt.get("action_id") != selected["action_id"]:
        raise ResourceAdapterError("execution receipt is foreign")
    kind = selected["verifier"].get("kind")
    passed = receipt.get("status") == "succeeded"
    if kind == "path_absent_parent_same":
        target = Path(selected["verifier"]["target"])
        passed = (
            passed and not target.exists() and not target.is_symlink()
            and _stat_identity(target.parent) == selected["verifier"]["parent_identity"]
        )
    elif kind == "workspace_identity_readback":
        passed = passed and evidence == {
            "workspace_identity": selected["verifier"]["workspace_identity"],
            "repository_id": selected["verifier"]["repository_id"],
        }
    elif kind == "figma_readback":
        passed = (
            passed and evidence == {
                "resource_id": selected["resource_id"],
                "payload_sha256": selected["verifier"]["payload_sha256"],
                "readback_sha256": selected["verifier"]["readback_sha256"],
            }
        )
    elif kind == "device_readback":
        passed = (
            passed and evidence == {
                "resource_id": selected["resource_id"],
                "operation": selected["action"],
            }
        )
    else:
        raise ResourceAdapterError("verifier kind is unsupported")
    return _verifier_receipt(selected, receipt, passed, evidence)


def _decode_execution_receipt(value: Any) -> dict[str, Any]:
    selected = deepcopy(_object(value, "execution receipt"))
    fields = frozenset(selected)
    expected_git = frozenset({
        "schema", "action_id", "dispatch_id", "status", "returncode",
        "stdout_sha256", "stderr_sha256", "receipt_sha256",
    })
    expected_adapter = frozenset({
        "schema", "action_id", "dispatch_id", "status", "result",
        "receipt_sha256",
    })
    if fields not in {expected_git, expected_adapter}:
        raise ResourceAdapterError("execution receipt fields are invalid")
    claimed = selected.pop("receipt_sha256")
    if selected.get("schema") != EXECUTION_RECEIPT_SCHEMA:
        raise ResourceAdapterError("execution receipt schema is invalid")
    if claimed != canonical_digest("typed-resource-execution-receipt", selected):
        raise ResourceAdapterError("execution receipt was tampered")
    selected["receipt_sha256"] = claimed
    return selected


def _verifier_receipt(
    action: dict[str, Any], execution: dict[str, Any], passed: bool, evidence: Any
) -> dict[str, Any]:
    value = {
        "schema": VERIFIER_RECEIPT_SCHEMA, "action_id": action["action_id"],
        "execution_receipt_sha256": execution.get("receipt_sha256", ""),
        "status": "passed" if passed else "failed", "evidence": deepcopy(evidence),
        "reusable_authority": False,
    }
    value["receipt_sha256"] = canonical_digest("typed-resource-verifier-receipt", value)
    return value


def resource_debt_blocker(action: Any, debts: Any) -> dict[str, Any] | None:
    """Only active debt for the same exact typed boundary blocks."""
    selected = decode_resource_action(action)
    if type(debts) is not list:
        raise ResourceAdapterError("resource debt projection must be a list")
    for row in debts:
        debt = _object(row, "resource debt")
        if debt.get("effect") == "read" or debt.get("state") in {
            "terminal", "quarantined", "aborted", "settled",
        }:
            continue
        if debt.get("state") not in {"unknown", "pending", "dispatched", "verifying"}:
            continue
        same = debt.get("resource_id") == selected["resource_id"]
        unresolved_same_kind = (
            not debt.get("resource_id")
            and debt.get("resource_kind") == selected["resource_kind"]
        )
        if same or unresolved_same_kind:
            return deepcopy(debt)
    return None


def classify_hook_resource(
    tool_name: str, tool_input: Any, *, cwd: str | Path,
    provider: str, session_id: str, phase: str = "started",
) -> dict[str, Any] | None:
    """Return classification facts only; parsing never yields authority."""
    if phase not in {"started", "completed"}:
        raise ResourceAdapterError("hook resource phase is invalid")
    name = str(tool_name).lower()
    data = tool_input if type(tool_input) is dict else {}
    if name in {"bash", "exec", "exec_command", "command_execution"}:
        command = str(data.get("command") or data.get("cmd") or "")
        # Git belongs to the host execution domain.  The adapter must not
        # inspect its subcommand, repository, refs or operands for policy.
        if git_execution_passthrough(command):
            return None
        if has_unquoted_shell_control(command):
            return None
        try:
            tokens = split_command_template(command)
        except ValueError:
            return None
        if tokens and Path(tokens[0]).name.lower() == "rm":
            arguments = tokens[1:]
            recursive = False
            if arguments and arguments[0] in {"-r", "-R", "-rf", "-fr"}:
                recursive = True
                arguments = arguments[1:]
            if not arguments or arguments[0] != "--" or len(arguments) != 2:
                return {
                    "schema": "sulde-typed-resource-classification-v1",
                    "kind": "local_delete", "status": "rejected",
                    "reason": "delete requires one exact operand after --",
                    "execution_authorized": False,
                }
            try:
                resource = classify_local_delete(
                    arguments[1], workspace_root=cwd,
                    allowed_effect="delete_tree" if recursive else "delete_file",
                )
            except ResourceAdapterError as error:
                return {
                    "schema": "sulde-typed-resource-classification-v1",
                    "kind": "local_delete", "status": "rejected",
                    "reason": str(error), "execution_authorized": False,
                }
            return {
                "schema": "sulde-typed-resource-classification-v1",
                "kind": "local_delete", "status": "classified",
                "resource_id": resource["resource_id"],
                "action": resource["allowed_effect"],
                "constraints": {
                    "recursive": recursive, "exact_target_only": True,
                },
                "world_state": resource_world_state(resource),
                "execution_authorized": False,
            }
        lifecycle = literal_git_worktree_lifecycle_action(command)
        if lifecycle is not None:
            execution_base = Path(cwd)
            repository_operand = str(lifecycle["repository"])
            if repository_operand:
                candidate = Path(repository_operand)
                execution_base = (
                    candidate if candidate.is_absolute()
                    else execution_base / candidate
                )
            if phase == "completed":
                target_operand = Path(str(lifecycle["target"])).expanduser()
                target = (
                    target_operand
                    if target_operand.is_absolute()
                    else execution_base / target_operand
                )
                return {
                    "schema": "sulde-typed-resource-classification-v1",
                    "kind": "git_worktree_lifecycle", "status": "completion",
                    "action": str(lifecycle["operation"]),
                    "capability": (
                        "git.worktree." + str(lifecycle["operation"])
                    ),
                    "target": str(target.resolve(strict=False)),
                    "execution_authorized": False,
                }
            try:
                resource = classify_git_worktree_lifecycle(
                    execution_base,
                    str(lifecycle["target"]),
                    operation=str(lifecycle["operation"]),
                    branch=str(lifecycle["branch"]),
                    base=str(lifecycle["base"]),
                )
            except ResourceAdapterError as error:
                return {
                    "schema": "sulde-typed-resource-classification-v1",
                    "kind": "git_worktree_lifecycle", "status": "rejected",
                    "reason": str(error),
                    "action": str(lifecycle["operation"]),
                    "capability": (
                        "git.worktree." + str(lifecycle["operation"])
                    ),
                    "execution_authorized": False,
                }
            return {
                "schema": "sulde-typed-resource-classification-v1",
                "kind": "git_worktree_lifecycle", "status": "classified",
                "resource_id": resource["resource_id"],
                "action": resource["operation"],
                "capability": "git.worktree." + resource["operation"],
                "target": resource["target_path"],
                "constraints": {
                    "repository_root": resource["repository_root"],
                    "target_path": resource["target_path"],
                    "branch_ref": resource["branch_ref"],
                    "base_ref": resource["base_ref"],
                    "base_oid": resource["base_oid"],
                    "single_use": True,
                },
                "resource": dict(resource),
                "world_state": resource_world_state(resource),
                "execution_authorized": False,
            }
        base = Path(cwd)
        if len(tokens) > 2 and Path(tokens[0]).name.lower() == "git" and tokens[1] == "-C":
            candidate = Path(tokens[2])
            base = candidate if candidate.is_absolute() else base / candidate
        parsed = literal_git_resource_action(command)
        if tokens and Path(tokens[0]).name.lower() == "git":
            if parsed is None:
                return {
                    "schema": "sulde-typed-resource-classification-v1",
                    "kind": "git_metadata", "status": "rejected",
                    "reason": "Git action is broad, malformed, or outside the finite policy",
                    "execution_authorized": False,
                }
            try:
                canonical_base = base.expanduser().resolve(strict=True)
                canonical_cwd = Path(cwd).expanduser().resolve(strict=True)
                if canonical_base != canonical_cwd:
                    workspace = classify_workspace(
                        canonical_base, original_workspace=canonical_cwd,
                        provider=provider, session_id=session_id,
                    )
                    return {
                        "schema": "sulde-typed-resource-classification-v1",
                        "kind": "workspace", "status": "classified",
                        "resource_id": workspace["resource_id"],
                        "action": f"git:{parsed['action']}",
                        "constraints": {
                            "exact_workspace_only": True,
                            "repository_id": workspace["repository_id"],
                            "git_arguments": deepcopy(parsed["arguments"]),
                        },
                        "world_state": resource_world_state(workspace),
                        "execution_authorized": False,
                    }
                resource = classify_git_metadata(canonical_base)
            except ResourceAdapterError as error:
                return {
                    "schema": "sulde-typed-resource-classification-v1",
                    "kind": "git_metadata", "status": "rejected",
                    "reason": str(error), "execution_authorized": False,
                }
            action = str(parsed["action"])
            if action in _GIT_WRITES and resource["head_ref"] in {
                "refs/heads/main", "refs/heads/master",
            }:
                return {
                    "schema": "sulde-typed-resource-classification-v1",
                    "kind": "git_metadata", "status": "rejected",
                    "reason": "Git writes to the release branch are forbidden",
                    "action": action, "execution_authorized": False,
                }
            constraints: dict[str, Any] = {
                "arguments": deepcopy(parsed["arguments"]),
            }
            if action == "add":
                constraints["paths"] = deepcopy(parsed["arguments"])
            elif action == "commit":
                constraints["message"] = parsed["arguments"][0]
                constraints["expected_head_oid"] = resource["head_oid"]
                constraints["expected_ref"] = resource["head_ref"]
            elif action == "merge":
                constraints["message"] = parsed["arguments"][0]
                constraints["merge_ref"] = parsed["arguments"][1]
                try:
                    constraints["merge_oid"] = _git_output(
                        Path(resource["worktree_root"]), "rev-parse", "--verify",
                        f"{parsed['arguments'][1]}^{{commit}}",
                    ).lower()
                except ResourceAdapterError as error:
                    return {
                        "schema": "sulde-typed-resource-classification-v1",
                        "kind": "git_metadata", "status": "rejected",
                        "reason": str(error), "action": action,
                        "execution_authorized": False,
                    }
            return {
                "schema": "sulde-typed-resource-classification-v1",
                "kind": "git_metadata", "status": "classified",
                "resource_id": resource["resource_id"], "action": action,
                "constraints": constraints,
                "world_state": resource_world_state(resource),
                "execution_authorized": False,
            }
    mcp_parts = name.split("__")
    if len(mcp_parts) >= 4 and mcp_parts[:2] == ["mcp", "codex_apps"]:
        mcp_server = mcp_parts[2]
        mcp_action = "__".join(mcp_parts[3:])
    elif (
        len(mcp_parts) == 3
        and mcp_parts[:2] == ["mcp", "codex_apps"]
        and mcp_parts[2].startswith("figma_")
    ):
        mcp_server = "figma"
        mcp_action = mcp_parts[2][len("figma_"):]
    elif len(mcp_parts) >= 3 and mcp_parts[0] == "mcp":
        mcp_server = mcp_parts[1]
        mcp_action = "__".join(mcp_parts[2:])
    else:
        mcp_server = ""
        mcp_action = ""
    if mcp_server == "figma":
        action = mcp_action
        try:
            resource = classify_figma(action, data, provider=provider or "figma")
        except ResourceAdapterError as error:
            return {
                "schema": "sulde-typed-resource-classification-v1",
                "kind": "figma", "status": "rejected", "reason": str(error),
                "action": action, "execution_authorized": False,
            }
        return {
            "schema": "sulde-typed-resource-classification-v1",
            "kind": "figma", "status": "classified",
            "resource_id": resource["resource_id"], "action": action,
            "effect": resource["effect"],
            "constraints": {
                "file_key": resource["file_key"], "page_id": resource["page_id"],
                "node_id": resource["node_id"],
                "mutation_kind": resource["mutation_kind"],
                "payload_sha256": resource["payload_sha256"],
                "readback_sha256": resource["readback_sha256"],
            },
            "world_state": resource_world_state(resource),
            "execution_authorized": False,
        }
    if mcp_server:
        server = mcp_server
        action = mcp_action
        if server in {"device", "android", "ios", "adb"}:
            aliases = {
                "install_app": "install", "run_tests": "run_test",
                "clear_data": "data_clear",
            }
            operation = aliases.get(action, action)
            try:
                resource = classify_device(
                    provider=provider or server,
                    serial=str(data.get("serial") or data.get("device_serial") or ""),
                    package=str(data.get("package") or data.get("bundle_id") or ""),
                    artifact=data.get("artifact") or data.get("artifact_path") or None,
                    artifact_sha256=str(data.get("artifact_sha256") or ""),
                    data_namespace=str(data.get("data_namespace") or ""),
                    original_user_data=data.get("original_user_data", False),
                )
                prepare_device_action(
                    resource, operation, grant_identity="classification-only",
                    dispatch_identity="classification-only", provider=resource["provider"],
                    session_id=session_id or "classification-only",
                    task_epoch="classification-only",
                )
            except ResourceAdapterError as error:
                return {
                    "schema": "sulde-typed-resource-classification-v1",
                    "kind": "device", "status": "rejected",
                    "reason": str(error), "action": operation,
                    "execution_authorized": False,
                }
            return {
                "schema": "sulde-typed-resource-classification-v1",
                "kind": "device", "status": "classified",
                "resource_id": resource["resource_id"], "action": operation,
                "constraints": {
                    "serial": resource["serial"], "package": resource["package"],
                    "artifact_path": resource["artifact_path"],
                    "artifact_sha256": resource["artifact_sha256"],
                    "data_namespace": resource["data_namespace"],
                    "original_user_data": resource["original_user_data"],
                },
                "world_state": resource_world_state(resource),
                "execution_authorized": False,
            }
    return None


__all__ = [
    "ResourceAdapterError", "GitMetadataResource",
    "GitWorktreeLifecycleResource", "LocalDeleteResource",
    "WorkspaceResource", "FigmaResource", "DeviceResource", "DispatchLedger",
    "canonical_json", "canonical_digest", "decode_resource",
    "decode_resource_action", "classify_git_metadata",
    "classify_git_worktree_lifecycle", "verify_git_worktree_lifecycle",
    "classify_local_delete",
    "classify_workspace", "classify_figma", "classify_device",
    "resource_world_state", "build_resource_action", "prepare_git_action",
    "prepare_delete_action", "prepare_workspace_action", "prepare_figma_action",
    "prepare_device_action", "authorize_resource_action", "execute_git_action",
    "execute_with_adapter", "verify_git_action", "verify_resource_readback",
    "resource_debt_blocker", "git_write_lease", "classify_hook_resource",
]
